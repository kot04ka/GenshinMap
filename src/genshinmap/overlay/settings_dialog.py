"""Окно настроек приложения: хоткеи и параметры.

Хоткеи вводятся строкой в формате pynput ("<ctrl>+<alt>+m") — это надёжнее, чем
конвертация из QKeySequence, и совпадает с тем, что понимает HotkeyManager.
"""
from __future__ import annotations

import copy

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..automark import DEFAULT_RULES, KINDS
from ..storage import DEFAULT_SETTINGS


class SettingsDialog(QDialog):
    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.setMinimumWidth(420)
        if parent is not None:
            self.setStyleSheet(parent.styleSheet())

        self._initial = copy.deepcopy(settings)
        root = QVBoxLayout(self)

        # --- Хоткеи ---
        hk_box = QGroupBox("Горячие клавиши (формат: <ctrl>+<alt>+m)")
        hk_form = QFormLayout(hk_box)
        hk = settings.get("hotkeys", {})
        self.ed_mark = QLineEdit(hk.get("mark_nearest", ""))
        self.ed_overlay = QLineEdit(hk.get("toggle_overlay", ""))
        self.ed_visible = QLineEdit(hk.get("toggle_visible", ""))
        self.ed_bookmark = QLineEdit(hk.get("bookmark", "<ctrl>+<alt>+b"))
        hk_form.addRow("Отметить ближайшую:", self.ed_mark)
        hk_form.addRow("Мини-оверлей:", self.ed_overlay)
        hk_form.addRow("Скрыть/показать:", self.ed_visible)
        hk_form.addRow("Закладка (запись отладки):", self.ed_bookmark)
        root.addWidget(hk_box)

        # --- Параметры ---
        p_box = QGroupBox("Параметры")
        p_form = QFormLayout(p_box)

        self.sp_markers = QSpinBox()
        self.sp_markers.setRange(100, 8000)
        self.sp_markers.setSingleStep(100)
        self.sp_markers.setValue(int(settings.get("max_markers", 1200)))
        p_form.addRow("Лимит маркеров:", self.sp_markers)

        self.sp_opacity = QDoubleSpinBox()
        self.sp_opacity.setRange(0.5, 1.0)
        self.sp_opacity.setSingleStep(0.05)
        self.sp_opacity.setDecimals(2)
        self.sp_opacity.setValue(float(settings.get("overlay_opacity", 0.9)))
        p_form.addRow("Прозрачность оверлея:", self.sp_opacity)

        size = settings.get("overlay_size", [460, 320])
        self.sp_w = QSpinBox(); self.sp_w.setRange(200, 1920); self.sp_w.setValue(int(size[0]))
        self.sp_h = QSpinBox(); self.sp_h.setRange(150, 1080); self.sp_h.setValue(int(size[1]))
        size_row = QWidget(); sl = QHBoxLayout(size_row); sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(self.sp_w); sl.addWidget(QLabel("×")); sl.addWidget(self.sp_h)
        p_form.addRow("Размер мини-окна:", size_row)
        root.addWidget(p_box)

        # --- Позиция и авто-отметка ---
        a_box = QGroupBox("Позиция игрока и авто-отметка")
        a_form = QFormLayout(a_box)
        self.sp_radius = QSpinBox()
        self.sp_radius.setRange(10, 300)
        self.sp_radius.setSingleStep(5)
        self.sp_radius.setSuffix(" ед.")
        self.sp_radius.setValue(int(settings.get("auto_mark_radius", 60)))
        self.sp_radius.setToolTip("Насколько далеко от игрока искать подобранную точку. "
                                  "Меньше — точнее, но можно промахнуться.")
        a_form.addRow("Радиус авто-отметки:", self.sp_radius)
        self.sp_interval = QDoubleSpinBox()
        self.sp_interval.setRange(0.15, 3.0)
        self.sp_interval.setSingleStep(0.05)
        self.sp_interval.setDecimals(2)
        self.sp_interval.setSuffix(" с")
        self.sp_interval.setValue(float(settings.get("track_interval", 0.4)))
        a_form.addRow("Обновление позиции:", self.sp_interval)
        self.cb_record = QCheckBox("Автозапись отладки, пока идёт игра (debug/, до 1 ГБ)")
        self.cb_record.setChecked(bool(settings.get("auto_record", True)))
        a_form.addRow(self.cb_record)
        self.cb_admin = QCheckBox("Всегда запускать от администратора (нужен перезапуск)")
        self.cb_admin.setChecked(bool(settings.get("run_as_admin", True)))
        a_form.addRow(self.cb_admin)
        self.cb_auto = QCheckBox("Отмечать собранное автоматически по позиции")
        self.cb_auto.setChecked(bool(settings.get("auto_mark_enabled", True)))
        a_form.addRow(self.cb_auto)
        rules = settings.get("auto_rules") or {}
        self.cb_kinds: dict[str, QCheckBox] = {}
        hints = {
            "teleport": "подошёл вплотную",
            "statue": "подошёл вплотную",
            "valuable": "значок пропал с мини-карты / коснулся",
            "chest": "нажал F у сундука",
            "seelie": "постоял у старта феи",
            "challenge": "постоял у старта испытания",
        }
        for kind, (emoji, title) in KINDS.items():
            cb = QCheckBox(f"{emoji} {title} — {hints[kind]}")
            cb.setChecked(bool(rules.get(kind, {}).get("on", DEFAULT_RULES[kind]["on"])))
            self.cb_kinds[kind] = cb
            a_form.addRow(cb)
        root.addWidget(a_box)

        hint = QLabel("Где на экране мини-карта и плашка подбора — задаётся мышью в окне "
                      "«🎯 Калибровка» на панели управления.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#6f7f9f; font-size:11px;")
        root.addWidget(hint)

        # --- Кнопки ---
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        btns.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(
            self._restore_defaults
        )
        root.addWidget(btns)

    def _restore_defaults(self) -> None:
        d = DEFAULT_SETTINGS
        hk = d["hotkeys"]
        self.ed_mark.setText(hk["mark_nearest"])
        self.ed_overlay.setText(hk["toggle_overlay"])
        self.ed_visible.setText(hk["toggle_visible"])
        self.ed_bookmark.setText(hk["bookmark"])
        self.sp_markers.setValue(d["max_markers"])
        self.sp_opacity.setValue(d["overlay_opacity"])
        self.sp_w.setValue(d["overlay_size"][0])
        self.sp_h.setValue(d["overlay_size"][1])
        self.sp_radius.setValue(d["auto_mark_radius"])
        self.sp_interval.setValue(d["track_interval"])
        self.cb_auto.setChecked(True)
        for kind, cb in self.cb_kinds.items():
            cb.setChecked(DEFAULT_RULES[kind]["on"])

    def values(self) -> dict:
        """Собрать настройки из полей (области экрана и масштаб — как были)."""
        result = copy.deepcopy(self._initial)
        result["hotkeys"] = {
            "mark_nearest": self.ed_mark.text().strip(),
            "toggle_overlay": self.ed_overlay.text().strip(),
            "toggle_visible": self.ed_visible.text().strip(),
            "bookmark": self.ed_bookmark.text().strip(),
        }
        result["max_markers"] = self.sp_markers.value()
        result["overlay_opacity"] = round(self.sp_opacity.value(), 2)
        result["overlay_size"] = [self.sp_w.value(), self.sp_h.value()]
        result["auto_mark_radius"] = self.sp_radius.value()
        result["track_interval"] = round(self.sp_interval.value(), 2)
        result["auto_mark_enabled"] = self.cb_auto.isChecked()
        result["auto_record"] = self.cb_record.isChecked()
        result["run_as_admin"] = self.cb_admin.isChecked()
        rules = dict(result.get("auto_rules") or {})
        for kind, cb in self.cb_kinds.items():
            rules[kind] = {**rules.get(kind, {}), "on": cb.isChecked()}
        result["auto_rules"] = rules
        return result
