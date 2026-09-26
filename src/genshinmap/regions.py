"""Регионы карты: названия area_id и их границы (для навигации и фильтра).

API HoYoLAB отдаёт у каждой точки `area_id`, но названий регионов не даёт —
их сопоставили вручную (по уникальным категориям: Гидрокул -> Фонтейн,
Лунокул -> Нод-Край, Криокул -> Снежная и т.д.).
"""
from __future__ import annotations

# map_id -> {area_id: (название, порядок в списке)}
AREA_NAMES: dict[int, dict[int, str]] = {
    2: {
        1: "Мондштадт",
        2: "Ли Юэ",
        3: "Инадзума",
        4: "Сумеру",
        8: "Фонтейн",
        11: "Натлан",
        13: "Нод-Край",
        16: "Снежная",
    },
}

# Сколько точек нужно, чтобы area считалась полноценным регионом (area 0 = мусор).
MIN_REGION_POINTS = 50


def _percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    i = min(len(sorted_vals) - 1, max(0, round(q * (len(sorted_vals) - 1))))
    return sorted_vals[i]


def build_regions(map_id: int, points: list[dict]) -> list[dict]:
    """Список регионов [{id, name, count, bbox:[x0,y0,x1,y1]}] в мировых координатах.

    bbox берётся по 1..99 перцентилям, чтобы одиночные выбросы (точки,
    ошибочно привязанные к региону) не раздували рамку на полкарты.
    """
    names = AREA_NAMES.get(map_id, {})
    xs: dict[int, list[float]] = {}
    ys: dict[int, list[float]] = {}
    for p in points:
        a = p.get("area_id")
        if a is None:
            continue
        xs.setdefault(a, []).append(p["x"])
        ys.setdefault(a, []).append(p["y"])

    regions = []
    for a, xa in xs.items():
        if len(xa) < MIN_REGION_POINTS:
            continue
        sx, sy = sorted(xa), sorted(ys[a])
        bbox = [_percentile(sx, 0.01), _percentile(sy, 0.01),
                _percentile(sx, 0.99), _percentile(sy, 0.99)]
        regions.append({
            "id": a,
            "name": names.get(a, f"Область {a}"),
            "count": len(xa),
            "bbox": [round(v, 1) for v in bbox],
        })
    # порядок: как в словаре названий (по сюжету), неизвестные — в конце
    order = list(names)
    regions.sort(key=lambda r: (order.index(r["id"]) if r["id"] in order else 999, r["id"]))
    # один регион на всю карту — навигация бессмысленна
    return regions if len(regions) > 1 else []
