"""Путь к цели по местности (A*), а не по прямой через горы и озёра.

Карта проходимости (клетка = CELL мировых единиц) строится из того, что уже
есть для трекера позиции:
  - вне контента карты — непроходимо;
  - вода (маска воды) — дорого: плыть долго, тратится выносливость;
  - обрывы/перепады (резкие контуры на карте) — дорого;
  - дороги (маска дорог по цвету тайлов) — дешевле всего;
  - остальная земля — обычная цена.
Поиск идёт в окне вокруг старта и цели; путь упрощается до ломаной.
"""
from __future__ import annotations

import heapq
import math
from pathlib import Path

import cv2
import numpy as np

from .vision.position_tracker import WATER_ZOOM, ensure_reference, ref_offset

CELL = 8.0                # мировых единиц в клетке сетки
COST_ROAD = 0.45
COST_LAND = 1.0
COST_EDGE = 4.0           # контуры обрывов/скал
COST_WATER = 6.0
WINDOW_PAD = 80           # клеток запаса вокруг старта/цели
MAX_CELLS = 700           # окно больше — путь не строим (слишком далеко)


def road_mask(bgr: np.ndarray) -> np.ndarray:
    """Дороги на тайлах HoYoLAB — светло-бежевые полосы."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    m = ((h >= 10) & (h <= 28) & (s >= 35) & (s <= 150) & (v >= 150)).astype(np.uint8) * 255
    return cv2.medianBlur(m, 3)


def road_reference_path(meta: dict, assets_dir: Path) -> Path:
    ver = str(meta.get("map_version", "v"))[:10]
    return assets_dir / f"road_{ver}_z{abs(WATER_ZOOM)}.png"


def ensure_road_reference(meta: dict, out_path: Path, progress=None) -> Path:
    return ensure_reference(meta, out_path, WATER_ZOOM, progress,
                            decode=lambda data: road_mask(
                                cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)))


class NavGrid:
    """Сетка стоимостей всей карты + A* в окне."""

    def __init__(self, meta: dict, gray_ref: Path, gray_zoom: int,
                 water_ref: Path, road_ref: Path | None = None) -> None:
        self.meta = meta
        # сетка строится в координатах маски воды (зум -2 -> 4 ед./px), затем /2 -> 8 ед.
        wscale = 2.0 ** WATER_ZOOM
        self.off = ref_offset(meta, WATER_ZOOM)
        water = cv2.imread(str(water_ref), cv2.IMREAD_GRAYSCALE)
        if water is None:
            raise FileNotFoundError(water_ref)
        k = 1.0 / (CELL * wscale)                               # 0.5
        size = (max(1, int(water.shape[1] * k)), max(1, int(water.shape[0] * k)))
        water = cv2.resize(water, size, interpolation=cv2.INTER_AREA)
        # серый референс (зум -1) -> та же сетка: контент и контуры
        gray = cv2.imread(str(gray_ref), cv2.IMREAD_GRAYSCALE)
        goff = ref_offset(meta, gray_zoom)
        gscale = 2.0 ** gray_zoom
        # сдвиг серого референса относительно водного в мировых единицах
        dx = goff[0] / gscale - self.off[0] / wscale
        dy = goff[1] / gscale - self.off[1] / wscale
        g = cv2.resize(gray, None, fx=1 / (CELL * gscale), fy=1 / (CELL * gscale),
                       interpolation=cv2.INTER_AREA)
        canvas = np.zeros(water.shape, np.uint8)
        ox, oy = round(dx / CELL), round(dy / CELL)
        h = min(g.shape[0], canvas.shape[0] - oy)
        w = min(g.shape[1], canvas.shape[1] - ox)
        if h > 0 and w > 0:
            canvas[oy:oy + h, ox:ox + w] = g[:h, :w]
        edges = cv2.dilate(cv2.Canny(canvas, 60, 140), np.ones((2, 2), np.uint8))

        cost = np.full(water.shape, COST_LAND, np.float32)
        cost[edges > 0] = COST_EDGE
        cost[water > 128] = COST_WATER
        if road_ref is not None and Path(road_ref).exists():
            road = cv2.imread(str(road_ref), cv2.IMREAD_GRAYSCALE)
            # дороги тонкие (1–2 px): расширяем до сжатия, иначе в клетках пропадут
            road = cv2.dilate(road, np.ones((3, 3), np.uint8))
            road = cv2.resize(road, (water.shape[1], water.shape[0]), interpolation=cv2.INTER_AREA)
            cost[(road > 40) & (water <= 128)] = COST_ROAD
        cost[canvas < 8] = np.inf                              # вне карты
        self.cost = cost
        self.wscale = wscale

    # --- координаты ---
    def _to_cell(self, x: float, y: float) -> tuple[int, int]:
        px = (x + self.meta["origin"][0]) * self.wscale - self.off[0]
        py = (y + self.meta["origin"][1]) * self.wscale - self.off[1]
        k = 1.0 / (CELL * self.wscale)
        return int(px * k), int(py * k)

    def _to_world(self, cx: float, cy: float) -> tuple[float, float]:
        k = CELL * self.wscale
        px, py = (cx + 0.5) * k + self.off[0], (cy + 0.5) * k + self.off[1]
        return (round(px / self.wscale - self.meta["origin"][0], 1),
                round(py / self.wscale - self.meta["origin"][1], 1))

    def plan(self, start: tuple[float, float], goal: tuple[float, float]) -> list[tuple[float, float]]:
        """Путь от start до goal (мировые координаты) или [] если не построить."""
        sx, sy = self._to_cell(*start)
        gx, gy = self._to_cell(*goal)
        H, W = self.cost.shape
        x0, x1 = max(0, min(sx, gx) - WINDOW_PAD), min(W, max(sx, gx) + WINDOW_PAD + 1)
        y0, y1 = max(0, min(sy, gy) - WINDOW_PAD), min(H, max(sy, gy) + WINDOW_PAD + 1)
        if x1 - x0 > MAX_CELLS or y1 - y0 > MAX_CELLS:
            return []
        win = self.cost[y0:y1, x0:x1]
        s = (sy - y0, sx - x0)
        g = (gy - y0, gx - x0)
        if not (0 <= s[0] < win.shape[0] and 0 <= s[1] < win.shape[1]
                and 0 <= g[0] < win.shape[0] and 0 <= g[1] < win.shape[1]):
            return []
        cells = self._astar(win, s, g)
        if not cells:
            return []
        pts = np.array([[c[1], c[0]] for c in cells], np.float32).reshape(-1, 1, 2)
        simple = cv2.approxPolyDP(pts, 1.5, False).reshape(-1, 2)
        path = [self._to_world(cx + x0, cy + y0) for cx, cy in simple]
        path[0], path[-1] = (round(start[0], 1), round(start[1], 1)), (round(goal[0], 1), round(goal[1], 1))
        return path

    @staticmethod
    def _astar(cost: np.ndarray, s: tuple[int, int], g: tuple[int, int]) -> list[tuple[int, int]]:
        H, W = cost.shape
        steps = [(-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
                 (-1, -1, 1.414), (-1, 1, 1.414), (1, -1, 1.414), (1, 1, 1.414)]
        hmin = COST_ROAD
        best = {s: 0.0}
        came: dict[tuple[int, int], tuple[int, int]] = {}
        heap = [(math.hypot(s[0] - g[0], s[1] - g[1]) * hmin, 0.0, s)]
        cost_s = cost if np.isfinite(cost[s]) else None
        while heap:
            _, d, cur = heapq.heappop(heap)
            if cur == g:
                out = [cur]
                while cur in came:
                    cur = came[cur]
                    out.append(cur)
                return out[::-1]
            if d > best.get(cur, math.inf):
                continue
            cy, cx = cur
            for dy, dx, m in steps:
                ny, nx = cy + dy, cx + dx
                if not (0 <= ny < H and 0 <= nx < W):
                    continue
                c = cost[ny, nx]
                if not math.isfinite(c):
                    if cost_s is not None or (ny, nx) != g:
                        continue
                    c = COST_LAND                         # цель у самого края — пускаем
                nd = d + m * c
                nb = (ny, nx)
                if nd < best.get(nb, math.inf):
                    best[nb] = nd
                    came[nb] = cur
                    heapq.heappush(heap, (nd + math.hypot(ny - g[0], nx - g[1]) * hmin, nd, nb))
        return []


def lookahead(path: list[tuple[float, float]], x: float, y: float,
              ahead: float = 35.0) -> tuple[tuple[float, float], float, float]:
    """(точка пути впереди на ahead ед., остаток пути, отклонение игрока от пути)."""
    if not path:
        return (x, y), 0.0, 0.0
    best_i, best_d, best_pt = 0, math.inf, path[0]
    for i in range(len(path) - 1):                     # ближайшая точка на ломаной
        ax, ay = path[i]
        bx, by = path[i + 1]
        vx, vy = bx - ax, by - ay
        L2 = vx * vx + vy * vy or 1e-9
        t = max(0.0, min(1.0, ((x - ax) * vx + (y - ay) * vy) / L2))
        px, py = ax + t * vx, ay + t * vy
        d = math.hypot(x - px, y - py)
        if d < best_d:
            best_i, best_d, best_pt = i, d, (px, py)
    # идём вперёд по ломаной на ahead единиц
    rest = 0.0
    cur = best_pt
    target = None
    for j in range(best_i + 1, len(path)):
        seg = math.hypot(path[j][0] - cur[0], path[j][1] - cur[1])
        if target is None and rest + seg >= ahead:
            k = (ahead - rest) / (seg or 1e-9)
            target = (cur[0] + (path[j][0] - cur[0]) * k, cur[1] + (path[j][1] - cur[1]) * k)
        rest += seg
        cur = path[j]
    return (target or path[-1]), rest, best_d
