"""
Снимок экрана: «Акира, посмотри на экран» / «что у меня на экране» / «помоги с этой ошибкой».

Как это работает: Акира делает скриншот и прикладывает его к твоему сообщению — AI разбирает
картинку и отвечает. Скриншот делается ТОЛЬКО когда ты сам попросил, ничего не записывается
и не отправляется в фоне. Учти: картинка уходит выбранному AI-провайдеру (Google, OpenAI...),
поэтому не проси «посмотри на экран», когда на нём пароли или чужая переписка.
Выключить совсем: ENABLE_SCREEN_VISION=false в .env.

Linux: работает в сессии X11 (в Linux Mint Cinnamon она по умолчанию). В Wayland системные
ограничения не дают программам снимать экран — Акира честно об этом скажет.
"""
from __future__ import annotations

import io
import logging
import os
import re

import config

log = logging.getLogger("akira.screen")

MAX_WIDTH = 1600     # крупнее не нужно: меньше картинка — быстрее и дешевле ответ


class ScreenError(Exception):
    """Не получилось сделать скриншот. Текст — понятное объяснение для пользователя."""


# Фразы, после которых скриншот делается сразу, без раздумий модели.
# Всё остальное («помоги с этой ошибкой» и т.п.) модель сама решает через инструмент look_at_screen.
_SCREEN_RE = re.compile(
    r"""(
        (?:посмотри|глянь|гляни|взгляни|погляди|смотри|подивись)\s+(?:пожалуйста\s+|ка\s+)?
            (?:на\s+)?(?:мой\s+|моё\s+|мое\s+)?(?:экран|монитор|екран)
      | что\s+(?:там\s+)?(?:у\s+меня\s+)?(?:на|в)\s+(?:моём\s+|моем\s+)?(?:экране|мониторе)
      | що\s+(?:там\s+)?(?:у\s+мене\s+)?на\s+екрані
      | что\s+ты\s+видишь\s+(?:у\s+меня\s+)?(?:на\s+)?(?:экране|мониторе)
      | (?:look|check)\s+(?:at\s+)?my\s+screen
      | what(?:'s|\s+is)\s+on\s+my\s+screen
    )""",
    re.IGNORECASE | re.VERBOSE,
)


def wants_screen(text: str) -> bool:
    return bool(_SCREEN_RE.search(text or ""))


def capture() -> tuple[bytes, str]:
    """Делает скриншот выбранного монитора -> (jpeg-байты, 'image/jpeg'). Бросает ScreenError."""
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        raise ScreenError("У меня не получается сделать скриншот: сейчас включена сессия Wayland, "
                          "а она не разрешает программам снимать экран. Войди в систему через сессию "
                          "X11 (на экране входа есть переключатель) — и заработает.")
    try:
        import mss
    except ImportError:
        raise ScreenError("Для скриншотов нужен пакет mss: pip install mss") from None
    try:
        from PIL import Image
    except ImportError:
        raise ScreenError("Для скриншотов нужен пакет Pillow: pip install Pillow") from None

    try:
        with mss.mss() as sct:
            monitors = sct.monitors                     # [0] — все экраны вместе, дальше по одному
            idx = config.SCREEN_MONITOR if 0 <= config.SCREEN_MONITOR < len(monitors) else 1
            shot = sct.grab(monitors[idx])
            img = Image.frombytes("RGB", shot.size, shot.rgb)
    except Exception as e:  # noqa: BLE001
        log.warning("Скриншот не удался: %s", e)
        raise ScreenError(f"Не получилось сделать скриншот ({type(e).__name__}).") from e

    if img.width > MAX_WIDTH:
        img = img.resize((MAX_WIDTH, round(img.height * MAX_WIDTH / img.width)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue(), "image/jpeg"
