"""
Генерация картинок по описанию — «Акира, нарисуй кота в скафандре», «сгенерируй картинку заката
над горами». Работает одинаково в консоли, окне, Telegram и Discord — где попросили, там и придёт
готовая картинка.

Провайдер выбирается автоматически (IMAGE_PROVIDER=auto, по умолчанию): если в .env уже есть ключ
OpenAI — рисует через него (DALL-E), иначе если есть ключ Gemini — через него (Imagen), а если нет
ни одного — через Pollinations.ai: бесплатно, без ключа и регистрации, но медленнее и попроще
качеством. Явно выбрать провайдера: IMAGE_PROVIDER=openai | gemini | pollinations.

Готовые картинки сохраняются в data/images/ — так их видно на вкладке «Картинки» в окне, даже
если доставка в Telegram/Discord не настроена.

Названия моделей для генерации картинок у Gemini и OpenAI со временем меняются — если начнёт
отказывать с ошибкой про неизвестную модель, обнови IMAGE_MODEL_GEMINI/IMAGE_MODEL_OPENAI в .env.
"""
from __future__ import annotations

import base64
import logging
import re
import time
import urllib.parse
from pathlib import Path
from typing import Optional

import config

log = logging.getLogger("akira.imagegen")

IMAGES_DIR = config.DATA_DIR / "images"
MAX_PROMPT = 800
MAX_STORED = 200          # старые картинки не копятся бесконечно на диске


class ImageError(Exception):
    """Не получилось нарисовать. Текст — понятное объяснение для пользователя."""


def _slug(prompt: str) -> str:
    s = re.sub(r"[^a-zA-Zа-яА-ЯёЁ0-9]+", "-", prompt.strip().lower())[:40].strip("-")
    return s or "картинка"


def _save(data: bytes, prompt: str, ext: str = "png") -> Path:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    path = IMAGES_DIR / f"{int(time.time())}_{_slug(prompt)}.{ext}"
    path.write_bytes(data)
    files = sorted(IMAGES_DIR.glob("*"), key=lambda p: p.stat().st_mtime)
    for old in files[:-MAX_STORED]:
        try:
            old.unlink()
        except OSError:
            pass
    return path


def list_images(limit: int = 60) -> list[Path]:
    if not IMAGES_DIR.is_dir():
        return []
    files = sorted(IMAGES_DIR.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]


# ------------------------------------------------------------------- ключи
def _find_key(provider_name: str) -> Optional[str]:
    """Первый ключ этого провайдера из тех же настроек .env, что использует чат (GEMINI_API_KEY(S),
    OPENAI_API_KEY(S) и т.д.) — но, в отличие от чата, без требования заодно задать *_MODELS: для
    картинок модель чата не нужна, ключ может быть вписан только ради генерации картинок."""
    try:
        import providers as providers_mod
    except ImportError:
        return None
    import os
    pfx = provider_name.upper()
    keys = providers_mod.dedupe(
        providers_mod.split_list(os.getenv(f"{pfx}_API_KEYS"))
        + [os.getenv(f"{pfx}_API_KEY") or getattr(config, f"{pfx}_API_KEY", None)]
        + [os.getenv(f"{pfx}_API_KEY_{i}") for i in range(1, 21)]
    )
    return keys[0] if keys else None


# --------------------------------------------------------------- провайдеры
def _via_openai(prompt: str, key: str) -> bytes:
    import httpx

    model = getattr(config, "IMAGE_MODEL_OPENAI", "") or "dall-e-3"
    body = {"model": model, "prompt": prompt, "size": "1024x1024", "n": 1, "response_format": "b64_json"}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        r = httpx.post("https://api.openai.com/v1/images/generations", json=body, headers=headers, timeout=90)
    except httpx.TransportError as e:
        raise ImageError(f"OpenAI недоступен: {type(e).__name__}") from e
    if r.status_code >= 400:
        raise ImageError(f"OpenAI отказал ({r.status_code}): {r.text[:200]}")
    try:
        b64 = r.json()["data"][0]["b64_json"]
    except (KeyError, IndexError, ValueError) as e:
        raise ImageError("OpenAI ответил в непонятном формате.") from e
    return base64.b64decode(b64)


def _via_gemini(prompt: str, key: str) -> bytes:
    try:
        from google import genai
        from google.genai import types as gtypes
    except ImportError as e:
        raise ImageError("Не установлен пакет google-genai.") from e

    model = getattr(config, "IMAGE_MODEL_GEMINI", "") or "imagen-4.0-generate-001"
    client = genai.Client(api_key=key)
    try:
        result = client.models.generate_images(
            model=model, prompt=prompt, config=gtypes.GenerateImagesConfig(number_of_images=1))
    except Exception as e:  # noqa: BLE001
        raise ImageError(f"Gemini отказал: {type(e).__name__}: {e}") from e
    images = getattr(result, "generated_images", None) or []
    if not images:
        raise ImageError("Gemini не вернул картинку (модель отказалась рисовать этот запрос?).")
    return images[0].image.image_bytes


def _via_pollinations(prompt: str) -> bytes:
    import httpx

    url = "https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt)
    try:
        r = httpx.get(url, params={"width": 1024, "height": 1024, "nologo": "true"}, timeout=120,
                      follow_redirects=True)
    except httpx.TransportError as e:
        raise ImageError(f"Pollinations недоступен: {type(e).__name__}") from e
    if r.status_code >= 400 or not r.content:
        raise ImageError(f"Pollinations отказал ({r.status_code}).")
    return r.content


_PROVIDERS = ("openai", "gemini", "pollinations")


def _order() -> list[str]:
    chosen = (getattr(config, "IMAGE_PROVIDER", "") or "auto").strip().lower()
    if chosen in _PROVIDERS:
        return [chosen]
    order = []
    if _find_key("openai"):
        order.append("openai")
    if _find_key("gemini"):
        order.append("gemini")
    order.append("pollinations")            # без ключа — всегда доступен как запасной вариант
    return order


def generate(prompt: str) -> tuple[Optional[Path], str]:
    """(путь к сохранённому файлу, подпись) при успехе; (None, понятная причина) при неудаче."""
    prompt = (prompt or "").strip()
    if not prompt:
        return None, "Опиши, что нарисовать."
    prompt = prompt[:MAX_PROMPT]

    last_error = ""
    for name in _order():
        try:
            if name == "openai":
                key = _find_key("openai")
                if not key:
                    continue
                data, ext = _via_openai(prompt, key), "png"
            elif name == "gemini":
                key = _find_key("gemini")
                if not key:
                    continue
                data, ext = _via_gemini(prompt, key), "png"
            else:
                data, ext = _via_pollinations(prompt), "jpg"
            path = _save(data, prompt, ext)
            return path, f"Нарисовала: «{prompt}»."
        except ImageError as e:
            last_error = str(e)
            log.warning("Генерация через %s не удалась: %s", name, e)
        except Exception as e:  # noqa: BLE001
            last_error = f"{type(e).__name__}: {e}"
            log.warning("Генерация через %s упала неожиданно: %s", name, e)

    return None, ("Не получилось нарисовать" + (f": {last_error}" if last_error else "."))
