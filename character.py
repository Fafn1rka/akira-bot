"""
Рендерер персонажа Акиры (numpy + OpenCV, БЕЗ привязки к какому-либо GUI).

Один и тот же код рисует:
  • окно-персонажа поверх рабочего стола (прозрачный RGBA-кадр);
  • видео-«кружки» для Telegram (непрозрачный RGB-кадр на фоне ночного неба).

Кадр — чистая функция от (t, state, level), поэтому видео можно рендерить
по любому кадру независимо, а окно — в реальном времени.

    state : "idle" | "listening" | "thinking" | "speaking"
    level : 0..1 — громкость голоса (амплитуда), двигает нимб/лучи/пламя

Проверить внешний вид без всяких окон:
    python character.py --preview preview.png
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np

ASSETS = Path(__file__).resolve().parent / "assets"

IDLE, LISTENING, THINKING, SPEAKING = "idle", "listening", "thinking", "speaking"
STATES = (IDLE, LISTENING, THINKING, SPEAKING)

# цвет пламени в руках для каждого состояния (RGB, 0..1)
_FLAME_COLOR = {
    IDLE: (0.78, 0.88, 1.00),
    LISTENING: (0.45, 0.88, 1.00),
    THINKING: (0.76, 0.60, 1.00),
    SPEAKING: (1.00, 0.92, 0.72),
}
_GOLD = np.array([1.00, 0.80, 0.43], np.float32)
_WARM_WHITE = np.array([1.00, 0.96, 0.84], np.float32)

Rect = Tuple[float, float, float, float]  # x0, y0, x1, y1 в координатах ассета


def _load_meta() -> dict:
    return json.loads((ASSETS / "akira_meta.json").read_text(encoding="utf-8"))


def _read_rgba_premult(path: Path) -> np.ndarray:
    """PNG -> float32 (H, W, 4), цвет уже умножен на альфу (premultiplied)."""
    import PIL.Image as Image  # Pillow нужен и так (см. requirements)

    arr = np.asarray(Image.open(path).convert("RGBA"), dtype=np.float32) / 255.0
    arr[..., :3] *= arr[..., 3:4]
    return arr


def _crop_pad(arr: np.ndarray, rect: Rect) -> np.ndarray:
    """Вырезает прямоугольник (может выходить за границы — добьём прозрачным)."""
    x0, y0, x1, y1 = (int(round(v)) for v in rect)
    h, w = arr.shape[:2]
    out = np.zeros((y1 - y0, x1 - x0, arr.shape[2]), arr.dtype)
    sx0, sy0 = max(x0, 0), max(y0, 0)
    sx1, sy1 = min(x1, w), min(y1, h)
    if sx1 > sx0 and sy1 > sy0:
        out[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = arr[sy0:sy1, sx0:sx1]
    return out


def _gauss_sprite(radius: int, sigma_frac: float = 0.45) -> np.ndarray:
    """Квадратный спрайт свечения (float32, 0..1), максимум в центре."""
    r = max(2, int(radius))
    ax = np.arange(-r, r + 1, dtype=np.float32)
    xx, yy = np.meshgrid(ax, ax)
    d2 = (xx * xx + yy * yy) / (r * r)
    g = np.exp(-d2 / (2 * sigma_frac * sigma_frac))
    g *= np.clip(1.0 - d2, 0, 1)  # мягко обрезаем к краю
    return g.astype(np.float32)


def _add_sprite(canvas: np.ndarray, sprite: np.ndarray, cx: float, cy: float,
                color: np.ndarray, gain: float) -> None:
    """Аддитивно (свет) кладёт спрайт на premultiplied-холст (H, W, 4)."""
    if gain <= 0.001:
        return
    h, w = canvas.shape[:2]
    sh, sw = sprite.shape
    x0 = int(round(cx)) - sw // 2
    y0 = int(round(cy)) - sh // 2
    ix0, iy0 = max(x0, 0), max(y0, 0)
    ix1, iy1 = min(x0 + sw, w), min(y0 + sh, h)
    if ix1 <= ix0 or iy1 <= iy0:
        return
    s = sprite[iy0 - y0:iy1 - y0, ix0 - x0:ix1 - x0] * gain
    region = canvas[iy0:iy1, ix0:ix1]
    region[..., 0] += s * color[0]
    region[..., 1] += s * color[1]
    region[..., 2] += s * color[2]
    region[..., 3] += s


class CharacterRenderer:
    """
    out_w      — ширина выходного кадра, px (высота считается из пропорций view)
    view       — какую часть холста ассета показывать (x0, y0, x1, y1);
                 по умолчанию — весь персонаж с небольшим запасом под качание лучей
    transparent— True: premultiplied RGBA (для окна); False: RGB на ночном небе (видео)
    """

    def __init__(self, out_w: int = 320, view: Optional[Rect] = None,
                 transparent: bool = True, seed: int = 11):
        meta = _load_meta()
        cw, ch = meta["canvas"]
        pad = 26
        self.view: Rect = view or (-pad, -pad, cw + pad, ch + pad)
        vx0, vy0, vx1, vy1 = self.view
        self.out_w = int(out_w)
        self.scale = self.out_w / (vx1 - vx0)
        self.out_h = int(round((vy1 - vy0) * self.scale))
        self.transparent = transparent

        def to_out(px: float, py: float) -> Tuple[float, float]:
            return (px - vx0) * self.scale, (py - vy0) * self.scale

        self.disk_c = to_out(*meta["disk_center"])
        self.disk_r = meta["disk_radius"] * self.scale
        self.flame_c = to_out(*meta["flame"])

        def prep(name: str) -> np.ndarray:
            a = _crop_pad(_read_rgba_premult(ASSETS / name), self.view)
            return cv2.resize(a, (self.out_w, self.out_h), interpolation=cv2.INTER_AREA)

        self.char = prep("akira_character.png")
        self.rays = prep("akira_rays.png")

        # мягкое свечение лучей (размытая альфа лучей)
        k = max(3, int(self.out_w * 0.04)) | 1
        self.rays_glow = cv2.GaussianBlur(self.rays[..., 3], (k, k), 0)

        # спрайты
        self.sp_flame = _gauss_sprite(int(self.out_w * 0.16), 0.40)
        self.sp_spark = _gauss_sprite(max(3, int(self.out_w * 0.022)), 0.5)
        self.sp_bloom = _gauss_sprite(int(self.disk_r * 1.5), 0.55)

        # искры пламени: фиксированные «характеры» частиц
        rng = np.random.default_rng(seed)
        n = 26
        self.sp_n = n
        self.sp_phase = rng.uniform(0, 1, n).astype(np.float32)
        self.sp_life = rng.uniform(1.3, 2.7, n).astype(np.float32)
        self.sp_xoff = rng.uniform(-1, 1, n).astype(np.float32)
        self.sp_rise = rng.uniform(0.55, 1.15, n).astype(np.float32)
        self.sp_size = rng.uniform(0.6, 1.5, n).astype(np.float32)
        self.sp_sway = rng.uniform(0.5, 1.6, n).astype(np.float32)

        # фон для видео
        self._bg = None
        if not transparent:
            self._make_background(seed)

    # ----------------------------------------------------------------- фон
    def _make_background(self, seed: int) -> None:
        h, w = self.out_h, self.out_w
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        cx, cy = self.disk_c
        d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / (0.95 * max(w, h))
        d = np.clip(d, 0, 1)[..., None]
        inner = np.array([0.15, 0.27, 0.36], np.float32)   # глубокий бирюзовый
        outer = np.array([0.02, 0.04, 0.08], np.float32)   # почти чёрно-синий
        self._bg = inner * (1 - d) + outer * d
        rng = np.random.default_rng(seed + 5)
        m = 70
        self._st_xy = np.stack([rng.uniform(0, w, m), rng.uniform(0, h, m)], 1)
        self._st_ph = rng.uniform(0, 6.28, m).astype(np.float32)
        self._st_sp = rng.uniform(0.6, 2.2, m).astype(np.float32)
        self._st_sz = rng.uniform(0.6, 1.4, m).astype(np.float32)
        self._sp_star = _gauss_sprite(max(2, int(self.out_w * 0.012)), 0.5)

    # --------------------------------------------------------------- кадр
    def render(self, t: float, state: str = IDLE, level: float = 0.0) -> np.ndarray:
        """
        Возвращает:
          transparent=True  -> uint8 (H, W, 4)  premultiplied RGBA
          transparent=False -> uint8 (H, W, 3)  RGB
        """
        level = float(min(1.0, max(0.0, level)))
        if state not in STATES:
            state = IDLE
        h, w = self.out_h, self.out_w
        thinking = state == THINKING
        speaking = state == SPEAKING
        breath = math.sin(t * 1.5)

        if self.transparent:
            canvas = np.zeros((h, w, 4), np.float32)
        else:
            canvas = np.zeros((h, w, 4), np.float32)
            canvas[..., :3] = self._bg
            canvas[..., 3] = 1.0
            self._draw_stars(canvas, t)

        # 1) лучи: качаются, пульсируют голосом
        sway = 2.2 * math.sin(t * 0.45)
        if thinking:
            sway = 4.5 * math.sin(t * 1.7)
        ang = sway + level * 1.6 * math.sin(t * 9.0)
        scl = 1.0 + 0.012 * math.sin(t * 0.9) + 0.035 * level
        M = cv2.getRotationMatrix2D(self.disk_c, ang, scl)
        rays_t = cv2.warpAffine(self.rays, M, (w, h), flags=cv2.INTER_LINEAR,
                                borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
        glow_t = cv2.warpAffine(self.rays_glow, M, (w, h), flags=cv2.INTER_LINEAR,
                                borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        # мягкое золотое свечение под лучами (аддитивно, размытая альфа)
        gg = glow_t * (0.10 + 0.55 * level + (0.05 if speaking else 0.0))
        canvas[..., 0] += gg * _GOLD[0]
        canvas[..., 1] += gg * _GOLD[1]
        canvas[..., 2] += gg * _GOLD[2]
        canvas[..., 3] += gg
        self._over(canvas, rays_t)

        # 2) сам персонаж: «дыхание»
        s = 1.0 + 0.004 * breath
        dy = 1.6 * self.scale * 1.6 * breath
        M2 = np.array([[s, 0, (1 - s) * w * 0.5],
                       [0, s, (1 - s) * h + dy]], np.float32)
        char_t = cv2.warpAffine(self.char, M2, (w, h), flags=cv2.INTER_LINEAR,
                                borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
        self._over(canvas, char_t)

        # 3) сияние нимба (bloom) — усиливается голосом
        bloom = 0.05 + 0.025 * math.sin(t * 1.2) + 0.20 * level
        _add_sprite(canvas, self.sp_bloom, self.disk_c[0], self.disk_c[1] + dy, _WARM_WHITE, bloom)

        # 4) пламя в руках + искры
        fcol = np.array(_FLAME_COLOR[state], np.float32)
        fx, fy = self.flame_c[0], self.flame_c[1] + dy
        flick = 0.5 + 0.5 * math.sin(t * 7.3 + 1.7 * math.sin(t * 2.9))
        base = 0.24 + 0.12 * flick + (0.08 if thinking else 0.0)
        _add_sprite(canvas, self.sp_flame, fx, fy, fcol, min(0.95, base + 0.50 * level))

        active = min(1.0, 0.30 + 0.70 * level + (0.25 if thinking else 0.0))
        rise_px = self.out_w * 0.42
        spread = self.out_w * 0.05
        for i in range(self.sp_n):
            if i / self.sp_n > active:
                continue
            life = self.sp_life[i]
            u = ((t / life) + self.sp_phase[i]) % 1.0
            px = fx + self.sp_xoff[i] * spread * (0.6 + u) + \
                math.sin(6.283 * (u * 1.4 + self.sp_phase[i])) * spread * 0.35 * self.sp_sway[i]
            py = fy - u * rise_px * self.sp_rise[i]
            fade = (1.0 - u) ** 1.4
            _add_sprite(canvas, self.sp_spark, px, py, fcol, 0.9 * fade * self.sp_size[i])

        # 5) финал
        rgb = np.minimum(canvas[..., :3], canvas[..., 3:4] if self.transparent else 1.0)
        if self.transparent:
            a = np.clip(canvas[..., 3:4], 0, 1)
            out = np.concatenate([np.clip(rgb, 0, 1), a], axis=2)
            return (out * 255.0 + 0.5).astype(np.uint8)
        return (np.clip(rgb, 0, 1) * 255.0 + 0.5).astype(np.uint8)

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _over(canvas: np.ndarray, layer: np.ndarray) -> None:
        """canvas = layer OVER canvas (обе premultiplied)."""
        inv = 1.0 - layer[..., 3:4]
        canvas *= inv
        canvas += layer

    def _draw_stars(self, canvas: np.ndarray, t: float) -> None:
        for (x, y), ph, sp, sz in zip(self._st_xy, self._st_ph, self._st_sp, self._st_sz):
            tw = 0.5 + 0.5 * math.sin(t * sp + ph)
            _add_sprite(canvas, self._sp_star, x, y, np.array([0.85, 0.92, 1.0], np.float32),
                        0.20 + 0.75 * tw * sz * 0.7)


# ---------------------------------------------------------------- видео-вид
def video_view() -> Rect:
    """Квадратный кадр для Telegram-«кружка»: весь нимб + бюст, влезает в круг."""
    meta = _load_meta()
    cw, ch = meta["canvas"]
    size = 1010.0
    x0 = cw / 2 - size / 2
    y0 = 24.0
    return (x0, y0, x0 + size, y0 + size)


# --------------------------------------------------------------------- CLI
def _premult_to_rgb_on(bg: Tuple[int, int, int], frame: np.ndarray) -> np.ndarray:
    a = frame[..., 3:4].astype(np.float32) / 255.0
    rgb = frame[..., :3].astype(np.float32)
    out = rgb + (1.0 - a) * np.array(bg, np.float32)
    return np.clip(out, 0, 255).astype(np.uint8)


if __name__ == "__main__":
    import argparse
    import time

    import PIL.Image as Image

    ap = argparse.ArgumentParser(description="Предпросмотр персонажа без всяких окон")
    ap.add_argument("--preview", default="preview.png", help="куда сохранить картинку")
    ap.add_argument("--width", type=int, default=300)
    args = ap.parse_args()

    r = CharacterRenderer(args.width)
    tiles = []
    for st, lv in ((IDLE, 0.0), (LISTENING, 0.0), (THINKING, 0.2), (SPEAKING, 0.85)):
        f = r.render(1.7, st, lv)
        tiles.append(_premult_to_rgb_on((22, 26, 42), f))
    sheet = np.concatenate(tiles, axis=1)
    Image.fromarray(sheet).save(args.preview)
    t0 = time.perf_counter()
    for i in range(60):
        r.render(i / 30.0, SPEAKING, 0.5)
    dt = (time.perf_counter() - t0) / 60 * 1000
    print(f"Сохранено: {args.preview}  |  {r.out_w}x{r.out_h}  |  {dt:.1f} мс/кадр")
