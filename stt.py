"""
Распознавание речи — один модуль на всех (микрофон, голосовые из Telegram).

Два движка на выбор (STT_ENGINE в .env):
  google  — онлайн, без ключа, ставить почти нечего (пакет SpeechRecognition). Нужен интернет,
            на длинных/тихих фразах ошибается чаще, у сервиса есть неофициальный лимит запросов.
  whisper — ЛОКАЛЬНО (пакет faster-whisper): без интернета, заметно точнее, не зависит от лимитов.
            Минус: при первом запуске скачивает модель (small ≈ 500 МБ) и грузит процессор.
  auto    — whisper, если установлен, иначе google (по умолчанию).

Звук везде один и тот же: float32, моно, 16 кГц, значения от -1 до 1.
"""
from __future__ import annotations

import importlib.util
import logging
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np

import config

log = logging.getLogger("akira.stt")

SAMPLE_RATE = 16000

# Whisper на тишине и шуме любит «дорисовывать» одни и те же фразы — выбрасываем их.
_HALLUCINATIONS = (
    "субтитры сделал", "субтитры создавал", "редактор субтитров", "продолжение следует",
    "спасибо за просмотр", "подписывайтесь на канал", "dimatorzok", "amara.org",
    "thanks for watching", "thank you for watching",
)


def _has(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def is_available() -> bool:
    """Есть ли хоть один движок (сам микрофон проверяет voice_listener)."""
    return _has("faster_whisper") or _has("speech_recognition")


# ------------------------------------------------------------------ движки
class _GoogleEngine:
    name = "google"

    def __init__(self) -> None:
        import speech_recognition as sr
        self._sr = sr
        self._rec = sr.Recognizer()
        self._last_warn = 0.0

    def transcribe(self, audio: np.ndarray) -> str:
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
        data = self._sr.AudioData(pcm, SAMPLE_RATE, 2)
        try:
            return self._rec.recognize_google(data, language=config.VOICE_INPUT_LANG)
        except self._sr.UnknownValueError:
            return ""                      # речи не разобрать — обычное дело
        except self._sr.RequestError as e:
            if time.time() - self._last_warn > 60:      # не спамить в лог
                self._last_warn = time.time()
                log.warning("Google-распознавание недоступно (нет интернета?): %s", e)
            return ""
        except Exception as e:  # noqa: BLE001
            log.info("Google-распознавание: %s", e)
            return ""


class _WhisperEngine:
    name = "whisper"

    def __init__(self) -> None:
        from faster_whisper import WhisperModel
        log.info("Загружаю модель распознавания речи «%s» (%s). При первом запуске она скачивается — "
                 "это может занять несколько минут...", config.WHISPER_MODEL, config.WHISPER_DEVICE)
        self._model = WhisperModel(config.WHISPER_MODEL, device=config.WHISPER_DEVICE,
                                   compute_type=config.WHISPER_COMPUTE)
        self._lock = threading.Lock()
        log.info("Модель распознавания готова.")

    def transcribe(self, audio: np.ndarray) -> str:
        lang_cfg = config.VOICE_INPUT_LANG.lower()
        lang = None if lang_cfg == "auto" else lang_cfg[:2]
        hint = config.WAKE_WORDS[0].capitalize() if config.WAKE_WORDS else None   # подсказка: имя «Акира»
        try:
            with self._lock:
                segments, _ = self._model.transcribe(
                    audio.astype(np.float32), language=lang, beam_size=1, vad_filter=True,
                    condition_on_previous_text=False, initial_prompt=hint)
                # мусорные «дорисованные» сегменты выбрасываем по одному — настоящая речь рядом остаётся
                parts = [t for t in (s.text.strip() for s in segments)
                         if t and not any(h in t.lower() for h in _HALLUCINATIONS)]
        except Exception as e:  # noqa: BLE001
            log.warning("Whisper: ошибка распознавания: %s", e)
            return ""
        return " ".join(parts).strip()


# --------------------------------------------------------------- выбор
_engine = None
_engine_lock = threading.Lock()
_engine_tried = False


def get_engine():
    """Создаёт (один раз) выбранный движок. None, если ни один не заработал.
    Whisper грузится долго — вызывай из фонового потока, не из основного цикла."""
    global _engine, _engine_tried
    with _engine_lock:
        if _engine is not None or _engine_tried:
            return _engine
        _engine_tried = True
        want = config.STT_ENGINE
        order = ["google"] if want == "google" else ["whisper", "google"]
        if want == "whisper" and not _has("faster_whisper"):
            log.warning("STT_ENGINE=whisper, но faster-whisper не установлен "
                        "(pip install faster-whisper) — использую Google.")
        for name in order:
            try:
                if name == "whisper" and _has("faster_whisper"):
                    _engine = _WhisperEngine()
                elif name == "google" and _has("speech_recognition"):
                    _engine = _GoogleEngine()
                else:
                    continue
                log.info("Распознавание речи: %s.", _engine.name)
                return _engine
            except Exception as e:  # noqa: BLE001
                log.warning("Движок распознавания «%s» не запустился: %s", name, e)
        log.warning("Ни один движок распознавания речи не доступен.")
        return None


def transcribe(audio: np.ndarray) -> str:
    """float32 моно 16 кГц -> текст ('' если не разобрала)."""
    engine = get_engine()
    if engine is None or audio is None or len(audio) == 0:
        return ""
    return engine.transcribe(audio)


def transcribe_file(path: str | Path) -> str:
    """Любой аудиофайл (ogg из Telegram, mp3, wav...) -> текст. Нужен ffmpeg (ставится через imageio-ffmpeg)."""
    import media
    pcm = media.decode_pcm(path, SAMPLE_RATE)
    if pcm is None or len(pcm) == 0:
        return ""
    return transcribe(pcm.astype(np.float32) / 32768.0)
