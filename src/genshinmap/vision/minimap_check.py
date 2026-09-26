"""Видна ли на экране настоящая мини-карта игры.

Меню, загрузка, катсцены, открытая большая карта — и окна поверх игры
(браузер и т.п.) — дают в области мини-карты что угодно, и трекер иногда
«находил» там позицию. Проверяем два постоянных элемента интерфейса игры:
  - иконка Паймон в левом верхнем углу области мини-карты (белая);
  - буква N (север) вверху круга.
Нет ни того, ни другого — мини-карты нет: позицию не ищем, кадры не пишем,
текст не читаем.
Эталоны сняты с кадра 1080p (область мини-карты 210x210): assets/ui/.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

SIDE = 210
PAIMON_BOX = (12, 58, 0, 30)          # y0, y1, x0, x1 в кадре SIDE x SIDE
N_WINDOW = (0, 45, 70, 145)
PAIMON_OK = 0.45                      # IoU белой маски Паймон
N_OK = 0.64                           # совпадение буквы N


class MinimapCheck:
    def __init__(self, ui_dir: Path) -> None:
        self.n = cv2.imread(str(ui_dir / "minimap_n.png"), cv2.IMREAD_GRAYSCALE)
        m = cv2.imread(str(ui_dir / "minimap_paimon_mask.png"), cv2.IMREAD_GRAYSCALE)
        self.paimon = None if m is None else m > 127

    @property
    def ready(self) -> bool:
        return self.n is not None and self.paimon is not None

    def scores(self, bgr: np.ndarray) -> tuple[float, float]:
        g = cv2.resize(bgr, (SIDE, SIDE), interpolation=cv2.INTER_AREA)
        y0, y1, x0, x1 = PAIMON_BOX
        hsv = cv2.cvtColor(g[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
        white = (hsv[..., 2] > 200) & (hsv[..., 1] < 50)
        iou = float((white & self.paimon).sum() / max(1, (white | self.paimon).sum()))
        y0, y1, x0, x1 = N_WINDOW
        win = cv2.cvtColor(g[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
        n = max(float(cv2.matchTemplate(win, cv2.resize(self.n, None, fx=s, fy=s),
                                        cv2.TM_CCOEFF_NORMED).max()) for s in (0.9, 1.0, 1.1))
        return iou, n

    def visible(self, bgr: np.ndarray) -> bool:
        if not self.ready:
            return True                       # без эталонов — как раньше
        iou, n = self.scores(bgr)
        return iou >= PAIMON_OK or n >= N_OK
