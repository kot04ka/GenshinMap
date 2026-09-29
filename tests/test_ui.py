"""Интерфейс карты в настоящем движке (QWebEngine): страница грузится без ошибок
JS, карта строится, на английском не остаётся русского текста.

Нужны скачанные данные карты (data/maps/2) — без них тесты пропускаются.
Каждый прогон ~10 с: страница открывается в отдельном процессе tools/ui_snapshot.py.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not (ROOT / "data" / "maps" / "2" / "points.json").exists(),
                                reason="нет данных карты (tools/fetch_map_data.py)")

# включить слои, открыть карточку точки и панель зачистки — чтобы проверить и их тексты
OPEN_ALL = ("LABELS.slice(0, 40).forEach(l => setLabel(l.id, true, true)); refreshPanel(); "
            "selectRegion(REGIONS[0].id); renderVisible(); "
            "openCard([...pointInfo.keys()][100]); toggleClear();")
# пещера: режим «Пещеры», карточка точки под землёй, галерея
CAVE = ("const pid = [...pointInfo.keys()].find(k => pointInfo.get(k)[5] && floorOfPoint(k)); "
        "showCave(pid); setTimeout(() => { openCard(pid); showPointInfo(pid, {tips: [{text: 'Tip', "
        "img: 'x.png', thumb: 'x.png', votes: 1}]}); openGallery(pid, 0); }, 800);")


def _snapshot(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, str(ROOT / "tools" / "ui_snapshot.py"),
                           "--out", str(tmp_path / "shot.png"), "--wait", "3", *args],
                          capture_output=True, text=True, encoding="utf-8", env=env, timeout=120,
                          check=False)


@pytest.mark.parametrize("args", [
    ("--js", OPEN_ALL),
    ("--lang", "en", "--js", OPEN_ALL),
    ("--compact", "--size", "460x560", "--js", "openCard([...pointInfo.keys()][100]);"),
    ("--lang", "en", "--wait", "4", "--js", CAVE),
], ids=["ru", "en", "compact", "cave-en"])
def test_map_page(tmp_path, args):
    r = _snapshot(tmp_path, *args)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "shot.png").stat().st_size > 10_000
