#!/usr/bin/env python3
"""
Точка входа. Запускает всё сразу (что доступно в системе):
  • консольный чат (работает всегда, даже без микрофона и Telegram);
  • голосовой ввод/вывод (если есть микрофон и пакеты для этого);
  • окно-персонаж на рабочем столе (если установлен PySide6);
  • Telegram-бота (если указан токен в .env);
  • Акира сама пишет первой при затянувшейся тишине.

Windows и Linux — без разницы, запускается одинаково:
    python main.py
"""
from __future__ import annotations

import asyncio
import logging
import random
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import avatar_state
import config
import persona
import voice
import voice_listener
from brain import Brain

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout),
             logging.FileHandler(config.LOGS_DIR / "akira.log", encoding="utf-8")],
)
log = logging.getLogger("akira.main")

DESKTOP_KEY = "desktop:owner"


class Akira:
    def __init__(self) -> None:
        self.brain = Brain()
        self.last_activity = time.time()
        self.idle_count = 0
        self.idle_day = datetime.now().day
        self.avatar_proc: subprocess.Popen | None = None
        self.telegram_app = None
        self._stop = asyncio.Event()

    # ---------------------------------------------------------- запуск
    async def run(self) -> None:
        self._banner()
        self._start_avatar()

        tasks = [asyncio.create_task(self._console_loop(), name="console"),
                 asyncio.create_task(self._idle_loop(), name="idle")]

        listener = None
        if config.VOICE_INPUT_ENABLED:
            loop = asyncio.get_running_loop()
            listener = voice_listener.make_asyncio_bridge(
                loop, self._on_voice_heard, self._on_voice_wake, self._on_voice_state)
            if listener.start():
                log.info("Голосовой ввод включён: скажи «Акира».")
            else:
                log.info("Голосовой ввод недоступен (нет микрофона или пакетов) — можно печатать в консоли.")

        tg_task = None
        if config.TELEGRAM_BOT_TOKEN:
            tg_task = asyncio.create_task(self._run_telegram(), name="telegram")
            tasks.append(tg_task)
        else:
            log.info("TELEGRAM_BOT_TOKEN не задан — Telegram-бот выключен.")

        if config.TWITCH_CHANNEL:
            tasks.append(asyncio.create_task(self._run_twitch(), name="twitch"))

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM) if not config.IS_WINDOWS else (signal.SIGINT,):
            try:
                loop.add_signal_handler(sig, self._stop.set)
            except NotImplementedError:
                pass  # некоторые окружения Windows не поддерживают add_signal_handler

        stopper = asyncio.create_task(self._stop.wait())
        await asyncio.wait([stopper, *tasks], return_when=asyncio.FIRST_COMPLETED)

        log.info("Завершаю работу...")
        if listener:
            listener.stop()
        for t in tasks:
            t.cancel()
        if self.avatar_proc:
            self.avatar_proc.terminate()
        avatar_state.write_state("idle", 0.0)

    def _banner(self) -> None:
        print("=" * 56)
        print("  АКИРА — голосовой ИИ-компаньон")
        print("=" * 56)
        if not config.GEMINI_API_KEY:
            print("! GEMINI_API_KEY не задан в .env — разговор пока не заработает.")
        print("Печатай сообщения прямо тут и жми Enter. Ctrl+C — выход.\n")

    # ------------------------------------------------------- рабочий стол
    def _start_avatar(self) -> None:
        if not config.ENABLE_AVATAR:
            return
        try:
            self.avatar_proc = subprocess.Popen(
                [sys.executable, str(Path(__file__).parent / "avatar.py")],
                cwd=str(Path(__file__).parent),
            )
            log.info("Окно персонажа запущено (PID %s).", self.avatar_proc.pid)
        except Exception as e:  # noqa: BLE001
            log.warning("Не удалось запустить окно персонажа: %s", e)

    # ------------------------------------------------------------ владелец
    async def _handle_owner_text(self, text: str, speak_reply: bool) -> str:
        self.last_activity = time.time()
        avatar_state.write_state("thinking", 0.0)
        reply = await self.brain.generate_response(
            key=DESKTOP_KEY, message=text, owner_name=config.OWNER_NAME,
            is_owner=True, allow_terminal=config.ENABLE_TERMINAL_COMMANDS,
        )
        print(f"Акира: {reply}")
        if speak_reply:
            ok = await voice.speak(reply)
            if not ok:
                avatar_state.write_state("idle", 0.0)
        else:
            avatar_state.write_state("idle", 0.0)
        return reply

    async def _console_loop(self) -> None:
        while True:
            try:
                line = await asyncio.to_thread(input, "> ")
            except (EOFError, KeyboardInterrupt):
                self._stop.set()
                return
            line = line.strip()
            if not line:
                continue
            if line.lower() in ("выход", "exit", "quit"):
                self._stop.set()
                return
            await self._handle_owner_text(line, speak_reply=False)

    # -------------------------------------------------------------- голос
    async def _on_voice_wake(self) -> None:
        print(f"Акира: {persona.poke_reaction()}")
        avatar_state.write_state("listening", 0.3)
        await asyncio.sleep(0.6)
        avatar_state.write_state("idle", 0.0)

    async def _on_voice_state(self, listening: bool) -> None:
        if listening:
            avatar_state.write_state("listening", 0.4)

    async def _on_voice_heard(self, text: str) -> None:
        print(f"[голос] {text}")
        await self._handle_owner_text(text, speak_reply=True)

    # ------------------------------------------------------------- скука
    async def _idle_loop(self) -> None:
        if not config.IDLE_CHAT_ENABLED:
            return
        while True:
            await asyncio.sleep(30)
            now = datetime.now()
            if now.day != self.idle_day:
                self.idle_day = now.day
                self.idle_count = 0
            if self.idle_count >= config.IDLE_MAX_PER_DAY:
                continue
            quiet = config.parse_quiet_hours(config.QUIET_HOURS)
            if quiet:
                minute = now.hour * 60 + now.minute
                a, b = quiet
                in_quiet = (a <= minute or minute < b) if a > b else (a <= minute < b)
                if in_quiet:
                    continue
            elapsed_min = (time.time() - self.last_activity) / 60
            if elapsed_min < config.IDLE_CHAT_INTERVAL:
                continue
            self.last_activity = time.time()  # не спамить, даже если реплика не удалась
            self.idle_count += 1
            try:
                reply = await self.brain.idle_message(DESKTOP_KEY, config.OWNER_NAME)
            except Exception as e:  # noqa: BLE001
                log.warning("idle_message: %s", e)
                continue
            if not reply:
                continue
            print(f"Акира: {reply}")
            await voice.speak(reply)
            if config.TELEGRAM_OWNER_ID and self.telegram_app:
                try:
                    await self.telegram_app.bot.send_message(config.TELEGRAM_OWNER_ID, reply)
                except Exception as e:  # noqa: BLE001
                    log.info("Не удалось написать владельцу в Telegram: %s", e)

    # ---------------------------------------------------------- telegram
    async def _run_twitch(self) -> None:
        from twitch_bot import TwitchCompanion

        companion = TwitchCompanion(self.brain)
        try:
            await companion.run()
        except Exception as e:  # noqa: BLE001
            log.warning("Twitch-чат отключился: %s", e)
        finally:
            companion.close()

    async def _run_telegram(self) -> None:
        from telegram_bot import TelegramBot

        bot = TelegramBot(self.brain)
        if not bot.available():
            log.warning("python-telegram-bot не установлен — Telegram выключен "
                       "(pip install 'python-telegram-bot>=21').")
            return
        app = bot.build()
        self.telegram_app = app
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        log.info("Telegram-бот запущен.")
        try:
            await self._stop.wait()
        finally:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()


def main() -> None:
    akira = Akira()
    try:
        asyncio.run(akira.run())
    except KeyboardInterrupt:
        pass
    print("\nАкира: До встречи!")


if __name__ == "__main__":
    main()
