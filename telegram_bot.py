"""
Telegram-бот Акиры. Отвечает видео-«кружком» (говорящий персонаж), голосовым
или текстом — на выбор в .env (TELEGRAM_REPLY_MODE). Понимает и голосовые
сообщения от пользователя.

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
import voice
from brain import Brain

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

    def available(self) -> bool:
        return Application is not None and bool(config.TELEGRAM_BOT_TOKEN)

    def build(self) -> "Application":
        app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", self._cmd_start))
        app.add_handler(CommandHandler("id", self._cmd_id))
        app.add_handler(CommandHandler("reset", self._cmd_reset))
        app.add_handler(CommandHandler("mode", self._cmd_mode))
        app.add_handler(MessageHandler(filters.VOICE & filters.ChatType.PRIVATE, self._on_voice))
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
        allowed, _ = _access(update.effective_chat.id)
        if not allowed:
            return
        self.brain.reset(f"tg:{update.effective_chat.id}")
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
                "Не смогла разобрать голосовое — для распознавания речи нужен пакет "
                "SpeechRecognition (см. requirements.txt) и интернет. Напиши текстом?")
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
                      chat_id: int, is_owner: bool) -> None:
        await ctx.bot.send_chat_action(chat_id, constants.ChatAction.TYPING)
        label = "" if is_owner else (update.effective_user.first_name or "гость")
        reply = await self.brain.generate_response(
            key=f"tg:{chat_id}", message=text, owner_name=config.OWNER_NAME,
            is_owner=is_owner, allow_terminal=is_owner, speaker_label=label,
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
    try:
        import speech_recognition as sr
    except ImportError:
        return ""
    wav_path = ogg_path + ".wav"
    if not media.to_wav(ogg_path, wav_path, sr=16000):
        return ""
    try:
        r = sr.Recognizer()
        with sr.AudioFile(wav_path) as src:
            audio = r.record(src)
        return r.recognize_google(audio, language="ru-RU")
    except Exception as e:  # noqa: BLE001
        log.info("распознавание голосового не удалось: %s", e)
        return ""
    finally:
        media.cleanup(wav_path)
