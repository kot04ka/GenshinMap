"""Окно-оверлей с интерактивной картой.

Показывает карту Leaflet внутри QWebEngineView, держит окно поверх других,
следит за статусом процесса Genshin и связывает клики по маркерам с хранилищем.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QIcon
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import (
    QWebEngineProfile,
    QWebEngineUrlRequestInterceptor,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizeGrip,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from genshinmap.backend.core import i18n
from genshinmap.backend.core.i18n import tr
from genshinmap.backend.core.paths import PROJECT_ROOT, WEB_DIR, WEB_TO_ROOT
from genshinmap.backend.core.storage import (
    ObservationStore,
    ProgressStore,
    SettingsStore,
    UIStateStore,
)
from genshinmap.backend.core.version import __version__
from genshinmap.backend.game.automark import AutoMarker
from genshinmap.backend.game.process_watcher import is_genshin_running
from genshinmap.backend.game.progress_io import export_progress, import_progress
from genshinmap.backend.game.rewards import PrimogemCounter
from genshinmap.backend.maps.custom_points import (
    CUSTOM_LABEL,
    CUSTOM_NAME,
    CustomPoints,
)
from genshinmap.backend.maps.mapdata import (
    ASSETS_MAPS,
    DATA_MAPS,
    load_map_index,
    map_dir,
    write_bundle,
)
from genshinmap.backend.maps.mapindex import Candidate, MapIndex
from genshinmap.backend.maps.navigation import (
    NavGrid,
    ensure_road_reference,
    lookahead,
    road_reference_path,
)
from genshinmap.backend.maps.pointinfo import PointInfoService
from genshinmap.backend.maps.regions import build_regions
from genshinmap.backend.services.datasync import DataSync
from genshinmap.backend.services.static_server import ensure_server
from genshinmap.backend.services.updater import Updater
from genshinmap.backend.vision.debug_recorder import DebugRecorder
from genshinmap.backend.vision.detection_service import DetectionService
from genshinmap.backend.vision.position_service import (
    PositionService,
    game_rect,
    region_from_frac,
)
from genshinmap.backend.vision.position_tracker import (
    DEFAULT_SCALE,
    REF_ZOOM,
    reference_path,
    water_reference_path,
)
from genshinmap.backend.vision.prompt_detector import PromptDetector
from genshinmap.frontend.qt.bridge import MapBridge
from genshinmap.frontend.qt.calibration_dialog import CalibrationDialog
from genshinmap.frontend.qt.hotkeys import HotkeyManager, is_admin
from genshinmap.frontend.qt.hud import NavHud
from genshinmap.frontend.qt.input_watcher import InputWatcher
from genshinmap.frontend.qt.settings_dialog import SettingsDialog

MAP_HTML = WEB_DIR / "map.html"
TEMPLATES_DIR = PROJECT_ROOT / "assets" / "templates"
LOGO = PROJECT_ROOT / "assets" / "logo.png"
DEBUG_DIR = PROJECT_ROOT / "debug"
PROMPTS_DIR = PROJECT_ROOT / "assets" / "prompts"
PROMPT_MAX_AGE = 1.5      # подсказки старше этого (с) для вывода не используем
OPEN_WINDOW_S = 6.0         # после F у сундука столько ждём плашку открытия
INTERACT_POS_AGE = 10.0     # позиция для F: последняя известная за столько секунд
CHEST_MARK_RADIUS = 15      # сундук открыт там, где стоял игрок: дальше — это другой сундук
CHEST_PROMPT_RADIUS = 22    # с подсказкой «… сундук» на экране ищем сундук чуть дальше
PROMPT_READ_RADIUS = 30     # у любого сундука ближе этого читаем подсказки (OCR)
PROMPT_GONE_READS = 2       # подсказка сундука пропала на столько чтений подряд после F…
PROMPT_GONE_MOVE = 4        # …а игрок почти не сдвинулся — сундук открыт
# что сейчас в игре -> (коротко для «Что я вижу», пояснение на карте или None)
SCENES = {
    "ok": ("в открытом мире", None),
    "unknown_area": ("место не узнаётся",
                     ("📍 Мини-карта видна, но место не узнаётся — пещера, подземелье или "
                      "многоуровневая зона (их нет на карте HoYoLAB). Точка — последнее известное место.")),
    "cutscene": ("катсцена", "🎬 Катсцена — позиция продолжится после неё."),
    "menu": ("меню, большая карта или диалог", "📋 Меню, большая карта или диалог — жду возврата в игру."),
    "loading": ("загрузка", "⏳ Загрузка…"),
    "background": ("игра не активна", "⏸ Игра свёрнута или не в фокусе — позиция на паузе."),
    "no_game": ("игра не запущена", None),
}
# относительный путь от web/map.html до assets/

# Позиция считается «свежей» для авто-отметки не дольше стольких секунд.
POSITION_MAX_AGE = 2.5
# Сколько ждать позицию, если авто-отметка пришла, а трекинг только запускается.
PENDING_MARK_TIMEOUT = 8.0
# Категория последнего обнаружения используется хоткеем не дольше стольких секунд.
LAST_DETECT_TTL = 20.0

# Тёмная тема Qt в тон веб-карте.
DARK_QSS = """
QMainWindow, QWidget { background: #0f1420; color: #dfe6f2;
    font-family: 'Segoe UI', sans-serif; font-size: 13px; }
QDockWidget { titlebar-close-icon: none; }
QDockWidget::title { background: #141b2b; padding: 8px 12px;
    border-bottom: 1px solid #26314a; color: #9fb3d8; font-weight: 600; }
QLabel { color: #b9c6df; }
QLabel#section { color: #7f93b8; font-size: 11px; font-weight: 700;
    text-transform: uppercase; padding-top: 6px; }
QLabel#hint { color: #6f7f9f; font-size: 11px; }
QLabel#posStatus { color: #cfe0ff; background: #0c1120; border: 1px solid #26314a;
    border-radius: 6px; padding: 5px 8px; font-size: 12px; }
