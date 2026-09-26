"""Запись отладочной сессии: кадры мини-карты/плашки + результат трекера.

Нужна, чтобы настраивать распознавание на НАСТОЯЩИХ кадрах игры без самой игры:
    debug/session_<дата>/
        log.jsonl          по строке на событие (кадр, закладка, статус)
        minimap/m_000123.png   кадр мини-карты (без потерь — для матчинга)
        pickup/p_000123.jpg    область плашки подбора
        screen/s_000004.jpg    весь экран изредка (контекст)

Проиграть запись: python tools/replay_position.py debug/session_<дата>
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

# Интервалы записи (с). Ручная запись — подробная; автозапись (всегда, пока идёт
# игра) — лёгкая, а у сундуков (boost) плашку/подсказку пишет часто.
FULL_RATES = {"minimap": 0.5, "pickup": 0.5, "prompt": 0.5, "screen": 20.0}
LIGHT_RATES = {"minimap": 2.0, "pickup": 3.0, "prompt": 3.0, "screen": 60.0}
BOOST_EVERY_S = 0.5       # у сундука: плашка/подсказка — часто (моменты открытия)
KEEP_SESSIONS = 5         # автоочистка: сколько последних сессий хранить
MAX_TOTAL_BYTES = 1_000_000_000   # и не больше 1 ГБ на все записи


class DebugRecorder:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.dir: Path | None = None
        self._lock = threading.Lock()
        self._n = 0
        self._last = {"minimap": 0.0, "pickup": 0.0, "screen": 0.0, "prompt": 0.0}
        self._t0 = 0.0
        self.rates = dict(FULL_RATES)
        self.boost = False        # игрок у сундука — пишем плашку/подсказку чаще
        self.auto = False         # запись запущена автоматически

    @property
    def active(self) -> bool:
        return self.dir is not None

    def start(self, meta: dict | None = None, light: bool = False) -> Path:
        self.prune()
        self.rates = dict(LIGHT_RATES if light else FULL_RATES)
        self.auto = light
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        d = self.root / f"session_{stamp}"
        for sub in ("minimap", "pickup", "screen", "prompt"):
            (d / sub).mkdir(parents=True, exist_ok=True)
        with self._lock:
            self.dir, self._n, self._t0 = d, 0, time.monotonic()
            self._last = {k: 0.0 for k in self._last}
        self.event("start", **(meta or {}))
        return d

    def stop(self) -> None:
        if self.dir is not None:
            self.event("stop")
        with self._lock:
            self.dir = None

    def prune(self) -> None:
        """Удалить старые сессии: оставить KEEP_SESSIONS и не больше MAX_TOTAL_BYTES.
        Сессии без кадров (игра не была активна) удаляются сразу и НЕ вытесняют
        настоящие записи."""
        import shutil

        sessions = sorted(self.root.glob("session_*"), reverse=True)   # новые первыми
        total = kept = 0
        for d in sessions:
            files = [f for f in d.rglob("*") if f.is_file()]
            if not any(f.suffix in (".jpg", ".png") for f in files):
                shutil.rmtree(d, ignore_errors=True)
                continue
            total += sum(f.stat().st_size for f in files)
            kept += 1
            if kept > KEEP_SESSIONS or total > MAX_TOTAL_BYTES:
                shutil.rmtree(d, ignore_errors=True)

    # ---------- запись ----------
    def _due(self, kind: str, every: float | None = None) -> bool:
        if every is None:
            every = self.rates[kind]
            if self.boost and kind in ("pickup", "prompt"):
                every = BOOST_EVERY_S
        now = time.monotonic()
        if now - self._last[kind] < every:
            return False
        self._last[kind] = now
        return True

    def _write_line(self, rec: dict) -> None:
        with self._lock:
            if self.dir is None:
                return
            rec["t"] = round(time.monotonic() - self._t0, 3)
            with open(self.dir / "log.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def event(self, kind: str, **data) -> None:
        self._write_line({"type": kind, **data})

    def minimap(self, frame: np.ndarray, pos, screen_h: int, force: bool = False) -> None:
        """Кадр мини-карты + то, что нашёл трекер (pos может быть None)."""
        if self.dir is None or not (force or self._due("minimap")):
            return
        self._n += 1
        name = f"m_{self._n:06d}.png"
        cv2.imwrite(str(self.dir / "minimap" / name), frame)
        rec = {"type": "minimap", "file": name, "screen_h": screen_h}
        if pos is not None:
            rec.update(x=pos.x, y=pos.y, score=round(pos.score, 3), margin=round(pos.margin, 3),
                       scale=round(pos.scale, 4), local=pos.local, reliable=pos.reliable)
        self._write_line(rec)

    def pickup(self, grab) -> None:
        """grab() -> кадр; вызывается только когда пора писать (экономим захват)."""
        if self.dir is None or not self._due("pickup"):
            return
        frame = grab()
        name = f"p_{self._n:06d}.jpg"
        cv2.imwrite(str(self.dir / "pickup" / name), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        self._write_line({"type": "pickup", "file": name})

    def prompt(self, frame: np.ndarray, found: dict) -> None:
        """Область подсказок взаимодействия + что в ней распознано."""
        if self.dir is None or not self._due("prompt"):
            return
        name = f"q_{self._n:06d}.jpg"
        cv2.imwrite(str(self.dir / "prompt" / name), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        self._write_line({"type": "prompt", "file": name,
                          "found": {k: round(v, 3) if isinstance(v, float) else v
                                    for k, v in found.items()}})

    def screen(self, grab, force: bool = False) -> None:
        if self.dir is None or not (force or self._due("screen")):
            return
        frame = grab()
        name = f"s_{self._n:06d}.jpg"
        cv2.imwrite(str(self.dir / "screen" / name), frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        self._write_line({"type": "screen", "file": name})
