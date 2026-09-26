"""Слежение за клавишей взаимодействия (F) — «игрок что-то открыл/подобрал».

Опрашиваем GetAsyncKeyState: это только ЧТЕНИЕ состояния клавиши, нажатие
не перехватывается и в игру доходит как обычно. В отличие от хуков
клавиатуры работает, даже когда Genshin запущен от администратора.
"""
from __future__ import annotations

import sys
import threading

from PyQt6.QtCore import QObject, pyqtSignal

from .hotkeys import _NAMED_VK

POLL_S = 0.03


def key_to_vk(name: str) -> int | None:
    n = name.strip().lower().strip("<>")
    if n in _NAMED_VK:
        return _NAMED_VK[n]
    if n in ("lmb", "mouse1"):
        return 0x01
    if n in ("rmb", "mouse2"):
        return 0x02
    if n in ("mmb", "mouse3"):
        return 0x04
    if len(n) == 1 and n.isalnum():
        return ord(n.upper())
    return None


class InputWatcher(QObject):
    pressed = pyqtSignal(str)      # имя клавиши — при нажатии (фронт)

    def __init__(self, keys: list[str] | None = None) -> None:
        super().__init__()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.set_keys(keys or ["F"])

    def set_keys(self, keys: list[str]) -> None:
        self.keys = {k: vk for k in keys if (vk := key_to_vk(k)) is not None}

    def start(self) -> None:
        if sys.platform != "win32" or self._thread is not None:
            return
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(self._stop,),
                                        name="input", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread = None

    def _run(self, stop: threading.Event) -> None:
        import ctypes

        get = ctypes.windll.user32.GetAsyncKeyState
        down: dict[str, bool] = {}
        while not stop.wait(POLL_S):
            for name, vk in list(self.keys.items()):
                is_down = bool(get(vk) & 0x8000)
                if is_down and not down.get(name):
                    self.pressed.emit(name)
                down[name] = is_down
