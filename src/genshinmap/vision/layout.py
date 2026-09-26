"""Где на экране элементы интерфейса Genshin — при любом разрешении и формате.

Настройки хранят области в «эталонной» раскладке 1920x1080 (доли от неё).
Игра масштабирует интерфейс по меньшей стороне (s = min(w/1920, h/1080)) и
прижимает элементы к краям окна:
  мини-карта        — к левому верхнему углу      ("lt")
  «Получено»        — к левому краю, по вертикали по центру ("lc")
  подсказки «F …»   — к центру                   ("cc")
  UID               — к правому нижнему углу      ("rb")
На 16:9 все привязки дают одно и то же; на 21:9, 16:10, в окне и на втором
мониторе — каждая свою, поэтому считаем от прямоугольника окна игры.
"""
from __future__ import annotations

REF_W, REF_H = 1920.0, 1080.0

ANCHORS = {
    "minimap": "lt",
    "pickup_region": "lc",
    "prompt_region": "cc",
    "uid": "rb",
}


def ui_scale(width: float, height: float) -> float:
    """Пикселей окна на пиксель эталонной раскладки 1920x1080."""
    return min(width / REF_W, height / REF_H)


def _axis(frac_pos: float, frac_size: float, origin: float, length: float,
          ref: float, s: float, anchor: str) -> tuple[float, float]:
    size = frac_size * ref * s
    if anchor in "lt":
        start = origin + frac_pos * ref * s
    elif anchor in "rb":
        start = origin + length - (1.0 - frac_pos) * ref * s
    else:                                   # "c" — от центра
        start = origin + length / 2 + (frac_pos - 0.5) * ref * s
    return start, size


def region_from_frac(frac: dict, rect: dict, anchor: str = "lt") -> dict[str, int]:
    """Доли эталонной раскладки -> пиксельная область внутри окна игры rect."""
    s = ui_scale(rect["width"], rect["height"])
    x, w = _axis(frac["left"], frac["width"], rect["left"], rect["width"], REF_W, s, anchor[0])
    y, h = _axis(frac["top"], frac["height"], rect["top"], rect["height"], REF_H, s, anchor[1])
    return {"left": round(x), "top": round(y), "width": max(8, round(w)), "height": max(8, round(h))}


def frac_from_region(x: float, y: float, w: float, h: float, width: float, height: float,
                     anchor: str = "lt") -> dict[str, float]:
    """Обратное: область в пикселях кадра окна игры (width x height) -> доли раскладки."""
    s = ui_scale(width, height)

    def inv(pos: float, length: float, ref: float, a: str) -> float:
        if a in "lt":
            return pos / (ref * s)
        if a in "rb":
            return 1.0 - (length - pos) / (ref * s)
        return 0.5 + (pos - length / 2) / (ref * s)

    return {"left": inv(x, width, REF_W, anchor[0]), "top": inv(y, height, REF_H, anchor[1]),
            "width": w / (REF_W * s), "height": h / (REF_H * s)}
