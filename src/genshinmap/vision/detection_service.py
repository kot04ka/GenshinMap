"""Фоновый сервис авто-распознавания сбора.

Пока запущен Genshin, периодически скриншотит область плашки предмета и прогоняет
через CollectorDetector. При обнаружении шлёт сигнал `detected`. Антидребезг:
один и тот же предмет не срабатывает чаще, чем раз в `cooldown_s` секунд.

Область по умолчанию — правый край экрана (там всплывает плашка). Настраивается.
"""
from __future__ import annotations

import time
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from ..detector.process_watcher import is_genshin_running
from .collector_detector import CollectorDetector, Detection


class DetectionService(QObject):
    # name, label_id (или -1), score
    detected = pyqtSignal(str, int, float)
    # изменение состояния сервиса (вкл/выкл)
    state_changed = pyqtSignal(bool)

    def __init__(
        self,
        templates_dir: str | Path,
        interval_ms: int = 700,
        cooldown_s: float = 6.0,
        region: dict[str, int] | None = None,
        require_game: bool = True,
    ) -> None:
        super().__init__()
        self.detector = CollectorDetector(templates_dir)
        self.cooldown_s = cooldown_s
        self.region = region
        self.require_game = require_game
        self._last_seen: dict[str, float] = {}

        self.timer = QTimer(self)
        self.timer.setInterval(interval_ms)
        self.timer.timeout.connect(self._tick)

    def start(self) -> None:
        self.detector.reload()
        self.timer.start()
        self.state_changed.emit(True)

    def stop(self) -> None:
        self.timer.stop()
        self.state_changed.emit(False)

    @property
    def running(self) -> bool:
        return self.timer.isActive()

    def _tick(self) -> None:
        if self.require_game and not is_genshin_running():
            return
        if not self.detector.templates:
            return
        try:
            hits = self.detector.detect_once(self.region)
        except Exception:  # noqa: BLE001 — сбой захвата не должен ронять сервис
            return
        now = time.monotonic()
        for hit in hits:
            self._emit_if_new(hit, now)

    def _emit_if_new(self, hit: Detection, now: float) -> None:
        name = hit.template.name
        last = self._last_seen.get(name, 0.0)
        if now - last < self.cooldown_s:
            return
        self._last_seen[name] = now
        label_id = hit.template.label_id if hit.template.label_id is not None else -1
        self.detected.emit(name, label_id, float(hit.score))
