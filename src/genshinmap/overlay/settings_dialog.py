"""Окно настроек: разделы слева, содержимое справа (с прокруткой), кнопки внизу.

Каждый раздел помещается на экран сам по себе — окно не вырастает выше экрана.
Горячие клавиши задаются нажатием сочетания (QKeySequenceEdit), а хранятся в
формате HotkeyManager ("<ctrl>+<alt>+m").
"""
from __future__ import annotations

import copy

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..automark import DEFAULT_RULES
from ..storage import DEFAULT_SETTINGS

MUTED = "#8b9ab8"

STYLE = """
QListWidget#nav { background: #0f1522; border: none; border-right: 1px solid #22304a;
  outline: 0; padding: 8px 6px; font-size: 13px; }
QListWidget#nav::item { padding: 10px 12px; border-radius: 8px; margin: 2px 0; color: #c9d4e8; }
QListWidget#nav::item:hover { background: #18233a; }
QListWidget#nav::item:selected { background: #1f3a66; color: #ffffff; font-weight: 600; }
QLabel#pageTitle { font-size: 17px; font-weight: 700; color: #f1f5fc; }
QLabel#pageLead { color: %(m)s; font-size: 12px; }
QLabel#desc { color: %(m)s; font-size: 11.5px; }
QLabel#warn { color: #ffb86b; font-size: 11.5px; }
QFrame#card { background: #121a2a; border: 1px solid #22304a; border-radius: 10px; }
QFrame#card QLabel, QFrame#card QCheckBox { background: transparent; border: none; }
QPushButton#clear { font-size: 14px; padding: 4px 0; min-height: 22px; }
QCheckBox { spacing: 10px; font-size: 13px; }
QCheckBox::indicator { width: 18px; height: 18px; }
QPushButton#primary { background: #1f6feb; color: white; border: none; border-radius: 8px;
  padding: 7px 18px; font-weight: 600; min-height: 22px; }
QPushButton#primary:hover { background: #3a82f0; }
QPushButton#flat { padding: 7px 14px; min-height: 22px; }
""".replace("%(m)s", MUTED)

# действие хоткея -> (название, пояснение)
HOTKEYS = (
    ("toggle_overlay", "Мини-окно поверх игры", "Маленькая карта в углу экрана и обратно"),
    ("toggle_visible", "Скрыть / показать окно карты", "Быстро убрать карту, не закрывая"),
    ("toggle_hud", "Подсказки поверх игры вкл/выкл", "Путь, компас, карточка у сундука"),
    ("stop_nav", "Перестать вести", "Убрать цель и маршрут"),
    ("undo", "Отменить авто-отметку", "Если приложение отметило не то"),
    ("mark_nearest", "Отметить ближайшую точку", "Ручная отметка того, что рядом"),
    ("bookmark", "Закладка в записи отладки", "Нужна только для настройки распознавания"),
)


def combo_to_seq(combo: str) -> QKeySequence:
    """"<ctrl>+<alt>+m" -> QKeySequence("Ctrl+Alt+M")."""
    parts = []
    for p in (combo or "").split("+"):
        p = p.strip().strip("<>")
        if not p:
            continue
        parts.append({"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "cmd": "Meta",
                      "win": "Meta"}.get(p.lower(), p.upper() if len(p) == 1 else p.capitalize()))
    return QKeySequence("+".join(parts))


def seq_to_combo(seq: QKeySequence) -> str:
    """QKeySequence -> "<ctrl>+<alt>+m" (только первое сочетание)."""
    text = seq.toString(QKeySequence.SequenceFormat.PortableText).split(",")[0].strip()
    if not text:
        return ""
    out = []
    for p in text.split("+"):
        low = p.strip().lower()
        if low in ("ctrl", "alt", "shift", "meta"):
            out.append(f"<{'cmd' if low == 'meta' else low}>")
        elif low:
            out.append({"pgup": "page_up", "pgdown": "page_down", "del": "delete",
                        "ins": "insert", "return": "enter", "escape": "esc"}.get(low, low))
    return "+".join(out)


