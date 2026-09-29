"""Экспорт/импорт прогресса одним файлом (перенос между ПК, резервная копия).

В файле: отметки «собрано» и «вероятно собрано», свои точки, память наблюдений.
Импорт — «объединить» (к текущему добавляется) или «заменить» (как в файле).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from genshinmap.backend.core.storage import ObservationStore, ProgressStore
from genshinmap.backend.maps.custom_points import CustomPoints

FORMAT = "genshinmap-progress"
FORMAT_VERSION = 1


def export_progress(path: Path, store: ProgressStore, custom: CustomPoints,
                    observations: ObservationStore) -> dict:
    data = {
        "format": FORMAT,
        "version": FORMAT_VERSION,
        "exported_at": int(time.time()),
        "collected": sorted(store.collected),
        "probable": sorted(store.probable),
        "custom_points": list(custom.items.values()),
        "observations": observations.data,
    }
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"collected": len(data["collected"]), "custom": len(data["custom_points"])}


def import_progress(path: Path, store: ProgressStore, custom: CustomPoints,
                    observations: ObservationStore, replace: bool) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("format") != FORMAT:
        raise ValueError("это не файл прогресса GenshinMap")
    collected = {str(x) for x in data.get("collected", [])}
    probable = {str(x) for x in data.get("probable", [])} & collected
    before = len(store.collected)
    if replace:
        store.collected, store.probable = collected, probable
        custom.items = {}
        observations.data = {}
    else:
        store.collected |= collected
        # «вероятно» не должно понижать уже подтверждённое
        store.probable = (store.probable | (probable - (store.collected - store.probable)))
        store.probable &= store.collected
    for p in data.get("custom_points", []):
        if isinstance(p, dict) and "id" in p:
            custom.items.setdefault(p["id"], p)
    for pid, rec in (data.get("observations") or {}).items():
        observations.data.setdefault(pid, rec)
    store.save()
    custom.save()
    observations.save()
    return {"collected": len(store.collected), "added": len(store.collected) - before,
            "custom": len(custom.items)}
