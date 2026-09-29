"""Данные карты для страницы: список карт, категории, точки, регионы, названия мест.

Собирает всё в web/mapdata_<id>.js (`window.__MAPDATA`) — страница подключает его
тегом <script>: через runJavaScript такой объём (~2 МБ) передавать нельзя.
"""
from __future__ import annotations

import json
from pathlib import Path

from genshinmap.backend.core import i18n
from genshinmap.backend.core.i18n import tr
from genshinmap.backend.core.paths import PROJECT_ROOT, WEB_DIR, WEB_TO_ROOT
from genshinmap.backend.game.automark import classify
from genshinmap.backend.game.rewards import DEFAULT_PRIMOGEMS
from genshinmap.backend.maps.custom_points import CUSTOM_LABEL, CUSTOM_NAME
from genshinmap.backend.maps.regions import build_regions

DATA_MAPS = PROJECT_ROOT / "data" / "maps"
ASSETS_MAPS = PROJECT_ROOT / "assets" / "maps"
ASSETS_REL = f"{WEB_TO_ROOT}/assets/maps"      # от страницы карты до иконок
# «Пещера» / «Подводная пещера» — входы на поверхности: через них ведём под землю
CAVE_ENTRY_NAMES = ("Пещера", "Подводная пещера")


def load_map_index() -> list[dict]:
    """Список карт из data/maps/index.json ([{id, name, has_tiles, points}])."""
    idx = DATA_MAPS / "index.json"
    if not idx.exists():
        return []
    return json.loads(idx.read_text(encoding="utf-8"))


def map_dir(map_id: int) -> Path:
    return DATA_MAPS / str(map_id)


def load_map_payload(map_id: int, name: str, custom: list[dict] | None = None) -> dict:
    """Собирает данные одной карты (геометрия + категории + точки + регионы)."""
    d = map_dir(map_id)
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    labels = json.loads((d / "labels.json").read_text(encoding="utf-8"))
    points = json.loads((d / "points.json").read_text(encoding="utf-8"))

    en = i18n.lang() == "en"
    meta["name"] = tr(name)
    # относительная база иконок этой карты (от web/map.html)
    meta["icons_base"] = f"{ASSETS_REL}/{map_id}/icons"

    points_by_label: dict[str, list] = {}
    counts: dict[int, int] = {}
    for p in points:
        lid = p["label_id"]
        points_by_label.setdefault(str(lid), []).append(
            [p["id"], p["x"], p["y"], p.get("area_id", 0), p.get("layer", 0)])
        counts[lid] = counts.get(lid, 0) + 1

    # group/kind — по русским данным (логика), name/group_label — на языке интерфейса
    used_labels = [
        {"id": l["id"], "name": (l.get("name_en") or tr(l["name"])) if en else l["name"],
         "group": l["group"], "group_label": (l.get("group_en") or tr(l["group"])) if en else l["group"],
         "count": counts[l["id"]],
         "gems": DEFAULT_PRIMOGEMS.get(l["name"], (0,))[0],
         # «Пещера» / «Подводная пещера» — входы (стоят на поверхности): через них ведём
         # к сундукам под землёй
         "kind": "cave" if l["name"] in CAVE_ENTRY_NAMES else classify(l["name"], l.get("group", ""))}
        for l in labels
        if l["id"] in counts
    ]
    # свои точки — отдельный слой (есть всегда, чтобы добавлять на лету)
    custom = custom or []
    used_labels.append({"id": CUSTOM_LABEL, "name": tr(CUSTOM_NAME), "group": CUSTOM_NAME,
                        "group_label": tr(CUSTOM_NAME), "count": len(custom), "gems": 0,
                        "kind": "chest"})
    points_by_label[str(CUSTOM_LABEL)] = [[c["id"], c["x"], c["y"], c.get("area")] for c in custom]
    anchors_f = map_dir(map_id) / ("anchors_en.json" if en else "anchors.json")
    anchors = json.loads(anchors_f.read_text(encoding="utf-8")) if anchors_f.exists() else []
    regions = build_regions(map_id, points)
    for r in regions:
        r["name"] = tr(r["name"])
    return {"meta": meta, "labels": used_labels, "points_by_label": points_by_label,
            "regions": regions, "anchors": anchors,
            "ui": {"lang": i18n.lang(), "table": i18n.table() if en else {}}}


def write_bundle(map_id: int, name: str, custom: list[dict] | None = None) -> None:
    """Записывает web/mapdata_<id>.js (отдельный файл на карту — без коллизий кеша)."""
    payload = load_map_payload(map_id, name, custom)
    js = "window.__MAPDATA=" + json.dumps(payload, ensure_ascii=False) + ";"
    (WEB_DIR / f"mapdata_{map_id}.js").write_text(js, encoding="utf-8")
