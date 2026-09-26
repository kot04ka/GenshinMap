"""Данные карт: загрузка с HoYoLAB, соответствие appsample, автообновление.

Используется и скриптами (tools/fetch_map_data.py, tools/fetch_appsample.py), и
самим приложением: раз в SYNC_EVERY_DAYS оно тихо проверяет HoYoLAB и, если
после патча игры появились новые точки или сменилась версия карты, докачивает
их (сигнал DataSync.updated -> окно перезагружает карту).

Раскладка:
    data/maps/index.json           [{id, name, has_tiles, points}, ...]
    data/maps/<id>/meta.json       геометрия v2 (origin, размеры, URL тайлов)
    data/maps/<id>/labels.json     категории
    data/maps/<id>/points.json     точки [id, label_id, x, y, area_id]
    data/maps/<id>/appsample.json  точка HoYoLAB -> метка appsample (для советов)
    assets/maps/<id>/icons/<label_id>.png
"""
from __future__ import annotations

import bisect
import collections
import json
import threading
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from .paths import PROJECT_ROOT

BASE = "https://sg-public-api.hoyolab.com/common/map_user/ys_obc/v1/map"
APP_SN = "ys_obc"
LANG = "ru-ru"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://act.hoyolab.com/"}
# Тайлы v2: {x}_{y}_{Z}, где Z = "N<n>" для зума -n и "P<n>" для +n (0 -> P0).
TILE_URL = ("https://act-webstatic.hoyoverse.com/map_manage/map/"
            "{map_id}/{version}/{{x}}_{{y}}_{{Z}}.png")

DATA_MAPS = PROJECT_ROOT / "data" / "maps"
ASSETS_MAPS = PROJECT_ROOT / "assets" / "maps"
SYNC_STATE = PROJECT_ROOT / "data" / "sync_state.json"
SYNC_EVERY_DAYS = 3

Log = Callable[[str], None]


def _get_json(url: str, headers: dict | None = None, timeout: int = 40) -> dict:
    req = urllib.request.Request(url, headers=headers or HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=40) as r:
        dest.write_bytes(r.read())


