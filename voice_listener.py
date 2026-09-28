"""
Слушает микрофон, ждёт слово «Акира» и передаёт распознанную фразу дальше.

Что изменилось по сравнению с первой версией:
  • микрофон читается через sounddevice — НЕ нужен PyAudio (его на Windows чаще всего и не удаётся
    поставить). sounddevice приносит PortAudio внутри себя;
  • пока Акира сама говорит (и ещё чуть-чуть после), микрофон «глохнет» — иначе через колонки она
    слышит свой голос и начинает разговаривать сама с собой;
  • можно выбрать микрофон (VOICE_MIC_DEVICE) и посмотреть список: `python voice_listener.py --devices`;
  • распознавание — Google онлайн или локальный Whisper (см. stt.py);
  • имя «Акира» находится и с небольшими ошибками распознавания («акиры», «акеро»...).

Работает в отдельном потоке, наружу отдаёт события колбэками — не блокирует бота.
Если микрофона или пакетов нет — модуль тихо отключается (is_available() == False), остальной
бот работает как обычно.

Проверка микрофона без запуска всей Акиры:   python voice_listener.py --test
"""
from __future__ import annotations

import asyncio
import difflib
import logging
import re
import sys
import threading
import time
from collections import deque
from typing import Optional

import numpy as np

import config
import stt
import voice

log = logging.getLogger("akira.ears")

SR = config.MIC_SAMPLE_RATE      # 16000 — то, что ждут оба движка распознавания
BLOCK = 512                      # 32 мс на блок
_SILENCE_END = 0.7               # секунд тишины = фраза закончилась
_MAX_PHRASE = 12.0               # длиннее не пишем
_MIN_SPEECH = 0.25               # короче — это щелчок, а не речь (короткое «да» ~0.3 с проходит)
_MIN_THRESHOLD = 150.0

_WAKE_WORDS = tuple(config.WAKE_WORDS) or ("акира", "akira")
_WAKE_RE = re.compile(r"(?<!\w)(" + "|".join(re.escape(w) for w in _WAKE_WORDS) + r")(?!\w)", re.IGNORECASE)


# ---------------------------------------------------------------- «Акира»
def strip_wake_word(text: str) -> str:
    return _WAKE_RE.sub("", text, count=1).strip(" ,.!—-")


def find_wake(text: str) -> tuple[bool, str]:
    """(услышано ли имя, фраза без имени). Точное совпадение — где угодно во фразе;
    приблизительное («акиры», «акеро») — только в первых трёх словах, чтобы не было ложных срабатываний."""
    if _WAKE_RE.search(text):
        return True, strip_wake_word(text)
    for w in re.findall(r"\w+", text)[:3]:
        low = w.lower().replace("ё", "е")
        if any(difflib.SequenceMatcher(None, low, ww).ratio() >= 0.8 for ww in _WAKE_WORDS):
            rest = re.sub(r"(?<!\w)" + re.escape(w) + r"(?!\w)", "", text, count=1)
            return True, rest.strip(" ,.!—-")
    return False, text


# ------------------------------------------------------------- микрофон
def _pick_device(spec: str):
    """'' -> микрофон по умолчанию; '3' -> устройство №3; 'Realtek' -> первое, в названии которого есть это."""
    if not spec:
        return None
    if spec.isdigit():
        return int(spec)
    import sounddevice as sd
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0 and spec.lower() in d["name"].lower():
            return i
    log.warning("Микрофон «%s» не найден — беру устройство по умолчанию.", spec)
    return None


def is_available() -> bool:
    if not config.VOICE_INPUT_ENABLED or not stt.is_available():
        return False
    try:
        import sounddevice as sd
        return any(d["max_input_channels"] > 0 for d in sd.query_devices())
    except Exception:  # noqa: BLE001
        return False


def _rms(block: np.ndarray) -> float:
    return float(np.sqrt(np.mean(block.astype(np.float32) ** 2)))


