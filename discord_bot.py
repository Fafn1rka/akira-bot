"""
Акира в Discord. Включается сама, если в .env указан DISCORD_BOT_TOKEN.

ТЕКСТ
  • отвечает в личных сообщениях, при упоминании (@Акира) и во всех каналах из DISCORD_CHANNEL_IDS;
  • ВЛАДЕЛЕЦ (DISCORD_OWNER_ID) — тот же человек, что за компьютером и в Telegram: общая память и все
    инструменты (открыть программу, сценарии, громкость, экран, поиск, напоминания). Консольные команды
    через Discord по умолчанию ВЫКЛЮЧЕНЫ (DISCORD_ALLOW_TERMINAL=true включает — только если уверен
    в защите своего аккаунта Discord);
  • у гостей своя отдельная память и ТОЛЬКО инструмент «запомнить»; между их сообщениями пауза;
  • вложения (несколько картинок, PDF, текстовые файлы) уходят модели вместе с текстом;
  • «!сброс» очищает память диалога.

ГОЛОС В ГОЛОСОВОМ КАНАЛЕ (команды — только владельцу)
  • «!зайди» — Акира заходит в тот голосовой канал, где сидишь ты;
  • пока она там, её ответы на твои сообщения в чате сервера ещё и ОЗВУЧИВАЮТСЯ голосом
    (гостям — только если DISCORD_VOICE_ALL=true);
  • «!скажи текст» — произнести именно этот текст; «!выйди» — выйти из канала;
  • если в канале не остаётся людей, она сама выходит через полминуты.
  Слушать людей в голосовом канале она пока не умеет — только говорить. Пиши ей текстом.
  Нужно: пакет PyNaCl (ставится с `discord.py[voice]`) и библиотека Opus
  (Linux: sudo apt install libopus0; Windows и macOS — уже внутри).

Настройка (https://discord.com/developers/applications → твоё приложение):
  1. Bot → Reset Token → скопируй в .env: DISCORD_BOT_TOKEN=...
  2. Bot → включи «MESSAGE CONTENT INTENT» (без него бот не видит текст сообщений).
  3. OAuth2 → URL Generator → scope «bot», права «View Channels», «Send Messages»,
     «Read Message History»; для голоса ещё «Connect» и «Speak» → открой ссылку и добавь бота на сервер.
  4. Свой ID: Discord → Настройки → Расширенные → Режим разработчика; ПКМ по себе → «Копировать ID»
     → DISCORD_OWNER_ID=...
"""
from __future__ import annotations

import asyncio
import io
import logging
import time
from typing import Optional

import discord

import config
import media
import voice
from brain import MAX_FILE_BYTES, MAX_FILES, Brain, is_safe_message

log = logging.getLogger("akira.discord")

RESET_WORDS = {"!reset", "!сброс", "сброс"}
JOIN_WORDS = {"!зайди", "!join", "!приди", "!войди"}
LEAVE_WORDS = {"!выйди", "!leave", "!уйди"}
SAY_WORDS = {"!скажи", "!say"}
_AUTO_LEAVE_AFTER = 30.0     # секунд одиночества в канале, после которых она выходит


def _chunks(text: str, limit: int = 1900):
    """Режет длинный ответ под лимит Discord (2000 символов)."""
    while text:
        if len(text) <= limit:
            yield text
            return
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        yield text[:cut]
        text = text[cut:].lstrip()


def voice_problem() -> Optional[str]:
    """Чего не хватает для голоса в Discord (None — всё есть)."""
    try:
        import nacl  # noqa: F401  (PyNaCl)
    except ImportError:
        return "Для голоса в Discord нужен пакет PyNaCl: pip install 'discord.py[voice]'"
    if not discord.opus.is_loaded():
        try:
            discord.opus._load_default()  # noqa: SLF001  (на Linux ищет системную libopus)
        except Exception:  # noqa: BLE001
            pass
    if not discord.opus.is_loaded():
        return ("Не нашла библиотеку Opus. Linux: sudo apt install libopus0 — и перезапусти меня. "
                "(Windows и macOS обычно ничего ставить не нужно.)")
    if not media.find_ffmpeg():
        return "Не нашла ffmpeg — он ставится вместе с пакетом imageio-ffmpeg (pip install imageio-ffmpeg)."
    return None


