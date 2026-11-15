"""Микрофон и выделение фраз (простой адаптивный VAD по громкости)."""
import queue
import time
from collections import deque

import numpy as np

SR = 16000
FRAME = 480  # 30 мс


class Segmenter:
    """Принимает кадры по 30 мс, возвращает готовую фразу (float32) или None."""

    def __init__(self, sr=SR, frame=FRAME, min_speech=0.35, end_silence=0.8, max_len=15.0,
                 preroll=0.3, start_frames=3, floor_min=0.008, mult=3.0, calib_frames=33):
        self.fs = frame / sr
        self.min_speech, self.max_len = min_speech, max_len
        self.end_frames = int(end_silence / self.fs)
        self.start_frames = start_frames
        self.floor_min, self.mult = floor_min, mult
        self.calib_frames = calib_frames
        self.preroll_n = int(preroll / self.fs)
        self.noise = None
        self._calib: list[float] = []
        self.reset()

    def reset(self):
        self.preroll = deque(maxlen=self.preroll_n)
        self.buf: list[np.ndarray] = []
        self.in_speech = False
        self.hot = 0
        self.silence = 0
        self.voiced = 0

    def feed(self, frame: np.ndarray):
        rms = float(np.sqrt(np.mean(frame * frame))) if len(frame) else 0.0
        if self.noise is None:  # калибровка шума ~1 сек
            self._calib.append(rms)
            if len(self._calib) >= self.calib_frames:
                self.noise = float(np.median(self._calib))
            return None
        thr = max(self.noise * self.mult, self.floor_min)

        if not self.in_speech:
            self.preroll.append(frame)
            if rms > thr:
                self.hot += 1
            else:
                self.hot = 0
                self.noise = 0.98 * self.noise + 0.02 * rms  # шум дрейфует
            if self.hot >= self.start_frames:
                self.in_speech = True
                self.buf = list(self.preroll)
                self.silence = 0
                self.voiced = self.hot
            return None

        self.buf.append(frame)
        self.silence = 0 if rms > thr else self.silence + 1
        if rms > thr:
            self.voiced += 1
        length = len(self.buf) * self.fs
        if self.silence >= self.end_frames or length >= self.max_len:
            seg = np.concatenate(self.buf) if self.voiced * self.fs >= self.min_speech else None
            self.reset()
            return seg
        return None


class Mic:
    def __init__(self, busy=lambda: False, device=None):
        self.busy = busy  # пока Акира говорит - микрофон «глохнет»
        self.device = device
        self.q: queue.Queue = queue.Queue()
        self.seg = Segmenter()
        self._stream = None

    def start(self):
        import sounddevice as sd
        self._stream = sd.InputStream(
            samplerate=SR, channels=1, dtype="float32", blocksize=FRAME, device=self.device,
            callback=lambda indata, frames, t, status: self.q.put(indata[:, 0].copy()))
        self._stream.start()

    def stop(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def next_utterance(self, timeout=None):
        """Ждёт следующую фразу. None - если за timeout секунд ничего не прозвучало."""
        deadline = None if timeout is None else time.time() + timeout
        while True:
            remaining = None if deadline is None else max(0.0, deadline - time.time())
            try:
                frame = self.q.get(timeout=remaining)
            except queue.Empty:
                return None
            if self.busy():
                self.seg.reset()
                continue
            out = self.seg.feed(frame)
            if out is not None:
                return out
            if deadline is not None and time.time() >= deadline:
                return None

    def utterances(self):
        self.start()
        try:
            while True:
                yield self.next_utterance()
        finally:
            self.stop()


def list_devices():
    import sounddevice as sd
    print(sd.query_devices())
