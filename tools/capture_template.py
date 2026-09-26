"""Инструмент для создания эталонов иконок предметов (Этап 2).

Как пользоваться:

1) Сделать снимок экрана игры в момент, когда видна плашка подобранного предмета:
       python tools/capture_template.py grab
   (даёт 4 секунды переключиться в игру; сохранит снимок в scratch/)

   …или используй любой свой скриншот (PNG/JPG).

2) Вырезать иконку предмета в эталон, привязав к категории карты:
       python tools/capture_template.py crop <файл-скриншота> <label_id> <имя>
   Откроется окно — выдели мышкой прямоугольник вокруг иконки, нажми ENTER.
   Сохранится в assets/templates/<label_id>__<имя>.png

label_id — id категории из data/maps/2/labels.json (напр. Анемокул). Найти можно:
       python tools/capture_template.py labels анемо
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2
import mss
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = ROOT / "assets" / "templates"
SCRATCH = ROOT / "scratch"
LABELS_FILE = ROOT / "data" / "maps" / "2" / "labels.json"


def cmd_grab() -> None:
    SCRATCH.mkdir(exist_ok=True)
    print("Переключись в игру. Снимок через:")
    for i in range(4, 0, -1):
        print(f"  {i}…")
        time.sleep(1)
    with mss.mss() as sct:
        shot = np.array(sct.grab(sct.monitors[1]))
    out = SCRATCH / f"screen_{int(time.time())}.png"
    cv2.imwrite(str(out), cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR))
    print(f"Сохранено: {out}")
    print(f"Теперь: python tools/capture_template.py crop \"{out}\" <label_id> <имя>")


def cmd_crop(image_path: str, label_id: str, name: str) -> None:
    img = cv2.imread(image_path)
    if img is None:
        sys.exit(f"Не удалось открыть {image_path}")
    print("Выдели прямоугольник вокруг иконки и нажми ENTER (или C для отмены).")
    roi = cv2.selectROI("Выдели иконку предмета", img, showCrosshair=True)
    cv2.destroyAllWindows()
    x, y, w, h = roi
    if w == 0 or h == 0:
        sys.exit("Область не выбрана.")
    crop = img[y : y + h, x : x + w]
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in name if c.isalnum() or c in "-_")
    out = TEMPLATES_DIR / f"{label_id}__{safe}.png"
    cv2.imwrite(str(out), crop)
    print(f"Эталон сохранён: {out}  ({w}x{h})")


def cmd_labels(query: str) -> None:
    labels = json.loads(LABELS_FILE.read_text(encoding="utf-8"))
    q = query.lower()
    found = [l for l in labels if q in l["name"].lower()]
    if not found:
        print("Ничего не найдено.")
        return
    for l in found[:40]:
        print(f"  id={l['id']:>4}  {l['name']}  [{l.get('group','')}]")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    cmd = args[0]
    if cmd == "grab":
        cmd_grab()
    elif cmd == "crop" and len(args) >= 4:
        cmd_crop(args[1], args[2], " ".join(args[3:]))
    elif cmd == "labels" and len(args) >= 2:
        cmd_labels(" ".join(args[1:]))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