class AkiraDiscord(discord.Client):
    def __init__(self, brain: Brain):
        intents = discord.Intents.default()          # в него уже входит voice_states — нужен для голоса
        intents.message_content = True
        # модель не должна уметь пинговать @everyone и роли
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.brain = brain
        self._last_guest_msg: dict[int, float] = {}
        self._voice_locks: dict[int, asyncio.Lock] = {}
        self._tasks: set = set()

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def setup_hook(self) -> None:
        self.brain.add_reminder_handler(self._deliver_reminder)

    async def on_ready(self) -> None:
        log.info("Discord: вошла как %s.", self.user)

    async def dm_owner(self, text: str) -> bool:
        """Написать владельцу в личные сообщения (напоминания, утренний брифинг)."""
        if not config.DISCORD_OWNER_ID:
            return False
        try:
            user = await self.fetch_user(config.DISCORD_OWNER_ID)
            for chunk in _chunks(text):
                await user.send(chunk)
            return True
        except Exception as e:  # noqa: BLE001
            log.info("Не удалось написать владельцу в Discord: %s", e)
            return False

    async def _deliver_reminder(self, key: str, text: str) -> None:
        await self.dm_owner(f"⏰ Напоминание: {text}")

    async def dm_owner_photo(self, data: bytes, filename: str, caption: str = "") -> bool:
        """Картинка владельцу в личку — файлом, а не ссылкой."""
        if not config.DISCORD_OWNER_ID:
            return False
        try:
            user = await self.fetch_user(config.DISCORD_OWNER_ID)
            await user.send(content=(caption[:2000] or None), file=discord.File(io.BytesIO(data), filename=filename))
            return True
        except Exception as e:  # noqa: BLE001
            log.info("Не удалось отправить картинку в Discord: %s", e)
            return False

    def _key(self, user_id: int, is_owner: bool) -> str:
        if is_owner and config.SHARED_OWNER_MEMORY:
            return config.OWNER_KEY
        return f"discord:{user_id}"

    # ------------------------------------------------------------ голос
    async def _join(self, message: discord.Message) -> str:
        if message.guild is None:
            return "Напиши эту команду в текстовом канале сервера, пока сидишь в голосовом."
        state = getattr(message.author, "voice", None)
        if state is None or state.channel is None:
            return "Сначала зайди в голосовой канал — и я приду к тебе."
        problem = voice_problem()
        if problem:
            return problem
        channel = state.channel
        try:
            vc = message.guild.voice_client
            if vc is not None and vc.is_connected():
                await vc.move_to(channel)
            else:
                await channel.connect()
        except Exception as e:  # noqa: BLE001
            log.warning("Не удалось зайти в голосовой канал: %s", e)
            return f"Не получилось зайти в «{channel.name}»: {e}. Проверь, что у меня есть права Connect и Speak."
        return f"Зашла в «{channel.name}». Пиши — буду отвечать голосом. «!выйди» — уйду."

    async def _leave(self, message: discord.Message) -> str:
        vc = message.guild.voice_client if message.guild else None
        if vc is None or not vc.is_connected():
            return "Я и так не в голосовом канале."
        await vc.disconnect()
        return "Вышла из голосового канала."

    def _voice_target(self, message: discord.Message, is_owner: bool):
        """Голосовое подключение, в котором надо озвучить ответ (или None)."""
        if not (is_owner or config.DISCORD_VOICE_ALL):
            return None
        vc = message.guild.voice_client if message.guild else None
        if vc is None and message.guild is None and is_owner and len(getattr(self, "voice_clients", [])) == 1:
            vc = self.voice_clients[0]          # владелец пишет в личку, а Акира сидит в одном канале
        return vc if vc is not None and vc.is_connected() else None

    async def speak_in_voice(self, vc, text: str) -> bool:
        """Произносит текст в голосовом канале. Реплики идут по очереди, друг на друга не накладываются."""
        if vc is None or not vc.is_connected():
            return False
        ffmpeg = media.find_ffmpeg()
        if not ffmpeg:
            return False
        lock = self._voice_locks.setdefault(vc.guild.id, asyncio.Lock())
        async with lock:
            mp3 = await voice.synthesize(text)
            if not mp3:
                return False
            try:
                loop = asyncio.get_running_loop()
                done = asyncio.Event()

                def _after(err) -> None:
                    if err:
                        log.warning("Ошибка воспроизведения в голосовом канале: %s", err)
                    loop.call_soon_threadsafe(done.set)

                vc.play(discord.FFmpegPCMAudio(str(mp3), executable=ffmpeg), after=_after)
                try:
                    await asyncio.wait_for(done.wait(), timeout=180)
                except asyncio.TimeoutError:
                    vc.stop()
                return True
            except Exception as e:  # noqa: BLE001
                log.warning("Не удалось озвучить в голосовом канале: %s", e)
                return False
            finally:
                media.cleanup(mp3)

    async def on_voice_state_update(self, member, before, after) -> None:
        """Все люди вышли из канала — через полминуты уходим и мы."""
        vc = member.guild.voice_client
        if vc is None or not vc.is_connected() or member.bot:
            return

        def humans():
            return [m for m in vc.channel.members if not m.bot]

        if humans():
            return
        await asyncio.sleep(_AUTO_LEAVE_AFTER)
        if vc.is_connected() and not humans():
            await vc.disconnect()
            log.info("В голосовом канале никого не осталось — вышла.")

    # ------------------------------------------------------------ текст
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return

        is_dm = message.guild is None
        mentioned = self.user is not None and self.user.mentioned_in(message) and not message.mention_everyone
        is_owner = bool(config.DISCORD_OWNER_ID) and message.author.id == config.DISCORD_OWNER_ID

        text = message.content
        if self.user is not None:
            text = text.replace(f"<@{self.user.id}>", "").replace(f"<@!{self.user.id}>", "")
        text = text.strip()
        cmd, _, arg = text.partition(" ")
        cmd = cmd.lower()

        # Команды владельца («!зайди», «!выйди», «!скажи ...») работают в любом канале и без упоминания.
        is_voice_cmd = is_owner and cmd in (JOIN_WORDS | LEAVE_WORDS | SAY_WORDS)
        if not (is_dm or mentioned or is_voice_cmd or message.channel.id in config.DISCORD_CHANNEL_IDS):
            return

        if not is_owner:
            if not config.DISCORD_ALLOW_GUESTS:
                return
            now = time.monotonic()
            if now - self._last_guest_msg.get(message.author.id, 0.0) < config.DISCORD_GUEST_COOLDOWN:
                return
            self._last_guest_msg[message.author.id] = now

        key = self._key(message.author.id, is_owner)

        if text.lower() in RESET_WORDS:
            self.brain.reset(key)
            await message.reply("Память диалога очищена.", mention_author=False)
            return

        if is_owner and cmd in JOIN_WORDS:
            await message.reply(await self._join(message), mention_author=False)
            return
        if is_owner and cmd in LEAVE_WORDS:
            await message.reply(await self._leave(message), mention_author=False)
            return
        if is_owner and cmd in SAY_WORDS:
            vc = self._voice_target(message, True)
            if vc is None:
                await message.reply("Я не в голосовом канале — сначала «!зайди».", mention_author=False)
            elif not arg.strip():
                await message.reply("Что сказать? Например: «!скажи всем привет».", mention_author=False)
            elif not is_safe_message(arg):
                await message.reply("Такое я вслух не скажу.", mention_author=False)
            else:
                self._spawn(self.speak_in_voice(vc, arg.strip()))
            return

        files: list[tuple] = []
        problems: list[str] = []
        for att in message.attachments[:MAX_FILES]:
            if att.size > MAX_FILE_BYTES:
                problems.append(f"{att.filename}: слишком большой")
                continue
            try:
                files.append((await att.read(), att.content_type or "", att.filename))
            except Exception as e:  # noqa: BLE001
                log.info("Не удалось скачать вложение: %s", e)
                problems.append(f"{att.filename}: не удалось скачать")
        if problems:
            text += "\n(Не удалось приложить: " + "; ".join(problems) + ")"
        if not text.strip() and not files:
            return

        try:
            async with message.channel.typing():
                reply = await self.brain.generate_response(
                    key, text, config.OWNER_NAME,
                    is_owner=is_owner,
                    allow_terminal=is_owner and config.DISCORD_ALLOW_TERMINAL,
                    speaker_label="" if is_owner else message.author.display_name,
                    files=files,
                )
        except Exception:  # noqa: BLE001
            log.exception("Ошибка при обработке сообщения")
            reply = "Что-то пошло не так на моей стороне."

        vc = self._voice_target(message, is_owner)
        if vc is not None and reply:
            self._spawn(self.speak_in_voice(vc, reply))       # говорит параллельно с отправкой текста

        first = True
        for chunk in _chunks(reply):
            if first:
                await message.reply(chunk, mention_author=False)
                first = False
            else:
                await message.channel.send(chunk)


# Запущенный бот — чтобы main.py мог написать владельцу (утренний брифинг) без знания подробностей.
_instance: Optional[AkiraDiscord] = None


async def dm_owner(text: str) -> bool:
    return await _instance.dm_owner(text) if _instance is not None else False


async def dm_owner_photo(data: bytes, filename: str, caption: str = "") -> bool:
    return await _instance.dm_owner_photo(data, filename, caption) if _instance is not None else False


async def run_discord(brain: Brain) -> None:
    global _instance
    if not config.DISCORD_BOT_TOKEN:
        log.info("DISCORD_BOT_TOKEN не задан — Discord-бот выключен.")
        return
    if not config.DISCORD_OWNER_ID:
        log.warning("DISCORD_OWNER_ID не задан — владельца нет, все будут гостями (без инструментов).")
    bot = AkiraDiscord(brain)
    _instance = bot
    try:
        await bot.start(config.DISCORD_BOT_TOKEN)
    finally:
        _instance = None
        await bot.close()
