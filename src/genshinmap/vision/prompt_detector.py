"""Распознавание подсказок взаимодействия Genshin («F Открыть», «F Подобрать»…).

Подсказка появляется правее центра экрана, когда игрок рядом с объектом, с
которым можно взаимодействовать. Для сундука это надёжный признак:
  - подсказка «Открыть» есть  -> сундук на месте, ещё не открыт;
  - была и пропала рядом       -> сундук только что открыли;
  - стоим вплотную, а её нет   -> сундука нет (уже собран).

Эталоны: assets/prompts/<вид>__<имя>.png, например open__chest.png — вырезанная
надпись подсказки (снимается в окне «Калибровка», режим «Подсказка»).
Эталоны сняты при высоте экрана 1080 (или масштабируются по высоте кадра).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

THRESHOLD = 0.78
SCALES = (0.92, 1.0, 1.08)

# В русской версии подсказка у сундука — его название: «F ▶ Богатый сундук».
# По слову редкости понимаем, какой именно сундук перед игроком.
RARITY = ("обычн", "богат", "драгоц", "роскош", "удивит")
# английский клиент: «Exquisite Chest» -> та же основа, что у русских категорий
RARITY_EN = {"common": "обычн", "exquisite": "богат", "precious": "драгоц",
             "luxurious": "роскош", "remarkable": "удивит"}
_LAT = str.maketrans("aeopcxmkbtyh", "аеорсхмквтун")   # OCR путает латиницу и кириллицу


def norm_text(text: str) -> str:
    return text.lower().replace("ё", "е").translate(_LAT)


def parse_prompt_lines(lines: list[str], lang: str = "ru") -> dict:
    """Строки OCR области подсказок -> {"open": 1.0, "rarity": "богат"}, если среди
    подсказок есть сундук, иначе {}. rarity — "" для особых сундуков."""
    if lang == "en":
        for raw in lines:
            t = raw.lower()
            if "chest" in t:
                return {"open": 1.0, "rarity": next((v for k, v in RARITY_EN.items() if k in t), "")}
        return {}
    for raw in lines:
        t = norm_text(raw)
        if "сундук" in t or "сундy" in t:
            return {"open": 1.0, "rarity": next((r for r in RARITY if r in t), "")}
    return {}


@dataclass
class PromptTemplate:
    kind: str           # "open" и т.п. — часть имени файла до "__"
    name: str
    image: np.ndarray   # серый
    base_h: int = 1080  # высота экрана, при которой снят эталон


class PromptDetector:
    def __init__(self, templates_dir: Path) -> None:
        self.dir = Path(templates_dir)
        self.templates: list[PromptTemplate] = []
        self.reload()

    def reload(self) -> None:
        self.templates = []
        if not self.dir.exists():
            return
        for f in sorted(self.dir.glob("*.png")):
            img = cv2.imdecode(np.fromfile(str(f), np.uint8), cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            kind = f.stem.split("__", 1)[0]
            self.templates.append(PromptTemplate(kind, f.stem, img))

    @property
    def ready(self) -> bool:
        return bool(self.templates)

    def kinds(self) -> set[str]:
        return {t.kind for t in self.templates}

    def detect(self, region_gray: np.ndarray, screen_h: int) -> dict[str, float]:
        """{вид подсказки: уверенность} для найденных в кадре области подсказок."""
        found: dict[str, float] = {}
        k_screen = screen_h / 1080.0
        rh, rw = region_gray.shape[:2]
        for t in self.templates:
            best = 0.0
            for s in SCALES:
                k = k_screen * s * 1080.0 / t.base_h
                h, w = int(t.image.shape[0] * k), int(t.image.shape[1] * k)
                if h < 6 or w < 6 or h >= rh or w >= rw:
                    continue
                tmpl = cv2.resize(t.image, (w, h), interpolation=cv2.INTER_AREA)
                res = cv2.matchTemplate(region_gray, tmpl, cv2.TM_CCOEFF_NORMED)
                best = max(best, float(res.max()))
            if best >= THRESHOLD and best > found.get(t.kind, 0.0):
                found[t.kind] = best
        return found

    def save_template(self, crop_bgr: np.ndarray, kind: str, name: str,
                      screen_h: int = 1080) -> Path:
        """Сохранить эталон, приведя его к экрану высотой 1080."""
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / f"{kind}__{name}.png"
        k = 1080.0 / max(1, screen_h)
        if abs(k - 1.0) > 0.01:
            crop_bgr = cv2.resize(crop_bgr, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".png", crop_bgr)       # путь может быть с кириллицей
        if ok:
            buf.tofile(str(path))
        self.reload()
        return path
