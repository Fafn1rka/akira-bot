#!/usr/bin/env python3
"""
Генерация слоёв персонажа из карточки assets/akira_avatar.jpg.

Нужен только для разработчика (обычному пользователю запускать НЕ надо —
готовые PNG уже лежат в assets/). Требует: opencv-python-headless, numpy, Pillow.

Создаёт:
  assets/akira_character.png  — Акира + светлый диск нимба (RGBA, без рамки и неба)
  assets/akira_rays.png       — золотые лучи солнца отдельным слоем (тот же размер)
  assets/akira_meta.json      — координаты центра нимба, пламени и т.д.

    python tools/make_assets.py
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / "akira_avatar.jpg"

# Геометрия исходной карточки (в пикселях исходника 848x1264)
DISK_CENTER = (426, 529)     # центр светлого диска нимба
DISK_R = 256                 # радиус диска
CROP = (40, 30, 808, 1104)   # x0, y0, x1, y1 — область вокруг персонажа
CUT_Y = 1100                 # ниже — табличка «AKIRA», её убираем
FADE_PX = 70                 # плавное исчезновение внизу


def _grabcut_character(img: np.ndarray) -> np.ndarray:
    H, W = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = (hsv[..., i].astype(int) for i in range(3))
    cx, cy = DISK_CENTER
    yy, xx = np.mgrid[0:H, 0:W]
    rr = np.hypot(xx - cx, yy - cy)

    BG, FG, PBG, PFG = 0, 1, 2, 3
    mask = np.full((H, W), PBG, np.uint8)
    mask[:, :66] = BG
    mask[:, 786:] = BG
    mask[:42, :] = BG
    mask[CUT_Y:, :] = BG

    mask[(rr < DISK_R) & (mask != BG)] = PFG
    mask[rr < DISK_R - 31] = FG

    gold = (h >= 10) & (h <= 30) & (s > 60) & (v > 150)
    mask[(rr >= DISK_R) & (rr < 420) & gold & (mask != BG)] = PFG

    poly_prob = np.array([[120, 700], [300, 620], [560, 620], [740, 700],
                          [790, 900], [700, 1100], [150, 1100], [70, 900]], np.int32)
    tmp = np.zeros((H, W), np.uint8)
    cv2.fillPoly(tmp, [poly_prob], 1)
    mask[(tmp == 1) & (mask != BG) & (mask != FG)] = PFG

    poly_core = np.array([[300, 720], [560, 720], [600, 1000], [540, 1090],
                          [310, 1090], [250, 1000]], np.int32)
    core = np.zeros((H, W), np.uint8)
    cv2.fillPoly(core, [poly_core], 1)
    mask[core == 1] = FG

    sky = (rr > DISK_R + 15) & (v < 110) & (s > 40) & (h > 70) & (h < 130) & (core == 0)
    mask[sky & (mask != FG)] = BG

    sc = 0.6
    small = cv2.resize(img, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA)
    msmall = cv2.resize(mask, (small.shape[1], small.shape[0]), interpolation=cv2.INTER_NEAREST)
    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    cv2.grabCut(small, msmall, None, bgd, fgd, 6, cv2.GC_INIT_WITH_MASK)
    fg_small = ((msmall == FG) | (msmall == PFG)).astype(np.uint8)
    fg = cv2.resize(fg_small, (W, H), interpolation=cv2.INTER_LINEAR)
    return fg


def _largest_component(m: np.ndarray) -> np.ndarray:
    n, lab, st, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
    if n <= 1:
        return m
    big = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    return (lab == big).astype(np.uint8)


def _fill_holes(m: np.ndarray) -> np.ndarray:
    H, W = m.shape
    inv = (1 - m).astype(np.uint8)
    ff = inv.copy()
    msk = np.zeros((H + 2, W + 2), np.uint8)
    cv2.floodFill(ff, msk, (0, 0), 2)
    holes = (ff == 1)
    out = m.copy()
    out[holes] = 1
    return out


def _soft_alpha(mask: np.ndarray, erode: int = 1, blur: float = 1.1) -> np.ndarray:
    m = mask.astype(np.uint8)
    if erode:
        m = cv2.erode(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * erode + 1,) * 2))
    a = cv2.GaussianBlur(m.astype(np.float32), (0, 0), blur)
    return np.clip(a, 0, 1)


def _bleed_colors(bgr: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Заливает цвет из непрозрачной зоны в край, чтобы не было тёмной каймы."""
    solid = (alpha > 0.9).astype(np.uint8)
    dist, labels = cv2.distanceTransformWithLabels(1 - solid, cv2.DIST_L2, 3, labelType=cv2.DIST_LABEL_PIXEL)
    ys, xs = np.nonzero(solid)
    if len(ys) == 0:
        return bgr
    lut = {}
    lab_solid = labels[ys, xs]
    # для каждой метки — цвет её «якорного» пикселя
    anchors = np.zeros((labels.max() + 1, 3), np.uint8)
    anchors[lab_solid] = bgr[ys, xs]
    filled = anchors[labels]
    out = bgr.copy()
    edge = alpha < 0.98
    out[edge] = np.where((dist[edge] < 4)[:, None], filled[edge], bgr[edge])
    return out


