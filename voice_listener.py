"""
Слушает микрофон, ждёт слово «Акира» и передаёт распознанную фразу дальше.

Работает в отдельном потоке (blocking-библиотеки speech_recognition это
требуют), наружу отдаёт события через asyncio.Queue — не блокирует бота.

Если пакетов speech_recognition/PyAudio нет или микрофона нет вовсе —
модуль тихо отключается (is_available() == False), остальной бот работает
как обычно (можно печатать текстом).
"""
from __future__ import annotations

import asyncio
import logging
import queue
import re
import threading
import time
from typing import Optional

import config

log = logging.getLogger("akira.ears")

_WAKE_WORDS = ("акира", "акіра", "akira")
_WAKE_RE = re.compile(r"\b(" + "|".join(_WAKE_WORDS) + r")\b", re.IGNORECASE)


def is_available() -> bool:
    if not config.VOICE_INPUT_ENABLED:
        return False
    try:
        import speech_recognition  # noqa: F401
    except ImportError:
        return False
    try:
        import speech_recognition as sr
        return len(sr.Microphone.list_microphone_names()) > 0
    except Exception:  # noqa: BLE001
        return False


def strip_wake_word(text: str) -> str:
    return _WAKE_RE.sub("", text, count=1).strip(" ,.!—-")


class VoiceListener:
    """
    on_heard(text)      — вызывается (из фонового потока!) когда распознана фраза
                           уже после «Акиры» (или в течение окна продолжения разговора)
    on_wake()           — вызывается сразу в момент, когда услышано только «Акира»
    on_state(listening) — True/False, слушает ли сейчас (для анимации персонажа)
    """

    def __init__(self, on_heard, on_wake=None, on_state=None):
        self._on_heard = on_heard
        self._on_wake = on_wake
        self._on_state = on_state
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_wake_ts = 0.0

    def start(self) -> bool:
        if not is_available():
            log.info("Микрофон/распознавание недоступны — голосовой ввод выключен.")
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="akira-ears", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------ поток
    def _run(self) -> None:
        import speech_recognition as sr

        r = sr.Recognizer()
        r.energy_threshold = config.VOICE_ENERGY_THRESHOLD
        r.dynamic_energy_threshold = True
        r.pause_threshold = 0.7

        try:
            mic = sr.Microphone(sample_rate=config.MIC_SAMPLE_RATE)
        except Exception as e:  # noqa: BLE001
            log.warning("Не смогла открыть микрофон: %s", e)
            return

        with mic:
            try:
                r.adjust_for_ambient_noise(mic, duration=1.0)
            except Exception as e:  # noqa: BLE001
                log.info("adjust_for_ambient_noise: %s", e)

        log.info("Слушаю микрофон (слово для пробуждения — «Акира»)...")
        while not self._stop.is_set():
            try:
                with mic:
                    audio = r.listen(mic, timeout=4, phrase_time_limit=12)
            except sr.WaitTimeoutError:
                continue
            except Exception as e:  # noqa: BLE001
                log.warning("Ошибка записи с микрофона: %s", e)
                time.sleep(1.0)
                continue

            self._set_state(True)
            text = self._recognize(r, audio)
            self._set_state(False)
            if not text:
                continue

            in_window = (time.time() - self._last_wake_ts) < config.VOICE_CONVERSATION_WINDOW
            has_wake = bool(_WAKE_RE.search(text))

            if has_wake:
                self._last_wake_ts = time.time()
                phrase = strip_wake_word(text)
                if phrase:
                    self._safe_call(self._on_heard, phrase)
                else:
                    self._safe_call(self._on_wake)
            elif in_window or not config.VOICE_WAKE_WORD_REQUIRED:
                self._safe_call(self._on_heard, text)
            # иначе — фоновая речь без «Акиры», игнорируем

    def _recognize(self, r, audio) -> str:
        try:
            return r.recognize_google(audio, language="ru-RU")
        except Exception:  # noqa: BLE001 — тишина/шум/нет сети: это нормально, просто пропускаем
            return ""

    def _set_state(self, listening: bool) -> None:
        if self._on_state:
            self._safe_call(self._on_state, listening)

    @staticmethod
    def _safe_call(fn, *args) -> None:
        if fn is None:
            return
        try:
            fn(*args)
        except Exception as e:  # noqa: BLE001
            log.warning("Обработчик голосового события упал: %s", e)


def make_asyncio_bridge(loop: asyncio.AbstractEventLoop, on_heard_coro, on_wake_coro=None, on_state_coro=None
                        ) -> VoiceListener:
    """Удобный мост: колбэки из потока -> корутины в основном asyncio-цикле."""

    def _submit(coro_fn, *args) -> None:
        if coro_fn is None:
            return
        asyncio.run_coroutine_threadsafe(coro_fn(*args), loop)

    return VoiceListener(
        on_heard=lambda text: _submit(on_heard_coro, text),
        on_wake=lambda: _submit(on_wake_coro) if on_wake_coro else None,
        on_state=lambda listening: _submit(on_state_coro, listening) if on_state_coro else None,
    )
