"""Глобальные горячие клавиши (работают, даже когда фокус в игре).

На Windows используем системный RegisterHotKey: комбинацию обрабатывает сама
Windows, до того как клавиши уйдут в окно игры. Перехват клавиатуры (pynput,
WH_KEYBOARD_LL) так не умеет: Genshin работает от администратора, и Windows не
отдаёт его ввод хукам обычного процесса — поэтому в игре хоткеи молчали.
pynput остаётся запасным вариантом для не-Windows.

Хоткеи слушаются в отдельном потоке; наружу — сигналы Qt (доставятся в
главный поток). Формат комбинаций: "<ctrl>+<alt>+m".
"""
from __future__ import annotations

import ctypes
import sys
import threading

from PyQt6.QtCore import QObject, pyqtSignal

IS_WINDOWS = sys.platform == "win32"

try:
    from pynput import keyboard
    _HAS_PYNPUT = True
except Exception:  # noqa: BLE001 — окружение без pynput не должно ронять приложение
    _HAS_PYNPUT = False

DEFAULT_HOTKEYS = {
    "mark_nearest": "<ctrl>+<alt>+m",
    "toggle_overlay": "<ctrl>+<alt>+o",
    "toggle_visible": "<ctrl>+<alt>+h",
    "bookmark": "<ctrl>+<alt>+b",
    "undo": "<ctrl>+<alt>+z",
    "stop_nav": "<ctrl>+<alt>+x",
    "toggle_hud": "<ctrl>+<alt>+g",
    "toggle_path": "<ctrl>+<alt>+p",
}

# --- Win32 ---
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
_MODS = {"ctrl": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT,
         "cmd": MOD_WIN, "win": MOD_WIN}
_NAMED_VK = {
    "space": 0x20, "enter": 0x0D, "tab": 0x09, "esc": 0x1B, "backspace": 0x08,
    "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23,
    "page_up": 0x21, "page_down": 0x22, "up": 0x26, "down": 0x28,
    "left": 0x25, "right": 0x27,
    **{f"f{i}": 0x6F + i for i in range(1, 13)},
}


def parse_combo(combo: str) -> tuple[int, int] | None:
    """"<ctrl>+<alt>+m" -> (модификаторы, virtual-key) или None, если не разобрать."""
    mods, vk = 0, None
    for part in combo.lower().replace(" ", "").split("+"):
        name = part.strip("<>")
        if not name:
            continue
        if name in _MODS:
            mods |= _MODS[name]
        elif name in _NAMED_VK:
            vk = _NAMED_VK[name]
        elif len(name) == 1 and (name.isalnum()):
            vk = ord(name.upper())
        else:
            return None
    return (mods, vk) if vk is not None else None


def is_admin() -> bool:
    if not IS_WINDOWS:
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


class _Win32HotkeyThread(threading.Thread):
    """Поток с очередью сообщений Windows: регистрирует хоткеи и ждёт WM_HOTKEY."""

    def __init__(self, combos: dict[int, tuple[int, int]], on_hotkey) -> None:
        super().__init__(name="hotkeys", daemon=True)
        self.combos = combos
        self.on_hotkey = on_hotkey
        self.thread_id = 0
        self.failed: list[int] = []
        self.ready = threading.Event()

    def run(self) -> None:
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self.thread_id = kernel32.GetCurrentThreadId()
        for hid, (mods, vk) in self.combos.items():
            if not user32.RegisterHotKey(None, hid, mods | MOD_NOREPEAT, vk):
                self.failed.append(hid)       # комбинация уже занята другой программой
        self.ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                self.on_hotkey(int(msg.wParam))
        for hid in self.combos:
            user32.UnregisterHotKey(None, hid)

    def stop(self) -> None:
        if self.thread_id:
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)


class HotkeyManager(QObject):
    markNearest = pyqtSignal()
    toggleOverlay = pyqtSignal()
    toggleVisible = pyqtSignal()
    bookmark = pyqtSignal()        # закладка в записи отладки («вот тут подобрал»)
    undo = pyqtSignal()            # снять последнюю авто-отметку
    stopNav = pyqtSignal()         # перестать вести (цель/маршрут)
    toggleHud = pyqtSignal()       # скрыть/показать всё поверх игры
    togglePath = pyqtSignal()      # показать/скрыть путь к цели

    ACTIONS = ("mark_nearest", "toggle_overlay", "toggle_visible", "bookmark", "undo",
               "stop_nav", "toggle_hud", "toggle_path")

    def __init__(self, hotkeys: dict | None = None) -> None:
        super().__init__()
        self._listener = None
        self._thread: _Win32HotkeyThread | None = None
        self.failed: list[str] = []    # комбинации, которые не удалось зарегистрировать
        self.hotkeys = dict(DEFAULT_HOTKEYS)
        if hotkeys:
            self.hotkeys.update({k: v for k, v in hotkeys.items() if v})

    @property
    def available(self) -> bool:
        return IS_WINDOWS or _HAS_PYNPUT

    def _signal(self, action: str):
        return {
            "mark_nearest": self.markNearest,
            "toggle_overlay": self.toggleOverlay,
            "toggle_visible": self.toggleVisible,
            "bookmark": self.bookmark,
            "undo": self.undo,
            "stop_nav": self.stopNav,
            "toggle_hud": self.toggleHud,
            "toggle_path": self.togglePath,
        }[action]

    def start(self) -> None:
        if self._thread is not None or self._listener is not None:
            return
        if IS_WINDOWS:
            self._start_win32()
        elif _HAS_PYNPUT:
            self._start_pynput()

    def _start_win32(self) -> None:
        combos: dict[int, tuple[int, int]] = {}
        ids: dict[int, str] = {}
        for i, action in enumerate(self.ACTIONS, start=1):
            parsed = parse_combo(self.hotkeys.get(action) or "")
            if parsed:
                combos[i], ids[i] = parsed, action

        def on_hotkey(hid: int) -> None:
            action = ids.get(hid)
            if action:
                self._signal(action).emit()   # из потока — Qt доставит в главный поток

        self._thread = _Win32HotkeyThread(combos, on_hotkey)
        self._thread.start()
        self._thread.ready.wait(2.0)
        self.failed = [self.hotkeys[ids[h]] for h in self._thread.failed]

    def _start_pynput(self) -> None:
        mapping = {}
        for action in self.ACTIONS:
            combo = (self.hotkeys.get(action) or "").strip()
            if combo:
                mapping[combo] = self._signal(action).emit
        if not mapping:
            return
        try:
            self._listener = keyboard.GlobalHotKeys(mapping)
            self._listener.start()
        except Exception:  # noqa: BLE001 — кривая комбинация не должна ронять приложение
            self._listener = None

    def stop(self) -> None:
        if self._thread is not None:
            self._thread.stop()
            self._thread.join(1.0)
            self._thread = None
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def rebind(self, hotkeys: dict) -> None:
        """Применить новые комбинации: перезапускает слушатель."""
        if hotkeys:
            self.hotkeys.update({k: v for k, v in hotkeys.items() if v})
        self.stop()
        self.start()
