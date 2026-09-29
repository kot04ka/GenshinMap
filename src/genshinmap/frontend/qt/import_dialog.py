"""Импорт уже собранного с HoYoLAB и appsample.

HoYoLAB: в окне открывается интерактивная карта HoYoLAB, пользователь входит в
свой аккаунт, по кнопке забираем его отметки (API map/point/mark_map_point_list,
куки сессии из этого окна). Профиль браузера — «инкогнито»: вход не
сохраняется на диск и после закрытия окна исчезает.

appsample: их сайт хранит отметки в облаке, копию — в браузере под ключом
gim-local-markers (у них кнопка «скачать в браузер»). Пользователь копирует её
одной командой в консоли своего браузера и вставляет сюда; их id меток
переводим в точки HoYoLAB по data/maps/<id>/appsample.json.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtWebEngineCore import QWebEngineProfile
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

HOYOLAB_MAP = "https://act.hoyolab.com/ys/app/interactive-map/index.html?lang=ru-ru#/map/{map_id}"
MARKS_API = ("https://sg-public-api.hoyolab.com/common/map_user/ys_obc/v1/map/point/"
             "mark_map_point_list?map_id={map_id}&app_sn=ys_obc&lang=ru-ru")
APPSAMPLE_SNIPPET = "copy(localStorage.getItem('gim-local-markers'))"


def extract_point_ids(obj, known: set[str]) -> set[str]:
    """Все id точек из ответа неизвестной формы: числа под ключами *point_id*/id
    и элементы списков — оставляем только те, что есть на карте."""
    out: set[str] = set()

    def walk(o, key: str = "") -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, k)
        elif isinstance(o, list):
            for v in o:
                walk(v, key)
        elif isinstance(o, (int, str)) and ("id" in key or "point" in key or key in ("list", "")):
            s = str(o)
            if s in known:
                out.add(s)

    walk(obj)
    return out


def appsample_to_points(pasted: str, map_dir: Path) -> set[str]:
    """Вставленный gim-local-markers -> id точек HoYoLAB."""
    text = pasted.strip()
    if text[:1] == "'" and text[-1:] == "'":        # вставили вместе с кавычками консоли
        text = text[1:-1]
    data = json.loads(text)
    if isinstance(data, str):                      # иногда копируется как строка JSON
        data = json.loads(data)
    their = {str(x) for x in (data.get("markerIds") if isinstance(data, dict) else data) or []}
    mapping = json.loads((map_dir / "appsample.json").read_text(encoding="utf-8"))
    reverse = {str(v[0]): pid for pid, v in mapping.items()}
    return {reverse[t] for t in their if t in reverse}


class ImportDialog(QDialog):
    imported = pyqtSignal(object, str)             # set[point_id], источник

    def __init__(self, map_id: int, map_dir: Path, known_ids: set[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Импорт собранного")
        self.resize(1000, 720)
        if parent is not None:
            self.setStyleSheet(parent.styleSheet())
        self.map_id, self.map_dir, self.known = map_id, map_dir, known_ids
        self._cookies: dict[str, str] = {}

        tabs = QTabWidget()
        tabs.addTab(self._hoyolab_tab(), "HoYoLAB")
        tabs.addTab(self._appsample_tab(), "appsample")
        root = QVBoxLayout(self)
        root.addWidget(tabs)

    # ---------- HoYoLAB ----------
    def _hoyolab_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("1. Войди в свой аккаунт HoYoLAB в окне ниже (вход не сохраняется).\n"
                           "2. Нажми «Импортировать мои отметки»."))
        self.profile = QWebEngineProfile(self)          # без имени = «инкогнито», в памяти
        self.profile.cookieStore().cookieAdded.connect(self._on_cookie)
        from PyQt6.QtWebEngineCore import QWebEnginePage

        self.web = QWebEngineView()
        self.web.setPage(QWebEnginePage(self.profile, self.web))
        self.web.load(QUrl(HOYOLAB_MAP.format(map_id=self.map_id)))
        v.addWidget(self.web, 1)
        self.hoyo_status = QLabel("")
        self.hoyo_status.setWordWrap(True)
        v.addWidget(self.hoyo_status)
        btn = QPushButton("⬇ Импортировать мои отметки с HoYoLAB")
        btn.clicked.connect(self._import_hoyolab)
        v.addWidget(btn)
        return w

    def _on_cookie(self, cookie) -> None:
        domain = cookie.domain()
        if "hoyolab" in domain or "hoyoverse" in domain:
            name = bytes(cookie.name()).decode(errors="ignore")
            self._cookies[name] = bytes(cookie.value()).decode(errors="ignore")

    def _import_hoyolab(self) -> None:
        if not any(k.startswith(("ltoken", "cookie_token", "ltuid")) for k in self._cookies):
            self.hoyo_status.setText("Сначала войди в аккаунт HoYoLAB в окне выше.")
            return
        cookie = "; ".join(f"{k}={v}" for k, v in self._cookies.items())
        req = urllib.request.Request(MARKS_API.format(map_id=self.map_id), headers={
            "User-Agent": "Mozilla/5.0", "Referer": "https://act.hoyolab.com/", "Cookie": cookie})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                resp = json.load(r)
        except Exception as e:  # noqa: BLE001
            self.hoyo_status.setText(f"Не удалось получить отметки: {e}")
            return
        if resp.get("retcode") not in (0, None):
            self.hoyo_status.setText(f"HoYoLAB ответил: {resp.get('message')} (код {resp.get('retcode')})")
            return
        ids = extract_point_ids(resp.get("data"), self.known)
        self.hoyo_status.setText(f"Найдено отмеченных точек: {len(ids)}")
        if ids:
            self.imported.emit(ids, "HoYoLAB")

    # ---------- appsample ----------
    def _appsample_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        text = QLabel(
            "1. Открой genshin-impact-map.appsample.com в своём браузере и войди в аккаунт.\n"
            "2. В их меню найди раздел резервной копии и нажми «download to browser» "
            "(скачать отметки в браузер).\n"
            "3. Нажми F12 → вкладка Console, вставь команду ниже, нажми Enter — данные скопируются.\n"
            "4. Вставь их в поле ниже (Ctrl+V) и нажми «Импортировать».")
        text.setWordWrap(True)
        v.addWidget(text)
        cmd = QPlainTextEdit(APPSAMPLE_SNIPPET)
        cmd.setReadOnly(True)
        cmd.setFixedHeight(40)
        v.addWidget(cmd)
        self.paste = QPlainTextEdit()
        self.paste.setPlaceholderText('Сюда вставить {"markerIds":[...]}')
        v.addWidget(self.paste, 1)
        self.app_status = QLabel("")
        v.addWidget(self.app_status)
        btn = QPushButton("⬇ Импортировать с appsample")
        btn.clicked.connect(self._import_appsample)
        v.addWidget(btn)
        return w

    def _import_appsample(self) -> None:
        try:
            ids = appsample_to_points(self.paste.toPlainText(), self.map_dir)
        except (ValueError, OSError, AttributeError, TypeError) as e:
            self.app_status.setText(f"Не получилось разобрать данные: {e}")
            return
        self.app_status.setText(f"Сопоставлено с картой: {len(ids)} точек")
        if ids:
            self.imported.emit(ids, "appsample")
