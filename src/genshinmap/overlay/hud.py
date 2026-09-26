"""HUD навигации поверх игры (тестовая функция).

Прозрачное окно на весь экран: клики проходят сквозь него в игру, фокус не
забирает. В игру ничего не встраивается и ничего не нажимается — только рисунок
поверх (работает в оконном/безрамочном режиме Genshin).

Рисует:
  - стрелку у края мини-карты в сторону цели + расстояние (мини-карта Genshin
    всегда смотрит на север — стрелка совпадает с ней);
  - рядом с целью — карточку: подсказка и фото места;
  - звук: подошёл близко — один сигнал, на месте — двойной.
"""
from __future__ import annotations

import contextlib
import math
import threading
import urllib.request

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import QWidget

NEAR_UNITS = 45        # «подходишь» — показать карточку, первый сигнал
HERE_UNITS = 12        # «на месте» — двойной сигнал
CARD_W = 300


def _beep(pattern: tuple[tuple[int, int], ...]) -> None:
    def run():
        with contextlib.suppress(Exception):   # нет звука — не страшно
            import winsound

            for freq, ms in pattern:
                winsound.Beep(freq, ms)

    threading.Thread(target=run, daemon=True).start()


class NavHud(QWidget):
    _photo_loaded = pyqtSignal(str, QImage)

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput
                            | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.target: dict | None = None      # {pid, x, y, name, left}
        self.player: tuple[float, float] | None = None
        self.minimap_frac: dict = {}
        self.tip_text = ""
        self.photo: QPixmap | None = None
        self._photo_url = ""
        self._stage = 0                      # 0 далеко, 1 близко, 2 на месте (для звука)
        self.game_active = False
        self._photo_loaded.connect(self._on_photo)

    # ---------- данные ----------
    def set_target(self, target: dict | None) -> None:
        if (target or {}).get("pid") != (self.target or {}).get("pid"):
            self.tip_text, self.photo, self._photo_url, self._stage = "", None, "", 0
        self.target = target
        self._refresh()

    def set_player(self, x: float, y: float) -> None:
        self.player = (x, y)
        d = self.distance()
        if d is not None:
            stage = 2 if d <= HERE_UNITS else 1 if d <= NEAR_UNITS else 0
            if stage > self._stage:
                _beep(((880, 120),) if stage == 1 else ((988, 110), (1319, 160)))
            self._stage = stage if stage > self._stage or stage == 0 else self._stage
        self._refresh()

    def set_info(self, pid: str, card: dict) -> None:
        """Подсказка к цели: HoYoLAB или первый совет игроков + фото."""
        if not self.target or self.target.get("pid") != pid:
            return
        tips = card.get("tips") or []
        self.tip_text = card.get("content") or (tips[0]["text"] if tips else "") or ""
        url = card.get("img") or next((t["img"] for t in tips if t.get("img")), "")
        if url and url != self._photo_url:
            self._photo_url = url
            threading.Thread(target=self._load_photo, args=(url,), daemon=True).start()
        self.update()

    def _load_photo(self, url: str) -> None:
        with contextlib.suppress(Exception):   # нет фото — карточка без него
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                                       "Referer": "https://act.hoyolab.com/"})
            with urllib.request.urlopen(req, timeout=15) as r:
                img = QImage.fromData(r.read())
            if not img.isNull():
                self._photo_loaded.emit(url, img)

    def _on_photo(self, url: str, img: QImage) -> None:
        if url == self._photo_url:
            self.photo = QPixmap.fromImage(img).scaledToWidth(
                CARD_W - 20, Qt.TransformationMode.SmoothTransformation)
            self.update()

    def set_game_active(self, active: bool) -> None:
        self.game_active = active
        self._refresh()

    def distance(self) -> float | None:
        if not self.target or not self.player:
            return None
        return math.hypot(self.target["x"] - self.player[0], self.target["y"] - self.player[1])

    def _refresh(self) -> None:
        visible = bool(self.target and self.player and self.game_active)
        if visible and not self.isVisible():
            screen = QGuiApplication.primaryScreen()   # тот же монитор, что снимает mss
            if screen is not None:
                self.setGeometry(screen.geometry())
            self.show()
        elif not visible and self.isVisible():
            self.hide()
        self.update()

    # ---------- рисование ----------
    def paintEvent(self, _e) -> None:
        d = self.distance()
        if d is None or not self.minimap_frac:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        f = self.minimap_frac
        cx = (f["left"] + f["width"] / 2) * w
        cy = (f["top"] + f["height"] / 2) * h
        r = min(f["width"] * w, f["height"] * h) / 2
        dx = self.target["x"] - self.player[0]
        dy = self.target["y"] - self.player[1]
        ang = math.atan2(dy, dx)                      # экранные оси: x вправо, y вниз
        here = d <= HERE_UNITS
        color = QColor("#3fb950") if here else QColor("#ffd24a")

        # стрелка у края мини-карты
        tip = QPointF(cx + math.cos(ang) * (r + 34), cy + math.sin(ang) * (r + 34))
        base = QPointF(cx + math.cos(ang) * (r + 6), cy + math.sin(ang) * (r + 6))
        side = QPointF(-math.sin(ang) * 14, math.cos(ang) * 14)
        path = QPainterPath(tip)
        path.lineTo(base + side)
        path.lineTo(base - side)
        path.closeSubpath()
        p.setPen(QPen(QColor(0, 0, 0, 220), 2.5))
        p.setBrush(color)
        p.drawPath(path)

        # подпись: расстояние / «на месте» + сколько осталось по маршруту
        label = "🧰 на месте" if here else f"🧰 {d:.0f}"
        if self.target.get("left"):
            label += f"  · осталось {self.target['left']}"
        font = QFont("Segoe UI", 11, QFont.Weight.Bold)
        p.setFont(font)
        tx = cx - r
        ty = cy + r + 26
        rect = QRectF(tx, ty - 16, max(150, len(label) * 9), 24)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(10, 14, 22, 200))
        p.drawRoundedRect(rect, 8, 8)
        p.setPen(color)
        p.drawText(rect.adjusted(8, 0, -6, 0), Qt.AlignmentFlag.AlignVCenter, label)

        # карточка рядом с целью: подсказка + фото
        if d <= NEAR_UNITS and (self.tip_text or self.photo):
            self._draw_card(p, w, h)
        p.end()

    def _draw_card(self, p: QPainter, w: int, h: int) -> None:
        x = w - CARD_W - 24
        y = h * 0.52
        text = self.tip_text[:180]
        text_h = 20 + 18 * max(1, math.ceil(len(text) / 34)) if text else 0
        photo_h = self.photo.height() + 8 if self.photo else 0
        card = QRectF(x, y, CARD_W, 34 + text_h + photo_h)
        p.setPen(QPen(QColor("#1f6feb"), 1))
        p.setBrush(QColor(14, 20, 32, 225))
        p.drawRoundedRect(card, 10, 10)
        p.setPen(QColor("#e6ecf6"))
        p.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        p.drawText(QRectF(x + 10, y + 6, CARD_W - 20, 22), Qt.AlignmentFlag.AlignVCenter,
                   f"🧰 {self.target.get('name', '')}")
        cy = y + 32
        if text:
            p.setFont(QFont("Segoe UI", 10))
            p.setPen(QColor("#c9d4e8"))
            p.drawText(QRectF(x + 10, cy, CARD_W - 20, text_h), Qt.TextFlag.TextWordWrap, text)
            cy += text_h
        if self.photo:
            p.drawPixmap(int(x + 10), int(cy), self.photo)
