"""
«Мозг» Акиры: Gemini + инструменты (открыть приложение, громкость, статус
системы, запомнить факт, предложить консольную команду) + отдельная память
на каждого собеседника (владелец ПК, гость Telegram, чат Twitch).

Приватность и права разграничены строго на уровне того, какие инструменты
вообще передаются модели — если инструмента нет в списке, модель физически
не может его вызвать, что бы ни было написано в сообщении.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

import config
import memory as memory_mod
import persona
import system_control

log = logging.getLogger("akira.brain")

try:
    from google import genai
    from google.genai import types as gtypes
except ImportError:  # пакет ставится через requirements.txt: google-genai
    genai = None
    gtypes = None

CONFIRM_WORDS = {
    "подтверждаю", "подтвердить", "да, подтверждаю", "підтверджую",
    "confirm", "i confirm", "yes confirm",
}
CANCEL_WORDS = {"отмена", "отменить", "скасувати", "cancel"}

_BANNED_PATTERNS = [
    r"\bn+[i1!|]+g+[e3a@]+r+s?\b",
    r"\bf+a+g+[o0]+t+s?\b",
    r"\bkys\b",
    r"\bkill\s+yourself\b",
]
_SECRET_PATTERNS = [
    re.compile(re.escape(config.GEMINI_API_KEY)) if config.GEMINI_API_KEY else None,
    re.compile(re.escape(config.TELEGRAM_BOT_TOKEN)) if config.TELEGRAM_BOT_TOKEN else None,
]


def is_safe_message(text: str) -> bool:
    low = text.lower()
    return not any(re.search(p, low) for p in _BANNED_PATTERNS)


def _scrub_secrets(text: str) -> str:
    for pat in _SECRET_PATTERNS:
        if pat:
            text = pat.sub("[скрыто]", text)
    return text


class Brain:
    def __init__(self, mem: Optional[memory_mod.Memory] = None):
        self.memory = mem or memory_mod.Memory()
        self.client = None
        self._sessions: dict[str, object] = {}
        self._pending_cmd: dict[str, str] = {}
        if genai and config.GEMINI_API_KEY:
            try:
                self.client = genai.Client(api_key=config.GEMINI_API_KEY)
            except Exception as e:  # noqa: BLE001
                log.error("Не удалось создать клиент Gemini: %s", e)

    def available(self) -> bool:
        return self.client is not None

    # ------------------------------------------------------------ tools
    def _make_tools(self, key: str, owner_name: str, is_owner: bool, allow_terminal: bool) -> list:
        tools: list = []

        def remember_fact(fact: str) -> str:
            """Сохраняет важный факт о собеседнике надолго (имя, вкусы, планы, обещания). \
Вызывай, когда узнаёшь что-то, что стоит помнить и в следующих разговорах."""
            self.memory.add_fact(key, fact)
            return "Запомнила."

        tools.append(remember_fact)

        if is_owner and config.ENABLE_SYSTEM_COMMANDS:
            def open_app(name: str) -> str:
                """Открывает приложение или сайт на компьютере владельца (например: браузер, \
ютуб, телеграм, vscode, терминал, проводник, калькулятор — или произвольное название/URL)."""
                return system_control.open_app(name)

            def control_volume(action: str, value: Optional[int] = None) -> str:
                """Управляет громкостью звука на компьютере владельца. action: 'up' (громче), \
'down' (тише), 'mute' (выключить/включить звук) или 'set' (выставить value процентов, 0..100)."""
                return system_control.control_volume(action, value)

            def get_system_status() -> str:
                """Возвращает состояние компьютера владельца: загрузка процессора, память, \
батарея, диск."""
                return system_control.get_system_status()

            tools += [open_app, control_volume, get_system_status]

            if allow_terminal:
                def propose_terminal_command(command: str, reason: str) -> str:
                    """Предлагает владельцу выполнить консольную команду на его компьютере. \
