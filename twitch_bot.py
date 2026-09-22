"""
Чтение и (необязательно) ответы в чате Twitch — напрямую по IRC поверх
asyncio, без сторонних библиотек. Работает «только на чтение», если
TWITCH_OAUTH_TOKEN не задан (можно просто подслушивать чат), и может писать
ответы, если токен есть: https://twitchapps.com/tmi/ (нужен scope chat:read
+ chat:edit; ник — TWITCH_BOT_NICK, реальный аккаунт бота на Twitch).

Включается только если в .env указан TWITCH_CHANNEL — по умолчанию выключено.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Callable, Dict, List, Optional

import config

log = logging.getLogger("akira.twitch")

_SYSTEM_BOTS = {"nightbot", "streamelements", "moobot", "streamlabs"}
_MSG_RE = re.compile(r"^:([^!]+)![^@]+@\S+\s+PRIVMSG\s+#(\S+)\s+:(.*)$")


class TwitchChatReader:
    """Низкоуровневый IRC-клиент: подключение, keepalive, разбор сообщений."""

    def __init__(self, channel: str, bot_nick: str = "", oauth_token: str = "",
                on_message: Optional[Callable[[str, str], None]] = None):
        self.channel = channel.lower().strip().lstrip("#")
        self.bot_nick = bot_nick or f"justinfan{int(time.time()) % 100000}"
        self.oauth_token = oauth_token or "SCHMOOPIIE"  # спец-значение Twitch для анонимного чтения
        self.on_message = on_message
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.running = False
        self.recent: List[Dict[str, str]] = []

    async def connect(self) -> None:
        if not self.channel:
            return
        log.info("Подключаюсь к Twitch IRC: #%s как %s...", self.channel, self.bot_nick)
        self.reader, self.writer = await asyncio.open_connection("irc.chat.twitch.tv", 6667)
        self.writer.write(f"PASS {self.oauth_token}\r\n".encode())
        self.writer.write(f"NICK {self.bot_nick}\r\n".encode())
        self.writer.write(f"JOIN #{self.channel}\r\n".encode())
        await self.writer.drain()
        self.running = True
        log.info("Подключено к #%s.", self.channel)

    async def send(self, message: str) -> None:
        if not self.writer or self.oauth_token == "SCHMOOPIIE":
            return  # без реального токена отправлять нельзя — только читаем
        try:
            self.writer.write(f"PRIVMSG #{self.channel} :{message[:480]}\r\n".encode())
            await self.writer.drain()
        except Exception as e:  # noqa: BLE001
            log.warning("Не удалось отправить сообщение в Twitch-чат: %s", e)

    async def listen(self) -> None:
        buffer = ""
        while self.running:
            try:
                assert self.reader is not None
                data = await self.reader.read(2048)
                if not data:
                    log.warning("Соединение с Twitch потеряно — переподключаюсь через 5 с.")
                    await asyncio.sleep(5)
                    await self.connect()
                    continue
                buffer += data.decode("utf-8", errors="ignore")
                *lines, buffer = buffer.split("\r\n")
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("PING"):
                        assert self.writer is not None
                        self.writer.write(line.replace("PING", "PONG").encode() + b"\r\n")
                        await self.writer.drain()
                        continue
                    m = _MSG_RE.match(line)
                    if not m:
                        continue
                    user, _, text = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
                    if user.lower() in _SYSTEM_BOTS:
                        continue
                    self.recent.append({"user": user, "text": text, "time": time.time()})
                    del self.recent[:-50]
                    if self.on_message:
                        try:
                            self.on_message(user, text)
                        except Exception as e:  # noqa: BLE001
                            log.warning("Обработчик сообщения Twitch упал: %s", e)
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                log.warning("Ошибка слушателя Twitch: %s", e)
                await asyncio.sleep(2)

    def close(self) -> None:
        self.running = False
        if self.writer:
            try:
                self.writer.close()
            except Exception:  # noqa: BLE001
                pass


class TwitchCompanion:
    """Связывает чат Twitch с Brain: читает всех, изредка отвечает (не чаще
    TWITCH_CHAT_INTERVAL секунд), чтобы не флудить и не тратить лимиты Gemini."""

    def __init__(self, brain):
        self.brain = brain
        self.reader = TwitchChatReader(config.TWITCH_CHANNEL, config.TWITCH_BOT_NICK,
                                       config.TWITCH_OAUTH_TOKEN, on_message=self._on_message)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._last_reply = 0.0

    def _on_message(self, user: str, text: str) -> None:
        if self._loop and time.time() - self._last_reply >= config.TWITCH_CHAT_INTERVAL:
            self._last_reply = time.time()
            asyncio.run_coroutine_threadsafe(self._reply(user, text), self._loop)

    async def _reply(self, user: str, text: str) -> None:
        try:
            reply = await self.brain.generate_response(
                key=f"twitch:{self.reader.channel}", message=text, owner_name=config.OWNER_NAME,
                is_owner=False, allow_terminal=False, speaker_label=f"Зритель {user}",
            )
        except Exception as e:  # noqa: BLE001
            log.warning("Ошибка ответа в Twitch-чат: %s", e)
            return
        if reply:
            await self.reader.send(reply)

    async def run(self) -> None:
        if not config.TWITCH_CHANNEL:
            return
        self._loop = asyncio.get_running_loop()
        await self.reader.connect()
        await self.reader.listen()

    def close(self) -> None:
        self.reader.close()
