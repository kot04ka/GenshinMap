"""Индекс точек карты для поиска ближайшей несобранной точки категории.

Связывает Этап 2 (что подобрано -> label_id) и Этап 3 (где игрок -> x,y):
находит ближайшую несобранную точку нужной категории (или нескольких) рядом
с игроком.
"""
from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Candidate:
    point_id: str
    label_id: int
    dist: float


class MapIndex:
    def __init__(self, points_file: Path) -> None:
        points = json.loads(Path(points_file).read_text(encoding="utf-8"))
        # label_id -> list of (point_id, x, y)
        self.by_label: dict[int, list[tuple[int, float, float]]] = {}
        # point_id -> (label_id, x, y)
        self.by_id: dict[str, tuple[int, float, float]] = {}
        for p in points:
            self.by_label.setdefault(p["label_id"], []).append((p["id"], p["x"], p["y"]))
            self.by_id[str(p["id"])] = (p["label_id"], p["x"], p["y"])

    def add_point(self, point_id: str, label_id: int, x: float, y: float) -> None:
        """Добавить точку на лету (свои точки)."""
        self.remove_point(point_id)
        self.by_label.setdefault(label_id, []).append((point_id, x, y))
        self.by_id[str(point_id)] = (label_id, x, y)

    def remove_point(self, point_id: str) -> None:
        rec = self.by_id.pop(str(point_id), None)
        if rec is not None:
            lst = self.by_label.get(rec[0], [])
            self.by_label[rec[0]] = [t for t in lst if str(t[0]) != str(point_id)]

    def candidates(
        self,
        label_ids: int | Iterable[int],
        wx: float,
        wy: float,
        collected: set[str],
        max_dist: float,
    ) -> list[Candidate]:
        """Несобранные точки категорий в радиусе max_dist, ближайшие первыми."""
        if isinstance(label_ids, int):
            label_ids = (label_ids,)
        out: list[Candidate] = []
        for lid in label_ids:
            for pid, x, y in self.by_label.get(lid, ()):
                spid = str(pid)
                if spid in collected:
                    continue
                d = math.hypot(x - wx, y - wy)
                if d <= max_dist:
                    out.append(Candidate(spid, lid, d))
        out.sort(key=lambda c: c.dist)
        return out

    def nearest_uncollected(
        self,
        label_id: int | Iterable[int],
        wx: float,
        wy: float,
        collected: set[str],
        max_dist: float = 60.0,
    ) -> tuple[str, float] | None:
        """Ближайшая несобранная точка категории к (wx, wy).

        Возвращает (point_id, distance) или None, если ничего нет в радиусе.
        """
        found = self.candidates(label_id, wx, wy, collected, max_dist)
        if not found:
            return None
        return found[0].point_id, found[0].dist
