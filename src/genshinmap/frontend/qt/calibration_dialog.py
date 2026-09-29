"""Окно калибровки: где на экране мини-карта и где всплывает плашка подбора.

Пользователь делает снимок экрана игры (или открывает свой скриншот), мышью
обводит мини-карту и область плашки подобранного предмета. Сохраняем в долях
экрана — так работает на любом разрешении. Кнопка «Проверить позицию» сразу
прогоняет трекер по выделенной мини-карте и показывает найденную точку.
"""
from __future__ import annotations

import threading

import cv2
import mss
import numpy as np
from PyQt6.QtCore import QPoint, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from genshinmap.backend.vision.position_tracker import DEFAULT_SCALE, inner_square
from genshinmap.frontend.qt.icons import icon

COLORS = {"minimap": QColor("#ffd24a"), "pickup": QColor("#4ad8ff"),
          "prompt": QColor("#ff6ad5")}
TITLES = {"minimap": "Мини-карта", "pickup": "Плашка подбора",
          "prompt": "Подсказка «Открыть»"}


def _to_qimage(bgr: np.ndarray) -> QImage:
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


class ShotCanvas(QWidget):
    """Снимок экрана, на котором мышью рисуются прямоугольники областей."""

    changed = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(640, 360)
        self.image: QImage | None = None
        self.rects: dict[str, tuple[float, float, float, float]] = {}   # доли экрана
        self.mode = "minimap"
        self._drag_from: QPoint | None = None
        self._drag_to: QPoint | None = None
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_image(self, img: QImage) -> None:
        self.image = img
        self.update()

    def _target(self) -> QRect:
        """Где на виджете нарисована картинка (с сохранением пропорций)."""
        if self.image is None:
            return QRect()
        iw, ih = self.image.width(), self.image.height()
        k = min(self.width() / iw, self.height() / ih)
        w, h = int(iw * k), int(ih * k)
        return QRect((self.width() - w) // 2, (self.height() - h) // 2, w, h)

    def _to_frac(self, p: QPoint) -> tuple[float, float]:
        t = self._target()
        return (min(1.0, max(0.0, (p.x() - t.x()) / max(1, t.width()))),
                min(1.0, max(0.0, (p.y() - t.y()) / max(1, t.height()))))

    def _frac_rect(self, fr: tuple[float, float, float, float]) -> QRect:
        t = self._target()
        return QRect(int(t.x() + fr[0] * t.width()), int(t.y() + fr[1] * t.height()),
                     int(fr[2] * t.width()), int(fr[3] * t.height()))

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#0a0e16"))
        if self.image is None:
            p.setPen(QColor("#8ea1c2"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Сделай снимок экрана игры или открой скриншот")
            return
        p.drawImage(self._target(), self.image)
        for key, fr in self.rects.items():
            p.setPen(QPen(COLORS[key], 2))
            r = self._frac_rect(fr)
            p.drawRect(r)
            p.drawText(r.x() + 3, r.y() - 4, TITLES[key])
        if self._drag_from and self._drag_to:
            p.setPen(QPen(COLORS[self.mode], 1, Qt.PenStyle.DashLine))
            p.drawRect(QRect(self._drag_from, self._drag_to).normalized())

    def mousePressEvent(self, e) -> None:
        if self.image is not None and e.button() == Qt.MouseButton.LeftButton:
            self._drag_from = self._drag_to = e.position().toPoint()

    def mouseMoveEvent(self, e) -> None:
        if self._drag_from:
            self._drag_to = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e) -> None:
        if not self._drag_from:
            return
        a = self._to_frac(self._drag_from)
        b = self._to_frac(e.position().toPoint())
        self._drag_from = self._drag_to = None
        x0, x1 = sorted((a[0], b[0])); y0, y1 = sorted((a[1], b[1]))
        if (x1 - x0) > 0.005 and (y1 - y0) > 0.005:
            if self.mode == "minimap":
                # мини-карта круглая — выравниваем до квадрата в пикселях экрана
                iw, ih = self.image.width(), self.image.height()
                side = min((x1 - x0) * iw, (y1 - y0) * ih)
                x1, y1 = x0 + side / iw, y0 + side / ih
            self.rects[self.mode] = (x0, y0, x1 - x0, y1 - y0)
            self.changed.emit()
        self.update()


# рамка на снимке <-> ключ настроек (доли эталонной раскладки 1920x1080, см. vision.layout)
_KEYS = {"minimap": "minimap", "pickup": "pickup_region", "prompt": "prompt_region"}


class CalibrationDialog(QDialog):
    # результат проверки позиции приходит из рабочего потока
    _located = pyqtSignal(object)

    def __init__(self, settings: dict, position_service, map_id: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Калибровка: мини-карта и плашка подбора")
        self.resize(1100, 720)
        if parent is not None:
            self.setStyleSheet(parent.styleSheet())
        self.service = position_service
        self.map_id = map_id
        self.shot: np.ndarray | None = None      # BGR полного экрана
        self.found_scale: float | None = None
        self.found_position = None
        scales = settings.get("minimap_scale") or {}
        self._scale = scales.get(str(map_id)) or DEFAULT_SCALE

        root = QVBoxLayout(self)
        top = QHBoxLayout()
        self.btn_grab = QPushButton(icon("camera"), "Снимок экрана через 3 с")
        self.btn_grab.clicked.connect(self._grab_delayed)
        self.btn_open = QPushButton(icon("folder"), "Открыть скриншот…")
        self.btn_open.clicked.connect(self._open_file)
        self.rb_mini = QRadioButton("Обвести мини-карту"); self.rb_mini.setChecked(True)
        self.rb_pick = QRadioButton("Обвести область плашки подбора")
        self.rb_prompt = QRadioButton("Обвести подсказку «Открыть»")
        self.rb_prompt.setToolTip("Встань у НЕоткрытого сундука, чтобы справа появилась "
                                  "подсказка «F Открыть», сделай снимок и обведи её")
        self.rb_mini.toggled.connect(lambda on: on and self._set_mode("minimap"))
        self.rb_pick.toggled.connect(lambda on: on and self._set_mode("pickup"))
        self.rb_prompt.toggled.connect(lambda on: on and self._set_mode("prompt"))
        for w in (self.btn_grab, self.btn_open, self.rb_mini, self.rb_pick, self.rb_prompt):
            top.addWidget(w)
        top.addStretch(1)
        root.addLayout(top)

        mid = QHBoxLayout()
        self.canvas = ShotCanvas()
        self.canvas.changed.connect(self._update_preview)
        mid.addWidget(self.canvas, 1)

        side = QVBoxLayout()
        side.addWidget(QLabel("Мини-карта (то, что пойдёт в поиск):"))
        self.preview = QLabel()
        self.preview.setFixedSize(220, 220)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("background:#0a0e16;border:1px solid #26314a;border-radius:6px;")
        side.addWidget(self.preview)
        self.btn_test = QPushButton(icon("locate"), "Проверить позицию")
        self.btn_test.clicked.connect(self._test_position)
        side.addWidget(self.btn_test)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        side.addWidget(self.result)
        help_ = QLabel(
            "1. Открой игру (оконный/безрамочный режим), встань на открытой местности.\n"
            "2. «Снимок через 3 с» — окно спрячется, переключись в игру.\n"
            "3. Обведи круг мини-карты (жёлтая рамка — ровно по кругу).\n"
            "4. Обведи область, где всплывают подобранные предметы (голубая).\n"
            "6. У неоткрытого сундука: снимок и обведи подсказку «F Открыть» (розовая) — "
            "по ней приложение понимает, есть сундук на месте или уже собран.\n"
            "5. «Проверить позицию» — точка должна совпасть с тем, где ты стоишь.")
        help_.setWordWrap(True)
        help_.setStyleSheet("color:#6f7f9f; font-size:11px;")
        side.addWidget(help_)
        side.addStretch(1)
        mid.addLayout(side)
        root.addLayout(mid, 1)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        # текущие значения из настроек (в раскладке; на снимок переводим в _set_shot)
        self._design = {mode: settings.get(key) for mode, key in _KEYS.items()
                        if mode != "prompt" and settings.get(key)}
        for mode, fr in self._design.items():
            self.canvas.rects[mode] = (fr["left"], fr["top"], fr["width"], fr["height"])
        self._located.connect(self._on_located)

    # ---------- снимок ----------
    def _set_mode(self, mode: str) -> None:
        self.canvas.mode = mode

    def _grab_delayed(self) -> None:
        # прячем и диалог, и главное окно (оно «поверх всех» и закрыло бы игру)
        self._hidden = [w for w in (self, self.parent()) if w is not None and w.isVisible()]
        for w in self._hidden:
            w.hide()
        QTimer.singleShot(3000, self._grab_now)

    def _grab_now(self) -> None:
        from genshinmap.backend.vision.position_service import game_rect

        with mss.mss() as sct:
            shot = np.array(sct.grab(game_rect(sct)))     # только окно игры
        for w in reversed(self._hidden):
            w.show()
        self.raise_(); self.activateWindow()
        self._set_shot(cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR))

    def _open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Скриншот игры", "",
                                              "Изображения (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        img = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)  # путь с кириллицей
        if img is not None:
            self._set_shot(img)

    def _set_shot(self, bgr: np.ndarray) -> None:
        from genshinmap.backend.vision.layout import ANCHORS, region_from_frac

        if self.shot is not None:                 # рамки прошлого снимка -> раскладка
            self._design.update(self._canvas_design())
        self.shot = bgr
        h, w = bgr.shape[:2]
        for mode, fr in self._design.items():     # раскладка -> рамки на этом снимке
            r = region_from_frac(fr, {"left": 0, "top": 0, "width": w, "height": h},
                                 ANCHORS[_KEYS[mode]])
            self.canvas.rects[mode] = (r["left"] / w, r["top"] / h, r["width"] / w, r["height"] / h)
        self.canvas.set_image(_to_qimage(bgr))
        self._update_preview()

    def _canvas_design(self) -> dict:
        """Рамки на текущем снимке -> доли эталонной раскладки (для любого разрешения)."""
        from genshinmap.backend.vision.layout import ANCHORS, frac_from_region

        if self.shot is None:
            return {m: {"left": fr[0], "top": fr[1], "width": fr[2], "height": fr[3]}
                    for m, fr in self.canvas.rects.items()}
        h, w = self.shot.shape[:2]
        return {m: frac_from_region(fr[0] * w, fr[1] * h, fr[2] * w, fr[3] * h, w, h,
                                    ANCHORS[_KEYS[m]])
                for m, fr in self.canvas.rects.items() if m in _KEYS}

    # ---------- мини-карта ----------
    def _minimap_crop(self) -> np.ndarray | None:
        fr = self.canvas.rects.get("minimap")
        if self.shot is None or not fr:
            return None
        h, w = self.shot.shape[:2]
        x, y = int(fr[0] * w), int(fr[1] * h)
        cw, ch = max(8, int(fr[2] * w)), max(8, int(fr[3] * h))
        crop = self.shot[y:y + ch, x:x + cw]
        return crop if crop.size else None

    def _update_preview(self) -> None:
        crop = self._minimap_crop()
        if crop is None:
            self.preview.clear()
            return
        vis = crop.copy()
        # показываем, какой квадрат реально уйдёт в поиск
        sq = inner_square(np.zeros(vis.shape[:2], np.uint8))
        s = sq.shape[0]
        y0, x0 = (vis.shape[0] - s) // 2, (vis.shape[1] - s) // 2
        cv2.rectangle(vis, (x0, y0), (x0 + s, y0 + s), (74, 210, 255), 1)
        pm = QPixmap.fromImage(_to_qimage(vis)).scaled(
            220, 220, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.preview.setPixmap(pm)

    def _test_position(self) -> None:
        crop = self._minimap_crop()
        if crop is None:
            self.result.setText("Сначала сделай снимок и обведи мини-карту.")
            return
        from genshinmap.backend.vision.layout import ui_scale

        screen_h = 1080.0 * ui_scale(self.shot.shape[1], self.shot.shape[0])
        self.btn_test.setEnabled(False)
        self.result.setText("Ищу… (первый раз — до ~15 с: подбирается масштаб мини-карты;"
                            " если карта для позиции ещё не скачана — дольше)")
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)

        def work():
            try:
                pos = self.service.locate_image(crop, screen_h, self._scale)
            except Exception as e:  # noqa: BLE001
                pos = e
            self._located.emit(pos)

        threading.Thread(target=work, daemon=True).start()

    def _on_located(self, pos) -> None:
        QApplication.restoreOverrideCursor()
        self.btn_test.setEnabled(True)
        if isinstance(pos, Exception):
            self.result.setText(f"Ошибка: {pos}")
            return
        if pos is None:
            self.result.setText("Не нашлось. Проверь, что рамка ровно по кругу мини-карты "
                                "и на ней видна местность (не меню/загрузка).")
            return
        ok = pos.reliable
        self.result.setText(
            f"{'✓ Надёжно' if ok else '⚠ Неуверенно'}: x={pos.x:.0f}, y={pos.y:.0f}\n"
            f"совпадение {pos.score:.0%}, однозначность {pos.margin:.2f}, "
            f"масштаб {pos.scale:.3f}\n"
            + ("Точка показана на карте — сверь с тем, где стоишь."
               if ok else "Попробуй встать в месте с приметными объектами "
                          "(дороги, скалы, постройки), не в пустыне/море."))
        self.found_position = pos
        if ok:
            self.found_scale = pos.scale
            parent = self.parent()
            if parent is not None and hasattr(parent, "show_player"):
                parent.show_player(pos)

    def prompt_crop(self):
        """(вырезанная подсказка BGR, высота раскладки) или None, если не обведена."""
        fr = self.canvas.rects.get("prompt")
        if self.shot is None or not fr:
            return None
        h, w = self.shot.shape[:2]
        x, y = int(fr[0] * w), int(fr[1] * h)
        crop = self.shot[y:y + max(6, int(fr[3] * h)), x:x + max(6, int(fr[2] * w))]
        from genshinmap.backend.vision.layout import ui_scale

        return (crop.copy(), round(1080 * ui_scale(w, h))) if crop.size else None

    # ---------- результат ----------
    def values(self) -> dict:
        """Изменённые настройки (доли экрана + масштаб мини-карты текущей карты)."""
        out: dict = {}
        design = self._canvas_design()
        for mode in ("minimap", "pickup"):
            fr = design.get(mode)
            if fr:
                out[_KEYS[mode]] = {k: round(v, 5) for k, v in fr.items()}
        return out
