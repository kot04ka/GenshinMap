"""Подземелья и многоуровневые места: картинки этажей, входы, путь внутри.

HoYoLAB знает, на каком этаже точка (point_group: group_id + floor_id), но картинок
этажей в его API нет. У appsample они есть: в коде их сайта лежит таблица
{map_id: [{id: floor_id, sid: group_id, name: "B1", img, bounds}]} — те же id,
что у HoYoLAB («sid 是 group id, id 是 floor id» — подпись из их кода).

bounds там в их координатах: lat = KY*y + BY (точно), lng = KX*x + b, где сдвиг b
свой у частей карты — считаем его для каждого этажа по нашим точкам на нём
(appsample.json сопоставляет наши точки их меткам).

    data/maps/<id>/floors.json  [{id, group, name, img, bbox: [x0, y0, x1, y1],
                                   entrances: [point_id, ...]}, ...]
    data/maps/<id>/floor_img/<floor_id>.png — картинка этажа (скачивается по запросу)

Входы в пещеру — метки «Пещера» / «Подводная пещера» у границ её этажей.
Путь внутри — A* по непрозрачной (нарисованной) части картинки этажа.
"""
from __future__ import annotations

import collections
import itertools
import json
import math
import re
import statistics
import urllib.request
from pathlib import Path

import cv2
import numpy as np

SITE = "https://genshin-impact-map.appsample.com/"
UA = {"User-Agent": "Mozilla/5.0"}
KX = 8.586e-05
KY = -8.58623815e-05
BY = 1.99458155e-01
ENTRY_NAMES = ("Пещера", "Подводная пещера")
ENTRY_MARGIN = 60          # мир. единиц: вход стоит у края пещеры, иногда чуть снаружи
NAV_CELL = 4.0             # мир. единиц в клетке сетки пути внутри этажа


def _get(url: str, timeout: int = 60) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def fetch_floor_table() -> dict[str, list[dict]]:
    """Таблица этажей из кода сайта appsample (имя файла бандла меняется — ищем по странице)."""
    html = _get(SITE).decode("utf-8", "ignore")
    scripts = re.findall(r'src="(/_next/static/chunks/pages/_app-[^"]+\.js)"', html)
    if not scripts:
        raise RuntimeError("appsample: не нашёл код сайта")
    js = _get(SITE.rstrip("/") + scripts[0], timeout=90).decode("utf-8", "ignore")
    i = js.find('"sid"')
    while i >= 0:
        s = js.rfind("JSON.parse('", 0, i)
        e = js.find("}')", i)
        if s >= 0 and e >= 0:
            try:
                table = json.loads(js[s + len("JSON.parse('"):e + 1])
                if isinstance(table, dict) and any(isinstance(v, list) for v in table.values()):
                    return table
            except json.JSONDecodeError:
                pass
        i = js.find('"sid"', e if e >= 0 else i + 5)
    raise RuntimeError("appsample: таблица этажей не найдена")


def build_floors(map_id: int, table: dict, points: list[dict], labels: list[dict],
                 appsample: dict, marker_lng: dict[int, float]) -> list[dict]:
    """Этажи карты в мировых координатах + входы. Этажи без наших точек пропускаем:
    без них не вычислить сдвиг, да и показывать на них нечего."""
    by_floor: dict[int, list[dict]] = collections.defaultdict(list)
    for p in points:
        if p.get("floor"):
            by_floor[p["floor"]].append(p)
    entry_ids = {lb["id"] for lb in labels if lb["name"] in ENTRY_NAMES}
    entries = [p for p in points if p["label_id"] in entry_ids]

    out = []
    for f in table.get(str(map_id), []):
        ps = by_floor.get(f["id"], [])
        shifts = [marker_lng[a[0]] - KX * p["x"] for p in ps
                  if (a := appsample.get(str(p["id"]))) and a[0] in marker_lng]
        if not shifts:
            continue
        b = statistics.median(shifts)
        bd = f["bounds"]
        x0, x1 = sorted(((bd["west"] - b) / KX, (bd["east"] - b) / KX))
        y0, y1 = sorted(((bd["north"] - BY) / KY, (bd["south"] - BY) / KY))
        out.append({"id": f["id"], "group": f["sid"], "name": f["name"], "img": f["img"],
                    "bbox": [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)]})

    # входы — общие для всех этажей пещеры (группы). Вход относим к ОДНОЙ пещере —
    # самой маленькой, у границ которой он стоит: огромные подводные зоны иначе
    # «забирают» входы всех пещер внутри себя.
    groups: dict[int, list[dict]] = collections.defaultdict(list)
    for f in out:
        groups[f["group"]].append(f)
    m = ENTRY_MARGIN
    owner: dict[str, tuple[float, int]] = {}
    for g, fl in groups.items():
        for f in fl:
            x0, y0, x1, y1 = f["bbox"]
            area = (x1 - x0) * (y1 - y0)
            for e in entries:
                if x0 - m <= e["x"] <= x1 + m and y0 - m <= e["y"] <= y1 + m:
                    k = str(e["id"])
                    if k not in owner or area < owner[k][0]:
                        owner[k] = (area, g)
    by_group: dict[int, list[str]] = collections.defaultdict(list)
    for k, (_a, g) in owner.items():
        by_group[g].append(k)
    for g, fl in groups.items():
        for f in fl:
            f["entrances"] = sorted(by_group.get(g, []), key=int)
    return out


