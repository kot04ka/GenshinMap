"""Загрузка карт Genshin из публичного API HoYoLAB (мультикарта).

    python tools/fetch_map_data.py            # все карты
    python tools/fetch_map_data.py 2 7        # только указанные map_id

Логика — в src/genshinmap/datasync.py (её же использует автообновление в
приложении). Тайлы не качаются: карта грузит их с CDN HoYoLAB по зумам.
ВНИМАНИЕ: неофициальный API HoYoLAB, данные — собственность miHoYo (личный трекинг).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from genshinmap.datasync import fetch_map, list_maps, update_index


def main() -> None:
    args = [int(a) for a in sys.argv[1:] if a.isdigit()]
    map_ids = args or [m["id"] for m in list_maps()]
    print("Карты к загрузке:", map_ids)
    entries = []
    for mid in map_ids:
        try:
            entries.append(fetch_map(mid))
        except Exception as e:  # noqa: BLE001
            print(f"  ОШИБКА map_id={mid}: {e}")
    update_index(entries)
    print("Готово.")


if __name__ == "__main__":
    main()
