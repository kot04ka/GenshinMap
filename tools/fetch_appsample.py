"""Соответствие точек HoYoLAB меткам genshin-impact-map.appsample.com (советы игроков).

    python tools/fetch_appsample.py        # пишет data/maps/2/appsample.json

Логика — в src/genshinmap/datasync.py. Данные сообщества appsample — для
личного использования, с указанием источника.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from genshinmap.datasync import build_appsample

if __name__ == "__main__":
    build_appsample(2)
