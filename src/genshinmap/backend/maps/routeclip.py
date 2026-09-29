"""Мини-анимация «как пройти»: путь к точке на настоящих тайлах карты.

Видео к точкам ни HoYoLAB, ни appsample не дают (только фото), поэтому
собираем свою: от ближайшего телепорта (или от игрока) по пути A* до цели.
Результат — анимированный WebP (≈3 с, зациклен), его показывает карточка точки.

    render_route_clip(meta, path, out, tiles_dir, labels=("Телепорт", "Цель"))
"""
from __future__ import annotations

import itertools
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from genshinmap.backend.vision.position_tracker import _fetch, _tile_url

TS = 256
OUT_W = 360               # ширина кадра, px
MARGIN_UNITS = 45         # поля вокруг пути, мировые единицы
MOVE_FRAMES = 42          # кадров движения
HOLD_FRAMES = 16          # кадров на месте (пульс у цели)
FRAME_MS = 70
GOLD = (255, 210, 74)
DARK = (10, 14, 22)


def _font(size: int) -> ImageFont.ImageFont:
    for name in ("segoeuib.ttf", "segoeui.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _pick_zoom(meta: dict, span_units: float) -> int:
    """Самый крупный зум, при котором весь путь влезает примерно в OUT_W."""
    zmax, zmin = int(meta.get("max_zoom", 0)), int(meta.get("min_zoom", -3))
    for z in range(min(zmax, 0), zmin - 1, -1):
        if span_units * 2.0 ** z <= OUT_W * 1.15:
            return z
    return zmin


def _tile(meta: dict, x: int, y: int, z: int, cache: Path) -> np.ndarray | None:
    f = cache / f"z{z}_{x}_{y}.jpg"
    if f.exists():
        return cv2.imread(str(f))
    data = _fetch(_tile_url(meta, x, y, z))
    if not data:
        return None
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is not None:
        cache.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(f), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return img


def _background(meta: dict, bbox: tuple[float, float, float, float], z: int,
                cache: Path) -> np.ndarray:
    """Картинка карты под bbox (мировые координаты) на зуме z."""
    s = 2.0 ** z
    ox, oy = meta["origin"]
    px0, py0 = (bbox[0] + ox) * s, (bbox[1] + oy) * s
    px1, py1 = (bbox[2] + ox) * s, (bbox[3] + oy) * s
    tx0, ty0 = int(px0 // TS), int(py0 // TS)
    tx1, ty1 = int(px1 // TS), int(py1 // TS)
    canvas = np.full(((ty1 - ty0 + 1) * TS, (tx1 - tx0 + 1) * TS, 3), (40, 30, 20), np.uint8)
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            t = _tile(meta, tx, ty, z, cache)
            if t is not None:
                h, w = t.shape[:2]
                canvas[(ty - ty0) * TS:(ty - ty0) * TS + h, (tx - tx0) * TS:(tx - tx0) * TS + w] = t
    cx0, cy0 = int(px0 - tx0 * TS), int(py0 - ty0 * TS)
    return canvas[cy0:cy0 + int(py1 - py0), cx0:cx0 + int(px1 - px0)]


def _resample(path: list[tuple[float, float]], n: int) -> list[tuple[float, float]]:
    """n точек, равномерно по длине пути."""
    seg = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in itertools.pairwise(path)]
    total = sum(seg) or 1e-9
    out, i, acc = [], 0, 0.0
    for k in range(n):
        d = total * k / (n - 1)
        while i < len(seg) - 1 and acc + seg[i] < d:
            acc += seg[i]
            i += 1
        t = (d - acc) / (seg[i] or 1e-9)
        a, b = path[i], path[i + 1]
        out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def render_route_clip(meta: dict, path: list[tuple[float, float]], out: Path, tiles_dir: Path,
                      labels: tuple[str, str] = ("Старт", "Цель")) -> Path:
    """Нарисовать анимацию пути path (мировые координаты) в out (.webp)."""
    if len(path) < 2:
        raise ValueError("путь из одной точки")
    xs, ys = [p[0] for p in path], [p[1] for p in path]
    bbox = (min(xs) - MARGIN_UNITS, min(ys) - MARGIN_UNITS, max(xs) + MARGIN_UNITS, max(ys) + MARGIN_UNITS)
    span = max(bbox[2] - bbox[0], bbox[3] - bbox[1])
    z = _pick_zoom(meta, span)
    bg = _background(meta, bbox, z, tiles_dir)
    k = OUT_W / bg.shape[1]                                   # подгоняем под ширину кадра
    bg = cv2.resize(bg, (OUT_W, max(1, round(bg.shape[0] * k))),
                    interpolation=cv2.INTER_CUBIC if k > 1 else cv2.INTER_AREA)
    base = Image.fromarray(cv2.cvtColor(bg, cv2.COLOR_BGR2RGB))
    s = 2.0 ** z * k

    def px(p: tuple[float, float]) -> tuple[float, float]:
        return ((p[0] - bbox[0]) * s, (p[1] - bbox[1]) * s)

    pts = [px(p) for p in _resample(path, MOVE_FRAMES)]
    full = [px(p) for p in path]
    font = _font(13)
    frames = []
    for f in range(MOVE_FRAMES + HOLD_FRAMES):
        im = base.copy()
        d = ImageDraw.Draw(im, "RGBA")
        d.line(full, fill=(255, 255, 255, 90), width=3, joint="curve")        # весь путь — бледно
        upto = pts[:min(f, MOVE_FRAMES - 1) + 1]
        if len(upto) > 1:
            d.line(upto, fill=(*DARK, 200), width=7, joint="curve")
            d.line(upto, fill=GOLD, width=4, joint="curve")
        sx, sy = full[0]
        d.ellipse((sx - 7, sy - 7, sx + 7, sy + 7), fill=(88, 166, 255), outline=(255, 255, 255), width=2)
        gx, gy = full[-1]
        pulse = 9 + (f - MOVE_FRAMES) % 8 * 1.5 if f >= MOVE_FRAMES else 9
        d.ellipse((gx - pulse, gy - pulse, gx + pulse, gy + pulse), outline=(*DARK, 220), width=5)
        d.ellipse((gx - pulse, gy - pulse, gx + pulse, gy + pulse), outline=(255, 90, 90), width=3)
        cx, cy = upto[-1]
        d.ellipse((cx - 6, cy - 6, cx + 6, cy + 6), fill=GOLD, outline=(*DARK, 255), width=2)
        for (lx, ly), text in ((full[0], labels[0]), (full[-1], labels[1])):
            tw = d.textlength(text, font=font)
            bx = min(max(4, lx - tw / 2), im.width - tw - 12)
            by = ly - 30 if ly > 36 else ly + 14
            d.rounded_rectangle((bx - 5, by - 2, bx + tw + 5, by + 17), 6, fill=(*DARK, 200))
            d.text((bx, by), text, font=font, fill=(240, 244, 252))
        frames.append(im)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.webp")
    frames[0].save(tmp, format="WEBP", save_all=True, append_images=frames[1:],
                   duration=FRAME_MS, loop=0, quality=78, method=4)
    tmp.replace(out)
    return out
