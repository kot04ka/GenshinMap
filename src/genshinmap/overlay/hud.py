"""HUD навигации поверх игры (тестовая функция).

Прозрачное окно на весь экран: клики проходят сквозь него в игру, фокус не
забирает. В игру ничего не встраивается и ничего не нажимается — только рисунок
поверх (работает в оконном/безрамочном режиме Genshin).

Рисует:
  - путь к цели прямо НА игровой мини-карте (как путь задания) и кольцо на цели;
  - стрелку у края мини-карты в сторону цели + расстояние (мини-карта Genshin
    всегда смотрит на север — стрелка совпадает с ней);
  - рядом с целью — карточку: подсказка и фото места;
  - звук: подошёл близко — один сигнал, на месте — двойной;
  - всплывашку «🧰 Богатый сундук отмечен · Ctrl+Alt+Z — отменить» (видна и без цели).

Окно HUD скрыто от захвата экрана (SetWindowDisplayAffinity): игрок его видит,
а распознавание — нет. Иначе путь поверх мини-карты сбивал бы поиск позиции, а
карточка «Богатый сундук» читалась бы как подсказка игры. Если Windows этого не
умеет (старше 10 2004), путь на мини-карте не рисуем.
"""
from __future__ import annotations

import contextlib
import ctypes
import math
import threading
import urllib.request

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
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
COMPASS_W = 420
TP_COLOR = "#b58cff"
TOAST_MS = 4500
WDA_EXCLUDEFROMCAPTURE = 0x11
MINIMAP_CLIP = 0.92    # доля радиуса области мини-карты, где реально видна карта
GOLD = "#ffd24a"


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
        self.target: dict | None = None      # {pid, x, y, name, left, layer}
        self.path: list[tuple[float, float]] = []   # путь по местности (A*)
        self.player: tuple[float, float] | None = None
        self.scale = 0.0                     # мир. единиц на px мини-карты @1080p
        self._mm: dict | None = None         # мини-карта на экране (физ. пиксели)
        self._ui_s = 1.0                     # физ. пикселей на пиксель раскладки 1080p
        self.capture_safe = False            # окно скрыто от захвата экрана
        self.heading: float | None = None    # куда бежит игрок, градусы (0 — север)
        # что показывать (⚙ Настройки → «Поверх игры»)
        self.show_path = self.show_compass = self.show_card = True
        self.show_toasts = self.sounds = True
        self.minimap_frac: dict = {}
        self.tip_text = ""
        self.photo: QPixmap | None = None
        self._photo_url = ""
        self._stage = 0                      # 0 далеко, 1 близко, 2 на месте (для звука)
        self.game_active = False
        self._photo_loaded.connect(self._on_photo)
        self._toast: tuple[str, str] | None = None     # (текст, цвет)
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._toast_done)

    def toast(self, text: str, color: str = "#3fb950") -> None:
        """Короткое сообщение поверх игры (отметка/отмена) на TOAST_MS."""
        from ..i18n import tr

        if not self.show_toasts:
            return
        self._toast = (tr(text), color)
        self._toast_timer.start(TOAST_MS)
        self._refresh()

    def _toast_done(self) -> None:
        self._toast = None
        self._refresh()

    # ---------- данные ----------
    def set_target(self, target: dict | None) -> None:
        if (target or {}).get("pid") != (self.target or {}).get("pid"):
            self.tip_text, self.photo, self._photo_url, self._stage = "", None, "", 0
        self.target = target
        self._refresh()

    def set_minimap(self, rect: dict | None, ui_s: float) -> None:
        """Где мини-карта игры на экране сейчас (из сервиса позиции)."""
        self._mm, self._ui_s = rect, ui_s or 1.0

    def _minimap_geom(self) -> tuple[float, float, float, float]:
        """(cx, cy, r, px_на_px_раскладки) мини-карты в координатах этого окна."""
        dpr = self.devicePixelRatioF() or 1.0
        if self._mm:
            with contextlib.suppress(Exception):
                from ctypes import wintypes

                pt = wintypes.POINT(int(self._mm["left"]), int(self._mm["top"]))
                ctypes.windll.user32.ScreenToClient(int(self.winId()), ctypes.byref(pt))
                mw, mh = self._mm["width"] / dpr, self._mm["height"] / dpr
                return (pt.x / dpr + mw / 2, pt.y / dpr + mh / 2, min(mw, mh) / 2,
                        self._ui_s / dpr)
        w, h = self.width(), self.height()
        f = self.minimap_frac
        return ((f["left"] + f["width"] / 2) * w, (f["top"] + f["height"] / 2) * h,
                min(f["width"] * w, f["height"] * h) / 2, h / 1080.0)

    def set_path(self, path: list) -> None:
        self.path = list(path)
        self.update()

    def set_player(self, x: float, y: float, scale: float = 0.0) -> None:
        self.player = (x, y)
        if scale:
            self.scale = scale
        d = self.distance()
        if d is not None:
            stage = 2 if d <= HERE_UNITS else 1 if d <= NEAR_UNITS else 0
            if stage > self._stage and self.sounds and not (self.target or {}).get("tp"):
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
        visible = bool(self.game_active and ((self.target and self.player) or self._toast))
        if visible and not self.isVisible():
            screen = self._game_screen()
            if screen is not None:
                self.setGeometry(screen.geometry())
            self.show()
            self._exclude_from_capture()
        elif not visible and self.isVisible():
            self.hide()
        self.update()

    @staticmethod
    def _game_screen():
        """Монитор, на котором окно игры (иначе основной)."""
        from ..detector.process_watcher import game_monitor_name

        name = game_monitor_name()
        for s in QGuiApplication.screens():
            if name and s.name() == name:
                return s
        return QGuiApplication.primaryScreen()

    def _exclude_from_capture(self) -> None:
        with contextlib.suppress(Exception):
            ok = ctypes.windll.user32.SetWindowDisplayAffinity(int(self.winId()),
                                                               WDA_EXCLUDEFROMCAPTURE)
            self.capture_safe = bool(ok)

    # ---------- рисование ----------
    def paintEvent(self, _e) -> None:
        if not self.minimap_frac and not self._mm:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy, r, ui_k = self._minimap_geom()
        if self._toast:
            self._draw_toast(p, cx - r, cy + r + 62)
        d = self.distance()
        if d is None:
            p.end()
            return
        from ..i18n import tr

        tp = self.target.get("tp")
        via = self.target.get("via")                   # вход в пещеру по пути к цели
        if via and not tp:                             # пока не у входа — считаем до входа
            d = math.hypot(via["x"] - self.player[0], via["y"] - self.player[1])
        # по пути: стрелка на точку пути впереди, расстояние — остаток пути
        if tp:                                          # далеко: сначала телепорт
            dx, dy = self.target["x"] - self.player[0], self.target["y"] - self.player[1]
            aim = (self.target["x"], self.target["y"])
        elif self.path:
            from ..navigation import lookahead

            (ax, ay), rest, _ = lookahead(self.path, *self.player)
            d = max(d, rest) if d > HERE_UNITS else d
            dx, dy = ax - self.player[0], ay - self.player[1]
            aim = (ax, ay)
        else:
            goal = via or self.target
            dx = goal["x"] - self.player[0]
            dy = goal["y"] - self.player[1]
            aim = (goal["x"], goal["y"])
        ang = math.atan2(dy, dx)                      # экранные оси: x вправо, y вниз
        here = d <= HERE_UNITS
        color = QColor(TP_COLOR) if tp else QColor("#3fb950") if here else QColor(GOLD)

        if self.show_path and not tp and self.capture_safe and self.scale:
            self._draw_minimap_path(p, cx, cy, r, ui_k / self.scale, color)

        # стрелка у края мини-карты
        if not tp:
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

        # строка состояния вверху по центру (под мини-картой в игре — строка задания,
        # её не закрываем): телепорт / куда повернуть / расстояние / номер точки
        top = 10.0
        if tp:
            place = f" у «{tp['name']}»" if tp.get("name") else ""
            status = f"🌀 ТП{place} → 🧰"
        elif via:
            status = f"🕳 к входу в пещеру · {d:.0f} ед."
            if self.show_compass and self.heading is not None:
                bearing = math.degrees(math.atan2(aim[0] - self.player[0], -(aim[1] - self.player[1])))
                top = self._draw_compass(p, w, (bearing - self.heading + 540) % 360 - 180, color)
                status = f"{self._turn_hint((bearing - self.heading + 540) % 360 - 180)} · " + status
        elif here:
            status = "🧰 на месте"
        else:
            status = f"🧰 {d:.0f} ед."
            if self.show_compass and self.heading is not None:
                bearing = math.degrees(math.atan2(aim[0] - self.player[0], -(aim[1] - self.player[1])))
                rel = (bearing - self.heading + 540) % 360 - 180
                top = self._draw_compass(p, w, rel, color)
                status = f"{self._turn_hint(rel)} · {d:.0f} ед."
        if not tp and not via:
            status += {1: " · 🕳 в пещере", 2: " · 🌊 под водой", 3: " · ⬇ нижний уровень"}.get(
                self.target.get("layer") or 0, "")
        step = self.target.get("step")
        if step:
            status += f" · {step[0]}/{step[1]}"
        self._draw_status(p, w, top, tr(status), color)

        # карточка рядом с целью: подсказка + фото
        if self.show_card and not tp and d <= NEAR_UNITS and (self.tip_text or self.photo):
            self._draw_card(p, w, h)
        p.end()

    @staticmethod
    def _turn_hint(rel: float) -> str:
        if abs(rel) < 15:
            return "↑ прямо"
        if abs(rel) > 120:
            return "↩ развернись"
        return "↖ левее" if rel < 0 else "↗ правее"

    def _draw_status(self, p: QPainter, w: int, y: float, text: str, color: QColor) -> None:
        """Плашка состояния по центру вверху: тёмная подложка, цветная рамка."""
        p.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        tw = p.fontMetrics().horizontalAdvance(text)
        box = QRectF(w / 2 - tw / 2 - 14, y, tw + 28, 28)
        p.setPen(QPen(color, 1.5))
        p.setBrush(QColor(10, 14, 22, 215))
        p.drawRoundedRect(box, 10, 10)
        p.setPen(QColor(236, 241, 250))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_compass(self, p: QPainter, w: int, rel: float, color: QColor) -> float:
        """Полоса-компас вверху по центру: ▼ — куда бежишь, метка — где цель.
        rel — угол цели относительно направления бега (−180..180, + — правее).
        Возвращает y, где рисовать строку состояния."""
        cw, ch = COMPASS_W, 30
        x0, y0 = (w - cw) / 2, 10
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.setBrush(QColor(10, 14, 22, 190))
        p.drawRoundedRect(QRectF(x0, y0, cw, ch), 10, 10)
        mid = x0 + cw / 2
        p.setPen(QPen(QColor(230, 236, 246, 110), 1.5))
        for a in range(-90, 91, 15):                       # деления каждые 15°
            x = mid + a / 90 * (cw / 2 - 16)
            tick = 9 if a % 45 == 0 else 5
            p.drawLine(QPointF(x, y0 + ch - 4 - tick), QPointF(x, y0 + ch - 4))
        # ▼ — направление бега
        tri = QPainterPath(QPointF(mid, y0 + ch + 2))
        tri.lineTo(QPointF(mid - 7, y0 + ch - 7))
        tri.lineTo(QPointF(mid + 7, y0 + ch - 7))
        tri.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(230, 236, 246, 230))
        p.drawPath(tri)
        # метка цели (за краем — стрелка у края)
        clamped = max(-90.0, min(90.0, rel))
        tx = mid + clamped / 90 * (cw / 2 - 16)
        p.setPen(QPen(QColor(0, 0, 0, 220), 2))
        p.setBrush(color)
        if abs(rel) <= 90:
            p.drawEllipse(QPointF(tx, y0 + ch / 2 - 2), 7, 7)
        else:
            s = 1 if rel > 0 else -1
            arr = QPainterPath(QPointF(tx + s * 8, y0 + ch / 2 - 2))
            arr.lineTo(QPointF(tx - s * 6, y0 + ch / 2 - 10))
            arr.lineTo(QPointF(tx - s * 6, y0 + ch / 2 + 6))
            arr.closeSubpath()
            p.drawPath(arr)
        return y0 + ch + 8

    def _draw_toast(self, p: QPainter, x: float, y: float) -> None:
        text, color = self._toast
        p.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        tw = p.fontMetrics().horizontalAdvance(text)
        rect = QRectF(x, y, tw + 24, 32)
        p.setPen(QPen(QColor(color), 1.5))
        p.setBrush(QColor(10, 14, 22, 225))
        p.drawRoundedRect(rect, 9, 9)
        p.setPen(QColor("#e6ecf6"))
        p.drawText(rect.adjusted(12, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter, text)

    def _draw_minimap_path(self, p: QPainter, cx: float, cy: float, r: float,
                           k: float, color: QColor) -> None:
        """Путь и цель поверх игровой мини-карты (она всегда на север, игрок в центре).
        k — пикселей окна на мировую единицу."""
        px, py = self.player
        tx, ty = self.target["x"], self.target["y"]
        if self.path:
            from ..navigation import nearest_index

            pts = [(px, py)] + self.path[nearest_index(self.path, px, py) + 1:]
        else:
            via = self.target.get("via")
            pts = [(px, py)] + ([(via["x"], via["y"])] if via else [])
        if self.target.get("via") or not self.path:
            pts.append((tx, ty))                      # путь ко входу — и дальше к цели

        def to_screen(x: float, y: float) -> QPointF:
            return QPointF(cx + (x - px) * k, cy + (y - py) * k)

        p.save()
        clip = QPainterPath()
        clip.addEllipse(QPointF(cx, cy), r * MINIMAP_CLIP, r * MINIMAP_CLIP)
        p.setClipPath(clip)
        line = QPainterPath(to_screen(*pts[0]))
        for x, y in pts[1:]:
            line.lineTo(to_screen(x, y))
        p.setBrush(Qt.BrushStyle.NoBrush)
        outline = QPen(QColor(0, 0, 0, 170), 6)
        outline.setCapStyle(Qt.PenCapStyle.RoundCap)
        outline.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(outline)
        p.drawPath(line)
        pen = QPen(color, 3, Qt.PenStyle.SolidLine if self.path else Qt.PenStyle.DashLine)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPath(line)
        # цель: кольцо, если она в пределах мини-карты
        t = to_screen(tx, ty)
        if math.hypot(t.x() - cx, t.y() - cy) <= r * MINIMAP_CLIP:
            p.setPen(QPen(QColor(0, 0, 0, 200), 5))
            p.drawEllipse(t, 8, 8)
            p.setPen(QPen(color, 3))
            p.drawEllipse(t, 8, 8)
        p.restore()

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
