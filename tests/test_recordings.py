"""Регрессия на РЕАЛЬНЫХ записях игры (debug/ — только локально, в репозиторий
не попадают). Нет записей или данных карты — тесты пропускаются.

    python -m pytest tests/test_recordings.py -v
"""
import json
import math
from pathlib import Path

import cv2
import pytest

ROOT = Path(__file__).resolve().parents[1]
DEBUG = ROOT / "debug"


def _sessions():
    out = []
    for d in sorted(DEBUG.glob("session_*")):
        log = d / "log.jsonl"
        if log.exists() and any((d / "minimap").glob("*.png")):
            out.append(d)
    return out


# ---------- подсказки у сундуков (кадры debug/samples/chest_*.jpg) ----------
def test_chest_prompt_on_samples():
    from genshinmap.vision.layout import region_from_frac
    from genshinmap.vision.ocr import ScreenOcr
    from genshinmap.vision.prompt_detector import parse_prompt_lines

    samples = sorted((DEBUG / "samples").glob("chest_*.jpg"))
    ocr = ScreenOcr("ru")
    if not ocr.ready or not (DEBUG / "samples" / "chest_143452.jpg").exists():
        pytest.skip("нет эталонного кадра у сундука (кадры ротируются) или Windows OCR")
    frac = {"left": 0.55, "top": 0.35, "width": 0.30, "height": 0.40}
    found = []
    for f in samples:
        img = cv2.imread(str(f))
        h, w = img.shape[:2]
        img[int(0.5 * h):, w - 420:] = 0          # карточка HUD (в новой версии скрыта от захвата)
        r = region_from_frac(frac, {"left": 0, "top": 0, "width": w, "height": h}, "cc")
        crop = img[r["top"]:r["top"] + r["height"], r["left"]:r["left"] + r["width"]]
        found.append((f.name, parse_prompt_lines(ocr.read(crop))))
    hits = [n for n, p in found if p]
    # подсказка «Богатый сундук» есть на кадре 14:34:52, после открытия — нет
    assert any(n == "chest_143452.jpg" for n in hits), found
    assert all(p.get("rarity") in ("богат", "обычн", "") for _, p in found if p)
    assert len(hits) <= 3, f"слишком много срабатываний: {hits}"


# ---------- позиция по кадрам мини-карты ----------
@pytest.mark.parametrize("session", _sessions(), ids=lambda d: d.name)
def test_replay_matches_recording(session):
    from genshinmap.vision.position_tracker import PositionTracker, reference_path

    log = [json.loads(line) for line in (session / "log.jsonl").read_text(encoding="utf-8").splitlines()
           if line.strip()]
    start = next((r for r in log if r["type"] == "start"), {})
    map_id = int(start.get("map_id", 2))
    meta_f = ROOT / "data" / "maps" / str(map_id) / "meta.json"
    if not meta_f.exists():
        pytest.skip("нет данных карты")
    meta = json.loads(meta_f.read_text(encoding="utf-8"))
    ref = reference_path(meta, ROOT / "assets" / "maps" / str(map_id))
    if not ref.exists():
        pytest.skip("нет референса карты (запусти приложение один раз)")
    tr = PositionTracker(meta, ref, scale=start.get("minimap_scale"))

    agree = total = 0
    prev_t = None
    for r in log:
        if r["type"] != "minimap" or not r.get("reliable"):
            continue
        img = cv2.imread(str(session / "minimap" / r["file"]))
        if img is None:
            continue
        if prev_t is not None and r["t"] - prev_t > 3.0:
            tr.last = None
        prev_t = r["t"]
        p = tr.locate(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), r.get("screen_h", 1080), minimap_bgr=img)
        total += 1
        if p and p.reliable and math.hypot(p.x - r["x"], p.y - r["y"]) <= 15:
            agree += 1
    if total < 5:
        pytest.skip("мало надёжных кадров в записи")
    assert agree / total >= 0.8, f"совпало {agree} из {total}"
