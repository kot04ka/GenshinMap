"""Мост между JavaScript-картой и Python.

QWebChannel пробрасывает этот объект в страницу как `bridge`.
JS вызывает слоты (on_ready, on_marker_clicked, …), Python шлёт сигналы обратно.
"""
from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot


class MapBridge(QObject):
    # Сигналы наружу (в Python-логику приложения)
    ready = pyqtSignal()
    markerClicked = pyqtSignal(str)
    stateChanged = pyqtSignal(str)  # JSON: {enabled:[...], view:{lat,lng,zoom}}
    pointInfoRequested = pyqtSignal(str)       # карточка точки (фото, «как найти»)
    openUrlRequested = pyqtSignal(str)         # открыть ссылку во внешнем браузере
    targetChanged = pyqtSignal(str)            # цель навигации (JSON или "") — для HUD
    customAdd = pyqtSignal(float, float)       # своя точка: мировые x, y
    navPathReady = pyqtSignal(str, str)        # путь к цели готов (из фонового потока)
    customDelete = pyqtSignal(str)
    routeClipRequested = pyqtSignal(str)       # анимация «как пройти» к точке
    routeClipReady = pyqtSignal(str, str)      # point_id, url ("" — не вышло)
    questDone = pyqtSignal(str, bool)          # название задания, сделано ли
    mapSwitchRequested = pyqtSignal(int)       # выбрана другая карта в заголовке

    @pyqtSlot()
    def on_ready(self) -> None:
        """JS сообщает, что карта загружена и готова принимать данные."""
        self.ready.emit()

    @pyqtSlot(str)
    def on_marker_clicked(self, marker_id: str) -> None:
        """Отметить/снять «собрано» (кнопка в карточке или правый клик по маркеру)."""
        self.markerClicked.emit(marker_id)

    @pyqtSlot(str)
    def on_state_changed(self, state_json: str) -> None:
        """JS сообщает об изменении состояния (слои/позиция) — для сохранения."""
        self.stateChanged.emit(state_json)

    @pyqtSlot(str)
    def request_point_info(self, point_id: str) -> None:
        self.pointInfoRequested.emit(point_id)

    @pyqtSlot(str)
    def on_target_changed(self, target_json: str) -> None:
        self.targetChanged.emit(target_json)

    @pyqtSlot(float, float)
    def on_custom_add(self, x: float, y: float) -> None:
        self.customAdd.emit(x, y)

    @pyqtSlot(str)
    def on_custom_delete(self, point_id: str) -> None:
        self.customDelete.emit(point_id)

    @pyqtSlot(str, bool)
    def on_quest_done(self, name: str, done: bool) -> None:
        self.questDone.emit(name, done)

    @pyqtSlot(str)
    def request_route_clip(self, point_id: str) -> None:
        self.routeClipRequested.emit(point_id)

    @pyqtSlot(int)
    def switch_map(self, map_id: int) -> None:
        self.mapSwitchRequested.emit(map_id)

    @pyqtSlot(str)
    def open_url(self, url: str) -> None:
        self.openUrlRequested.emit(url)
