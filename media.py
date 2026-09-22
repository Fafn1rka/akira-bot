"""
Работа со звуком и видео (одинаково на Windows / Linux / macOS).

• find_ffmpeg()          — ищет ffmpeg: переменная FFMPEG_BINARY → системный → из pip-пакета
                           imageio-ffmpeg (ставится сам, отдельно ничего качать не нужно);
• decode_pcm()           — mp3/ogg → моно PCM (numpy int16);
• loudness_envelope()    — «громкость по кадрам» 0..1 (двигает нимб и пламя при речи);
• render_video_note()    — собирает круглое видео-сообщение Telegram: анимированная
                           Акира + её голос.
"""
from __future__ import annotations

import logging
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional, Tuple

import numpy as np

log = logging.getLogger("akira.media")

_IS_WIN = os.name == "nt"
_NOWIN = {"creationflags": subprocess.CREATE_NO_WINDOW} if _IS_WIN else {}
_ffmpeg_cache: Optional[str] = None
_ffmpeg_checked = False


def find_ffmpeg() -> Optional[str]:
    global _ffmpeg_cache, _ffmpeg_checked
    if _ffmpeg_checked:
        return _ffmpeg_cache
    _ffmpeg_checked = True
    cand = os.getenv("FFMPEG_BINARY", "").strip()
    if cand and Path(cand).exists():
        _ffmpeg_cache = cand
        return cand
    sysbin = shutil.which("ffmpeg")
    if sysbin:
        _ffmpeg_cache = sysbin
        return sysbin
    try:
        import imageio_ffmpeg  # type: ignore

        _ffmpeg_cache = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:  # noqa: BLE001
        log.info("ffmpeg не найден (%s). Видео-кружки и огибающая голоса будут отключены.", e)
        _ffmpeg_cache = None
    return _ffmpeg_cache


def decode_pcm(path: str | Path, sr: int = 16000) -> Optional[np.ndarray]:
    """Файл любого аудио-формата -> моно int16 PCM. None, если ffmpeg недоступен."""
    ff = find_ffmpeg()
    if not ff:
        return None
    cmd = [ff, "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", str(sr), "-"]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=60, **_NOWIN)
    except Exception as e:  # noqa: BLE001
        log.warning("decode_pcm: %s", e)
        return None
    if out.returncode != 0 or not out.stdout:
        log.warning("decode_pcm: ffmpeg код %s: %s", out.returncode, out.stderr[-200:])
        return None
    return np.frombuffer(out.stdout, dtype=np.int16)


def to_wav(src: str | Path, dst: str | Path, sr: int = 44100) -> bool:
    """mp3 -> wav (WAV проигрывается везде надёжнее, чем mp3)."""
    ff = find_ffmpeg()
    if not ff:
        return False
    cmd = [ff, "-y", "-v", "error", "-i", str(src), "-ac", "2", "-ar", str(sr), str(dst)]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=60, **_NOWIN)
        return r.returncode == 0 and Path(dst).exists()
    except Exception as e:  # noqa: BLE001
        log.warning("to_wav: %s", e)
        return False


def loudness_envelope(pcm: np.ndarray, sr: int, fps: float) -> np.ndarray:
    """
    Громкость по кадрам 0..1 (float32). Быстрая атака, плавное затухание —
    так пламя «вспыхивает» на слогах и мягко гаснет в паузах.
    """
    if pcm is None or len(pcm) == 0:
        return np.zeros(1, np.float32)
    x = pcm.astype(np.float32) / 32768.0
    win = max(1, int(round(sr / fps)))
    n = int(math.ceil(len(x) / win))
    x = np.pad(x, (0, n * win - len(x)))
    rms = np.sqrt((x.reshape(n, win) ** 2).mean(axis=1))
    ref = float(np.percentile(rms, 95)) or 1e-6
    env = np.clip(rms / ref, 0.0, 1.0) ** 0.85
    env[rms < 0.004] = 0.0
    out = np.zeros_like(env)
    v = 0.0
    for i, e in enumerate(env):
        v = e if e > v else v * 0.72 + e * 0.28
        out[i] = v
    return out.astype(np.float32)


