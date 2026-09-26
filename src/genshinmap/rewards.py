"""Примогемы за сундуки: сколько собрано и сколько осталось (по регионам).

Точных чисел игра не публикует, и они плавают от региона к региону, поэтому
держим «типичное» значение и диапазон (мин–макс) по данным вики/гайдов:
  Обычный 0–2, Богатый (Exquisite) 2–5, Драгоценный (Precious) 5–10,
  Роскошный (Luxurious) 10–40, Удивительный (Remarkable) 5.
Значения можно переопределить в data/settings.json -> "primogems".
Счётчик — оценка, а не данные игры.
"""
from __future__ import annotations

# название категории -> (типично, минимум, максимум)
DEFAULT_PRIMOGEMS: dict[str, tuple[int, int, int]] = {
    "Обычный сундук": (0, 0, 2),
    "Богатый сундук": (2, 2, 5),
    "Драгоценный сундук": (5, 5, 10),
    "Роскошный сундук": (10, 10, 40),
    "Удивительный сундук": (5, 5, 5),
}


class PrimogemCounter:
    """Считает примогемы по собранным точкам: всего, по регионам, за сессию."""

    def __init__(self, labels: list[dict], points: list[dict],
                 overrides: dict | None = None) -> None:
        table = dict(DEFAULT_PRIMOGEMS)
        for name, v in (overrides or {}).items():
            if isinstance(v, (int, float)):
                table[name] = (int(v), int(v), int(v))
            elif isinstance(v, (list, tuple)) and len(v) == 3:
                table[name] = tuple(int(x) for x in v)
        # label_id -> (типично, мин, макс)
        self.value: dict[int, tuple[int, int, int]] = {
            l["id"]: table[l["name"]] for l in labels if l["name"] in table
        }
        # point_id -> (label_id, area_id) только для «примогемных» точек
        self.points: dict[str, tuple[int, int]] = {
            str(p["id"]): (p["label_id"], p.get("area_id", 0))
            for p in points if p["label_id"] in self.value
        }
        self.session: dict[str, int] = {}     # point_id -> примогемы (эта сессия)

    def gems(self, point_id: str) -> int:
        rec = self.points.get(point_id)
        return self.value[rec[0]][0] if rec else 0

    def on_marked(self, point_id: str, collected: bool) -> int:
        """Учесть отметку/снятие за сессию. Возвращает примогемы этой точки."""
        g = self.gems(point_id)
        if collected and g:
            self.session[point_id] = g
        else:
            self.session.pop(point_id, None)
        return g

    def session_total(self) -> int:
        return sum(self.session.values())

    def by_region(self, collected: set[str]) -> dict[int, dict]:
        """{area_id: {got, total, got_chests, chests}} — типичные значения."""
        out: dict[int, dict] = {}
        for pid, (lid, area) in self.points.items():
            r = out.setdefault(area, {"got": 0, "total": 0, "got_chests": 0, "chests": 0})
            g = self.value[lid][0]
            r["total"] += g
            r["chests"] += 1
            if pid in collected:
                r["got"] += g
                r["got_chests"] += 1
        return out
