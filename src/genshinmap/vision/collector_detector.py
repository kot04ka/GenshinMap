"""ЭТАП 2: распознавание факта сбора предмета по экрану.

Когда в Genshin что-то подбираешь, справа всплывает плашка с иконкой и названием
предмета. Мы делаем скриншот заданной области экрана и ищем в нём эталонные
иконки (multi-scale template matching, OpenCV). Никакого чтения памяти игры.

Эталоны кладутся в `assets/templates/` как PNG. Имя файла:
    <label_id>__<любое-описание>.png     напр. 2__anemoculus.png
label_id связывает эталон с категорией карты (см. data/labels.json). Часть до
"__" должна быть числом label_id; если "__" нет — привязки к категории не будет,
но детект имени всё равно работает.

Инструмент для нарезки эталонов: tools/capture_template.py
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import mss
import numpy as np


@dataclass
class Template:
    name: str            # имя из файла (для лога)
    label_id: int | None # категория карты, если закодирована в имени
    image: np.ndarray    # grayscale


@dataclass
class Detection:
    template: Template
    score: float
    location: tuple[int, int]  # (x, y) левый-верхний угол совпадения в области


class CollectorDetector:
    def __init__(
        self,
        templates_dir: str | Path,
        threshold: float = 0.80,
        scales: tuple[float, ...] = (0.6, 0.75, 0.9, 1.0, 1.15, 1.3),
    ) -> None:
        self.templates_dir = Path(templates_dir)
        self.threshold = threshold
        self.scales = scales
        self.templates: list[Template] = self._load_templates()

    # ---- загрузка эталонов ----
    def _parse_label_id(self, stem: str) -> int | None:
        head = stem.split("__", 1)[0]
        return int(head) if head.isdigit() else None

    def _load_templates(self) -> list[Template]:
        out: list[Template] = []
        if not self.templates_dir.exists():
            return out
        for path in sorted(self.templates_dir.glob("*.png")):
            img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            out.append(Template(path.stem, self._parse_label_id(path.stem), img))
        return out

    def reload(self) -> None:
        self.templates = self._load_templates()

    # ---- захват экрана ----
    def grab_region(self, region: dict[str, int] | None = None) -> np.ndarray:
        """Скриншот области экрана -> grayscale. region=None -> весь монитор."""
        with mss.mss() as sct:
            monitor = region or sct.monitors[1]
            shot = np.array(sct.grab(monitor))  # BGRA
        return cv2.cvtColor(shot, cv2.COLOR_BGRA2GRAY)

    # ---- сопоставление ----
    def match_in_image(self, screen: np.ndarray) -> list[Detection]:
        """Вернуть по одному лучшему совпадению на эталон (выше порога)."""
        hits: list[Detection] = []
        sh, sw = screen.shape[:2]
        for tmpl in self.templates:
            best_score, best_loc = 0.0, (0, 0)
            for s in self.scales:
                th = max(1, int(tmpl.image.shape[0] * s))
                tw = max(1, int(tmpl.image.shape[1] * s))
                if th > sh or tw > sw:
                    continue
                resized = cv2.resize(tmpl.image, (tw, th), interpolation=cv2.INTER_AREA)
                res = cv2.matchTemplate(screen, resized, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                if max_val > best_score:
                    best_score, best_loc = max_val, max_loc
            if best_score >= self.threshold:
                hits.append(Detection(tmpl, best_score, best_loc))
        hits.sort(key=lambda d: d.score, reverse=True)
        return hits

    def detect_once(self, region: dict[str, int] | None = None) -> list[Detection]:
        """Один проход по текущему экрану."""
        if not self.templates:
            return []
        return self.match_in_image(self.grab_region(region))