class VoiceListener:
    """
    on_heard(text)      — вызывается (из фонового потока!) когда распознана фраза
                           уже после «Акиры» (или в течение окна продолжения разговора)
    on_wake()           — вызывается сразу в момент, когда услышано только «Акира»
    on_state(listening) — True/False, распознаёт ли сейчас (для анимации персонажа)
    """

    def __init__(self, on_heard, on_wake=None, on_state=None):
        self._on_heard = on_heard
        self._on_wake = on_wake
        self._on_state = on_state
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_wake_ts = 0.0
        self._noise = 100.0                       # оценка фонового шума
        self._fixed = config.VOICE_ENERGY_THRESHOLD > 0

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

    # ----------------------------------------------------------- порог
    @property
    def threshold(self) -> float:
        if self._fixed:
            return config.VOICE_ENERGY_THRESHOLD
        return max(_MIN_THRESHOLD, self._noise * 3.0)

    def _calibrate(self, stream) -> None:
        levels = [_rms(stream.read(BLOCK)[0]) for _ in range(int(SR / BLOCK))]      # ~1 секунда тишины
        self._noise = float(np.median(levels))
        log.info("Микрофон: фоновый шум %.0f, порог речи %.0f%s.", self._noise, self.threshold,
                 " (задан вручную)" if self._fixed else " (подобран автоматически)")

    # ----------------------------------------------------------- запись
    @staticmethod
    def _flush(stream) -> None:
        try:
            n = stream.read_available
            if n:
                stream.read(n)
        except Exception:  # noqa: BLE001
            pass

    def _record(self, stream) -> Optional[np.ndarray]:
        """Ждёт фразу и возвращает её float32 [-1..1]. None — шум/щелчок/или нас остановили."""
        pre: deque = deque(maxlen=8)               # чуть звука ДО речи, чтобы не срезать первый слог
        frames: list = []
        pre_len = 0                                # сколько блоков в начале — это тишина ДО речи
        speaking = False
        silence = 0
        silence_blocks = int(_SILENCE_END * SR / BLOCK)
        max_blocks = int(_MAX_PHRASE * SR / BLOCK)

        while not self._stop.is_set():
            if voice.is_speaking():                # Акира говорит — не слушаем саму себя
                self._flush(stream)
                pre.clear()
                frames, speaking, silence = [], False, 0
                time.sleep(0.05)
                continue

            block = stream.read(BLOCK)[0][:, 0].copy()
            level = _rms(block)
            loud = level > self.threshold

            if not speaking:
                if not loud and not self._fixed:   # медленно подстраиваемся под шум комнаты
                    self._noise = 0.98 * self._noise + 0.02 * level
                pre.append(block)
                if loud:
                    speaking = True
                    frames = list(pre)
                    pre_len = len(frames) - 1      # последний блок буфера — уже громкий, он часть речи
            else:
                frames.append(block)
                silence = 0 if loud else silence + 1
                if silence >= silence_blocks or len(frames) >= max_blocks:
                    break
        else:
            return None

        if (len(frames) - pre_len - silence) * BLOCK / SR < _MIN_SPEECH:
            return None
        return np.concatenate(frames).astype(np.float32) / 32768.0

    # ------------------------------------------------------------ поток
    def _run(self) -> None:
        import sounddevice as sd

        engine = stt.get_engine()                  # Whisper грузится тут, в фоне
        if engine is None:
            log.warning("Нет движка распознавания речи — голосовой ввод выключен.")
            return
        try:
            stream = sd.InputStream(samplerate=SR, channels=1, dtype="int16", blocksize=BLOCK,
                                    device=_pick_device(config.VOICE_MIC_DEVICE))
        except Exception as e:  # noqa: BLE001
            log.warning("Не смогла открыть микрофон: %s", e)
            return

        try:
            with stream:
                self._calibrate(stream)
                log.info("Слушаю микрофон (слово для пробуждения — «%s», распознаю: %s)...",
                         _WAKE_WORDS[0].capitalize(), engine.name)
                while not self._stop.is_set():
                    try:
                        audio = self._record(stream)
                    except Exception as e:  # noqa: BLE001
                        log.warning("Ошибка записи с микрофона: %s", e)
                        time.sleep(1.0)
                        continue
                    if audio is None:
                        continue

                    self._set_state(True)
                    try:
                        text = engine.transcribe(audio)
                    except Exception as e:  # noqa: BLE001
                        log.warning("Ошибка распознавания: %s", e)
                        text = ""
                    self._set_state(False)
                    if text:
                        self._dispatch(text)
        except Exception as e:  # noqa: BLE001
            log.warning("Голосовой ввод остановлен: %s", e)

    def _dispatch(self, text: str) -> None:
        in_window = (time.time() - self._last_wake_ts) < config.VOICE_CONVERSATION_WINDOW
        has_wake, phrase = find_wake(text)

        if has_wake:
            self._last_wake_ts = time.time()
            if phrase:
                self._safe_call(self._on_heard, phrase)
            else:
                self._safe_call(self._on_wake)
        elif in_window or not config.VOICE_WAKE_WORD_REQUIRED:
            self._safe_call(self._on_heard, text)
        # иначе — фоновая речь без «Акиры», игнорируем

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


# ------------------------------------------------------- проверка микрофона
def _cli() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    if "--devices" in sys.argv:
        import sounddevice as sd
        print("Устройства ввода (номер — для VOICE_MIC_DEVICE в .env):\n")
        default_in = sd.default.device[0]
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                mark = "  <- по умолчанию" if i == default_in else ""
                print(f"  {i}: {d['name']}{mark}")
        return

    print("Проверка микрофона. Говори что-нибудь — увидишь, что я услышала. Ctrl+C — выход.")
    print(f"Слово «{_WAKE_WORDS[0].capitalize()}» для проверки не нужно.\n")
    config.VOICE_WAKE_WORD_REQUIRED = False
    listener = VoiceListener(
        on_heard=lambda t: print(f"  услышала: {t}"),
        on_wake=lambda: print("  услышала только имя"),
        on_state=lambda s: print("  ... распознаю") if s else None,
    )
    if not listener.start():
        print("Не получилось: нет микрофона, пакетов (sounddevice, SpeechRecognition или faster-whisper) "
              "или VOICE_INPUT_ENABLED=false.")
        return
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        listener.stop()


if __name__ == "__main__":
    _cli()