def floor_image_path(data_dir: Path, floor_id: int) -> Path:
    return Path(data_dir) / "floor_img" / f"{floor_id}.png"


def ensure_floor_image(data_dir: Path, floor: dict) -> Path:
    path = floor_image_path(data_dir, floor["id"])
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_get(floor["img"]))
    return path


class FloorNav:
    """Путь внутри этажа: сетка по непрозрачной части картинки, A* (Rust, если собран)."""

    def __init__(self, floor: dict, image: Path) -> None:
        im = cv2.imread(str(image), cv2.IMREAD_UNCHANGED)
        if im is None or im.ndim != 3 or im.shape[2] != 4:
            raise ValueError(f"нет прозрачности у картинки этажа {floor['id']}")
        self.bbox = floor["bbox"]
        x0, y0, x1, y1 = self.bbox
        w = max(2, int((x1 - x0) / NAV_CELL))
        h = max(2, int((y1 - y0) / NAV_CELL))
        alpha = cv2.resize(im[:, :, 3], (w, h), interpolation=cv2.INTER_AREA)
        walk = alpha > 128
        # узкие проходы на картинке — 1–2 клетки; чуть расширяем, чтобы путь не рвался
        walk = cv2.dilate(walk.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
        cost = np.full(walk.shape, np.inf, np.float32)
        cost[walk] = 1.0
        # у стен дороже — путь идёт серединой прохода, как бегут в игре
        edge = cv2.erode(walk.astype(np.uint8), np.ones((5, 5), np.uint8)) == 0
        cost[walk & edge] = 2.5
        self.cost = cost
        self.kx, self.ky = w / (x1 - x0), h / (y1 - y0)

    def _cell(self, x: float, y: float) -> tuple[int, int]:
        h, w = self.cost.shape
        cx = min(w - 1, max(0, int((x - self.bbox[0]) * self.kx)))
        cy = min(h - 1, max(0, int((y - self.bbox[1]) * self.ky)))
        return cy, cx

    def _nearest_walkable(self, cell: tuple[int, int]) -> tuple[int, int] | None:
        if math.isfinite(self.cost[cell]):
            return cell
        ys, xs = np.nonzero(np.isfinite(self.cost))
        if not len(ys):
            return None
        i = int(np.argmin((ys - cell[0]) ** 2 + (xs - cell[1]) ** 2))
        return int(ys[i]), int(xs[i])

    def plan(self, start: tuple[float, float], goal: tuple[float, float]) -> list[tuple[float, float]]:
        from genshinmap.backend.maps.navigation import NavGrid

        s = self._nearest_walkable(self._cell(*start))
        g = self._nearest_walkable(self._cell(*goal))
        if s is None or g is None:
            return []
        cells = NavGrid._astar(self.cost, s, g)
        if not cells:
            return []
        pts = np.array([[c[1], c[0]] for c in cells], np.float32).reshape(-1, 1, 2)
        simple = cv2.approxPolyDP(pts, 1.2, False).reshape(-1, 2)
        path = [(round(self.bbox[0] + (cx + 0.5) / self.kx, 1),
                 round(self.bbox[1] + (cy + 0.5) / self.ky, 1)) for cx, cy in simple.tolist()]
        return [(round(start[0], 1), round(start[1], 1)), *path, (round(goal[0], 1), round(goal[1], 1))]


PROJ_FAR = 40.0            # вход дальше этого от нарисованной части этажа — он ведёт на другой этаж


def cave_route(data_dir: Path, floors: list[dict], points: dict[str, tuple[float, float]],
               pid: str, floor_id: int, player: tuple[float, float] | None = None) -> dict | None:
    """Путь от лучшего входа пещеры до точки на её этаже.

    Лучший вход — с самым коротким путём внутри (если позиция игрока известна —
    плюс путь от игрока до входа по прямой). Если вход далеко от нарисованной части
    этажа точки, он ведёт на другой этаж — путь примерный (лестниц на картах нет)."""
    floor = next((f for f in floors if f["id"] == floor_id), None)
    goal = points.get(str(pid))
    if floor is None or goal is None or not floor.get("entrances"):
        return None
    nav = FloorNav(floor, ensure_floor_image(data_dir, floor))
    best = None
    for no, eid in enumerate(floor["entrances"], 1):
        e = points.get(str(eid))
        if e is None:
            continue
        cell = nav._cell(*e)
        near = nav._nearest_walkable(cell)
        if near is None:
            continue
        proj = math.hypot((near[0] - cell[0]) / nav.ky, (near[1] - cell[1]) / nav.kx)
        path = nav.plan(e, goal)
        if len(path) < 2:
            continue
        length = sum(math.dist(a, b) for a, b in itertools.pairwise(path))
        score = length + 3 * proj + (math.dist(player, e) if player else 0)
        if best is None or score < best["score"]:
            best = {"score": score, "path": path, "entrance": str(eid), "entrance_no": no,
                    "length": round(length), "approx": proj > PROJ_FAR, "floor": floor_id}
    if best:
        best.pop("score")
    return best


def load_floors(data_dir: Path) -> list[dict]:
    try:
        return json.loads((Path(data_dir) / "floors.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
