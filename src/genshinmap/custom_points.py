"""Свои точки: сундуки и прочее, чего нет на карте HoYoLAB.

Появляются сами (открыл сундук, а на карте его нет — ставим метку «собрано»)
или вручную (правый клик по пустому месту карты). Геометрия хранится здесь,
отметка «собрано» — в общем прогрессе (id вида "u1727351234567").
На карте — отдельный слой «Свои точки» (label_id = CUSTOM_LABEL).
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

from .paths import PROJECT_ROOT

CUSTOM_PATH = PROJECT_ROOT / "data" / "custom_points.json"
CUSTOM_LABEL = -1
CUSTOM_NAME = "Свои точки"
SAME_POINT_UNITS = 10     # ближе этого — это та же своя точка, не дубль


class CustomPoints:
    def __init__(self, path: Path = CUSTOM_PATH) -> None:
        self.path = path
        self.items: dict[str, dict] = {}
        if path.exists():
            try:
                self.items = {p["id"]: p for p in json.loads(path.read_text(encoding="utf-8"))}
            except (OSError, json.JSONDecodeError, KeyError, TypeError):
                self.items = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(list(self.items.values()), ensure_ascii=False, indent=1),
                             encoding="utf-8")

    def for_map(self, map_id: int) -> list[dict]:
        return [p for p in self.items.values() if p.get("map_id") == map_id]

    def near(self, map_id: int, x: float, y: float,
             radius: float = SAME_POINT_UNITS) -> dict | None:
        best = None
        for p in self.for_map(map_id):
            d = math.hypot(p["x"] - x, p["y"] - y)
            if d <= radius and (best is None or d < best[0]):
                best = (d, p)
        return best[1] if best else None

    def add(self, map_id: int, x: float, y: float, kind: str = "chest",
            note: str = "", area: int | None = None) -> dict:
        pid = f"u{int(time.time() * 1000)}"
        item = {"id": pid, "map_id": map_id, "x": round(x, 1), "y": round(y, 1),
                "kind": kind, "note": note, "area": area, "t": int(time.time())}
        self.items[pid] = item
        self.save()
        return item

    def remove(self, pid: str) -> bool:
        if self.items.pop(pid, None) is None:
            return False
        self.save()
        return True
