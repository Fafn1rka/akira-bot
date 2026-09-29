#!/usr/bin/env python3
"""
Точка входа. Запускает всё сразу (что доступно в системе):
  • консольный чат (работает всегда, даже без микрофона и Telegram) — понимает и файлы: /файл ...;
  • голосовой ввод/вывод (если есть микрофон и пакеты для этого);
  • окно-персонаж на рабочем столе (если установлен PySide6);
  • Telegram-бота (если указан токен в .env);
  • Discord-бота (если указан DISCORD_BOT_TOKEN);
  • чат Twitch (если указан TWITCH_CHANNEL);
  • напоминания, которые Акира ставит по твоей просьбе;
  • утренний брифинг (дата, погода, напоминания) — MORNING_BRIEFING в .env;
  • Акира сама пишет первой при затянувшейся тишине.

Windows и Linux — без разницы, запускается одинаково:
    python main.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import avatar_state
import briefing
import config
import persona
import voice
import voice_listener
from brain import Brain, _scrub_secrets
from memory import JsonStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout),
             logging.FileHandler(config.LOGS_DIR / "akira.log", encoding="utf-8")],
)


class _SecretFilter(logging.Filter):
    """Прячет токены и ключи из ЛЮБЫХ строк лога. Раньше httpx печатал адрес запроса к Telegram
    вместе с токеном бота — а токен даёт полный доступ к боту."""
    _TG = re.compile(r"bot\d{6,}:[A-Za-z0-9_-]{20,}")

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        clean = self._TG.sub("bot<скрыто>", _scrub_secrets(msg))
        if clean != msg:
            record.msg, record.args = clean, ()
        return True


for _handler in logging.getLogger().handlers:
    _handler.addFilter(_SecretFilter())
# Служебная болтовня библиотек: httpx пишет строку на КАЖДЫЙ опрос Telegram (раз в 10 секунд),
# google-genai — предупреждения о своём внутреннем режиме. Настоящие ошибки они показывают и так.
for _noisy in ("httpx", "httpcore", "google_genai.models", "google_genai._api_client"):
    logging.getLogger(_noisy).setLevel(logging.ERROR if _noisy.startswith("google") else logging.WARNING)

log = logging.getLogger("akira.main")

DESKTOP_KEY = config.OWNER_KEY

_FILE_COMMANDS = ("/файл", "/файлы", "/file", "/files")


def parse_file_command(line: str):
    """'/файл C:\\a.png "C:\\мои файлы\\b.pdf" что тут?' -> (['C:\\a.png', 'C:\\мои файлы\\b.pdf'], 'что тут?').
    Файлы — сначала, вопрос — после них. None, если это не команда /файл."""
    parts = line.strip().split(maxsplit=1)
    if not parts or parts[0].lower() not in _FILE_COMMANDS:
        return None
    rest = parts[1] if len(parts) > 1 else ""
    try:
        tokens = shlex.split(rest, posix=False)      # posix=False — чтобы не съедать обратные слэши Windows
    except ValueError:
        tokens = rest.split()
    files: list[str] = []
    words: list[str] = []
    for tok in tokens:
        path = tok.strip("\"'")
        if not words and os.path.isfile(os.path.expanduser(path)):
            files.append(os.path.expanduser(path))
        else:
            words.append(tok)
    return files, " ".join(words)


class Akira:
    def __init__(self) -> None:
        self.brain = Brain()
        self.last_activity = time.time()
        self.idle_count = 0
        self.idle_day = datetime.now().day
        self.avatar_proc: subprocess.Popen | None = None
        self.telegram_app = None
        self._stop = asyncio.Event()
        self.loop: Optional[asyncio.AbstractEventLoop] = None   # выставляется в run(); нужен gui.py, чтобы слать команды из окна
        self._briefing_state = JsonStore(config.DATA_DIR / "briefing.json")   # когда здоровались в последний раз
        self._merge_owner_memory()
        self.brain.add_reminder_handler(self._on_reminder)
        self.brain.add_notice_handler(self._on_notice)

    def _merge_owner_memory(self) -> None:
        """Раньше владелец в Telegram/Discord имел отдельную память. Переносим его факты в общую."""
        if not config.SHARED_OWNER_MEMORY:
            return
        old_keys = []
        if config.TELEGRAM_OWNER_ID:
            old_keys.append(f"tg:{config.TELEGRAM_OWNER_ID}")
        if config.DISCORD_OWNER_ID:
            old_keys.append(f"discord:{config.DISCORD_OWNER_ID}")
        for old in old_keys:
            try:
                n = self.brain.memory.merge_facts(old, DESKTOP_KEY)
            except Exception as e:  # noqa: BLE001
                log.warning("Не удалось объединить память %s: %s", old, e)
                continue
            if n:
                log.info("Перенесла %d фактов о тебе из «%s» в общую память.", n, old)

    # ---------------------------------------------------------- запуск
    async def run(self, headless: bool = False) -> None:
        """headless=True — используется из gui.py: без консольного ввода (окно уже заменяет его)."""
        self.loop = asyncio.get_running_loop()
        if not headless:
            self._banner()
        self._start_avatar()

        tasks = [asyncio.create_task(self._idle_loop(), name="idle")]
        if not headless:
            tasks.insert(0, asyncio.create_task(self._console_loop(), name="console"))
        if config.MORNING_BRIEFING:
            tasks.append(asyncio.create_task(self._briefing_loop(), name="briefing"))

        listener = None
        if config.VOICE_INPUT_ENABLED:
            loop = asyncio.get_running_loop()
            listener = voice_listener.make_asyncio_bridge(
                loop, self._on_voice_heard, self._on_voice_wake, self._on_voice_state)
            if listener.start():
                log.info("Голосовой ввод включён: скажи «Акира».")
            else:
                log.info("Голосовой ввод недоступен (нет микрофона или пакетов) — можно печатать в консоли. "
                         "Диагностика: check.bat")
        else:
            log.warning("Голосовой ввод ВЫКЛЮЧЕН: в .env стоит VOICE_INPUT_ENABLED=false. "
                        "Поставь true и перезапусти Акиру.")

        if config.TELEGRAM_BOT_TOKEN:
            tasks.append(asyncio.create_task(self._run_telegram(), name="telegram"))
        else:
            log.info("TELEGRAM_BOT_TOKEN не задан — Telegram-бот выключен.")

        if config.DISCORD_BOT_TOKEN:
            tasks.append(asyncio.create_task(self._run_discord(), name="discord"))
        else:
            log.info("DISCORD_BOT_TOKEN не задан — Discord-бот выключен.")

        if config.TWITCH_CHANNEL:
            tasks.append(asyncio.create_task(self._run_twitch(), name="twitch"))

        for t in tasks:
            t.add_done_callback(self._log_task_end)

        # Обработчик Ctrl+C можно ставить только в главном потоке главного интерпретатора — headless-режим
        # (окно gui.py) запускает Акиру в фоновом потоке, там это упало бы с ошибкой.
        if not headless and threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGINT, signal.SIGTERM) if not config.IS_WINDOWS else (signal.SIGINT,):
                try:
                    self.loop.add_signal_handler(sig, self._stop.set)
                except (NotImplementedError, RuntimeError):
                    pass  # некоторые окружения Windows не поддерживают add_signal_handler

        # Работаем, пока не попросят выйти. Раньше тут стояло «до первой завершившейся задачи» — из-за
        # этого вся программа закрывалась, например, при IDLE_CHAT_ENABLED=false или без пакета Telegram.
        await self._stop.wait()

        log.info("Завершаю работу...")
        if listener:
            listener.stop()
        for t in tasks:
            t.cancel()
        if self.avatar_proc:
            self.avatar_proc.terminate()
        avatar_state.write_state("idle", 0.0)

    def request_stop(self) -> None:
        """Остановить Акиру из другого потока (например, из окна gui.py). Потокобезопасно."""
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self._stop.set)

    async def ask(self, text: str, speak_reply: bool = False) -> str:
        """Задать вопрос владельца и получить ответ текстом — то, что использует gui.py для чата."""
        return await self._handle_owner_text(text, speak_reply=speak_reply)

    @staticmethod
    def _log_task_end(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            log.warning("Модуль «%s» остановился из-за ошибки: %s", task.get_name(), exc)

    def _banner(self) -> None:
        print("=" * 56)
        print("  АКИРА — голосовой ИИ-компаньон")
        print("=" * 56)
        if not self.brain.available():
            print("! Не настроен ни один AI — впиши GEMINI_API_KEY (или ключи другого провайдера) в .env.")
        else:
            print(f"AI: {self.brain.describe()}")
        print("Печатай сообщения прямо тут и жми Enter. Ctrl+C — выход.")
        print("Файлы:  /файл путь1 путь2 ... вопрос   (можно перетащить файлы мышью в это окно)")
        print("Ещё:    /брифинг — утреннее приветствие сейчас;  «Акира, посмотри на экран»;  «включи рабочий режим»\n")

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
    async def _handle_owner_text(self, text: str, speak_reply: bool, files: list | None = None) -> str:
        self.last_activity = time.time()
        avatar_state.write_state("thinking", 0.0)
        reply = await self.brain.generate_response(
            key=DESKTOP_KEY, message=text, owner_name=config.OWNER_NAME,
            is_owner=True, allow_terminal=config.ENABLE_TERMINAL_COMMANDS, files=files,
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
        if sys.stdin is None:          # запущено без консоли (pythonw) — работаем без неё
            return
        loop = asyncio.get_running_loop()
        lines: asyncio.Queue = asyncio.Queue()

        def _reader() -> None:
            # Отдельный демон-поток вместо asyncio.to_thread: input() нельзя прервать, и из-за него
            # программа могла «зависнуть» при выходе, пока не нажмёшь Enter.
            while True:
                try:
                    line = input("> ")
                except (EOFError, KeyboardInterrupt, RuntimeError, OSError):
                    line = None
                try:
                    loop.call_soon_threadsafe(lines.put_nowait, line)
                except RuntimeError:       # программа уже закрылась — цикла событий больше нет
                    return
                if line is None:
                    return

        threading.Thread(target=_reader, name="akira-console", daemon=True).start()

        while True:
            line = await lines.get()
            if line is None:
                self._stop.set()
                return
            line = line.strip()
            if not line:
                continue
            if line.lower() in ("выход", "exit", "quit"):
                self._stop.set()
                return

            if line.lower() in ("/брифинг", "/briefing"):
                await self._run_briefing()
                continue

            cmd = parse_file_command(line)
            if cmd is not None:
                files, question = cmd
                if not files:
                    print("Не нашла таких файлов. Пример:  /файл C:\\картинка.png C:\\отчёт.pdf что здесь?")
                    continue
                await self._handle_owner_text(question, speak_reply=False, files=files)
                continue
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

    # --------------------------------------------------------- напоминания
    async def _on_reminder(self, key: str, text: str) -> None:
        """Сработало напоминание, которое владелец попросил поставить (в любом канале связи)."""
        await self._tell_owner(f"Напоминание: {text}", prefix="⏰ ")

    async def _on_notice(self, key: str, text: str) -> None:
        """Ссылка или другая информация, которую Акира нашла сама (play_music, web_search) —
        не произносится вслух, только текстом в Telegram и Discord (и видно в окне на вкладке «Ссылки»)."""
        await self._deliver_text(text)

    # ------------------------------------------------- сообщение владельцу
    async def _deliver_text(self, text: str, prefix: str = "") -> None:
        """Текстом — в Telegram и Discord (без голоса). Отдельно от _tell_owner, потому что
        не каждое сообщение владельцу стоит ещё и произносить вслух (например, найденные ссылки)."""
        if config.TELEGRAM_OWNER_ID and self.telegram_app:
            try:
                await self.telegram_app.bot.send_message(config.TELEGRAM_OWNER_ID, prefix + text)
            except Exception as e:  # noqa: BLE001
                log.info("Не удалось отправить владельцу в Telegram: %s", e)
        if config.DISCORD_BOT_TOKEN:
            try:
                from discord_bot import dm_owner
                await dm_owner(prefix + text)
            except Exception as e:  # noqa: BLE001
                log.info("Не удалось отправить владельцу в Discord: %s", e)

    async def _tell_owner(self, text: str, prefix: str = "") -> None:
        """Сказать владельцу везде, где он может быть: голосом за компьютером, в Telegram и в Discord."""
        print(f"Акира: {prefix}{text}")
        self.last_activity = time.time()
        await voice.speak(text)
        await self._deliver_text(text, prefix)

    # ---------------------------------------------------- утренний брифинг
    async def _run_briefing(self) -> None:
        facts = await asyncio.to_thread(briefing.gather_facts, self.brain)
        if self.brain.available():
            reply = await self.brain.generate_response(
                DESKTOP_KEY, briefing.build_prompt(config.OWNER_NAME, facts), config.OWNER_NAME, True, False)
        else:
            reply = await asyncio.to_thread(briefing.gather_facts, self.brain, None, None, True)   # без AI — сухая сводка
        if reply:
            await self._tell_owner(reply)

    async def _briefing_loop(self) -> None:
        at = config.parse_hhmm(config.BRIEFING_TIME)
        if at is None:
            log.warning("BRIEFING_TIME=%r — нужно ЧЧ:ММ, например 08:30. Утренний брифинг выключен.",
                        config.BRIEFING_TIME)
            return
        await asyncio.sleep(20)                 # дать Telegram/Discord подключиться, если брифинг «догоняет» при запуске
        while True:
            now = datetime.now()
            if briefing.is_due(now, at, self._briefing_state.data.get("last_date")):
                self._briefing_state.data["last_date"] = now.date().isoformat()   # отметить СРАЗУ: не повторять, даже если сбой
                self._briefing_state.save()
                try:
                    await self._run_briefing()
                except Exception as e:  # noqa: BLE001
                    log.warning("Утренний брифинг не удался: %s", e)
            await asyncio.sleep(30)

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

    # ------------------------------------------------------ Twitch / Discord / Telegram
    async def _run_twitch(self) -> None:
        from twitch_bot import TwitchCompanion

        companion = TwitchCompanion(self.brain)
        try:
            await companion.run()
        except Exception as e:  # noqa: BLE001
            log.warning("Twitch-чат отключился: %s", e)
        finally:
            companion.close()

    async def _run_discord(self) -> None:
        try:
            from discord_bot import run_discord
        except ImportError:
            log.warning("discord.py не установлен — Discord выключен (pip install discord.py).")
            return
        try:
            await run_discord(self.brain)
        except Exception as e:  # noqa: BLE001
            log.warning("Discord-бот остановился: %s (проверь DISCORD_BOT_TOKEN и Message Content Intent)", e)

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