def main() -> None:
    img = cv2.imread(str(SRC))
    if img is None:
        raise SystemExit(f"Не найден {SRC}")
    H, W = img.shape[:2]
    x0, y0, x1, y1 = CROP

    # ---------- персонаж + диск ----------
    fg = _grabcut_character(img)
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    fg = _largest_component(fg)
    fg = _fill_holes(fg)
    a_char = _soft_alpha(fg, erode=1, blur=1.1)

    # плавное исчезновение снизу
    yy = np.arange(H, dtype=np.float32)[:, None]
    fade = np.clip((CUT_Y - yy) / FADE_PX, 0, 1)
    a_char = a_char * fade

    char_bgr = _bleed_colors(img, a_char)

    # ---------- лучи ----------
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = (hsv[..., i].astype(int) for i in range(3))
    cx, cy = DISK_CENTER
    yy2, xx2 = np.mgrid[0:H, 0:W]
    rr = np.hypot(xx2 - cx, yy2 - cy)
    gold = (h >= 8) & (h <= 32) & (s > 55) & (v > 120)
    ring = (rr >= DISK_R - 25) & (rr <= 440) & (xx2 > 60) & (xx2 < 790) & (yy2 > 40) & (yy2 < CUT_Y)
    rays = (gold & ring & (fg == 0)).astype(np.uint8)
    rays = cv2.morphologyEx(rays, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    n, lab, st, _ = cv2.connectedComponentsWithStats(rays, connectivity=8)
    keep = np.zeros_like(rays)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] > 400:
            keep[lab == i] = 1
    a_rays = _soft_alpha(keep, erode=1, blur=1.0) * fade
    rays_bgr = _bleed_colors(img, a_rays)

    # ---------- пламя в руках ----------
    fy0, fy1, fx0, fx1 = 820, 1000, 330, 530
    patch = img[fy0:fy1, fx0:fx1]
    lum = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY).astype(np.float32)
    sat = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)[..., 1].astype(np.float32)
    score = lum - 0.6 * sat
    score = cv2.GaussianBlur(score, (0, 0), 6)
    py, px = np.unravel_index(int(np.argmax(score)), score.shape)
    flame = (fx0 + int(px), fy0 + int(py))

    # ---------- кроп и сохранение ----------
    def crop_rgba(bgr: np.ndarray, a: np.ndarray) -> np.ndarray:
        rgba = np.dstack([bgr[..., ::-1], (a * 255).astype(np.uint8)])
        return rgba[y0:y1, x0:x1]

    char_rgba = crop_rgba(char_bgr, a_char)
    rays_rgba = crop_rgba(rays_bgr, a_rays)

    from PIL import Image
    Image.fromarray(char_rgba, "RGBA").save(ROOT / "assets" / "akira_character.png", optimize=True)
    Image.fromarray(rays_rgba, "RGBA").save(ROOT / "assets" / "akira_rays.png", optimize=True)

    meta = {
        "canvas": [x1 - x0, y1 - y0],
        "disk_center": [cx - x0, cy - y0],
        "disk_radius": DISK_R,
        "flame": [flame[0] - x0, flame[1] - y0],
        "face": [430 - x0, 560 - y0],
    }
    (ROOT / "assets" / "akira_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print("OK:", meta)


if __name__ == "__main__":
    main()