class SettingsDialog(QDialog):
    applied = pyqtSignal(dict)            # «Применить» — настройки без закрытия окна
    restartRequested = pyqtSignal()       # перезапуск (смена языка)
    calibrationRequested = pyqtSignal()

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.setStyleSheet((parent.styleSheet() if parent is not None else "") + STYLE)
        self._initial = copy.deepcopy(settings)
        s = settings

        # размер — по экрану, но не больше разумного
        scr = parent.screen() if parent is not None else None
        avail = scr.availableGeometry() if scr is not None else None
        w = min(820, int(avail.width() * 0.9)) if avail else 820
        h = min(600, int(avail.height() * 0.85)) if avail else 600
        self.resize(w, h)
        self.setMinimumSize(560, 380)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        body = QHBoxLayout()
        body.setSpacing(0)
        root.addLayout(body, 1)

        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(200)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.pages = QStackedWidget()
        body.addWidget(self.nav)
        body.addWidget(self.pages, 1)

        self._build_hud(s)
        self._build_automark(s)
        self._build_hotkeys(s)
        self._build_window(s)
        self._build_language(s)
        self._build_advanced(s)
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)

        # --- кнопки (всегда видны) ---
        bar = QFrame()
        bar.setStyleSheet("QFrame { border-top: 1px solid #22304a; }")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 10, 16, 12)
        reset = QPushButton("Сбросить этот раздел")
        reset.setObjectName("flat")
        reset.clicked.connect(self._reset_page)
        bl.addWidget(reset)
        bl.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.setObjectName("flat")
        cancel.clicked.connect(self.reject)
        apply_ = QPushButton("Применить")
        apply_.setObjectName("flat")
        apply_.clicked.connect(self._apply)
        ok = QPushButton("Сохранить")
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.clicked.connect(self._ok)
        for b in (cancel, apply_, ok):
            bl.addWidget(b)
        root.addWidget(bar)

    # ---------- каркас раздела ----------
    def _page(self, icon: str, title: str, lead: str) -> QVBoxLayout:
        self.nav.addItem(QListWidgetItem(f"{icon}  {title}"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)
        t = QLabel(title)
        t.setObjectName("pageTitle")
        lay.addWidget(t)
        if lead:
            ld = QLabel(lead)
            ld.setObjectName("pageLead")
            ld.setWordWrap(True)
            lay.addWidget(ld)
        scroll.setWidget(inner)
        self.pages.addWidget(scroll)
        return lay

    @staticmethod
    def _card(lay: QVBoxLayout) -> QVBoxLayout:
        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 12, 16, 12)
        cl.setSpacing(10)
        lay.addWidget(card)
        return cl

    @staticmethod
    def _check(cl: QVBoxLayout, text: str, desc: str, on: bool) -> QCheckBox:
        cb = QCheckBox(text)
        cb.setChecked(bool(on))
        cl.addWidget(cb)
        if desc:
            d = QLabel(desc)
            d.setObjectName("desc")
            d.setWordWrap(True)
            d.setContentsMargins(28, 0, 0, 4)
            cl.addWidget(d)
        return cb

    @staticmethod
    def _row(cl: QVBoxLayout, label: str, widget: QWidget, desc: str = "") -> None:
        row = QGridLayout()
        row.setHorizontalSpacing(12)
        lb = QLabel(label)
        lb.setWordWrap(True)
        row.addWidget(lb, 0, 0)
        row.addWidget(widget, 0, 1, alignment=Qt.AlignmentFlag.AlignRight)
        row.setColumnStretch(0, 1)
        if desc:
            d = QLabel(desc)
            d.setObjectName("desc")
            d.setWordWrap(True)
            row.addWidget(d, 1, 0, 1, 2)
        cl.addLayout(row)

    # ---------- разделы ----------
    def _build_hud(self, s: dict) -> None:
        lay = self._page("🎯", "Поверх игры", "Что рисовать прямо поверх окна Genshin. "
                         "В игру ничего не встраивается — это прозрачный слой.")
        c = self._card(lay)
        self.cb_hud_master = self._check(
            c, "Показывать подсказки поверх игры", "Быстро: Ctrl+Alt+G", s.get("hud_enabled", True))
        c = self._card(lay)
        self.cb_hud = {"hud_enabled": self.cb_hud_master}
        for key, text, desc in (
            ("hud_path", "Путь на мини-карте", "Линия от стрелки персонажа до цели, как путь задания"),
            ("hud_compass", "Компас вверху экрана", "Куда повернуть: «↑ прямо / ↖ левее / ↗ правее» и расстояние"),
            ("hud_card", "Карточка с подсказкой и фото", "Появляется справа, когда подходишь к цели"),
            ("hud_toasts", "Сообщения «отмечено»", "На 4 секунды после авто-отметки, с отменой Ctrl+Alt+Z"),
            ("hud_sounds", "Звуки", "Один сигнал — близко, двойной — на месте"),
        ):
            self.cb_hud[key] = self._check(c, text, desc, s.get(key, True))
        c = self._card(lay)
        self.cb_hud["auto_next"] = self._check(
            c, "Собрал сундук — вести к следующему самому",
            "Без маршрута: цель переходит на ближайший несобранный сундук", s.get("auto_next", True))
        self.cb_hud["route_teleports"] = self._check(
            c, "Маршрут может предлагать телепорты",
            "Если от открытого телепорта идти ближе — подскажет «🌀 ТП». Выключи, чтобы только пешком",
            s.get("route_teleports", True))
        lay.addStretch(1)
        self.cb_hud_master.toggled.connect(self._sync_hud)
        self._sync_hud(self.cb_hud_master.isChecked())

    def _sync_hud(self, on: bool) -> None:
        for key in ("hud_path", "hud_compass", "hud_card", "hud_toasts", "hud_sounds"):
            self.cb_hud[key].setEnabled(on)

    def _build_automark(self, s: dict) -> None:
        lay = self._page("✅", "Авто-отметка", "Когда приложение само ставит «собрано». "
                         "Отметку всегда можно снять: Ctrl+Alt+Z или клик по маркеру.")
        c = self._card(lay)
        self.cb_auto = self._check(c, "Отмечать собранное автоматически", "",
                                   s.get("auto_mark_enabled", True))
        rules = s.get("auto_rules") or {}
        c = self._card(lay)
        self.cb_kinds: dict[str, QCheckBox] = {}
        for kind, text, desc in (
            ("chest", "🧰 Сундуки", "Нажал F у сундука (подсказка «F ▶ … сундук») и в «Получено» пришла награда"),
            ("valuable", "🔮 Окулусы и ценности", "Их название появилось в списке «Получено»"),
            ("teleport", "📍 Телепорты", "Подошёл вплотную (активация)"),
            ("statue", "🗿 Статуи Архонтов", "Подошёл вплотную"),
            ("seelie", "🧚 Феи", "Постоял у старта. Ненадёжно — лучше вручную (Ctrl+Alt+M)"),
            ("challenge", "⏱ Испытания", "Постоял у старта. Ненадёжно — лучше вручную"),
        ):
            on = rules.get(kind, {}).get("on", DEFAULT_RULES[kind]["on"])
            self.cb_kinds[kind] = self._check(c, text, desc, on)
        c = self._card(lay)
        self.cb_absence = self._check(
            c, "Сундука нет на месте во второй заход — считать собранным",
            "Первый раз — «❔ вероятно», через 10+ минут снова нет — «✓ собрано». "
            "Только сундуки на поверхности, не после загадок.", s.get("absence_mark", True))
        lay.addStretch(1)

        def sync(on: bool) -> None:
            for cb in [*self.cb_kinds.values(), self.cb_absence]:
                cb.setEnabled(on)

        self.cb_auto.toggled.connect(sync)
        sync(self.cb_auto.isChecked())

    def _build_hotkeys(self, s: dict) -> None:
        lay = self._page("⌨", "Горячие клавиши", "Щёлкни по полю и нажми сочетание. Нужен Ctrl "
                         "или Alt — иначе клавиша будет мешать игре. ✕ — отключить.")
        c = self._card(lay)
        hk = s.get("hotkeys") or {}
        self.hk_edits: dict[str, QKeySequenceEdit] = {}
        for action, title, desc in HOTKEYS:
            ed = QKeySequenceEdit(combo_to_seq(hk.get(action, "")))
            ed.setMaximumSequenceLength(1)
            ed.setFixedWidth(170)
            ed.keySequenceChanged.connect(self._check_hotkeys)
            clr = QPushButton("✕")
            clr.setObjectName("clear")
            clr.setFixedWidth(34)
            clr.setToolTip("Отключить")
            clr.clicked.connect(ed.clear)
            box = QWidget()
            bl = QHBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(6)
            bl.addWidget(ed)
            bl.addWidget(clr)
            self._row(c, title, box, desc)
            self.hk_edits[action] = ed
        self.hk_warn = QLabel("")
        self.hk_warn.setObjectName("warn")
        self.hk_warn.setWordWrap(True)
        lay.addWidget(self.hk_warn)
        lay.addStretch(1)
        self._check_hotkeys()

    def _check_hotkeys(self) -> None:
        combos = {a: seq_to_combo(e.keySequence()) for a, e in self.hk_edits.items()}
        used: dict[str, str] = {}
        problems = []
        names = {a: t for a, t, _ in HOTKEYS}
        for a, c in combos.items():
            if not c:
                continue
            if "<ctrl>" not in c and "<alt>" not in c:
                problems.append(f"«{names[a]}»: добавь Ctrl или Alt")
            if c in used:
                problems.append(f"«{names[a]}» и «{names[used[c]]}» — одинаковое сочетание")
            used[c] = a
        self.hk_warn.setText("⚠ " + "; ".join(problems) if problems else "")

    def _build_window(self, s: dict) -> None:
        lay = self._page("🗺", "Мини-окно и карта", "Место и размер мини-окна запоминаются сами — "
                         "двигай его за полосу сверху, размер меняй за уголок.")
        c = self._card(lay)
        self.sl_opacity = QSlider(Qt.Orientation.Horizontal)
        self.sl_opacity.setRange(50, 100)
        self.sl_opacity.setFixedWidth(200)
        self.sl_opacity.setValue(round(float(s.get("overlay_opacity", 0.9)) * 100))
        self.lb_opacity = QLabel(f"{self.sl_opacity.value()}%")
        self.lb_opacity.setFixedWidth(44)
        self.sl_opacity.valueChanged.connect(lambda v: self.lb_opacity.setText(f"{v}%"))
        box = QWidget()
        bl = QHBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(self.sl_opacity)
        bl.addWidget(self.lb_opacity)
        self._row(c, "Прозрачность мини-окна", box, "Меньше — сквозь карту лучше видно игру")
        c = self._card(lay)
        self.sp_markers = QSpinBox()
        self.sp_markers.setRange(100, 8000)
        self.sp_markers.setSingleStep(100)
        self.sp_markers.setFixedWidth(120)
        self.sp_markers.setValue(int(s.get("max_markers", 1200)))
        self._row(c, "Сколько значков рисовать сразу", self.sp_markers,
                  "Меньше — карта быстрее на слабом компьютере; остальные видны при приближении")
        lay.addStretch(1)

    def _build_language(self, s: dict) -> None:
        from ..i18n import LANGS

        lay = self._page("🌐", "Язык", "")
        c = self._card(lay)
        self.cb_ui_lang, self.cb_game_lang = QComboBox(), QComboBox()
        for code, name in LANGS.items():
            self.cb_ui_lang.addItem(name, code)
            self.cb_game_lang.addItem(name, code)
        for cb in (self.cb_ui_lang, self.cb_game_lang):
            cb.setFixedWidth(170)
        self.cb_ui_lang.setCurrentIndex(max(0, self.cb_ui_lang.findData(s.get("ui_lang", "ru"))))
        self.cb_game_lang.setCurrentIndex(max(0, self.cb_game_lang.findData(s.get("game_lang", "ru"))))
        self._row(c, "Язык приложения", self.cb_ui_lang, "Окна, карта, подсказки")
        self._row(c, "Язык в самой игре", self.cb_game_lang,
                  "Какой язык стоит в Genshin — по нему читаются «Получено» и подсказки у сундуков")
        note = QLabel("Язык меняется после перезапуска приложения.")
        note.setObjectName("desc")
        lay.addWidget(note)
        self.btn_restart = QPushButton("↻ Сохранить и перезапустить")
        self.btn_restart.setObjectName("primary")
        self.btn_restart.setVisible(False)
        self.btn_restart.clicked.connect(self._save_and_restart)
        lay.addWidget(self.btn_restart, alignment=Qt.AlignmentFlag.AlignLeft)
        start = (self.cb_ui_lang.currentData(), self.cb_game_lang.currentData())

        def changed() -> None:
            self.btn_restart.setVisible((self.cb_ui_lang.currentData(),
                                         self.cb_game_lang.currentData()) != start)

        self.cb_ui_lang.currentIndexChanged.connect(changed)
        self.cb_game_lang.currentIndexChanged.connect(changed)
        lay.addStretch(1)

    def _build_advanced(self, s: dict) -> None:
        lay = self._page("🛠", "Дополнительно", "Обычно менять не нужно.")
        c = self._card(lay)
        btn = QPushButton("🎯 Калибровка экрана…")
        btn.setObjectName("flat")
        btn.clicked.connect(self._open_calibration)
        self._row(c, "Где на экране мини-карта и «Получено»", btn,
                  "Если позиция не находится или точка стоит «не там»")
        c = self._card(lay)
        self.sp_interval = QDoubleSpinBox()
        self.sp_interval.setRange(0.15, 3.0)
        self.sp_interval.setSingleStep(0.05)
        self.sp_interval.setDecimals(2)
        self.sp_interval.setSuffix(" с")
        self.sp_interval.setFixedWidth(120)
        self.sp_interval.setValue(float(s.get("track_interval", 0.4)))
        self._row(c, "Как часто искать позицию", self.sp_interval,
                  "Меньше — точка двигается плавнее, но больше нагрузка на компьютер")
        self.sp_radius = QSpinBox()
        self.sp_radius.setRange(10, 300)
        self.sp_radius.setSingleStep(5)
        self.sp_radius.setSuffix(" ед.")
        self.sp_radius.setFixedWidth(120)
        self.sp_radius.setValue(int(s.get("auto_mark_radius", 60)))
        self._row(c, "Радиус «отметить ближайшую»", self.sp_radius,
                  "Для горячей клавиши ручной отметки: как далеко искать точку")
        c = self._card(lay)
        self.cb_admin = self._check(c, "Запускать от администратора",
                                    "Игра работает от администратора — с теми же правами горячие "
                                    "клавиши срабатывают в игре. Нужен перезапуск.",
                                    s.get("run_as_admin", True))
        self.cb_record = self._check(c, "Записывать кадры для отладки распознавания",
                                     "Только когда видна мини-карта игры; папка debug/, до 1 ГБ",
                                     s.get("auto_record", True))
        lay.addStretch(1)

    # ---------- кнопки ----------
    def _reset_page(self) -> None:
        d = DEFAULT_SETTINGS
        i = self.pages.currentIndex()
        if i == 0:
            for key, cb in self.cb_hud.items():
                cb.setChecked(bool(d.get(key, True)))
        elif i == 1:
            self.cb_auto.setChecked(True)
            for kind, cb in self.cb_kinds.items():
                cb.setChecked(DEFAULT_RULES[kind]["on"])
            self.cb_absence.setChecked(True)
        elif i == 2:
            for a, ed in self.hk_edits.items():
                ed.setKeySequence(combo_to_seq(d["hotkeys"].get(a, "")))
        elif i == 3:
            self.sl_opacity.setValue(round(d["overlay_opacity"] * 100))
            self.sp_markers.setValue(d["max_markers"])
        elif i == 4:
            self.cb_ui_lang.setCurrentIndex(max(0, self.cb_ui_lang.findData("ru")))
            self.cb_game_lang.setCurrentIndex(max(0, self.cb_game_lang.findData("ru")))
        elif i == 5:
            self.sp_interval.setValue(d["track_interval"])
            self.sp_radius.setValue(d["auto_mark_radius"])
            self.cb_admin.setChecked(True)
            self.cb_record.setChecked(True)

    def _apply(self) -> None:
        self.applied.emit(self.values())

    def _ok(self) -> None:
        self._apply()
        self.accept()

    def _save_and_restart(self) -> None:
        self._apply()
        self.accept()
        self.restartRequested.emit()

    def _open_calibration(self) -> None:
        self._apply()
        self.accept()
        self.calibrationRequested.emit()

    def values(self) -> dict:
        """Собрать настройки из полей (области экрана и масштаб — как были)."""
        result = copy.deepcopy(self._initial)
        hk = dict(result.get("hotkeys") or {})
        for action, ed in self.hk_edits.items():
            hk[action] = seq_to_combo(ed.keySequence())
        result["hotkeys"] = hk
        for key, cb in self.cb_hud.items():
            result[key] = cb.isChecked()
        result["overlay_opacity"] = round(self.sl_opacity.value() / 100, 2)
        result["max_markers"] = self.sp_markers.value()
        result["auto_mark_radius"] = self.sp_radius.value()
        result["track_interval"] = round(self.sp_interval.value(), 2)
        result["auto_mark_enabled"] = self.cb_auto.isChecked()
        result["absence_mark"] = self.cb_absence.isChecked()
        result["auto_record"] = self.cb_record.isChecked()
        result["run_as_admin"] = self.cb_admin.isChecked()
        result["ui_lang"] = self.cb_ui_lang.currentData()
        result["game_lang"] = self.cb_game_lang.currentData()
        rules = dict(result.get("auto_rules") or {})
        for kind, cb in self.cb_kinds.items():
            rules[kind] = {**rules.get(kind, {}), "on": cb.isChecked()}
        result["auto_rules"] = rules
        return result