def synthetic_envelope(seconds: float, fps: float) -> np.ndarray:
    """Запасной вариант, если аудио не удалось декодировать: «правдоподобное» дыхание речи."""
    n = max(1, int(seconds * fps))
    t = np.arange(n) / fps
    e = 0.45 + 0.30 * np.sin(t * 9.0) + 0.20 * np.sin(t * 3.7 + 1.0)
    return np.clip(e, 0.05, 1.0).astype(np.float32)


# ------------------------------------------------------------------- видео
def render_video_note(
    audio_path: str | Path,
    out_path: str | Path,
    size: int = 384,
    fps: int = 24,
    tail: float = 0.35,
    progress: Optional[Callable[[float], None]] = None,
) -> Optional[float]:
    """
    Круглое видео-сообщение: анимированная Акира произносит аудио.
    Возвращает длительность в секундах или None при неудаче.
    Работает синхронно (вызывайте через asyncio.to_thread).
    """
    ff = find_ffmpeg()
    if not ff:
        return None
    from character import CharacterRenderer, SPEAKING, IDLE, video_view  # локально: тяжёлый импорт

    pcm = decode_pcm(audio_path, sr=16000)
    if pcm is None or len(pcm) == 0:
        return None
    dur = len(pcm) / 16000.0
    env = loudness_envelope(pcm, 16000, fps)
    n_frames = int(math.ceil((dur + tail) * fps))

    rend = CharacterRenderer(size, view=video_view(), transparent=False)
    size_h = rend.out_h

    codecs = ("libx264", "libopenh264", "mpeg4")
    last_err = ""
    for codec in codecs:
        cmd = [
            ff, "-y", "-v", "error",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{rend.out_w}x{size_h}", "-r", str(fps), "-i", "-",
            "-i", str(audio_path),
            "-c:v", codec, "-pix_fmt", "yuv420p",
        ]
        if codec == "libx264":
            cmd += ["-preset", "veryfast", "-crf", "27"]
        else:
            cmd += ["-b:v", "700k"]
        cmd += ["-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(out_path)]

        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, **_NOWIN)
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            continue
        try:
            assert proc.stdin is not None
            for i in range(n_frames):
                t = i / fps
                lvl = float(env[i]) if i < len(env) else 0.0
                state = SPEAKING if t < dur else IDLE
                frame = rend.render(t + 0.37, state, lvl)   # смещение t — чтобы старт не был «на нуле»
                proc.stdin.write(frame.tobytes())
                if progress and i % 12 == 0:
                    progress(i / n_frames)
            proc.stdin.close()
            err = proc.stderr.read().decode("utf-8", "ignore") if proc.stderr else ""
            code = proc.wait(timeout=120)
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
            continue
        if code == 0 and Path(out_path).exists() and Path(out_path).stat().st_size > 1000:
            return n_frames / fps
        last_err = err[-300:]
        log.info("кодек %s не сработал: %s", codec, last_err)

    log.warning("render_video_note: не удалось собрать видео (%s)", last_err)
    return None


def to_ogg_opus(src: str | Path, dst: str | Path) -> bool:
    """mp3 -> ogg/opus — «родной» формат голосовых сообщений Telegram (с волной)."""
    ff = find_ffmpeg()
    if not ff:
        return False
    cmd = [ff, "-y", "-v", "error", "-i", str(src), "-c:a", "libopus", "-b:a", "48k", "-ar", "48000",
          "-ac", "1", str(dst)]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=60, **_NOWIN)
        return r.returncode == 0 and Path(dst).exists()
    except Exception as e:  # noqa: BLE001
        log.warning("to_ogg_opus: %s", e)
        return False


def cleanup(*paths: Optional[str | Path]) -> None:
    for p in paths:
        try:
            if p and Path(p).exists():
                Path(p).unlink()
        except Exception:  # noqa: BLE001
            pass
