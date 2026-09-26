"""Проигрывание записи отладки: трекер позиции по сохранённым кадрам мини-карты.

    python tools/replay_position.py debug/session_20260926_190000
    python tools/replay_position.py debug/session_... --scale 0.8    # задать масштаб
    python tools/replay_position.py debug/session_... --sweep        # подобрать заново

Пишет в папку сессии:
    replay.csv         по кадру: запись vs повтор (x, y, score, margin, надёжность)
    trajectory.png     путь игрока на карте (зелёный — надёжно, красный — нет,
                       синие ромбы — закладки Ctrl+Alt+B)
    unreliable.png     первые кадры, где позицию найти не удалось
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from genshinmap.vision.position_tracker import (
    PositionTracker,
    ensure_reference,
    reference_path,
)

JUMP_WORLD = 150      # скачок дальше этого за < JUMP_S — подозрительно (не телепорт же)
JUMP_S = 2.0


def load_log(session: Path) -> list[dict]:
    lines = (session / "log.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(l) for l in lines if l.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("session", type=Path)
    ap.add_argument("--scale", type=float, default=None)
    ap.add_argument("--sweep", action="store_true", help="игнорировать сохранённый масштаб")
    args = ap.parse_args()
    session: Path = args.session

    log = load_log(session)
    start = next((r for r in log if r["type"] == "start"), {})
    map_id = int(start.get("map_id", 2))
    meta = json.loads((ROOT / "data" / "maps" / str(map_id) / "meta.json").read_text(encoding="utf-8"))
    ref = reference_path(meta, ROOT / "assets" / "maps" / str(map_id))
    ensure_reference(meta, ref)
    scale = args.scale if args.scale else (None if args.sweep else start.get("minimap_scale"))
    tr = PositionTracker(meta, ref, scale=scale)
    print(f"карта {map_id}, масштаб: {scale or 'подбор'}")

    frames = [r for r in log if r["type"] == "minimap"]
    bookmarks = [r for r in log if r["type"] == "bookmark" and "x" in r]
    rows, path, bad = [], [], []
    prev_t, prev_ok = None, None
    for r in frames:
        img = cv2.imread(str(session / "minimap" / r["file"]), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        if prev_t is not None and r["t"] - prev_t > 3.0:
            tr.last = None                      # в записи был разрыв — как после телепорта
        prev_t = r["t"]
        p = tr.locate(img, r.get("screen_h", 1080))
        ok = bool(p and p.reliable)
        jump = ""
        if ok and prev_ok and r["t"] - prev_ok[2] < JUMP_S:
            d = math.hypot(p.x - prev_ok[0], p.y - prev_ok[1])
            if d > JUMP_WORLD:
                jump = f"{d:.0f}"
        if ok:
            prev_ok = (p.x, p.y, r["t"])
            path.append((p.x, p.y))
        else:
            bad.append(r["file"])
        rows.append({
            "file": r["file"], "t": r["t"],
            "rec_x": r.get("x", ""), "rec_y": r.get("y", ""), "rec_ok": r.get("reliable", ""),
            "x": p.x if p else "", "y": p.y if p else "",
            "score": round(p.score, 3) if p else "", "margin": round(p.margin, 3) if p else "",
            "scale": round(p.scale, 4) if p else "", "local": p.local if p else "",
            "ok": ok, "jump": jump,
        })

    with open(session / "replay.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["file"], delimiter=";")
        w.writeheader(); w.writerows(rows)

    n = len(rows)
    n_ok = sum(r["ok"] for r in rows)
    n_jump = sum(1 for r in rows if r["jump"])
    print(f"кадров: {n}, надёжно: {n_ok} ({n_ok / max(1, n):.0%}), подозрительных скачков: {n_jump}")
    print(f"итоговый масштаб: {tr.scale}")

    # --- траектория на карте ---
    if path:
        xs = [p[0] for p in path] + [b["x"] for b in bookmarks]
        ys = [p[1] for p in path] + [b["y"] for b in bookmarks]
        pad = 250
        x0, y0 = tr._world_to_ref(min(xs) - pad, min(ys) - pad)
        x1, y1 = tr._world_to_ref(max(xs) + pad, max(ys) + pad)
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(tr.fine.shape[1], int(x1)), min(tr.fine.shape[0], int(y1))
        crop = cv2.cvtColor(tr.fine[y0:y1, x0:x1], cv2.COLOR_GRAY2BGR)
        k = 1200 / max(1, max(crop.shape[:2]))
        k = min(k, 4.0)
        crop = cv2.resize(crop, None, fx=k, fy=k, interpolation=cv2.INTER_LINEAR)

        def to_px(wx, wy):
            rx, ry = tr._world_to_ref(wx, wy)
            return int((rx - x0) * k), int((ry - y0) * k)

        pts = [to_px(*p) for p in path]
        for a, b in itertools.pairwise(pts):
            cv2.line(crop, a, b, (80, 200, 80), 2)
        for p in pts:
            cv2.circle(crop, p, 3, (60, 230, 60), -1)
        for b in bookmarks:
            c = to_px(b["x"], b["y"])
            cv2.drawMarker(crop, c, (255, 160, 40), cv2.MARKER_DIAMOND, 16, 3)
        cv2.imwrite(str(session / "trajectory.png"), crop)

    # --- кадры без позиции ---
    if bad:
        tiles = []
        for name in bad[:40]:
            im = cv2.imread(str(session / "minimap" / name))
            if im is None:
                continue
            im = cv2.resize(im, (120, 120))
            cv2.putText(im, name[2:8], (3, 115), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 255), 1)
            tiles.append(im)
        while len(tiles) % 8:
            tiles.append(np.zeros((120, 120, 3), np.uint8))
        grid = np.vstack([np.hstack(tiles[i:i + 8]) for i in range(0, len(tiles), 8)])
        cv2.imwrite(str(session / "unreliable.png"), grid)
    print(f"результаты: {session}")


if __name__ == "__main__":
    main()
