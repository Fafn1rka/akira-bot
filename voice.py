"""
Голос Акиры: синтез речи через edge-tts (голоса Microsoft, ЖЕНСКИЕ) и
кроссплатформенное воспроизведение звука.

edge-tts бесплатен и не требует ключа, но требует интернет на момент
озвучивания. Если сети нет — вызывающий код получит False и покажет текст.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

import config

log = logging.getLogger("akira.voice")

_LANG_VOICES = {
    "ru": config.VOICE_AKIRA,
    "uk": config.VOICE_UKRAINIAN,
    "en": config.VOICE_ENGLISH,
}

_CYR_UK_ONLY = set("їієґ")
_NOWIN = {"creationflags": subprocess.CREATE_NO_WINDOW} if config.IS_WINDOWS else {}


def detect_lang(text: str) -> str:
    low = text.lower()
    if any(ch in low for ch in _CYR_UK_ONLY):
        return "uk"
    cyr = len(re.findall(r"[а-яёА-ЯЁ]", text))
    lat = len(re.findall(r"[a-zA-Z]", text))
    if lat > cyr and lat > 0:
        return "en"
    return "ru"


def pick_voice(text: str) -> str:
    return _LANG_VOICES.get(detect_lang(text), config.VOICE_AKIRA)


def _clean_for_speech(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\((?:https?://|www\.)[^)]+\)", r"\1", text)  # [текст](ссылка) -> текст
    text = re.sub(r"https?://\S+", "ссылка", text)
    text = re.sub(r"[*_`#>~]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > config.MAX_SPEECH_CHARS:
        cut = text[: config.MAX_SPEECH_CHARS]
        m = re.search(r"[.!?][^.!?]*$", cut)
        text = cut[: m.start() + 1] if m else cut
    return text


async def synthesize(text: str, out_path: Optional[str | Path] = None,
                     voice: Optional[str] = None) -> Optional[Path]:
    """Синтезирует речь в mp3-файл. None, если не получилось (нет сети/пакета)."""
    text = _clean_for_speech(text)
    if not text:
        return None
    try:
        import edge_tts  # type: ignore
    except ImportError:
        log.warning("edge-tts не установлен: pip install edge-tts")
        return None

    voice = voice or pick_voice(text)
    dst = Path(out_path) if out_path else Path(tempfile.mktemp(suffix=".mp3", dir=config.AUDIO_CACHE))
    try:
        comm = edge_tts.Communicate(text, voice, rate=config.VOICE_RATE, pitch=config.VOICE_PITCH)
        await comm.save(str(dst))
    except Exception as e:  # noqa: BLE001
        log.warning("edge-tts не смог озвучить (%s): %s", voice, e)
        return None
    if not dst.exists() or dst.stat().st_size < 200:
        return None
    return dst


async def play_audio(path: str | Path) -> bool:
    """Проигрывает звук, не блокируя event loop. True, если удалось запустить."""
    path = str(path)
    system_cmd = _player_command(path)
    if system_cmd:
        try:
            proc = await asyncio.create_subprocess_exec(
                *system_cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                **({"creationflags": subprocess.CREATE_NO_WINDOW} if config.IS_WINDOWS else {}))
            await proc.wait()
            return True
        except Exception as e:  # noqa: BLE001
            log.info("системный плеер не сработал (%s), пробую sounddevice", e)

    return await _play_with_sounddevice(path)


def _player_command(path: str) -> Optional[list[str]]:
    import shutil as _sh
    if config.IS_WINDOWS:
        return None  # для mp3 надёжнее sounddevice/afplay-аналога; сразу используем запасной путь
    if config.IS_MAC and _sh.which("afplay"):
        return ["afplay", path]
    if config.IS_LINUX:
        for exe, args in (("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"]),
                          ("mpg123", ["-q"]),
                          ("paplay", []),
                          ("aplay", [])):
            if _sh.which(exe):
                if exe == "aplay" and path.endswith(".mp3"):
                    continue  # aplay mp3 не умеет
                return [exe, *args, path]
    return None


async def _play_with_sounddevice(path: str) -> bool:
    try:
        import numpy as np
        import sounddevice as sd
        import media
    except ImportError:
        log.warning("Нет плеера для звука: поставь ffmpeg или пакет sounddevice.")
        return False

    def _blocking() -> bool:
        wav = Path(tempfile.mktemp(suffix=".wav", dir=config.AUDIO_CACHE))
        try:
            if not media.to_wav(path, wav):
                return False
            import wave
            with wave.open(str(wav), "rb") as w:
                sr = w.getframerate()
                ch = w.getnchannels()
                raw = w.readframes(w.getnframes())
            data = np.frombuffer(raw, dtype=np.int16).reshape(-1, ch).astype(np.float32) / 32768.0
            sd.play(data, sr)
            sd.wait()
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("sounddevice playback: %s", e)
            return False
        finally:
            wav.unlink(missing_ok=True)

    return await asyncio.to_thread(_blocking)


async def speak(text: str, animate: bool = True) -> bool:
    """Синтезирует и сразу проигрывает. Если animate — параллельно двигает
    персонажа на рабочем столе в такт голосу. True, если реально прозвучало."""
    mp3 = await synthesize(text)
    if not mp3:
        return False
    anim_task = asyncio.create_task(_animate_while(mp3)) if animate and config.ENABLE_AVATAR else None
    try:
        ok = await play_audio(mp3)
        return ok
    finally:
        if anim_task:
            anim_task.cancel()
            try:
                import avatar_state
                avatar_state.write_state("idle", 0.0)
            except Exception:  # noqa: BLE001
                pass
        try:
            mp3.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass


async def _animate_while(mp3_path: Path) -> None:
    """Пока mp3 играет, шлёт (state='speaking', level) в avatar_state — окно
    персонажа читает это и двигает нимб/пламя в такт словам."""
    try:
        import media
        import avatar_state
    except Exception:  # noqa: BLE001
        return
    try:
        pcm = await asyncio.to_thread(media.decode_pcm, str(mp3_path), 16000)
    except Exception:  # noqa: BLE001
        pcm = None
    fps = 20.0
    if pcm is None or len(pcm) == 0:
        # звук есть, но огибающую посчитать не смогли — просто покажем «говорит»
        avatar_state.write_state("speaking", 0.5)
        try:
            while True:
                await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            return
    env = media.loudness_envelope(pcm, 16000, fps)
    try:
        for lvl in env:
            avatar_state.write_state("speaking", float(lvl))
            await asyncio.sleep(1.0 / fps)
    except asyncio.CancelledError:
        return
