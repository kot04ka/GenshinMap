"""Язык интерфейса: русский (исходный) или английский.

Строки в коде написаны по-русски. В английском режиме их переводит словарь
web/i18n_en.json (русская фраза -> английская), общий для окон Qt и карты:
  - целая строка ищется в словаре; иначе заменяются известные фразы внутри
    неё (так переводятся и строки с подставленными числами/именами);
  - окна, диалоги, меню Qt переводятся сами при показе (фильтр событий) и при
    setText/setToolTip/… — править каждое место в коде не нужно;
  - карта (map.html) переводит свои надписи тем же словарём (MutationObserver).
В русском режиме переводится только стандартный текст Qt (кнопки «Save» и т.п.).

Язык игры (что читает OCR) настраивается отдельно — см. settings["game_lang"].
"""
from __future__ import annotations

import json
import re

from .paths import WEB_DIR

LANGS = {"ru": "Русский", "en": "English"}
_CYR = re.compile("[А-Яа-яЁё]")
_state: dict = {"lang": "ru", "table": {}, "rx": None}


def lang() -> str:
    return _state["lang"]


def table() -> dict[str, str]:
    return _state["table"]


def set_lang(code: str) -> None:
    code = code if code in LANGS else "ru"
    _state["lang"], _state["table"], _state["rx"] = code, {}, None
    if code == "ru":
        return
    try:
        t = json.loads((WEB_DIR / f"i18n_{code}.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    t = {k: v for k, v in t.items() if len(k) >= 2}
    _state["table"] = t
    keys = sorted(t, key=len, reverse=True)
    # фраза — только целиком (не внутри русского слова)
    _state["rx"] = re.compile("(?<![А-Яа-яЁё])(" + "|".join(map(re.escape, keys)) + ")(?![А-Яа-яЁё])")


def tr(text):
    """Перевести строку интерфейса на текущий язык (не строку — вернуть как есть)."""
    if not isinstance(text, str) or _state["rx"] is None or not _CYR.search(text):
        return text
    t = _state["table"]
    core = text.strip()
    if core in t:
        return text.replace(core, t[core])
    return _state["rx"].sub(lambda m: t[m.group(1)], text)


# ---------- Qt ----------
def install_qt(app) -> None:
    """Стандартные переводы Qt + автоматический перевод виджетов (en)."""
    from PyQt6.QtCore import QEvent, QLibraryInfo, QObject, QTranslator

    if lang() == "ru":                       # «Save»/«Cancel» в диалогах — по-русски
        path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        for name in ("qtbase_ru", "qtwebengine_ru"):
            qt = QTranslator(app)
            if qt.load(name, path):
                app.installTranslator(qt)
        return

    _patch_setters()

    class _Filter(QObject):
        def eventFilter(self, obj, ev):
            if ev.type() == QEvent.Type.Show:
                translate_widget(obj)
            return False

    app._i18n_filter = _Filter(app)          # держим ссылку, иначе фильтр удалит GC
    app.installEventFilter(app._i18n_filter)


def translate_widget(w) -> None:
    """Перевести тексты виджета и всех его детей (идемпотентно)."""
    from PyQt6.QtWidgets import (
        QAbstractButton,
        QComboBox,
        QDoubleSpinBox,
        QGroupBox,
        QLabel,
        QLineEdit,
        QListWidget,
        QMenu,
        QSpinBox,
        QTabWidget,
        QWidget,
    )

    if not isinstance(w, QWidget):
        return
    for x in [w, *w.findChildren(QWidget)]:
        if isinstance(x, (QLabel, QAbstractButton)) and _CYR.search(x.text() or ""):
            x.setText(tr(x.text()))
        if isinstance(x, (QSpinBox, QDoubleSpinBox)) and _CYR.search(x.suffix() or ""):
            x.setSuffix(tr(x.suffix()))
        if isinstance(x, QGroupBox) and _CYR.search(x.title() or ""):
            x.setTitle(tr(x.title()))
        if isinstance(x, QLineEdit) and _CYR.search(x.placeholderText() or ""):
            x.setPlaceholderText(tr(x.placeholderText()))
        if isinstance(x, QComboBox):
            for i in range(x.count()):
                if _CYR.search(x.itemText(i)):
                    x.setItemText(i, tr(x.itemText(i)))
        if isinstance(x, QListWidget):
            for i in range(x.count()):
                it = x.item(i)
                if _CYR.search(it.text()):
                    it.setText(tr(it.text()))
        if isinstance(x, QTabWidget):
            for i in range(x.count()):
                x.setTabText(i, tr(x.tabText(i)))
        if isinstance(x, QMenu):
            if _CYR.search(x.title() or ""):
                x.setTitle(tr(x.title()))
            for a in x.actions():
                a.setText(tr(a.text()))
                a.setToolTip(tr(a.toolTip()))
        if _CYR.search(x.toolTip() or ""):
            x.setToolTip(tr(x.toolTip()))
        if x.isWindow() and _CYR.search(x.windowTitle() or ""):
            x.setWindowTitle(tr(x.windowTitle()))


def _patch_setters() -> None:
    """setText/setToolTip/… из кода сразу получают перевод."""
    from PyQt6.QtGui import QAction
    from PyQt6.QtWidgets import (
        QAbstractButton,
        QGroupBox,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMenu,
        QWidget,
    )

    def wrap(cls, name, arg=0):
        orig = getattr(cls, name)

        def f(self, *a):
            a = list(a)
            if len(a) > arg:
                if isinstance(a[arg], QListWidgetItem):      # строка журнала — объектом
                    a[arg].setText(a[arg].text())
                else:
                    a[arg] = tr(a[arg])
            return orig(self, *a)

        setattr(cls, name, f)

    for cls, name, arg in (
        (QLabel, "setText", 0), (QAbstractButton, "setText", 0), (QWidget, "setToolTip", 0),
        (QWidget, "setWindowTitle", 0), (QGroupBox, "setTitle", 0),
        (QLineEdit, "setPlaceholderText", 0), (QAction, "setText", 0), (QAction, "setToolTip", 0),
        (QMenu, "setTitle", 0), (QMenu, "addAction", 0), (QListWidgetItem, "setText", 0),
        (QListWidget, "addItem", 0), (QListWidget, "insertItem", 1),
    ):
        wrap(cls, name, arg)
