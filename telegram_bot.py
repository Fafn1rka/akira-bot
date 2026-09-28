"""
Telegram-бот Акиры. Отвечает видео-«кружком» (говорящий персонаж), голосовым
или текстом — на выбор в .env (TELEGRAM_REPLY_MODE). Понимает и голосовые
сообщения от пользователя.

Понимает и файлы: фото, документы (PDF, текстовые файлы и т.д.), аудио — можно прислать сразу
несколько (альбомом). Подпись к файлам считается вопросом. Всё это уходит модели вместе с текстом.

Права доступа:
  • владелец (TELEGRAM_OWNER_ID)      — полный доступ, включая управление ПК;
  • разрешённые (TELEGRAM_ALLOWED_IDS) и все (TELEGRAM_PUBLIC=true) — обычная
    болтовня, без доступа к компьютеру и без долгой памяти между сессиями
    сверх текущего разговора.
Отвечает только в личных сообщениях (группы игнорируются) — так проще не
превратить бота в случайный паблик-чат.
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Optional

import config
import media
import stt
import voice
from brain import MAX_FILE_BYTES, Brain

log = logging.getLogger("akira.telegram")

try:
    from telegram import Update, constants
    from telegram.ext import (Application, ApplicationBuilder, CommandHandler,
                              ContextTypes, MessageHandler, filters)
except ImportError:
    Application = None  # type: ignore


def _access(chat_id: int) -> tuple[bool, bool]:
    """-> (доступ_разрешён, это_владелец)"""
    if config.TELEGRAM_OWNER_ID and chat_id == config.TELEGRAM_OWNER_ID:
        return True, True
    if chat_id in config.TELEGRAM_ALLOWED_IDS:
        return True, False
    if config.TELEGRAM_PUBLIC:
        return True, False
    return False, False


class TelegramBot:
    def __init__(self, brain: Brain):
        self.brain = brain
        self.app: Optional["Application"] = None
        self._albums: dict[str, dict] = {}     # media_group_id -> накопленные файлы альбома
        self._tasks: set = set()               # ссылки на фоновые задачи (иначе их может съесть сборщик мусора)

    @staticmethod
    def _key(chat_id: int, is_owner: bool) -> str:
        """Владелец во всех каналах — один человек с одной памятью (если SHARED_OWNER_MEMORY=true)."""
        if is_owner and config.SHARED_OWNER_MEMORY:
            return config.OWNER_KEY
        return f"tg:{chat_id}"

    def available(self) -> bool:
        return Application is not None and bool(config.TELEGRAM_BOT_TOKEN)

    def build(self) -> "Application":
        app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", self._cmd_start))
        app.add_handler(CommandHandler("id", self._cmd_id))
        app.add_handler(CommandHandler("reset", self._cmd_reset))
        app.add_handler(CommandHandler("mode", self._cmd_mode))
        app.add_handler(MessageHandler(filters.VOICE & filters.ChatType.PRIVATE, self._on_voice))
        app.add_handler(MessageHandler(
            (filters.PHOTO | filters.Document.ALL | filters.AUDIO) & filters.ChatType.PRIVATE, self._on_media))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
                                       self._on_text))
        self.app = app
        return app

    # ------------------------------------------------------------ команды
    async def _cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        allowed, is_owner = _access(update.effective_chat.id)
        if not allowed:
            await update.message.reply_text(
                "Привет! Этот бот приватный — попроси владельца добавить твой ID в .env "
                f"(твой ID: {update.effective_chat.id}).")
            return
        who = "Создатель" if is_owner else "друг"
        await update.message.reply_text(f"Привет, {who}! Я Акира. Пиши или присылай голосовые — отвечу тем же.")

    async def _cmd_id(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(f"Твой chat_id: {update.effective_chat.id}")

    async def _cmd_reset(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        allowed, is_owner = _access(update.effective_chat.id)
        if not allowed:
            return
        self.brain.reset(self._key(update.effective_chat.id, is_owner))
        await update.message.reply_text("Хорошо, начнём с чистого листа.")

    async def _cmd_mode(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        allowed, is_owner = _access(update.effective_chat.id)
        if not (allowed and is_owner):
            return
        arg = (ctx.args[0].lower() if ctx.args else "")
        if arg not in ("video", "voice", "text"):
            await update.message.reply_text(f"Текущий режим ответа: {config.TELEGRAM_REPLY_MODE}. "
                                            f"Укажи /mode video|voice|text")
            return
        config.TELEGRAM_REPLY_MODE = arg
        await update.message.reply_text(f"Готово, теперь отвечаю: {arg}")

    # -------------------------------------------------------------- ввод
    async def _on_voice(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        allowed, is_owner = _access(chat_id)
        if not allowed:
            return
        await ctx.bot.send_chat_action(chat_id, constants.ChatAction.TYPING)
        tg_file = await ctx.bot.get_file(update.message.voice.file_id)
        with tempfile.TemporaryDirectory() as td:
            ogg = Path(td) / "in.ogg"
            await tg_file.download_to_drive(str(ogg))
            text = await asyncio.to_thread(_transcribe, str(ogg))
        if not text:
            await update.message.reply_text(
                "Не смогла разобрать голосовое — для распознавания речи нужен пакет SpeechRecognition "
                "(или faster-whisper), ffmpeg и, для режима google, интернет. Напиши текстом?")
            return
        await self._handle(update, ctx, text, chat_id, is_owner)

    async def _on_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        allowed, is_owner = _access(chat_id)
        if not allowed:
            await update.message.reply_text(
                f"Извини, это приватный бот. Твой ID: {chat_id} — можешь попросить владельца добавить тебя.")
            return
        await self._handle(update, ctx, update.message.text, chat_id, is_owner)

    # -------------------------------------------------------------- ядро
    async def _handle(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE, text: str,
                      chat_id: int, is_owner: bool, files: Optional[list] = None) -> None:
        await ctx.bot.send_chat_action(chat_id, constants.ChatAction.TYPING)
        label = "" if is_owner else (update.effective_user.first_name or "гость")
        reply = await self.brain.generate_response(
            key=self._key(chat_id, is_owner), message=text, owner_name=config.OWNER_NAME,
            is_owner=is_owner, allow_terminal=is_owner, speaker_label=label, files=files,
        )
        if not reply:
            return

        if is_owner and config.DESKTOP_SPEAKS_TELEGRAM:
            asyncio.create_task(voice.speak(reply))

        mode = config.TELEGRAM_REPLY_MODE
        sent_media = False
        if mode in ("video", "voice"):
            sent_media = await self._reply_media(update, ctx, reply, mode)
        if not sent_media or (mode != "text" and config.TELEGRAM_TEXT_WITH_MEDIA):
            await update.message.reply_text(reply)

    # ------------------------------------------------------ файлы и альбомы
    async def _download(self, ctx: ContextTypes.DEFAULT_TYPE, msg) -> tuple[Optional[tuple], str]:
        """Скачивает вложение сообщения -> ((байты, mime, имя) | None, пометка о проблеме)."""
        if msg.photo:
            ph = msg.photo[-1]                       # самая большая копия фото
            fid, mime, name, size = ph.file_id, "image/jpeg", f"фото_{ph.file_unique_id}.jpg", ph.file_size
        elif msg.document:
            d = msg.document
            fid, mime, name, size = d.file_id, d.mime_type or "", d.file_name or "файл", d.file_size
        elif msg.audio:
            a = msg.audio
            fid, mime, name, size = a.file_id, a.mime_type or "", a.file_name or "аудио", a.file_size
        else:
            return None, ""
        if size and size > MAX_FILE_BYTES:
            return None, f"{name}: слишком большой (максимум {MAX_FILE_BYTES // 1024 // 1024} МБ)"
        try:
            tg_file = await ctx.bot.get_file(fid)
            data = bytes(await tg_file.download_as_bytearray())
        except Exception as e:  # noqa: BLE001
            log.info("Не удалось скачать файл из Telegram: %s", e)
            return None, f"{name}: не удалось скачать"
        return (data, mime, name), ""

    async def _on_media(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.message
        chat_id = update.effective_chat.id
        allowed, is_owner = _access(chat_id)
        if not allowed:
            return
        await ctx.bot.send_chat_action(chat_id, constants.ChatAction.UPLOAD_DOCUMENT)
        item, problem = await self._download(ctx, msg)
        gid = msg.media_group_id

        if not gid:                                  # одиночный файл — отвечаем сразу
            text = msg.caption or ""
            if problem:
                text += f"\n(Не удалось приложить: {problem})"
            await self._handle(update, ctx, text, chat_id, is_owner, files=[item] if item else [])
            return

        # альбом: Telegram присылает каждый файл отдельным сообщением — копим 1.5 секунды и отвечаем один раз
        buf = self._albums.get(gid)
        if buf is None:
            buf = self._albums[gid] = {"files": [], "caption": "", "problems": []}
            task = asyncio.create_task(self._flush_album(gid, update, ctx, chat_id, is_owner))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        if item:
            buf["files"].append(item)
        if problem:
            buf["problems"].append(problem)
        if msg.caption:
            buf["caption"] = msg.caption

    async def _flush_album(self, gid: str, update: Update, ctx: ContextTypes.DEFAULT_TYPE,
                           chat_id: int, is_owner: bool) -> None:
        await asyncio.sleep(1.5)
        buf = self._albums.pop(gid, None)
        if not buf:
            return
        text = buf["caption"]
        if buf["problems"]:
            text += "\n(Не удалось приложить: " + "; ".join(buf["problems"]) + ")"
        try:
            await self._handle(update, ctx, text, chat_id, is_owner, files=buf["files"])
        except Exception as e:  # noqa: BLE001
            log.warning("Не удалось ответить на альбом: %s", e)

    async def _reply_media(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE, text: str, mode: str) -> bool:
        chat_id = update.effective_chat.id
        mp3 = await voice.synthesize(text)
        if not mp3:
            return False
        try:
            if mode == "video":
                await ctx.bot.send_chat_action(chat_id, constants.ChatAction.RECORD_VIDEO_NOTE)
                out = Path(tempfile.mktemp(suffix=".mp4", dir=config.AUDIO_CACHE))
                dur = await asyncio.to_thread(media.render_video_note, str(mp3), str(out),
                                              config.TELEGRAM_VIDEO_SIZE)
                if not dur:
                    return False
                try:
                    with open(out, "rb") as f:
                        await ctx.bot.send_video_note(chat_id, f, duration=int(round(dur)),
                                                      length=config.TELEGRAM_VIDEO_SIZE)
                finally:
                    media.cleanup(out)
                return True
            if mode == "voice":
                await ctx.bot.send_chat_action(chat_id, constants.ChatAction.RECORD_VOICE)
                ogg = Path(tempfile.mktemp(suffix=".ogg", dir=config.AUDIO_CACHE))
                if not await asyncio.to_thread(media.to_ogg_opus, str(mp3), str(ogg)):
                    return False
                try:
                    with open(ogg, "rb") as f:
                        await ctx.bot.send_voice(chat_id, f)
                finally:
                    media.cleanup(ogg)
                return True
        except Exception as e:  # noqa: BLE001
            log.warning("Не удалось отправить медиа-ответ: %s", e)
            return False
        finally:
            media.cleanup(mp3)
        return False


def _transcribe(ogg_path: str) -> str:
    """Голосовое из Telegram -> текст (движок выбирается в .env: STT_ENGINE)."""
    try:
        return stt.transcribe_file(ogg_path)
    except Exception as e:  # noqa: BLE001
        log.info("распознавание голосового не удалось: %s", e)
        return ""
