"""Пути приложения: из исходников и из собранного exe (PyInstaller).

Из исходников корень — папка проекта. В exe корень — папка рядом с
GenshinMap.exe: туда при сборке кладутся data/, assets/ и src/genshinmap/frontend/web/
в той же структуре, что и в проекте (относительные ссылки страницы карты
остаются рабочими), и туда же пишутся прогресс/настройки пользователя.
"""
from __future__ import annotations

import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))

if FROZEN:
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parents[4]

WEB_DIR = PROJECT_ROOT / "src" / "genshinmap" / "frontend" / "web"
# относительный путь от страницы карты до корня (для ссылок на assets/ и data/)
WEB_TO_ROOT = "/".join([".."] * len(WEB_DIR.relative_to(PROJECT_ROOT).parts))
