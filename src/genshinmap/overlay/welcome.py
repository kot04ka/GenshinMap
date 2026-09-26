"""Первый запуск (3 живых шага) и «Что нового» после обновления.

Оба окна маленькие и немодальные: игре и карте не мешают, закрываются одной
кнопкой. Первый запуск — один раз (settings["onboarded"]); «Что нового» — один
раз на версию (ui_state["last_version"]).
"""
from __future__ import annotations

import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

STYLE = """
QDialog { background: #0f1522; }
QLabel#title { font-size: 17px; font-weight: 700; color: #f1f5fc; }
QLabel#lead { color: #8b9ab8; font-size: 12px; }
QFrame#step { background: #121a2a; border: 1px solid #22304a; border-radius: 10px; }
QFrame#step[done="true"] { border-color: #2f7d45; }
QFrame#step QLabel { background: transparent; border: none; }
QLabel#mark { font-size: 16px; min-width: 22px; }
QLabel#stepText { font-size: 13px; color: #e6ecf6; }
QLabel#stepHint { font-size: 11.5px; color: #8b9ab8; }
QPushButton#primary { background: #1f6feb; color: white; border: none; border-radius: 8px;
  padding: 7px 18px; font-weight: 600; }
QPushButton#primary:hover { background: #3a82f0; }
QPushButton#pick { padding: 6px 12px; }
QLabel#bullet { font-size: 13px; color: #e6ecf6; }
"""

CALIB_AFTER_S = 20          # мини-карта не находится столько секунд — предложить калибровку

WHATS_NEW = {
    "1.0.5": [
        "🧭 Компас вверху экрана и путь прямо на мини-карте игры",
        "🗺 Маршрут по сундукам с телепортами, номерами точек и «⏭ пропустить»",
        "🧰 Сундук определяется по подсказке игры «F ▶ Богатый сундук»",
        "⚙ Новые настройки: всё поверх игры можно выключить (Ctrl+Alt+G), Ctrl+Alt+X — перестать вести",
        "🌐 Русский и английский интерфейс, мини-окно помнит место и размер",
    ],
}


class _Step(QFrame):
    def __init__(self, text: str, hint: str = "", buttons_below: bool = False) -> None:
        super().__init__()
        self.setObjectName("step")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        self.mark = QLabel("○")
        self.mark.setObjectName("mark")
        lay.addWidget(self.mark, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(text)
        t.setObjectName("stepText")
        t.setWordWrap(True)
        col.addWidget(t)
        self.hint = QLabel(hint)
        self.hint.setObjectName("stepHint")
        self.hint.setWordWrap(True)
        self.hint.setVisible(bool(hint))
        col.addWidget(self.hint)
        lay.addLayout(col, 1)
        self.extra = QHBoxLayout()
        if buttons_below:                      # кнопки строкой под текстом
            col.addSpacing(4)
            col.addLayout(self.extra)
        else:
            lay.addLayout(self.extra)

    def set_done(self, done: bool) -> None:
        self.mark.setText("✅" if done else "○")
        self.setProperty("done", "true" if done else "false")
        self.style().unpolish(self)
        self.style().polish(self)


class WelcomeDialog(QDialog):
    """Первый запуск: игра → мини-карта → позиция → что собираем."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self.w = window
        self.setWindowTitle("GenshinMap — первый запуск")
        self.setStyleSheet(STYLE)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(480, 420)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(10)
        t = QLabel("Добро пожаловать!")
        t.setObjectName("title")
        v.addWidget(t)
        lead = QLabel("Три шага — и карта сама покажет, где ты, и будет отмечать собранное.")
        lead.setObjectName("lead")
        lead.setWordWrap(True)
        v.addWidget(lead)

        self.s_game = _Step("Запусти Genshin в оконном или безрамочном режиме")
        self.s_mini = _Step("Выйди в открытый мир — ищу мини-карту игры")
        self.s_pos = _Step("Позиция на карте найдена")
        self.calib_btn = QPushButton("🎯 Калибровка")
        self.calib_btn.setObjectName("pick")
        self.calib_btn.clicked.connect(self.w._open_calibration)
        self.calib_btn.hide()
        self.s_mini.extra.addWidget(self.calib_btn)
        for s in (self.s_game, self.s_mini, self.s_pos):
            v.addWidget(s)

        pick = _Step("Что собираем?", "Остальные слои скроются — вернуть можно в панели слева",
                     buttons_below=True)
        for text, kinds in (("🧰 Сундуки", "['chest']"), ("🔮 Окулусы", "['valuable']"),
                            ("🧭 Всё", "['chest','valuable','seelie','challenge','teleport','statue']")):
            b = QPushButton(text)
            b.setObjectName("pick")
            b.clicked.connect(lambda _=False, k=kinds, s=pick: (
                self.w._js(f"window.showKinds({k});"), s.set_done(True)))
            pick.extra.addWidget(b)
        pick.extra.addStretch(1)
        v.addWidget(pick)

        tips = QLabel("Ctrl+Alt+O — мини-окно поверх игры · Ctrl+Alt+X — перестать вести · "
                      "всё остальное — в ⚙ Настройках")
        tips.setObjectName("lead")
        tips.setWordWrap(True)
        v.addStretch(1)
        v.addWidget(tips)
        row = QHBoxLayout()
        row.addStretch(1)
        done = QPushButton("Готово")
        done.setObjectName("primary")
        done.clicked.connect(self.accept)
        row.addWidget(done)
        v.addLayout(row)

        self._mini_wait_t: float | None = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self._tick()
        self.finished.connect(self._finish)

    def _tick(self) -> None:
        from ..detector.process_watcher import is_genshin_running

        game = is_genshin_running()
        ps = self.w.position_service
        mini = game and ps.running and ps.minimap_visible
        pos = ps.latest(3.0) is not None
        self.s_game.set_done(game)
        self.s_mini.set_done(mini or pos)
        self.s_pos.set_done(pos)
        # игра есть, а мини-карта долго не находится — предложить калибровку
        if game and not (mini or pos):
            self._mini_wait_t = self._mini_wait_t or time.monotonic()
            self.calib_btn.setVisible(time.monotonic() - self._mini_wait_t > CALIB_AFTER_S)
        else:
            self._mini_wait_t = None
            self.calib_btn.hide()

    def _finish(self) -> None:
        self._timer.stop()
        self.w.settings.set("onboarded", True)


class WhatsNewDialog(QDialog):
    def __init__(self, window, version: str) -> None:
        super().__init__(window)
        self.setWindowTitle(f"Что нового в {version}")
        self.setStyleSheet(STYLE)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(10)
        t = QLabel(f"Что нового в {version}")
        t.setObjectName("title")
        v.addWidget(t)
        for line in WHATS_NEW.get(version, []):
            b = QLabel(line)
            b.setObjectName("bullet")
            b.setWordWrap(True)
            v.addWidget(b)
        row = QHBoxLayout()
        row.addStretch(1)
        ok = QPushButton("Понятно")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        v.addSpacing(6)
        v.addLayout(row)
        self.setFixedWidth(480)
        self.setFixedHeight(v.totalHeightForWidth(480))         # высота — ровно по тексту