НЕ выполняет её — только откладывает и просит подтверждения. Используй, только если владелец \
явно попросил что-то сделать в терминале/консоли."""
                    self._pending_cmd[key] = command
                    return (f"Хочу выполнить команду: {command} — {reason}. "
                           f"Скажи «подтверждаю», и я запущу, или «отмена», если передумал.")

                tools.append(propose_terminal_command)

        return tools

    # --------------------------------------------------------- сессия
    def _system_instruction(self, owner_name: str, key: str, is_owner: bool, allow_terminal: bool) -> str:
        facts = self.memory.facts(key) if is_owner else []
        prompt = persona.build_system_prompt(owner_name, facts, is_owner, allow_terminal)
        return prompt + "\n" + persona.time_context()

    def _get_or_create_session(self, key: str, owner_name: str, is_owner: bool, allow_terminal: bool):
        if key in self._sessions:
            return self._sessions[key]
        if not self.client:
            return None
        cfg = gtypes.GenerateContentConfig(
            system_instruction=self._system_instruction(owner_name, key, is_owner, allow_terminal),
            tools=self._make_tools(key, owner_name, is_owner, allow_terminal) or None,
        )
        history = self._build_history(key) if is_owner else []
        kwargs = {"model": config.GEMINI_MODEL, "config": cfg}
        if history:
            kwargs["history"] = history
        try:
            session = self.client.aio.chats.create(**kwargs)
        except TypeError:
            kwargs.pop("history", None)
            session = self.client.aio.chats.create(**kwargs)
        except Exception as e:  # noqa: BLE001
            log.error("Не удалось создать чат-сессию Gemini: %s", e)
            return None
        self._sessions[key] = session
        return session

    def _build_history(self, key: str) -> list:
        if not gtypes:
            return []
        out = []
        for t in self.memory.turns(key)[-16:]:
            role = "user" if t["role"] == "user" else "model"
            try:
                out.append(gtypes.Content(role=role, parts=[gtypes.Part(text=t["text"])]))
            except Exception:  # noqa: BLE001
                pass
        return out

    def reset(self, key: str) -> None:
        self._sessions.pop(key, None)
        self._pending_cmd.pop(key, None)
        self.memory.clear(key)

    # ------------------------------------------------------------- API
    async def generate_response(self, key: str, message: str, owner_name: str = "Создатель",
                                is_owner: bool = True, allow_terminal: bool = False,
                                speaker_label: str = "") -> str:
        """
        key            — уникальный идентификатор собеседника/чата (своя память и сессия)
        is_owner       — True для владельца ПК: доступ к инструментам и постоянной памяти
        allow_terminal — разрешить предлагать консольные команды (только владельцу)
        speaker_label  — как подписать реплику модели (например, имя зрителя в Twitch)
        """
        message = message.strip()
        if not message:
            return ""
        if not is_safe_message(message):
            return "Давай общаться уважительно — иначе не отвечу."

        low = message.lower().strip(" .!")
        if low in CONFIRM_WORDS and key in self._pending_cmd:
            cmd = self._pending_cmd.pop(key)
            result = await asyncio.to_thread(system_control.run_confirmed_terminal_command, cmd)
            reply = f"Выполняю: {cmd}\n{result}"
            self.memory.add_turn(key, "user", message)
            self.memory.add_turn(key, "model", reply)
            return _scrub_secrets(reply)
        if low in CANCEL_WORDS and key in self._pending_cmd:
            self._pending_cmd.pop(key, None)
            return "Хорошо, отменяю."

        if not self.available():
            if not config.GEMINI_API_KEY:
                return "Мне нужен ключ Gemini — впиши GEMINI_API_KEY в файл .env."
            return "Не получается связаться с Gemini прямо сейчас — проверь интернет."

        session = self._get_or_create_session(key, owner_name, is_owner, allow_terminal)
        if session is None:
            return "Не удалось начать разговор с моделью — проверь ключ и интернет."

        text_in = f"[{speaker_label}]: {message}" if speaker_label else message
        try:
            res = await session.send_message(text_in)
            reply = (res.text or "").strip()
        except Exception as e:  # noqa: BLE001
            log.warning("Ошибка запроса к Gemini (%s), пробую пересоздать сессию: %s", key, e)
            self._sessions.pop(key, None)
            session = self._get_or_create_session(key, owner_name, is_owner, allow_terminal)
            try:
                res = await session.send_message(text_in)
                reply = (res.text or "").strip()
            except Exception as e2:  # noqa: BLE001
                log.error("Повторная ошибка Gemini: %s", e2)
                return "Что-то пошло не так на моей стороне — попробуй ещё раз чуть позже."

        reply = _scrub_secrets(reply) or "Готово."
        if not is_safe_message(reply):
            return "Не стану произносить это вслух."

        self.memory.add_turn(key, "user", message)
        self.memory.add_turn(key, "model", reply)
        return reply

    async def idle_message(self, key: str, owner_name: str) -> str:
        """Акира сама начинает разговор (тишина/скука)."""
        return await self.generate_response(key, persona.get_idle_prompt(owner_name), owner_name, True, False)