def _write_json(path: Path, obj, indent: int | None = None) -> None:
    """Атомарно: сначала во временный файл — приложение не прочтёт половину."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=indent), encoding="utf-8")
    tmp.replace(path)


def list_maps() -> list[dict]:
    return _get_json(f"{BASE}/list?app_sn={APP_SN}&lang={LANG}")["data"]["list"]


def fetch_map(map_id: int, log: Log = print) -> dict:
    """Скачать одну карту целиком. Возвращает запись для index.json + статистику."""
    node = _get_json(f"{BASE}/info?map_id={map_id}&app_sn={APP_SN}&lang={LANG}")["data"]["info"]
    name = node.get("name") or f"map {map_id}"
    data_dir = DATA_MAPS / str(map_id)
    icons_dir = ASSETS_MAPS / str(map_id) / "icons"
    data_dir.mkdir(parents=True, exist_ok=True)

    d2 = node.get("detail_v2") or {}
    if not d2.get("map_version"):
        raise RuntimeError("у карты нет detail_v2 — формат не поддерживается")
    total_size = d2["total_size"]
    meta = {
        "v2": True,
        "map_id": map_id,
        "map_version": d2["map_version"],
        "origin": d2["origin"],
        "total_size": total_size,
        # реальная картинка занимает только часть холста: padding + original_map_size
        "padding": d2.get("padding", [0, 0]),
        "content_size": d2.get("original_map_size", total_size),
        "tile_size": 256,
        "min_zoom": d2.get("min_zoom", -3),
        "max_zoom": d2.get("max_zoom", 0),
        "tile_url": TILE_URL.format(map_id=map_id, version=d2["map_version"]),
    }

    pdata = _get_json(f"{BASE}/point/list?map_id={map_id}&app_sn={APP_SN}&lang={LANG}")["data"]
    tree = _get_json(f"{BASE}/label/tree?map_id={map_id}&app_sn={APP_SN}&lang={LANG}")["data"]["tree"]
    group_of = {child["id"]: group["name"]
                for group in tree for child in group.get("children", [])}
    labels = [{"id": l["id"], "name": l["name"], "icon": l.get("icon", ""),
               "parent_id": l.get("parent_id", 0), "group": group_of.get(l["id"], "Прочее")}
              for l in pdata["label_list"]]
    points = [{"id": p["id"], "label_id": p["label_id"],
               "x": round(p["x_pos"], 2), "y": round(p["y_pos"], 2),
               "area_id": p.get("area_id", 0)} for p in pdata["point_list"]]

    # что изменилось по сравнению с тем, что уже было
    old_ids: set[int] = set()
    old_version = ""
    if (data_dir / "points.json").exists():
        old_ids = {p["id"] for p in json.loads((data_dir / "points.json").read_text(encoding="utf-8"))}
    if (data_dir / "meta.json").exists():
        old_version = json.loads((data_dir / "meta.json").read_text(encoding="utf-8")).get("map_version", "")
    new_ids = {p["id"] for p in points}

    _write_json(data_dir / "meta.json", meta, indent=2)
    _write_json(data_dir / "labels.json", labels)
    _write_json(data_dir / "points.json", points)

    # иконки категорий (только новые)
    used = {p["label_id"] for p in points}
    icons_dir.mkdir(parents=True, exist_ok=True)
    for l in labels:
        dest = icons_dir / f"{l['id']}.png"
        if l["id"] in used and l["icon"] and not dest.exists():
            try:
                _download(l["icon"], dest)
            except Exception as e:  # noqa: BLE001 — одна иконка не должна срывать загрузку
                log(f"  иконка {l['id']} не скачалась: {e}")

    added, removed = len(new_ids - old_ids), len(old_ids - new_ids) if old_ids else 0
    log(f"  {name}: точек {len(points)} (+{added} / -{removed}), категорий {len(labels)}")
    return {"id": map_id, "name": name, "has_tiles": True, "points": len(points),
            "added": added, "removed": removed, "version_changed": old_version != meta["map_version"]}


def update_index(entries: list[dict]) -> None:
    idx_path = DATA_MAPS / "index.json"
    existing = {}
    if idx_path.exists():
        existing = {e["id"]: e for e in json.loads(idx_path.read_text(encoding="utf-8"))}
    for e in entries:
        existing[e["id"]] = {k: e[k] for k in ("id", "name", "has_tiles", "points")}
    _write_json(idx_path, sorted(existing.values(), key=lambda e: e["id"]), indent=2)


# ---------- appsample: соответствие меток (для советов игроков) ----------
MARKERS_URL = "https://game-data.lemonapi.com/gim/markers_all.v5.json"
KX = 8.586e-05            # мир. x -> доля по долготе (одинаково по всей карте)
KY = -8.58623815e-05      # мир. y -> доля по широте
BY = 1.99458155e-01
LAT_TOL = 3e-5            # ≈ 0.35 мир. единицы
B_TOL = 4e-4              # допуск к «типичному» сдвигу по x
MIN_OFFSET_VOTES = 200    # сдвиг считается типичным, если столько точек его подтверждают


def build_appsample(map_id: int = 2, log: Log = print) -> dict[str, list]:
    """Точка HoYoLAB -> метка appsample. Их метки — зеркало HoYoLAB (тип "o<label_id>"),
    id свои; lat = KY*y + BY точно, lng = KX*x + b, где b свой у частей карты."""
    markers = _get_json(MARKERS_URL, {"User-Agent": "Mozilla/5.0"}, timeout=60)["data"]
    points = json.loads((DATA_MAPS / str(map_id) / "points.json").read_text(encoding="utf-8"))
    by_type: dict[str, list] = collections.defaultdict(list)
    for m in markers:
        if m[2] == map_id:
            by_type[m[1]].append(m)
    for lst in by_type.values():
        lst.sort(key=lambda m: m[5])

    offsets: collections.Counter = collections.Counter()
    cands: dict[int, list[tuple[float, int]]] = {}
    for p in points:
        lst = by_type.get(f"o{p['label_id']}", [])
        lat = KY * p["y"] + BY
        lats = [m[5] for m in lst]
        i = bisect.bisect_left(lats, lat - LAT_TOL)
        c = []
        while i < len(lst) and lst[i][5] <= lat + LAT_TOL:
            b = lst[i][4] - KX * p["x"]
            c.append((b, lst[i][0]))
            offsets[round(b, 3)] += 1
            i += 1
        cands[p["id"]] = c
    typical = [b for b, n in offsets.items() if n >= MIN_OFFSET_VOTES]

    mapping: dict[str, list] = {}
    for p in points:
        best = None
        for b, aid in cands[p["id"]]:
            d = min((abs(b - t) for t in typical), default=1.0)
            if d < B_TOL and (best is None or d < best[0]):
                best = (d, aid)
        if best:
            mapping[str(p["id"])] = [best[1], f"o{p['label_id']}"]
    _write_json(DATA_MAPS / str(map_id) / "appsample.json", mapping)
    log(f"appsample: сопоставлено {len(mapping)} из {len(points)} точек")
    return mapping


# ---------- автообновление в приложении ----------
class DataSync(QObject):
    """Раз в SYNC_EVERY_DAYS тихо обновляет данные карт в фоне."""

    updated = pyqtSignal(str)          # текст для журнала; окно перезагружает карту
    failed = pyqtSignal(str)

    def check_async(self, force: bool = False) -> None:
        if not force and not self._due():
            return
        threading.Thread(target=self._run, daemon=True).start()

    @staticmethod
    def _due() -> bool:
        try:
            last = json.loads(SYNC_STATE.read_text(encoding="utf-8")).get("last", 0)
        except (OSError, json.JSONDecodeError):
            last = 0
        return time.time() - last > SYNC_EVERY_DAYS * 86400

    def _run(self) -> None:
        notes: list[str] = []
        try:
            ids = [m["id"] for m in list_maps()]
            entries = []
            for mid in ids:
                e = fetch_map(mid, log=lambda _t: None)
                entries.append(e)
                if e["added"] or e["removed"] or e["version_changed"]:
                    notes.append(f"{e['name']}: +{e['added']} / -{e['removed']} точек"
                                 + (", новая версия карты" if e["version_changed"] else ""))
            update_index(entries)
            if any(e["id"] == 2 and (e["added"] or e["removed"]) for e in entries):
                build_appsample(2, log=lambda _t: None)
            _write_json(SYNC_STATE, {"last": int(time.time())})
        except Exception as e:  # noqa: BLE001 — нет сети: попробуем в следующий раз
            self.failed.emit(f"Данные карты не обновились: {e}")
            return
        if notes:
            self.updated.emit("Данные карты обновлены — " + "; ".join(notes))