QComboBox { background: #0c1120; border: 1px solid #2c3956; border-radius: 6px;
    padding: 6px 10px; color: #eaf0fb; }
QComboBox:hover { border-color: #4d90fe; }
QComboBox QAbstractItemView { background: #10192b; color: #eaf0fb;
    selection-background-color: #2b62c4; border: 1px solid #2c3956; outline: none; }
QPushButton { background: #1c2740; border: 1px solid #2c3956; border-radius: 8px;
    padding: 8px 12px; color: #eaf0fb; font-weight: 600; }
QPushButton:hover { background: #24345a; border-color: #4d90fe; }
QPushButton:pressed { background: #182238; }
QPushButton:checked { background: #1f3d2a; border-color: #3fb950; color: #c9f5c0; }
QPushButton:disabled { color: #56627a; border-color: #222c40; }
QPushButton#resetBtn { background: #3a1f26; border-color: #6e3540; color: #ffd7dc; }
QPushButton#resetBtn:hover { background: #522a33; border-color: #b0566a; }
QListWidget { background: #0c1120; border: 1px solid #26314a; border-radius: 8px;
    padding: 4px; }
QListWidget::item { padding: 4px 6px; border-radius: 5px; }
QListWidget::item:hover { background: #182236; }
QListWidget::item:selected { background: #1f3358; }
QStatusBar { background: #141b2b; color: #9fb3d8; border-top: 1px solid #26314a; }
QScrollBar:vertical { background: #0c1120; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #2c3956; border-radius: 5px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: #3f5686; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QGroupBox { border: 1px solid #26314a; border-radius: 8px; margin-top: 14px; padding: 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; color: #9fb3d8; }
QLineEdit, QSpinBox, QDoubleSpinBox { background: #0c1120; border: 1px solid #2c3956;
    border-radius: 6px; padding: 4px 8px; color: #eaf0fb; }
"""


class _RefererInterceptor(QWebEngineUrlRequestInterceptor):
    """Проставляет Referer для CDN HoYoLAB (иначе тайлы отдаются с 403)."""

    def interceptRequest(self, info) -> None:
        host = info.requestUrl().host()
        if "hoyoverse" in host or "hoyolab" in host or "mihoyo" in host:
            info.setHttpHeader(b"Referer", b"https://act.hoyolab.com/")


def _map_url(map_id: int) -> QUrl:
    """URL страницы карты через локальный http-сервер (нужен http-origin для CDN)."""
    port = ensure_server()
    rel = MAP_HTML.relative_to(PROJECT_ROOT).as_posix()
    return QUrl(f"http://127.0.0.1:{port}/{rel}#map={map_id}")


def _section(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("section")
    return lbl


def _hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("hint")
    lbl.setWordWrap(True)
    return lbl


class _TitleBar(QWidget):
    """Полоса сверху мини-оверлея: тянешь за любое место — двигается окно.

    Справа — крупная кнопка ⤢ (вернуть обычный вид). Карта внутри окна
    перехватывает мышь, поэтому окну без рамки нужна своя «шапка».
    """

    HEIGHT = 30

    def __init__(self, parent, on_restore, on_released=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(self.HEIGHT)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "_TitleBar{background:rgba(14,20,32,.96);border-bottom:1px solid #26314a;}"
            "QLabel{color:#9fb3d8;font-size:12px;font-weight:600;background:transparent;}"
            "QPushButton{background:#1c2740;border:1px solid #2c3956;border-radius:6px;"
            "color:#eaf0fb;font-size:15px;font-weight:700;padding:0;}"
            "QPushButton:hover{background:#2b62c4;border-color:#4d90fe;}")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 2, 4, 2)
        row.setSpacing(6)
        title = QLabel("⠿  Genshin Map — тяни, чтобы передвинуть")
        row.addWidget(title, 1)
        restore = QPushButton("⤢")
        restore.setFixedSize(34, 26)
        restore.setCursor(Qt.CursorShape.PointingHandCursor)
        restore.setToolTip("Вернуть обычный вид (Ctrl+Alt+O)")
        restore.clicked.connect(on_restore)
        row.addWidget(restore)
        self._offset = None
        self._on_released = on_released

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            win = self.window()
            self._offset = e.globalPosition().toPoint() - win.frameGeometry().topLeft()

    def mouseMoveEvent(self, e) -> None:
        if self._offset is not None:
            self.window().move(e.globalPosition().toPoint() - self._offset)

    def mouseReleaseEvent(self, e) -> None:
        self._offset = None
        if self._on_released:
            self._on_released()


class OverlayWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Genshin Interactive Map")
        self.resize(1280, 800)
        self.setStyleSheet(DARK_QSS)
        if LOGO.exists():
            self.setWindowIcon(QIcon(str(LOGO)))
        self._overlay_mode = False
        self.settings = SettingsStore()
        # поверх всех окон — по настройке (кнопка 📌 на панели)
        self.setWindowFlags(Qt.WindowType.Window | self._top_flags())

        # прогресс — свой на каждый аккаунт (UID читается с экрана игры)
        self._uid = self.settings.get("active_uid")
        self._open_profile_stores()
        self._current_region = None
        # карточки точек (фото/«как найти» с HoYoLAB), кеш — data/point_info/
        self.point_info = PointInfoService(PROJECT_ROOT / "data" / "point_info", DATA_MAPS)
        self.point_info.loaded.connect(self._on_point_info)
        # сундуки, связанные с заданием (по тексту описаний), и где задания начинаются
        from genshinmap.backend.maps.quests import QuestIndex

        self.quests = QuestIndex(DATA_MAPS)
        self._quest_flags: dict[str, str] = {}    # point_id -> название задания ("" — без названия)
        self._quest_checked: set[str] = set()     # у каких сундуков уже смотрели описание
        self.ui_state = UIStateStore()
        self._prompts: dict = {}
        self._prompts_t = 0.0
        self._prompt_open_t = 0.0      # когда последний раз видели подсказку сундука
        self._prompt_rarity = ""       # его редкость из подсказки («богат», …)
        self._icons: dict = {}
        self._icons_t = 0.0
        self._pending_interact = 0.0   # F нажата без свежей позиции — ждём её до этого момента
        self._last_interact_t = 0.0
        self._pending_open: dict | None = None   # F у сундука — ждём плашку открытия
        self._pickup_lines: list[str] = []        # последняя прочитанная плашка
        self._interact_pos = None      # (позиция, время) последнего нажатия F
        self._ocr_ok = self._check_ocr()
        self._map_ready = False
        self._last_label_id = -1      # последняя распознанная категория (для хоткея)
        self._last_label_t = 0.0
        self._enabled_labels: list[int] = []   # включённые на карте слои (из JS)
        self._pending_mark: tuple[tuple[int, ...], float, str] | None = None
        self._auto_marks: list[str] = []       # стек авто-отметок (для отмены)
        self._normal_geometry = None

        # --- Мультикарта: индекс карт и выбор текущей ---
        self.maps = load_map_index()
        if not self.maps:
            raise RuntimeError("Нет данных карт. Запусти: python tools/fetch_map_data.py")
        map_ids = {m["id"] for m in self.maps}
        # восстанавливаем последнюю выбранную карту, если она есть
        saved = self.ui_state.get_current_map()
        self.current_map_id = saved if saved in map_ids else self.maps[0]["id"]
        self.meta: dict = {}
        self.map_index: MapIndex | None = None

        # --- Позиция игрока (Этап 3): фоновый сервис ---
        self.position_service = PositionService(
            interval_s=float(self.settings.get("track_interval", 0.4)))
        self.position_service.minimap_frac = self.settings.get("minimap")
        self.position_service.pickup_frac = self.settings.get("pickup_region")
        self.position_service.game_lang = self._game_lang()
        self.recorder = DebugRecorder(DEBUG_DIR)
        self.position_service.recorder = self.recorder
        self.prompt_detector = PromptDetector(PROMPTS_DIR)
        self.position_service.prompt_detector = self.prompt_detector
        self.position_service.prompt_frac = self.settings.get("prompt_region")
        self.position_service.prompts.connect(self._on_prompts)
        self.position_service.icons.connect(self._on_icons)
        self.position_service.pickupText.connect(self._on_pickup_text)
        self.position_service.uidSeen.connect(self._on_uid_seen)
        # клавиша взаимодействия (F) — «открыл сундук»; только чтение, игре не мешает
        self.input_watcher = InputWatcher(self.settings.get("interact_keys") or ["F"])
        self.input_watcher.pressed.connect(self._on_interact)
        self.input_watcher.start()
        self.position_service.position.connect(self._on_position)
        self.position_service.lost.connect(self._on_position_lost)
        self.position_service.scene.connect(self._on_scene)
        self._scene = "no_game"
        self._last_pickup: tuple[str, float] | None = None
        self.position_service.status.connect(self._on_position_status)
        self.position_service.scaleCalibrated.connect(self._on_scale_calibrated)
        self.position_service.runningChanged.connect(self._on_tracking_state)

        self._load_current_map()  # meta + index + bundle + карта для трекера

        # --- WebView с картой ---
        # Referer-перехватчик для тайлов CDN (храним ссылку, чтобы не собрал GC).
        self._interceptor = _RefererInterceptor()
        QWebEngineProfile.defaultProfile().setUrlRequestInterceptor(self._interceptor)
        self.view = QWebEngineView()
        self.channel = QWebChannel()
        self.bridge = MapBridge()
        self.channel.registerObject("bridge", self.bridge)
        self.view.page().setWebChannel(self.channel)

        self.bridge.ready.connect(self._on_map_ready)
        self.bridge.markerClicked.connect(self._on_marker_clicked)
        self.bridge.stateChanged.connect(self._on_state_changed)
        self.bridge.pointInfoRequested.connect(self.point_info.request)
        self.bridge.customAdd.connect(self._on_custom_add)
        self.bridge.customDelete.connect(self._on_custom_delete)
        self.bridge.openUrlRequested.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
        # HUD навигации поверх игры (тест): стрелка у мини-карты, подсказка, звук
        self.hud = NavHud()
        self.hud.minimap_frac = self.settings.get("minimap")
        self._track: list[tuple[float, float, float]] = []   # (t, x, y) — для направления бега
        self._apply_hud_options()
        self.bridge.targetChanged.connect(self._on_target_changed)
        self.bridge.navPathReady.connect(self._on_nav_path)
        self.bridge.routeClipRequested.connect(self._on_route_clip_requested)
        self.bridge.questDone.connect(self._on_quest_done)
        self.bridge.routeClipReady.connect(
            lambda pid, url: self._js(f"window.showRouteClip({json.dumps(pid)}, {json.dumps(url)});"))
        self.point_info.loaded.connect(self._on_card_for_hud)
        self._fg_timer = QTimer(self)
        self._fg_timer.timeout.connect(self._check_game_foreground)
        self._fg_timer.start(700)
        # автообновление: программа (GitHub Releases) и данные карт (HoYoLAB)
        self.updater = Updater()
        self.updater.available.connect(self._on_update_available)
        self.updater.progress.connect(lambda pct: self.update_btn.setText(f"⬇ Скачиваю… {pct}%"))
        self.updater.failed.connect(self._on_update_failed)
        self.updater.ready.connect(self._on_update_ready)
        self.data_sync = DataSync()
        self.data_sync.updated.connect(self._on_data_updated)
        self.data_sync.failed.connect(self._diag)
        QTimer.singleShot(4000, self._check_updates)          # после старта
        self._upd_timer = QTimer(self)
        self._upd_timer.timeout.connect(self._check_updates)
        self._upd_timer.start(6 * 3600 * 1000)                # и раз в 6 часов

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.setCentralWidget(central)

        # --- Статус-бар: запущен ли Genshin ---
        self.status = QStatusBar()
        self.status_label = QLabel("Проверяю Genshin…")
        self.status.addPermanentWidget(self.status_label)
        self.setStatusBar(self.status)

        # --- Панель управления (карта, позиция, распознавание, журнал) ---
        self._build_control_dock()

        # --- Глобальные горячие клавиши ---
        self.hotkeys = HotkeyManager(self.settings.get("hotkeys"))
        self.hotkeys.markNearest.connect(self._hotkey_mark_nearest)
        self.hotkeys.toggleOverlay.connect(self.toggle_overlay_mode)
        self.hotkeys.toggleVisible.connect(self._toggle_visible)
        self.hotkeys.bookmark.connect(self._bookmark)
        self.hotkeys.undo.connect(self._undo_auto_mark)
        self.hotkeys.stopNav.connect(self._stop_nav)
        self.hotkeys.toggleHud.connect(self._toggle_hud)
        self.hotkeys.togglePath.connect(lambda: self._js("window.togglePath && window.togglePath();"))
        self.hotkeys.start()
        if self.hotkeys.failed:
            self._log("Хоткеи заняты другой программой: " + ", ".join(self.hotkeys.failed)
                      + " — поменяй в ⚙ Настройках")
        if not is_admin():
            self.admin_btn = QPushButton("🛡 Запустить от администратора")
            self.admin_btn.setToolTip("Genshin работает с правами администратора; с теми же "
                                      "правами хоткеи и чтение клавиш из игры надёжнее. "
                                      "Включает постоянный запуск от администратора.")
            self.admin_btn.setStyleSheet("padding:3px 10px;font-weight:500;")
            self.admin_btn.clicked.connect(self._restart_as_admin)
            self.status.addWidget(self.admin_btn)

        # Мини-режим: полоса сверху (перетаскивание + ⤢) и уголок размера.
        self.title_bar = _TitleBar(self, self.toggle_overlay_mode,
                                   on_released=self._save_overlay_geometry)
        self.title_bar.hide()
        self.size_grip = QSizeGrip(self)
        self.size_grip.setFixedSize(18, 18)
        self.size_grip.hide()

        self.view.load(_map_url(self.current_map_id))

        # Периодически обновляем статус процесса игры.
        self.proc_timer = QTimer(self)
        self.proc_timer.timeout.connect(self._update_game_status)
        self.proc_timer.start(3000)
        self._update_game_status()

        # Восстанавливаем размер/позицию окна с прошлого раза.
        geom = self.ui_state.get_window()
        if geom and len(geom) == 4 and self._on_screen(geom):
            self.setGeometry(*geom)

    # ---- helpers ----
    def _js(self, code: str) -> None:
        if self._map_ready:
            self.view.page().runJavaScript(code)

    def _map_name(self, map_id: int) -> str:
        return next((m["name"] for m in self.maps if m["id"] == map_id), f"Карта {map_id}")

    # ---- Сохранение состояния UI ----
    def _on_state_changed(self, state_json: str) -> None:
        """JS прислал текущее состояние (слои + позиция) — сохраняем для карты."""
        try:
            st = json.loads(state_json)
        except (json.JSONDecodeError, TypeError):
            return
        self._enabled_labels = [int(x) for x in st.get("enabled", [])]
        if st.get("compact"):
            # мини-режим: свой масштаб; вид обычного окна не затираем
            zoom = (st.get("view") or {}).get("zoom")
            if zoom is not None and zoom != self.ui_state.data.get("compact_zoom"):
                self.ui_state.data["compact_zoom"] = zoom
                self.ui_state.save()
            self.ui_state.set_map_state(self.current_map_id, st.get("enabled", []),
                                        self.ui_state.get_view(self.current_map_id),
                                        {k: st.get(k) for k in ("region", "hide_collected", "follow")})
            return
        extra = {k: st.get(k) for k in ("region", "hide_collected", "follow")}
        if st.get("region") != self._current_region:
            self._current_region = st.get("region")
            self._update_gems()
        self.ui_state.set_map_state(
            self.current_map_id, st.get("enabled", []), st.get("view"), extra
        )

    # ---- Мультикарта ----
    def _map_scale(self, map_id: int) -> float:
        return (self.settings.get("minimap_scale") or {}).get(str(map_id)) or DEFAULT_SCALE

    def _load_current_map(self) -> None:
        """Загружает meta/индекс текущей карты, пишет bundle, переключает трекер."""
        mid = self.current_map_id
        self.ui_state.set_current_map(mid)
        self.meta = json.loads((map_dir(mid) / "meta.json").read_text(encoding="utf-8"))
        write_bundle(mid, self._map_name(mid), self.custom.for_map(mid))
        self.map_index = MapIndex(map_dir(mid) / "points.json")
        self._enabled_labels = list(self.ui_state.get_enabled(mid))
        # авто-отметка: понимает по категории, что это (сундук, окулус, фея…)
        labels = json.loads((map_dir(mid) / "labels.json").read_text(encoding="utf-8"))
        self.auto_marker = AutoMarker(self.map_index, labels, self.settings.get("auto_rules"))
        # свои точки участвуют в авто-отметке как сундуки
        self.auto_marker.register_label(CUSTOM_LABEL, tr(CUSTOM_NAME), "chest")
        en_names = {l["id"]: l["name_en"] for l in labels if l.get("name_en")}
        self.auto_marker.set_names(en_names if i18n.lang() == "en" else {},
                                   en_names if self._game_lang() == "en" else {},
                                   self._game_lang())
        for c in self.custom.for_map(mid):
            self.map_index.add_point(c["id"], CUSTOM_LABEL, c["x"], c["y"])
        # после телепорта игрок у телепорта/статуи — трекер ищет там первым делом
        tp_labels = (self.auto_marker.labels_by_kind.get("teleport", ())
                     + self.auto_marker.labels_by_kind.get("statue", ()))
        self.position_service.set_anchors(
            [(x, y) for lid in tp_labels for _, x, y in self.map_index.by_label.get(lid, [])])
        self.point_info.map_id = mid
        self.point_info.lang = i18n.lang()
        self._load_quests(mid, labels)
        points = json.loads((map_dir(mid) / "points.json").read_text(encoding="utf-8"))
        self.gems = PrimogemCounter(labels, points, self.settings.get("primogems"))
        self._regions = build_regions(mid, points)
        import numpy as np

        self._points_xy = np.array([[p["x"], p["y"]] for p in points], dtype=np.float32)
        self._points_area = np.array([p.get("area_id", 0) for p in points], dtype=np.int32)
        self._region_names = {r["id"]: r["name"] for r in self._regions}
        self._current_region = self.ui_state.get_extra(mid).get("region")
        if hasattr(self, "gems_label"):
            self._update_gems()
        self.position_service.set_map(mid, self.meta, ASSETS_MAPS / str(mid), self._map_scale(mid))
        self._build_nav_grid(mid)

    def switch_map(self, map_id: int) -> None:
        if map_id == self.current_map_id:
            return
        self.current_map_id = map_id
        self.ui_state.set_current_map(map_id)
        self._map_ready = False
        self._load_current_map()
        self.view.load(_map_url(self.current_map_id))  # перезагрузка с новым bundle

    def _on_map_combo(self, index: int) -> None:
        map_id = self.map_combo.itemData(index)
        if map_id is not None:
            self.switch_map(int(map_id))

    # ---- Панель управления ----
    def _build_control_dock(self) -> None:
        self.detector_service = DetectionService(TEMPLATES_DIR)
        self.detector_service.detected.connect(self._on_detected)
        self.detector_service.state_changed.connect(self._on_service_state)
        self._apply_pickup_region()

        dock = QDockWidget("Управление", self)
        dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
        dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.control_dock = dock
        panel = QWidget()
        panel.setMinimumWidth(270)
        v = QVBoxLayout(panel)
        v.setSpacing(6)

        # --- выбор карты ---
        v.addWidget(_section("Карта"))
        self.map_combo = QComboBox()
        for m in self.maps:
            self.map_combo.addItem(m["name"], m["id"])
            if m["id"] == self.current_map_id:
                self.map_combo.setCurrentIndex(self.map_combo.count() - 1)
        self.map_combo.currentIndexChanged.connect(self._on_map_combo)
        v.addWidget(self.map_combo)

        self.overlay_btn = QPushButton("🔲 Мини-оверлей поверх игры")
        self.overlay_btn.setToolTip("Ctrl+Alt+O — вкл/выкл. В мини-режиме окно тащится мышью.")
        self.overlay_btn.clicked.connect(self.toggle_overlay_mode)
        v.addWidget(self.overlay_btn)
        self.ontop_btn = QPushButton("📌 Поверх всех окон")
        self.ontop_btn.setCheckable(True)
        self.ontop_btn.setChecked(bool(self.settings.get("always_on_top", True)))
        self.ontop_btn.setToolTip("Держать окно карты поверх игры (в обычном режиме)")
        self.ontop_btn.clicked.connect(self._toggle_on_top)
        v.addWidget(self.ontop_btn)

        # --- позиция игрока ---
        v.addWidget(_section("Позиция игрока"))
        row = QHBoxLayout()
        self.track_btn = QPushButton("📍 Отслеживать")
        self.track_btn.setCheckable(True)
        self.track_btn.setToolTip("Определять позицию по мини-карте и показывать на карте")
        self.track_btn.clicked.connect(self._toggle_tracking)
        self.calib_btn = QPushButton("🎯 Калибровка")
        self.calib_btn.setToolTip("Указать, где на экране мини-карта и плашка подбора")
        self.calib_btn.clicked.connect(self._open_calibration)
        row.addWidget(self.track_btn, 1)
        row.addWidget(self.calib_btn, 1)
        v.addLayout(row)
        # «Что я вижу»: что распознаётся прямо сейчас (понятно, на каком этапе сбой)
        self.see_label = QLabel()
        self.see_label.setObjectName("posStatus")
        self.see_label.setWordWrap(True)
        self.see_label.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(self.see_label)
        self._see_timer = QTimer(self)
        self._see_timer.timeout.connect(self._update_see)
        self._see_timer.start(1000)
        self.pos_label = QLabel("Отслеживание выключено")
        self.pos_label.setObjectName("posStatus")
        self.pos_label.setWordWrap(True)
        v.addWidget(self.pos_label)
        self.rec_btn = QPushButton("⏺ Запись отладки")
        self.rec_btn.setCheckable(True)
        self.rec_btn.setToolTip("Сохранять кадры мини-карты и плашки подбора в папку debug/ — "
                                "для настройки распознавания. Ctrl+Alt+B — закладка.")
        self.rec_btn.clicked.connect(self._toggle_recording)
        self.rec_btn.hide()            # запись автоматическая (⚙ Настройки → автозапись)

        # --- авто-отметка ---
        # Блок «Авто-отметка сбора» не показываем: авто-отметка включена всегда
        # (сундуки — по плашке «Опыт приключений», окулусы — по мини-карте).
        self.detect_btn = QPushButton("▶ Распознавать подбор")
        self.detect_btn.setCheckable(True)
        self.detect_btn.clicked.connect(self._toggle_detection)
        self.detect_btn.hide()
        n_tmpl = len(self.detector_service.detector.templates)
        self.detect_info = _hint(self._templates_hint(n_tmpl))
        self.detect_info.hide()

        head = QHBoxLayout()
        head.addWidget(_section("Журнал"), 1)
        self.undo_btn = QPushButton("↶ Отменить")
        self.undo_btn.setToolTip("Снять последнюю авто-отметку")
        self.undo_btn.setEnabled(False)
        self.undo_btn.clicked.connect(self._undo_auto_mark)
        head.addWidget(self.undo_btn)
        v.addLayout(head)
        self.detect_log = QListWidget()
        self.detect_log.setToolTip("Двойной клик по отметке — показать точку на карте")
        self.detect_log.itemDoubleClicked.connect(self._on_log_double_click)
        v.addWidget(self.detect_log, 1)

        # --- примогемы (оценка по типам собранных сундуков) ---
        v.addWidget(_section("💎 Примогемы из сундуков"))
        self.gems_label = QLabel()
        self.gems_label.setObjectName("posStatus")
        self.gems_label.setWordWrap(True)
        self.gems_label.setToolTip("Оценка по типам сундуков: Обычный ~0, Богатый ~2, "
                                   "Драгоценный ~5, Роскошный ~10, Удивительный ~5.\n"
                                   "Точные числа в игре плавают — меняются в settings.json "
                                   "(\"primogems\").")
        v.addWidget(self.gems_label)
        self._update_gems()

        # --- обновление (кнопка видна, только когда есть новая версия) ---
        self.update_btn = QPushButton("⬇ Обновить")
        self.update_btn.setStyleSheet("background:#1f3d2a;border-color:#3fb950;color:#c9f5c0;")
        self.update_btn.clicked.connect(self._install_update)
        self.update_btn.hide()
        v.addWidget(self.update_btn)

        # --- прочее ---
        row = QHBoxLayout()
        self.settings_btn = QPushButton("⚙ Настройки")
        self.settings_btn.clicked.connect(self._open_settings)
        self.reset_btn = QPushButton("🗑 Сброс")
        self.reset_btn.setToolTip("Снять все отметки «собрано» (двойное нажатие)")
        self.reset_btn.setObjectName("resetBtn")
        self.reset_btn.clicked.connect(self._reset_progress)
        self.progress_btn = QPushButton("💾 Прогресс")
        self.progress_btn.setToolTip("Сохранить прогресс в файл / загрузить из файла")
        menu = QMenu(self.progress_btn)
        menu.addAction("Сохранить в файл…", self._export_progress)
        menu.addAction("Загрузить из файла…", self._import_progress)
        menu.addSeparator()
        menu.addAction("Импорт с HoYoLAB / appsample…", self._open_import)
        self.progress_btn.setMenu(menu)
        row.addWidget(self.settings_btn, 1)
        row.addWidget(self.progress_btn, 1)
        row.addWidget(self.reset_btn)
        v.addLayout(row)
        ver = QHBoxLayout()
        ver.addWidget(_hint(f"Версия {__version__}"), 1)
        check_btn = QPushButton("⟳ Обновления")
        check_btn.setToolTip("Проверить новую версию программы и данные карты сейчас")
        check_btn.clicked.connect(lambda: self._check_updates(force=True))
        ver.addWidget(check_btn)
        v.addLayout(ver)

        dock.setWidget(panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self._reset_armed = False

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.settings.data, parent=self)
        dlg.applied.connect(self._settings_applied)
        dlg.restartRequested.connect(lambda: QTimer.singleShot(0, self._restart_app))
        dlg.calibrationRequested.connect(lambda: QTimer.singleShot(0, self._open_calibration))
        dlg.exec()

    def _settings_applied(self, values: dict) -> None:
        self.settings.update(values)
        self._apply_settings()
        self._log("Настройки сохранены")

    def _restart_app(self) -> None:
        """Перезапуск (после смены языка) — с теми же правами, что сейчас."""
        import ctypes
        import sys

        args = " ".join(f'"{a}"' for a in sys.argv)
        verb = "runas" if is_admin() else "open"
        rc = ctypes.windll.shell32.ShellExecuteW(None, verb, sys.executable, args,
                                                 str(PROJECT_ROOT), 1)
        if rc > 32:
            self.close()
            QApplication.quit()

    def _open_calibration(self) -> None:
        dlg = CalibrationDialog(self.settings.data, self.position_service,
                                self.current_map_id, parent=self)
        if dlg.exec():
            self.settings.update(dlg.values())
            if dlg.found_scale:
                self._save_scale(self.current_map_id, dlg.found_scale)
            pc = dlg.prompt_crop()
            if pc is not None:
                path = self.prompt_detector.save_template(pc[0], "open", "chest", pc[1])
                self._log(f"Эталон подсказки сохранён: {path.name}")
            self._apply_settings()
            self._log("Калибровка сохранена")

    def _apply_settings(self) -> None:
        """Применить настройки на лету (без перезапуска)."""
        self.hotkeys.rebind(self.settings.get("hotkeys", {}))
        self._js(f"window.setMaxMarkers({int(self.settings.get('max_markers', 1200))});")
        self.position_service.minimap_frac = self.settings.get("minimap")
        self.position_service.pickup_frac = self.settings.get("pickup_region")
        self.hud.minimap_frac = self.settings.get("minimap")
        self.position_service.prompt_frac = self.settings.get("prompt_region")
        self.position_service.interval_s = float(self.settings.get("track_interval", 0.4))
        self._apply_pickup_region()
        self.auto_marker.set_rules(self.settings.get("auto_rules"))
        self._apply_hud_options()
        self._check_game_foreground()
        # прозрачность/размер оверлея — если сейчас в мини-режиме, применяем сразу
        if self._overlay_mode:
            self.setWindowOpacity(float(self.settings.get("overlay_opacity", 0.9)))
            size = self.settings.get("overlay_size", [460, 320])
            self.resize(int(size[0]), int(size[1]))

    def _apply_pickup_region(self) -> None:
        """Область поиска плашки подбора (доли экрана -> пиксели монитора)."""
        frac = self.settings.get("pickup_region")
        if not frac:
            self.detector_service.region = None
            return
        import mss

        with mss.mss() as sct:
            self.detector_service.region = region_from_frac(frac, game_rect(sct), "pickup_region")

    def _reset_progress(self) -> None:
        """Снять все отметки «собрано» — по второму нажатию (защита от случайного клика)."""
        if not self._reset_armed:
            self._reset_armed = True
            self.reset_btn.setText("Точно?")
            QTimer.singleShot(3000, self._disarm_reset)
            return
        self._disarm_reset()
        self.store.collected.clear()
        self.store.save()
        self._auto_marks.clear()
        self.undo_btn.setEnabled(False)
        self.store.probable.clear()
        self.store.save()
        self._js("window.applyCollected([], []);")
        self._log("Прогресс сброшен — ничего не отмечено")

    def _disarm_reset(self) -> None:
        self._reset_armed = False
        self.reset_btn.setText("🗑 Сброс")

    def _templates_hint(self, n: int) -> str:
        if n == 0:
            return ("Эталонов подбора нет — распознавание не сработает. Создай их: "
                    "python tools/capture_template.py grab, затем crop.")
        return f"Эталонов подбора: {n}. Область плашки задаётся в «Калибровке»."

    # ---- Распознавание подбора (Этап 2) ----
    def _toggle_detection(self) -> None:
        if self.detector_service.running:
            self.detector_service.stop()
        else:
            self.detector_service.start()
            n = len(self.detector_service.detector.templates)
            self.detect_info.setText(self._templates_hint(n))
            # без позиции авто-отметка невозможна — включаем трекинг заодно
            if not self.position_service.running:
                self.position_service.start()

    def _on_service_state(self, running: bool) -> None:
        self.detect_btn.setChecked(running)
        self.detect_btn.setText("⏸ Распознавание подбора" if running else "▶ Распознавать подбор")

    def _on_detected(self, name: str, label_id: int, score: float) -> None:
        ts = datetime.now().astimezone().strftime("%H:%M:%S")
        self._log(f"{ts}  подобрано: {name}  ({score:.0%})")
        self.recorder.event("detected", name=name, label=label_id, score=round(score, 3))
        if label_id <= 0 or not self._map_ready:
            return
        self._last_label_id, self._last_label_t = label_id, time.monotonic()
        self._js(f"window.enableCategory({label_id});")
        self._try_auto_mark((label_id,), "подбор")

    # ---- Авто-отметка ----
    def _try_auto_mark(self, label_ids: tuple[int, ...], reason: str) -> None:
        """Отметить ближайшую несобранную точку; если позиции нет — дождаться её."""
        pos = self.position_service.latest(POSITION_MAX_AGE)
        if pos is not None:
            self._mark_nearest_at(pos, label_ids, reason)
            return
        if not self.position_service.running:
            self.position_service.start()
        self._pending_mark = (label_ids, time.monotonic() + PENDING_MARK_TIMEOUT, reason)
        self._log("   жду позицию игрока…")

    def _mark_nearest_at(self, pos, label_ids: tuple[int, ...], reason: str,
                         radius: float | None = None) -> bool:
        if radius is None:
            radius = float(self.settings.get("auto_mark_radius", 60))
        cands = self.map_index.candidates(label_ids, pos.x, pos.y, self.store.collected, radius)
        if not cands:
            self._log(f"   рядом нет несобранных точек (радиус {radius:.0f})")
            return False
        best = cands[0]
        note = ""
        if len(cands) > 1 and cands[1].dist < best.dist * 1.3 + 5:
            note = " · рядом есть ещё — проверь"
        self._do_mark(best, pos, reason, note)
        return True

    def _do_mark(self, cand: Candidate, pos, reason: str, note: str = "") -> None:
        """Отметить точку собранной + журнал (с типом объекта) + кольцо на карте."""
        self.recorder.event("auto_mark", point=cand.point_id, label=cand.label_id,
                            dist=round(cand.dist, 1), reason=reason, px=pos.x, py=pos.y)
        self.observations.record(cand.point_id, "collected", reason)
        self.mark_collected(cand.point_id)
        self._auto_marks.append(cand.point_id)
        self.undo_btn.setEnabled(True)
        ts = datetime.now().astimezone().strftime("%H:%M:%S")
        item = QListWidgetItem(f"{ts}  {self.auto_marker.describe(cand.label_id)} — собрано "
                               f"({reason}, {cand.dist:.0f} ед.){note}")
        item.setData(Qt.ItemDataRole.UserRole, cand.point_id)
        self.detect_log.insertItem(0, item)
        # подсветить, НЕ двигая карту: куда смотреть, решает пользователь
        self._js(f"window.highlightPoint({json.dumps(cand.point_id)}, false);")
        self.hud.toast(f"{self.auto_marker.describe(cand.label_id)} — отмечено · "
                       f"{self._undo_keys()} — отменить")

    def _undo_keys(self) -> str:
        combo = (self.settings.get("hotkeys") or {}).get("undo") or "<ctrl>+<alt>+z"
        return "+".join(part.strip("<>").capitalize() for part in combo.split("+"))

    def _hotkey_mark_nearest(self) -> None:
        """Ctrl+Alt+M — отметить ближайшую несобранную точку рядом с игроком.

        Кандидаты: категория последнего распознанного подбора (если недавно),
        иначе — ВСЕ собираемые категории (сундуки, окулусы, феи…, даже если их
        слой на карте выключен) плюс включённые слои.
        """
        if self._last_label_id > 0 and time.monotonic() - self._last_label_t < LAST_DETECT_TTL:
            labels = (self._last_label_id,)
        else:
            labels = tuple(set(self._enabled_labels) | set(self.auto_marker.all_collectible_labels()))
        self._try_auto_mark(labels, "хоткей")

    def _undo_auto_mark(self) -> None:
        if not self._auto_marks:
            return
        pid = self._auto_marks.pop()
        self.store.unmark(pid)
        self._push_collected(pid, False)
        self._log("   ↶ отметка снята")
        self.undo_btn.setEnabled(bool(self._auto_marks))
        name = self.auto_marker.describe(self.map_index.by_id[pid][0])             if pid in self.map_index.by_id else "точка"
        self.hud.toast(f"↶ {name} — отметка снята", "#d29922")

    def _on_log_double_click(self, item: QListWidgetItem) -> None:
        pid = item.data(Qt.ItemDataRole.UserRole)
        if pid:
            self._js(f"window.highlightPoint({json.dumps(pid)});")

    def _log(self, text: str) -> None:
        self.detect_log.insertItem(0, text)
        while self.detect_log.count() > 300:
            self.detect_log.takeItem(self.detect_log.count() - 1)

    # ---- Запись отладки ----
    def _auto_recording(self, game_running: bool) -> None:
        """Лёгкая запись отладки — всегда, пока запущена игра (пишет только кадры
        окна игры; старые сессии чистятся сами: 5 последних, не больше 1 ГБ)."""
        if not self.settings.get("auto_record", True) or os.environ.get("GENSHINMAP_NO_RECORD"):
            if self.recorder.active and self.recorder.auto:
                self.recorder.stop()
            return
        if game_running and not self.recorder.active:
            self._rec_dir = self.recorder.start(self._record_meta(), light=True)
        elif not game_running and self.recorder.active and self.recorder.auto:
            self.recorder.stop()

    def _record_meta(self) -> dict:
        return {
            "map_id": self.current_map_id,
            "minimap": self.settings.get("minimap"),
            "pickup_region": self.settings.get("pickup_region"),
            "minimap_scale": self._map_scale(self.current_map_id),
            "enabled_labels": self._enabled_labels,
        }

    def _toggle_recording(self) -> None:
        if self.recorder.active:
            self.recorder.stop()
            self.rec_btn.setChecked(False)
            self.rec_btn.setText("⏺ Запись отладки")
            self._log(f"Запись остановлена: {self._rec_dir}")
            return
        self._rec_dir = self.recorder.start(self._record_meta())
        self.rec_btn.setChecked(True)
        self.rec_btn.setText("⏹ Остановить запись")
        self._log(f"Запись: {self._rec_dir.relative_to(PROJECT_ROOT)}")
        if not self.position_service.running:
            self.position_service.start()

    def _bookmark(self) -> None:
        """Ctrl+Alt+B — закладка «вот здесь что-то произошло» (подобрал, стою у объекта)."""
        pos = self.position_service.latest(POSITION_MAX_AGE)
        data = {"x": pos.x, "y": pos.y} if pos else {}
        if self.recorder.active:
            self.recorder.event("bookmark", **data)
        where = f"{pos.x:.0f}, {pos.y:.0f}" if pos else "позиция неизвестна"
        self._log(f"{datetime.now().astimezone():%H:%M:%S}  🔖 закладка ({where})")

    # ---- Позиция игрока (Этап 3) ----
    def _toggle_tracking(self) -> None:
        if self.position_service.running:
            self.position_service.stop()
        else:
            self.position_service.start()

    def _on_tracking_state(self, running: bool) -> None:
        self.track_btn.setChecked(running)
        if not running:
            self._js("window.clearPlayer();")

    def _on_position(self, pos) -> None:
        if getattr(self, "_lost", False):
            self._lost = False
            self._js("window.setLostHint(false);")
        self.show_player(pos)
        self._auto_by_position(pos)
        if self._pending_mark:
            labels, deadline, reason = self._pending_mark
            self._pending_mark = None
            if time.monotonic() <= deadline:
                self._mark_nearest_at(pos, labels, reason)

    # ---- Аккаунты (профили по UID) ----
    @staticmethod
    def _profile_dir(uid: str | None) -> Path:
        return PROJECT_ROOT / "data" / "profiles" / uid if uid else PROJECT_ROOT / "data"

    def _open_profile_stores(self) -> None:
        d = self._profile_dir(self._uid)
        self.store = ProgressStore(d / "progress.json")
        self.observations = ObservationStore(d / "observations.json")   # память у точек
        self.custom = CustomPoints(d / "custom_points.json")            # свои точки

    def _on_uid_seen(self, uid: str) -> None:
        """В игре другой аккаунт — переключаем прогресс. Первый увиденный UID
        забирает себе прогресс, накопленный до появления профилей."""
        if uid == self._uid:
            return
        new_dir = self._profile_dir(uid)
        if not new_dir.exists():
            new_dir.mkdir(parents=True)
            if self._uid is None:                      # первый UID: переносим текущий прогресс
                import shutil

                for name in ("progress.json", "observations.json", "custom_points.json"):
                    src = self._profile_dir(None) / name
                    if src.exists():
                        shutil.move(str(src), str(new_dir / name))
        first = self._uid is None
        self._uid = uid
        self.settings.set("active_uid", uid)
        self._open_profile_stores()
        self._log(f"{datetime.now().astimezone():%H:%M:%S}  👤 аккаунт UID {uid}"
                  + (" — текущий прогресс привязан к нему" if first else " — прогресс переключён"))
        self._auto_marks.clear()
        self._map_ready = False
        self._load_current_map()
        self.view.load(_map_url(self.current_map_id))

    # ---- Прогресс в файл ----
    def _export_progress(self) -> None:
        name = f"genshinmap_progress_{datetime.now().astimezone():%Y-%m-%d}.json"
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить прогресс",
                                              str(Path.home() / "Desktop" / name), "JSON (*.json)")
        if not path:
            return
        r = export_progress(Path(path), self.store, self.custom, self.observations)
        self._log(f"💾 Прогресс сохранён: {r['collected']} отметок, {r['custom']} своих точек")

    def _import_progress(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Загрузить прогресс", str(Path.home() / "Desktop"),
                                              "JSON (*.json)")
        if not path:
            return
        box = QMessageBox(self)
        box.setWindowTitle("Загрузка прогресса")
        box.setText("Как загрузить прогресс из файла?")
        merge = box.addButton("Объединить с текущим", QMessageBox.ButtonRole.AcceptRole)
        replace = box.addButton("Заменить текущий", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() not in (merge, replace):
            return
        try:
            r = import_progress(Path(path), self.store, self.custom, self.observations,
                                replace=box.clickedButton() is replace)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            self._log(f"Не удалось загрузить прогресс: {e}")
            return
        self._log(f"💾 Прогресс загружен: {r['collected']} отметок (+{r['added']}), "
                  f"своих точек {r['custom']}")
        self._map_ready = False
        self._load_current_map()           # свои точки/счётчики — заново
        self.view.load(_map_url(self.current_map_id))

    def _open_import(self) -> None:
        from genshinmap.frontend.qt.import_dialog import ImportDialog

        dlg = ImportDialog(self.current_map_id, map_dir(self.current_map_id),
                           set(self.map_index.by_id), parent=self)
        dlg.imported.connect(self._apply_imported)
        dlg.exec()

    def _apply_imported(self, ids: set, source: str) -> None:
        new = set(ids) - self.store.collected
        self.store.collected |= set(ids)
        self.store.save()
        for pid in new:
            self.observations.data.setdefault(pid, {"state": "collected", "t": 0, "n": 1,
                                                    "src": f"импорт {source}"})
        self.observations.save()
        collected = json.dumps(sorted(self.store.collected))
        probable = json.dumps(sorted(self.store.probable))
        self._js(f"window.applyCollected({collected}, {probable});")
        self._update_gems()
        self._log(f"⬇ Импорт с {source}: отмечено ещё {len(new)} (всего в файле {len(ids)})")

    # ---- Обновления ----
    def _check_updates(self, force: bool = False) -> None:
        self.updater.check_async()
        self.data_sync.check_async(force=force)
        if force:
            self._log("Проверяю обновления…")

    def _on_update_available(self, tag: str, notes: str, url: str) -> None:
        self._update_url = url
        self.update_btn.setText(f"⬇ Обновить до {tag}")
        self.update_btn.setToolTip(notes[:500] or "Новая версия")
        self.update_btn.show()
        self._log(f"Доступна новая версия {tag}")

    def _install_update(self) -> None:
        url = getattr(self, "_update_url", "")
        if not url:
            return
        self.update_btn.setEnabled(False)
        self.updater.install_async(url)

    def _on_update_failed(self, text: str) -> None:
        self.update_btn.setEnabled(True)
        self.update_btn.setText("⬇ Обновить (повторить)")
        self._log(text)

    def _on_update_ready(self) -> None:
        """Скачано — закрываемся ПОЛНОСТЬЮ (скрипт обновления ждёт конца процесса).
        Одного self.close() мало: открытый HUD/диалог держит приложение живым."""
        self._log("Обновление скачано — перезапускаюсь…")

        def quit_all() -> None:
            self.close()
            QApplication.instance().quit()
            # страховка: если что-то всё же держит процесс — выходим жёстко
            threading.Timer(5.0, lambda: os._exit(0)).start()

        QTimer.singleShot(500, quit_all)

    def _on_data_updated(self, text: str) -> None:
        self._log(text)
        # перечитать данные текущей карты и перезагрузить страницу
        self._map_ready = False
        self._load_current_map()
        self.view.load(_map_url(self.current_map_id))

    # ---- HUD навигации ----
    # ---- Путь по местности (A*) ----
    def _build_nav_grid(self, mid: int) -> None:
        """Сетка проходимости — в фоне (ждёт референсы, которые готовит трекер)."""
        self.nav_grid = None
        self._nav_path: list = []
        meta = dict(self.meta)

        def work() -> None:
            a = ASSETS_MAPS / str(mid)
            gray, water = reference_path(meta, a), water_reference_path(meta, a)
            for _ in range(600):                          # до 10 мин на первую загрузку
                if gray.exists() and water.exists():
                    break
                time.sleep(1)
            else:
                return
            try:
                road = road_reference_path(meta, a)
                ensure_road_reference(meta, road)
                grid = NavGrid(meta, gray, REF_ZOOM, water, road)
            except Exception as e:  # noqa: BLE001 — без сетки ведём по прямой
                self._diag(f"сетка пути не построена: {e}")
                return
            if mid == self.current_map_id:
                self.nav_grid = grid

        threading.Thread(target=work, daemon=True).start()

    def _replan(self, force: bool = False) -> None:
        """Проложить путь от игрока к цели (в фоне, не чаще раза в 2 с)."""
        target, pos = self.hud.target, self.position_service.latest(POSITION_MAX_AGE)
        if not target or pos is None or self.nav_grid is None or target.get("tp") \
                or not target.get("show_path"):
            return                      # далеко и выгоднее телепорт — путь пешком не строим
        now = time.monotonic()
        if not force and now - getattr(self, "_nav_t", 0.0) < 2.0:
            return
        if getattr(self, "_nav_busy", False):
            return
        self._nav_t, self._nav_busy = now, True
        aim = target.get("via") or target                   # сначала ко входу в пещеру
        grid, start, goal, pid = self.nav_grid, (pos.x, pos.y), (aim["x"], aim["y"]), target["pid"]

        def work() -> None:
            try:
                path = grid.plan(start, goal)
            except Exception:  # noqa: BLE001
                path = []
            self._nav_busy = False
            self.bridge.navPathReady.emit(pid, json.dumps(path))

        threading.Thread(target=work, daemon=True).start()

    def _on_nav_path(self, pid: str, path_json: str) -> None:
        if not self.hud.target or self.hud.target.get("pid") != pid:
            return
        self._nav_path = [tuple(p) for p in json.loads(path_json)]
        self.hud.set_path(self._nav_path)
        self._js(f"window.setNavPath({path_json});")

    def _follow_path(self, pos) -> None:
        """Каждая позиция: отклонился от пути — перестроить."""
        if not self.hud.target:
            return
        if not self._nav_path:
            self._replan()
            return
        _, _, dev = lookahead(self._nav_path, pos.x, pos.y)
        if dev > 50:
            self._replan()

    # ---- Анимация «как пройти» ----
    def _on_route_clip_requested(self, pid: str) -> None:
        """Путь от ближайшего телепорта (или от игрока, если он ближе) до точки —
        анимацией на тайлах карты. В фоне; результат — сигнал routeClipReady."""
        entry = self.map_index.by_id.get(pid) if self.map_index else None
        if entry is None:
            self.bridge.routeClipReady.emit(pid, "")
            return
        _, gx, gy = entry
        tp_labels = (self.auto_marker.labels_by_kind.get("teleport", ())
                     + self.auto_marker.labels_by_kind.get("statue", ()))
        tps = self.map_index.candidates(tp_labels, gx, gy, set(), 4000)
        start, start_name, key = None, "", ""
        if tps:
            _, tx, ty = self.map_index.by_id[tps[0].point_id]
            start, key = (tx, ty), tps[0].point_id
            is_tp = tps[0].label_id in self.auto_marker.labels_by_kind.get("teleport", ())
            start_name = tr("Телепорт") if is_tp else tr("Статуя")
        pos = self.position_service.latest(POSITION_MAX_AGE)
        if pos is not None and (start is None or math.hypot(pos.x - gx, pos.y - gy) < tps[0].dist):
            start, start_name, key = (pos.x, pos.y), tr("Ты здесь"), ""
        if start is None:
            self.bridge.routeClipReady.emit(pid, "")
            return
        mid, meta, grid = self.current_map_id, dict(self.meta), self.nav_grid
        name = (self.auto_marker.display_of.get(entry[0]) or self.auto_marker.name_of.get(entry[0], "")
                or tr("Цель"))
        out = PROJECT_ROOT / "data" / "point_info" / str(mid) / f"{pid}_route_{key or 'me'}_{i18n.lang()}.webp"
        url = f"{WEB_TO_ROOT}/data/point_info/{mid}/{out.name}"

        def work() -> None:
            from genshinmap.backend.maps.routeclip import render_route_clip

            try:
                if not (key and out.exists()):
                    path = grid.plan(start, (gx, gy)) if grid is not None else []
                    render_route_clip(meta, path or [start, (gx, gy)], out,
                                      ASSETS_MAPS / str(mid) / "tile_cache",
                                      (start_name, name[:28]))
                self.bridge.routeClipReady.emit(pid, url + f"?t={int(out.stat().st_mtime)}")
            except Exception as e:  # noqa: BLE001 — нет сети/тайлов: карточка без анимации
                self._diag(f"анимация пути {pid}: {e}")
                self.bridge.routeClipReady.emit(pid, "")

        threading.Thread(target=work, daemon=True).start()

    def _on_target_changed(self, target_json: str) -> None:
        target = json.loads(target_json) if target_json else None
        old = self.hud.target or {}
        if (target or {}).get("pid") != old.get("pid") or \
                bool((target or {}).get("tp")) != bool(old.get("tp")) or \
                bool((target or {}).get("via")) != bool(old.get("via")) or \
                bool((target or {}).get("show_path")) != bool(old.get("show_path")):
            self._nav_path = []                         # новая цель или телепорт/пешком
            self.hud.set_path([])
        self.hud.set_target(target)
        if target:
            self._replan(force=True)
        if target and self.settings.get("hud_enabled", True):
            self.point_info.request(target["pid"])        # подсказка + фото для HUD

    def _on_card_for_hud(self, pid: str, card_json: str) -> None:
        try:
            self.hud.set_info(pid, json.loads(card_json))
        except (json.JSONDecodeError, TypeError):
            pass

    # ---- Поверх игры: что показывать ----
    def _apply_hud_options(self) -> None:
        g = self.settings.get
        h = self.hud
        h.show_path, h.show_compass = g("hud_path", True), g("hud_compass", True)
        h.show_ground = g("hud_ground", True)
        h.show_card, h.show_toasts = g("hud_card", True), g("hud_toasts", True)
        h.update()
        opts = {"autoNext": bool(g("auto_next", True)), "useTp": bool(g("route_teleports", True))}
        self._js(f"window.setNavOptions && window.setNavOptions({json.dumps(opts)});")

    def _stop_nav(self) -> None:
        """Хоткей: перестать вести к цели / закончить маршрут."""
        if self.hud.target:
            self._js("window.clearTarget && window.clearTarget();")
            self._log("✕ ведение остановлено")

    def _toggle_hud(self) -> None:
        """Хоткей: скрыть/показать всё поверх игры (настройка сохраняется)."""
        on = not self.settings.get("hud_enabled", True)
        self.settings.set("hud_enabled", on)
        self._check_game_foreground()
        self._log("Подсказки поверх игры: " + ("включены" if on else "выключены"))

    def _update_heading(self, pos) -> None:
        """Куда бежит игрок: смещение за ~1.5 с (не меньше 5 ед.)."""
        now = time.monotonic()
        self._track.append((now, pos.x, pos.y))
        self._track = [p for p in self._track if now - p[0] <= 3.0]
        older = [p for p in self._track if now - p[0] >= 1.0]
        _, x, y = older[-1] if older else self._track[0]
        dx, dy = pos.x - x, pos.y - y
        if math.hypot(dx, dy) >= 5:                    # стоит на месте — прежнее направление
            self.hud.heading = math.degrees(math.atan2(dx, -dy)) % 360

    def _check_game_foreground(self) -> None:
        from genshinmap.backend.game.process_watcher import is_genshin_foreground

        on = self.settings.get("hud_enabled", True) and is_genshin_foreground()
        if on != self.hud.game_active:
            self.hud.set_game_active(on)

    def show_player(self, pos, weak: bool = False) -> None:
        self._js(f"window.setPlayer({pos.x}, {pos.y}, {pos.score:.3f}, {str(weak).lower()});")
        if not weak:
            self.hud.set_minimap(self.position_service.minimap_px, self.position_service.ui_s)
            self._update_heading(pos)
            self.hud.set_player(pos.x, pos.y,
                                pos.scale or self._map_scale(self.current_map_id))
            self._follow_path(pos)

    def _on_position_lost(self) -> None:
        """Позиция потеряна: чаще всего подземелье/многоуровневая зона (их карт у
        HoYoLAB нет) или меню/загрузка. Точка — тусклая на последнем месте,
        стрелка HUD прячется, на карте — пояснение."""
        self._lost = True
        last = self.position_service.latest(float("inf"))
        if last is not None:
            self.show_player(last, weak=True)
        self._show_scene_hint(self._scene if self._scene != "ok" else "unknown_area")
        self.hud.player = None
        self.hud.update()
        if self._pending_mark and time.monotonic() > self._pending_mark[1]:
            self._pending_mark = None
            self._log("   позиция не найдена — отметь точку вручную")

    # ---- что сейчас в игре ----
    def _on_scene(self, name: str) -> None:
        self._scene = name
        if name == "ok":
            self._js("window.setLostHint(false);")
        elif self.position_service.running:
            self._show_scene_hint(name)
        self._update_see()

    def _show_scene_hint(self, name: str) -> None:
        text = SCENES.get(name, (None, None))[1]
        if text:
            self._js(f"window.setLostHint(true, {json.dumps(tr(text))});")
        else:
            self._js("window.setLostHint(false);")

    def _update_see(self) -> None:
        """Строка «Что я вижу»: игра · мини-карта · позиция · подсказка сундука."""
        ps = self.position_service
        game = getattr(self, "_game_running_cache", False)
        tracking = ps.running
        mini = tracking and ps.minimap_visible
        pos = ps.latest(3.0)

        def chip(ok: bool, text: str) -> str:
            color = "#3fb950" if ok else "#6f7f9f"
            return f"<span style='color:{color}'>{'●' if ok else '○'} {tr(text)}</span>"

        chest_t = time.monotonic() - self._prompt_open_t if self._prompt_open_t else None
        html = " &nbsp;".join([chip(game, "игра"), chip(mini, "мини-карта"),
                               chip(pos is not None, "позиция"),
                               chip(chest_t is not None and chest_t < 60, "сундук")])
        scene = SCENES.get(self._scene, ("", None))[0]
        if not tracking:
            scene = "отслеживание выключено"
        html += f"<br><span style='color:#c9d4e8'>{tr('Сейчас')}: {tr(scene)}</span>"
        if self._last_pickup and time.monotonic() - self._last_pickup[1] < 60:
            html += f"<br><span style='color:#8b9ab8'>{tr('Получено')}: {self._last_pickup[0]}</span>"
        self.see_label.setText(html)

    def _prompts_on(self) -> bool:
        """Подсказки читаются: эталоном-картинкой или OCR."""
        return self.prompt_detector.ready or self._ocr_ok

    def _on_prompts(self, found: dict) -> None:
        self._prompts, self._prompts_t = found, time.monotonic()
        if "open" in found:
            self._prompt_open_t = self._prompts_t
            self._prompt_rarity = found.get("rarity") or ""
            self._prompt_seen = True     # подсказки сундуков в этой сессии читаются
        self._chest_prompt_gone(found)

    def _chest_prompt_gone(self, found: dict) -> None:
        """F нажата, когда на экране была подсказка сундука, и она пропала, а игрок
        стоит на месте — сундук открыт (запасной путь, если «Получено» не прочиталось)."""
        po = self._pending_open
        if po is None or not po.get("prompt") or po["cand"] is None:
            return
        if "open" in found:
            po["gone"] = 0
            return
        pos = self.position_service.latest(INTERACT_POS_AGE)
        if pos is None or math.hypot(pos.x - po["pos"].x, pos.y - po["pos"].y) > PROMPT_GONE_MOVE:
            po["gone"] = 0
            return
        po["gone"] = po.get("gone", 0) + 1
        if po["gone"] >= PROMPT_GONE_READS:
            self._pending_open = None
            self._diag(f"сундук {po['cand'].point_id} открыт: подсказка пропала после F")
            self._do_mark(po["cand"], po["pos"], "открыт — подсказка сундука пропала")

    def _on_icons(self, scores: dict) -> None:
        self._icons, self._icons_t = scores, time.monotonic()

    def _diag(self, text: str) -> None:
        """Журнал диагностики авто-отметки: debug/automark.log (всегда, без записи)."""
        try:
            DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            with open(DEBUG_DIR / "automark.log", "a", encoding="utf-8") as f:
                f.write(f"{datetime.now().astimezone():%Y-%m-%d %H:%M:%S}  {text}\n")
        except OSError:
            pass

    def _on_interact(self, key: str) -> None:
        """Нажата F (или другая клавиша взаимодействия): открыл сундук рядом?"""
        if not self.settings.get("auto_mark_enabled", True):
            return
        self._last_interact_t = time.monotonic()
        pos = self.position_service.latest(INTERACT_POS_AGE)
        if pos is None:
            # позиция на мгновение потерялась — решим, когда она появится
            self._pending_interact = time.monotonic() + 3.0
            self._diag(f"{key}: позиции нет — жду до 3 с")
            return
        self._interact_at(pos, key)

    @staticmethod
    def _check_ocr() -> bool:
        from genshinmap.backend.vision.ocr import ScreenOcr

        return ScreenOcr("ru").ready

    def _interact_at(self, pos, key: str) -> None:
        """F рядом с сундуком. Если плашка подбора читается (OCR) — F только
        запоминает МЕСТО, а сундук отмечается, когда в плашке появится
        «Опыт приключений» (его дают сундуки, а не цветы/враги). Без OCR —
        старое правило: F у сундука = открыт."""
        now = time.monotonic()
        self._interact_pos = (pos, now)
        # подсказка «F ▶ Богатый сундук» была на экране — F открыла сундук, и мы
        # знаем его редкость: берём ближайший ТАКОЙ, а не просто ближайший
        chest_prompt = self._prompts_on() and now - self._prompt_open_t <= PROMPT_MAX_AGE
        if chest_prompt:
            near = self.auto_marker.chest_by_prompt(pos.x, pos.y, self.store.collected,
                                                    self._prompt_rarity, 60)
            radius = CHEST_PROMPT_RADIUS
        else:
            near = self.auto_marker.chest_near(pos.x, pos.y, self.store.collected, 60)
            radius = CHEST_MARK_RADIUS
        cand = near if near is not None and near.dist <= radius else None
        if cand is not None or self._ocr_ok:
            po = self._pending_open
            if po is None or now - po["t"] > OPEN_WINDOW_S:
                # первое F: запоминаем, что УЖЕ было в плашке («до»); повторные F
                # (подбор выпавших предметов) снимок не перезаписывают. Сундука
                # на карте может и не быть (cand=None) — тогда будет своя точка.
                self._pending_open = {"cand": cand, "pos": pos, "t": now,
                                      "base": Counter(self._pickup_lines),
                                      "prompt": chest_prompt, "gone": 0}
            elif cand is not None and (po["cand"] is None or chest_prompt
                                       or cand.dist < po["cand"].dist):
                po["cand"], po["pos"] = cand, pos
            if chest_prompt:
                po = self._pending_open
                po["prompt"], po["gone"] = True, 0
            self._pending_open["t"] = now
        act = None
        if not self._ocr_ok:
            prompt_recent = None
            if self.prompt_detector.ready:
                prompt_recent = time.monotonic() - self._prompt_open_t <= 3.0
            act = self.auto_marker.on_interact(pos.x, pos.y, self.store.collected, prompt_recent)
            if act is not None:
                self._do_mark(act.cand, pos, act.reason)
        self._diag(f"{key} @ ({pos.x:.0f},{pos.y:.0f}) score={pos.score:.2f} "
                   f"подсказка: {('сундук ' + self._prompt_rarity) if chest_prompt else 'нет'}; "
                   f"ближайший сундук: {near.point_id + f' {near.dist:.0f} ед.' if near else 'нет'}"
                   f" -> {'отмечен' if act else ('жду плашку' if self._ocr_ok and self._pending_open else 'нет')}")
        if near is not None and near.dist <= 25:
            # образец экрана после открытия — проверить, где плашка подбора
            QTimer.singleShot(1000, self._save_pickup_sample)

    def _save_pickup_sample(self) -> None:
        """Снимок экрана игры (только если активна игра) в debug/samples/, не больше 20."""
        from genshinmap.backend.game.process_watcher import is_genshin_foreground

        if not is_genshin_foreground():
            return
        import cv2
        import mss
        import numpy as np

        out = DEBUG_DIR / "samples"
        out.mkdir(parents=True, exist_ok=True)
        files = sorted(out.glob("chest_*.jpg"))
        for old in files[:-19]:
            old.unlink(missing_ok=True)
        with mss.mss() as sct:
            img = np.array(sct.grab(game_rect(sct)))       # только окно игры
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        cv2.imwrite(str(out / f"chest_{datetime.now().astimezone():%H%M%S}.jpg"), img,
                    [cv2.IMWRITE_JPEG_QUALITY, 85])

    def _game_lang(self) -> str:
        return "en" if self.settings.get("game_lang", "ru") == "en" else "ru"

    def _norm_ocr(self, text: str) -> str:
        """OCR путает похожие латинские и русские буквы: «Mopa» -> «мора»."""
        if self._game_lang() == "en":
            return text.lower()
        return text.lower().translate(str.maketrans("aeopcxmkbtyh", "аеорсхмквтун"))

    def _on_pickup_text(self, lines: list) -> None:
        """Плашка подбора прочитана. Сундук открыт, если ПОСЛЕ нажатия F у него
        в плашке появились НОВЫЕ строки сундука: «Опыт приключений» (его дают
        сундуки, а не враги/цветы) или несколько новых предметов вместе с Морой."""
        norm = [self._norm_ocr(line) for line in lines]
        fresh = list((Counter(x for x in norm if x) - Counter(self._pickup_lines)).elements())
        self._pickup_lines = norm
        if fresh:
            self._last_pickup = (lines[-1][:40], time.monotonic())
        self._valuables_from_pickup(fresh)
        po = self._pending_open
        if po is None:
            return
        now = time.monotonic()
        if now - po["t"] > OPEN_WINDOW_S:
            if po["cand"] is not None:
                self._diag(f"F у сундука {po['cand'].point_id}, но сундучной плашки не было")
            self._pending_open = None
            return
        # новые строки с учётом повторов: два одинаковых сундука дают одинаковые строки
        new = list((Counter(line for line in norm if line) - po["base"]).elements())
        exp, mora = ("adventure", "mora") if self._game_lang() == "en" else ("приключ", "мора")
        chest_like = any(exp in line for line in new) or \
            (any(mora in line for line in new) and len(new) >= 2)
        if not chest_like:
            return
        self._pending_open = None
        if po["cand"] is None:
            self._chest_not_on_map(po["pos"], new)
            return
        self._diag(f"сундук {po['cand'].point_id} открыт: новые строки {new!r}")
        self._do_mark(po["cand"], po["pos"], "открыт — плашка подбора")

    # ---- Свои точки ----
    def _area_of(self, x: float, y: float) -> int | None:
        """Регион места — по ближайшей точке карты (рамки регионов перекрываются)."""
        xy = getattr(self, "_points_xy", None)
        if xy is None or not len(xy):
            return None
        import numpy as np

        i = int(np.argmin((xy[:, 0] - x) ** 2 + (xy[:, 1] - y) ** 2))
        return int(self._points_area[i])

    def _chest_not_on_map(self, pos, lines: list[str]) -> None:
        """Открыт сундук, которого нет на HoYoLAB — своя точка «собрано»."""
        mid = self.current_map_id
        item = self.custom.near(mid, pos.x, pos.y)
        if item is None:
            item = self._add_custom(pos.x, pos.y, note="открыт, нет на HoYoLAB")
            self._diag(f"сундук не на карте @ ({pos.x:.0f},{pos.y:.0f}) -> своя точка {item['id']}")
        self._do_mark(Candidate(item["id"], CUSTOM_LABEL, 0.0), pos, "сундук не на карте — своя точка")

    def _add_custom(self, x: float, y: float, note: str = "") -> dict:
        item = self.custom.add(self.current_map_id, x, y, "chest", note, self._area_of(x, y))
        self.map_index.add_point(item["id"], CUSTOM_LABEL, item["x"], item["y"])
        self._js(f"window.addCustomPoint({json.dumps(item['id'])}, {item['x']}, {item['y']}, "
                 f"{json.dumps(item['area'])});")
        return item

    def _on_custom_add(self, x: float, y: float) -> None:
        item = self._add_custom(x, y, note="добавлена вручную")
        self._log(f"{datetime.now().astimezone():%H:%M:%S}  ⭐ своя точка добавлена")
        self._js(f"window.highlightPoint({json.dumps(item['id'])}, false);")

    def _on_custom_delete(self, pid: str) -> None:
        if self.custom.remove(pid):
            self.map_index.remove_point(pid)
            self.store.unmark(pid)
            self._js(f"window.removeCustomPoint({json.dumps(pid)});")
            self._log(f"{datetime.now().astimezone():%H:%M:%S}  ⭐ своя точка удалена")

    def _valuables_from_pickup(self, fresh: list[str]) -> None:
        """Новые строки «Получено» с названием окулуса/ценности рядом — отмечаем его."""
        if not fresh:
            return
        pos = self.position_service.latest(INTERACT_POS_AGE)
        if pos is None:
            return
        cands = self.auto_marker.valuables_near(pos.x, pos.y, self.store.collected)
        for line in fresh:
            c = self.auto_marker.match_pickup(line, cands)
            if c is not None:
                self._diag(f"подобран {c.point_id}: «{line}»")
                self._do_mark(c, pos, f"получено: {line}")
                cands = [x for x in cands if x.point_id != c.point_id]

    def _auto_by_position(self, pos) -> None:
        """Авто-отметка по позиции + выводы по подсказке «Открыть» (см. automark)."""
        if not pos.reliable or not self.settings.get("auto_mark_enabled", True):
            self.position_service.watch = []
            return
        self.position_service.watch = self.auto_marker.watch_points(
            pos.x, pos.y, self.store.collected)
        # у несобранного сундука — читаем плашку подбора (OCR); иначе не тратим CPU
        near_chest = self.auto_marker.chest_near(pos.x, pos.y, self.store.collected)
        # читаем плашку у несобранного сундука (нужен снимок «до» F) и пока ждём открытия
        near_valuable = bool(self._ocr_ok and self.auto_marker.valuables_near(
            pos.x, pos.y, self.store.collected))
        self.position_service.read_pickup = (near_chest is not None or near_valuable
                                             or self._pending_open is not None)
        # подсказки читаем у любого сундука (и собранного/«вероятного» — вдруг он на месте)
        self.position_service.read_prompts = self._pending_open is not None or bool(
            self.map_index.candidates(self.auto_marker.labels_by_kind.get("chest", ()),
                                      pos.x, pos.y, set(), PROMPT_READ_RADIUS))
        if not self.position_service.read_pickup:
            self._pickup_lines = []
        if self._pending_interact and time.monotonic() <= self._pending_interact:
            self._pending_interact = 0.0
            self._interact_at(pos, "F (отложено)")
        prompts = None
        if self._prompts_on() and time.monotonic() - self._prompts_t <= PROMPT_MAX_AGE:
            prompts = self._prompts
        icons = self._icons if time.monotonic() - self._icons_t <= PROMPT_MAX_AGE else None
        self._quest_scan(pos)
        for act in self.auto_marker.update(pos.x, pos.y, self.store.collected,
                                           prompts=prompts, probable=self.store.probable,
                                           icons=icons, valuables_by_pickup=self._ocr_ok,
                                           absence=getattr(self, "_prompt_seen", False)):
            c = act.cand
            what = self.auto_marker.describe(c.label_id)
            if act.action == "probable" and self._quest_open(c.point_id):
                continue                  # сундук появляется по заданию — «нет на месте» ничего не значит
            if act.action == "collected":
                self._do_mark(c, pos, act.reason)
            elif act.action == "probable" and self.settings.get("absence_mark", True) \
                    and self._absent_again(c.point_id):
                # второй заход в другой раз — сундука снова нет: собран
                self.observations.record(c.point_id, "absent", act.reason)
                self._do_mark(c, pos, "нет на месте уже во второй заход")
            elif act.action == "probable" and c.point_id not in self.store.probable:
                self.observations.record(c.point_id, "absent", act.reason)
                self.store.mark_probable(c.point_id)
                self._push_collected(c.point_id, True)
                self._auto_marks.append(c.point_id)
                self.undo_btn.setEnabled(True)
                self._log_point(f"❔ {what} — вероятно собран ({act.reason}). "
                                "Клик по маркеру — подтвердить", c.point_id)
                self.hud.toast(f"❔ {what} — вероятно уже собран · {self._undo_keys()} — отменить",
                               "#d29922")
                self._js(f"window.highlightPoint({json.dumps(c.point_id)}, false);")
            elif act.action == "probable":
                # тот же заход (стоит рядом): обновляем время — второй заход считается,
                # только если игрок уходил и вернулся
                self.observations.record(c.point_id, "absent", act.reason)
            elif act.action == "present":
                self.observations.record(c.point_id, "present", act.reason)
                self.store.unmark(c.point_id)
                self._push_collected(c.point_id, False)
                self._log_point(f"↩ {what} — на месте, отметка снята", c.point_id)
            elif act.action == "seen":
                self.observations.record(c.point_id, "present", act.reason)
                self.recorder.event("seen", point=c.point_id)

    SECOND_VISIT_S = 600          # второй заход — не раньше чем через 10 минут

    def _absent_again(self, point_id: str) -> bool:
        """Сундука уже не было в прошлый заход (и это был другой заход)."""
        prev = self.observations.get(point_id)
        return bool(prev and prev.get("state") == "absent"
                    and time.time() - prev.get("t", 0) >= self.SECOND_VISIT_S)

    def _log_point(self, text: str, point_id: str) -> None:
        ts = datetime.now().astimezone().strftime("%H:%M:%S")
        item = QListWidgetItem(f"{ts}  {text}")
        item.setData(Qt.ItemDataRole.UserRole, point_id)
        self.detect_log.insertItem(0, item)

    def _covers(self, key: str) -> bool:
        """Окно приложения закрывает область экрана игры (настройка key)?"""
        frac = self.settings.get(key)
        if not frac or not self.isVisible() or self.isMinimized():
            return False
        import mss
        from PyQt6.QtCore import QRect

        with mss.mss() as sct:
            r = region_from_frac(frac, game_rect(sct), key)
        dpr = self.devicePixelRatioF() or 1.0
        area = QRect(int(r["left"] / dpr), int(r["top"] / dpr),
                     int(r["width"] / dpr), int(r["height"] / dpr))
        return self.frameGeometry().intersects(area)

    def _minimap_covered(self) -> bool:
        """Окно приложения закрывает мини-карту игры? (тогда позицию не найти)"""
        return self._covers("minimap")

    def _on_position_status(self, text: str) -> None:
        if self.position_service.running and self._minimap_covered():
            text = ("⚠ Окно карты закрывает мини-карту игры — позицию не найти. "
                    "Сдвинь окно вправо или включи мини-оверлей (Ctrl+Alt+O).\n" + text)
        elif self.position_service.running and self._covers("prompt_region"):
            text = ("⚠ Окно карты закрывает подсказки у персонажа («F ▶ … сундук») — "
                    "сундуки распознаются хуже. Сдвинь окно в сторону.\n" + text)
        elif self.position_service.running and self._covers("pickup_region"):
            text = ("⚠ Окно карты закрывает список «Получено» слева — открытие сундуков "
                    "не распознать. Сдвинь окно правее.\n" + text)
        self.pos_label.setText(text)

    def _on_scale_calibrated(self, map_id: int, scale: float) -> None:
        self._save_scale(map_id, scale)
        self._log(f"Масштаб мини-карты подобран: {scale:.3f}")

    def _save_scale(self, map_id: int, scale: float) -> None:
        scales = dict(self.settings.get("minimap_scale") or {})
        scales[str(map_id)] = round(float(scale), 4)
        self.settings.set("minimap_scale", scales)

    # ---- Мини-оверлей поверх игры ----
    def _top_flags(self) -> Qt.WindowType:
        on_top = self._overlay_mode or bool(self.settings.get("always_on_top", True))
        return Qt.WindowType.WindowStaysOnTopHint if on_top else Qt.WindowType.Widget

    def _toggle_on_top(self) -> None:
        """Обычный режим: держать окно поверх всех или нет (сохраняется)."""
        self.settings.set("always_on_top", self.ontop_btn.isChecked())
        if not self._overlay_mode:
            geom = self.geometry()
            self.setWindowFlags(Qt.WindowType.Window | self._top_flags())
            self.setGeometry(geom)
            self.show()

    def toggle_overlay_mode(self) -> None:
        """Компактное окно без рамки поверх игры (и обратно в обычный режим).

        Двигается за ручку ✥ слева сверху, размер — за уголок справа снизу;
        место и размер запоминаются. Работает поверх игры в оконном/безрамочном
        режиме; в эксклюзивном полноэкранном оверлеи Windows не показывает.
        """
        self._overlay_mode = not self._overlay_mode
        if self._overlay_mode:
            self._normal_geometry = self.geometry()
            self.control_dock.hide()
            self.statusBar().hide()
            # прячем панели веб-карты, чтобы карта заняла всё окно
            self._js(f"window.setCompact(true, {json.dumps(self.ui_state.data.get('compact_zoom'))});")
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
            )
            self.setWindowOpacity(float(self.settings.get("overlay_opacity", 0.9)))
            saved = self.ui_state.data.get("overlay_geometry")
            if saved and len(saved) == 4 and self._on_screen(saved):
                self.setGeometry(*saved)
            else:
                # по умолчанию — правый верхний угол (мини-карта игры слева)
                screen = self.screen().availableGeometry()
                size = self.settings.get("overlay_size", [460, 320])
                w, h = int(size[0]), int(size[1])
                self.setGeometry(screen.right() - w - 20, screen.top() + 20, w, h)
            for wdg in (self.title_bar, self.size_grip):
                wdg.show()
                wdg.raise_()
            self._position_mini_controls()
            self.show()
            self._save_mode()
        else:
            self._save_overlay_geometry()
            for wdg in (self.title_bar, self.size_grip):
                wdg.hide()
            self.control_dock.show()
            self.statusBar().show()
            self._js("window.setCompact(false);")
            self.setWindowFlags(Qt.WindowType.Window | self._top_flags())
            self._save_mode()
            self.setWindowOpacity(1.0)
            if getattr(self, "_normal_geometry", None):
                self.setGeometry(self._normal_geometry)
            self.show()

    def _save_overlay_geometry(self) -> None:
        if self._overlay_mode:
            g = self.geometry()
            rect = [g.x(), g.y(), g.width(), g.height()]
            if self.ui_state.data.get("overlay_geometry") != rect:
                self.ui_state.data["overlay_geometry"] = rect
                self.ui_state.save()

    def _save_mode(self) -> None:
        """Запомнить, в каком режиме окно: следующий запуск — в нём же."""
        self.ui_state.data["overlay_on"] = self._overlay_mode
        self.ui_state.save()

    def _save_geometry_soon(self) -> None:
        """Место/размер меняются (тянут мышью) — сохраняем через полсекунды покоя."""
        if not hasattr(self, "_geom_timer"):
            self._geom_timer = QTimer(self)
            self._geom_timer.setSingleShot(True)
            self._geom_timer.timeout.connect(self._save_current_geometry)
        self._geom_timer.start(500)

    def _save_current_geometry(self) -> None:
        if self._overlay_mode:
            self._save_overlay_geometry()
        elif not self.isMinimized() and not self.isMaximized():
            g = self.geometry()
            self.ui_state.set_window([g.x(), g.y(), g.width(), g.height()])

    @staticmethod
    def _on_screen(rect: list) -> bool:
        """Сохранённое место хотя бы наполовину на каком-то мониторе (мониторы меняются)."""
        from PyQt6.QtCore import QRect

        r = QRect(*[int(v) for v in rect])
        for s in QApplication.screens():
            inter = s.availableGeometry().intersected(r)
            if inter.width() * inter.height() >= r.width() * r.height() / 2:
                return True
        return False

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        if getattr(self, "_map_ready", False):
            self._save_geometry_soon()

    def _position_mini_controls(self) -> None:
        self.title_bar.setGeometry(0, 0, self.width(), _TitleBar.HEIGHT)
        self.size_grip.move(self.width() - 18, self.height() - 18)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._overlay_mode:
            self._position_mini_controls()
        if getattr(self, "_map_ready", False):
            self._save_geometry_soon()

    def _toggle_visible(self) -> None:
        """Ctrl+Alt+H — быстро спрятать/показать окно (для альт-таба в игру)."""
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def closeEvent(self, event) -> None:
        if not self._overlay_mode:  # сохраняем обычную геометрию, не мини
            g = self.geometry()
            self.ui_state.set_window([g.x(), g.y(), g.width(), g.height()])
        self._save_overlay_geometry()
        self.hud.close()
        self.hotkeys.stop()
        self.input_watcher.stop()
        self.recorder.stop()
        self.position_service.stop()
        self.detector_service.stop()
        super().closeEvent(event)

    def _restart_as_admin(self) -> None:
        """Перезапуск с правами администратора (UAC) — тогда хоткеи доходят из игры."""
        import ctypes
        import sys

        self.settings.set("run_as_admin", True)      # дальше — всегда от администратора
        args = " ".join(f'"{a}"' for a in sys.argv)
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, args,
                                                 str(PROJECT_ROOT), 1)
        if rc > 32:          # запустилось — закрываем текущий экземпляр
            self.close()
        else:
            self._log("Запуск от администратора отменён")

    # ---- Мост с картой ----
    def _on_map_ready(self) -> None:
        self._map_ready = True
        # Данные карты страница берёт из mapdata.js сама; через мост шлём только
        # (небольшой) список уже собранных точек.
        collected = json.dumps(sorted(self.store.collected))
        probable = json.dumps(sorted(self.store.probable))
        self._js(f"window.applyCollected({collected}, {probable});")
        # Восстанавливаем сохранённое состояние карты (слои, позиция, регион…).
        state = {
            "enabled": self.ui_state.get_enabled(self.current_map_id),
            "view": self.ui_state.get_view(self.current_map_id),
            **self.ui_state.get_extra(self.current_map_id),
        }
        self._js(f"window.applyState({json.dumps(state, ensure_ascii=False)});")
        # применяем лимит маркеров из настроек
        self._js(f"window.setMaxMarkers({int(self.settings.get('max_markers', 1200))});")
        self._apply_hud_options()
        self._send_quest_flags()
        if not getattr(self, "_welcome_done", False) and not os.environ.get("GENSHINMAP_NO_WELCOME"):
            self._welcome_done = True
            QTimer.singleShot(800, self._show_welcome)
        if self._overlay_mode:
            self._js(f"window.setCompact(true, {json.dumps(self.ui_state.data.get('compact_zoom'))});")
        elif self.ui_state.data.get("overlay_on") and not getattr(self, "_mode_restored", False):
            self._mode_restored = True
            QTimer.singleShot(300, self.toggle_overlay_mode)
        last = self.position_service.latest(10.0)
        if last is not None:
            self.show_player(last)

    def _show_welcome(self) -> None:
        """Первый запуск — 3 шага; после обновления — «Что нового» (по разу)."""
        from genshinmap.frontend.qt.welcome import (
            WHATS_NEW,
            WelcomeDialog,
            WhatsNewDialog,
        )

        last = self.ui_state.data.get("last_version")
        self.ui_state.data["last_version"] = __version__
        self.ui_state.save()
        if not self.settings.get("onboarded", False):
            self._welcome = WelcomeDialog(self)
            self._welcome.show()
        elif last != __version__ and __version__ in WHATS_NEW:
            self._whatsnew = WhatsNewDialog(self, __version__)
            self._whatsnew.show()

    # ---- Задания у сундуков ----
    def _quest_flags_file(self, mid: int) -> Path:
        return PROJECT_ROOT / "data" / "point_info" / str(mid) / "quest_flags.json"

    def _load_quests(self, mid: int, labels: list[dict]) -> None:
        try:
            self._quest_flags = json.loads(self._quest_flags_file(mid).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._quest_flags = {}
        self._quest_checked = set(self._quest_flags)
        if not self.quests.load(mid):
            # точки начала заданий: разово скачать описания меток «Задания мира»
            from genshinmap.backend.maps.pointinfo import BASE, HEADERS, _get_json

            def fetch(pid) -> str:
                info = _get_json(f"{BASE}/point/info?point_id={pid}&map_id={mid}"
                                 f"&app_sn=ys_obc&lang=ru-ru", HEADERS)["data"]["info"]
                return info.get("content") or ""

            points = json.loads((map_dir(mid) / "points.json").read_text(encoding="utf-8"))
            self.quests.build_async(mid, points, labels, fetch)

    def _quests_done(self) -> set[str]:
        from genshinmap.backend.maps.quests import norm_name

        return {norm_name(n) for n in self.ui_state.data.get("quests_done", [])}

    def _quest_open(self, pid: str) -> bool:
        """Сундук связан с заданием, которое игрок ещё не отметил сделанным."""
        from genshinmap.backend.maps.quests import norm_name

        if pid not in self._quest_flags:
            return False
        name = self._quest_flags[pid]
        return not name or norm_name(name) not in self._quests_done()

    def _on_point_info(self, pid: str, card_json: str) -> None:
        """Карточка точки пришла: ищем в тексте задание, дополняем карточку."""
        from genshinmap.backend.maps.quests import norm_name, quest_mention

        try:
            card = json.loads(card_json)
        except (json.JSONDecodeError, TypeError):
            card = {}
        self._quest_checked.add(pid)
        entry = self.map_index.by_id.get(pid) if self.map_index else None
        chest = entry is not None and self.auto_marker.kind(entry[0]) == "chest"
        m = quest_mention([card.get("content", ""), card.get("summary", ""),
                           *[t.get("text", "") for t in card.get("tips", [])]]) if chest else None
        if m:
            name = m["names"][0] if m["names"] else ""
            start = next((self.quests.find(n) for n in m["names"] if self.quests.find(n)), None)
            done = bool(name) and norm_name(name) in self._quests_done()
            card["quest"] = {"name": name, "quote": m["quote"][:220], "done": done,
                             "start": {"pid": start["pid"]} if start else None}
            if self._quest_flags.get(pid) != name:
                self._quest_flags[pid] = name
                self._save_quest_flags()
            self._js(f"window.setQuestFlags([{json.dumps(pid)}], {str(not done).lower()});")
        self._js(f"window.showPointInfo({json.dumps(pid)}, {json.dumps(card, ensure_ascii=False)});")

    def _save_quest_flags(self) -> None:
        f = self._quest_flags_file(self.current_map_id)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(self._quest_flags, ensure_ascii=False), encoding="utf-8")

    def _on_quest_done(self, name: str, done: bool) -> None:
        from genshinmap.backend.maps.quests import norm_name

        names = [n for n in self.ui_state.data.get("quests_done", []) if norm_name(n) != norm_name(name)]
        if done:
            names.append(name)
        self.ui_state.data["quests_done"] = names
        self.ui_state.save()
        ids = [pid for pid, n in self._quest_flags.items() if n and norm_name(n) == norm_name(name)]
        self._js(f"window.setQuestFlags({json.dumps(ids)}, {str(not done).lower()});")
        for pid in ids:                                  # карточки — с новым состоянием
            self.point_info.request(pid)
        self._log(("✓ задание сделано: «" if done else "↶ задание не сделано: «") + name + "»")

    def _send_quest_flags(self) -> None:
        ids = [pid for pid in self._quest_flags if self._quest_open(pid)]
        if ids:
            self._js(f"window.setQuestFlags({json.dumps(ids)}, true);")

    QUEST_SCAN_S = 4.0            # не чаще одной точки за столько секунд — бережём HoYoLAB
    QUEST_SCAN_RADIUS = 350

    def _quest_scan(self, pos) -> None:
        """В фоне понемногу смотрим описания несобранных сундуков рядом с игроком."""
        now = time.monotonic()
        if now - getattr(self, "_quest_scan_t", 0.0) < self.QUEST_SCAN_S:
            return
        self._quest_scan_t = now
        labels = self.auto_marker.labels_by_kind.get("chest", ())
        for c in self.map_index.candidates(labels, pos.x, pos.y, self.store.collected,
                                           self.QUEST_SCAN_RADIUS):
            if c.point_id not in self._quest_checked and not str(c.point_id).startswith("u"):
                self._quest_checked.add(c.point_id)
                self.point_info.request(c.point_id)
                return

    def _on_marker_clicked(self, marker_id: str) -> None:
        collected = self.store.toggle(marker_id)
        self._push_collected(marker_id, collected)

    def _update_gems(self) -> None:
        """Примогемы: за сессию, в текущем регионе (или везде) — оценка."""
        if not hasattr(self, "gems_label") or not hasattr(self, "gems"):
            return
        stats = self.gems.by_region(self.store.collected)
        world_got = sum(r["got"] for r in stats.values())
        world_total = sum(r["total"] for r in stats.values())
        lines = [f"За эту сессию: <b>+{self.gems.session_total()}</b>"]
        reg = self._current_region
        if reg is not None and reg in stats:
            r = stats[reg]
            name = self._region_names.get(reg, f"Область {reg}")
            lines.append(f"{name}: <b>~{r['got']}</b> из ~{r['total']} "
                         f"(сундуков {r['got_chests']}/{r['chests']})")
        lines.append(f"Всего на карте: ~{world_got} из ~{world_total}")
        self.gems_label.setText("<br>".join(lines))

    def _push_collected(self, marker_id: str, collected: bool) -> None:
        """Отправить на карту новое состояние маркера (вызывается и извне — из vision)."""
        self.gems.on_marked(marker_id, collected)
        self._update_gems()
        probable = marker_id in self.store.probable
        self._js(f"window.setCollected({json.dumps(marker_id)}, {str(collected).lower()}, "
                 f"{str(probable).lower()});")

    def mark_collected(self, marker_id: str) -> None:
        """Публичный метод: отметить маркер собранным (для авто-распознавания)."""
        self.store.mark_collected(marker_id)
        self._push_collected(marker_id, True)

    # ---- Статус игры ----
    def _update_game_status(self) -> None:
        self._game_running_cache = is_genshin_running()
        if self._game_running_cache:
            self.status_label.setText("🟢 Genshin запущен")
            self._auto_recording(True)
            # игра запущена — сразу следим за позицией (для авто-отметки);
            # один раз за запуск игры, чтобы ручное выключение не перебивать
            if not getattr(self, "_auto_track_done", False):
                self._auto_track_done = True
                if self.settings.get("auto_mark_enabled", True) and not self.position_service.running:
                    self.position_service.start()
        else:
            self._auto_track_done = False
            self._auto_recording(False)
            self.status_label.setText("⚪ Genshin не запущен")

