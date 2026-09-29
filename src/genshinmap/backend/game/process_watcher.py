"""Определяет, запущен ли Genshin Impact.

Игра называется по-разному в зависимости от региона:
  - GenshinImpact.exe  (глобальная версия)
  - YuanShen.exe       (китайская версия / 原神)

Мы просто периодически смотрим список процессов через psutil.
Никакого чтения памяти игры — только факт "запущен / не запущен".
"""
from __future__ import annotations

import psutil

# Имена процессов игры (в нижнем регистре для сравнения).
GENSHIN_PROCESS_NAMES = {"genshinimpact.exe", "yuanshen.exe"}


def find_genshin_process() -> psutil.Process | None:
    """Возвращает процесс игры, если он найден, иначе None."""
    for proc in psutil.process_iter(["name"]):
        try:
            name = (proc.info["name"] or "").lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if name in GENSHIN_PROCESS_NAMES:
            return proc
    return None


def is_genshin_running() -> bool:
    """True, если процесс игры сейчас активен."""
    return find_genshin_process() is not None


def is_genshin_foreground() -> bool:
    """True, если сейчас активно (на переднем плане) именно окно игры.

    Нужно записи отладки: не сохранять кадры рабочего стола, мессенджеров и т.п.
    """
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return psutil.Process(pid.value).name().lower() in GENSHIN_PROCESS_NAMES
    except Exception:  # noqa: BLE001 — не Windows / процесс недоступен
        return False


def _game_hwnd() -> int:
    """Главное окно игры (видимое окно процесса игры с наибольшей площадью) или 0."""
    import ctypes
    from ctypes import wintypes

    pids = set()
    for proc in psutil.process_iter(["name"]):
        try:
            if (proc.info["name"] or "").lower() in GENSHIN_PROCESS_NAMES:
                pids.add(proc.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if not pids:
        return 0
    user32 = ctypes.windll.user32
    best = [0, 0]

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum(hwnd, _lp):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids:
            r = wintypes.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(r))
            area = r.right * r.bottom
            if area > best[1]:
                best[0], best[1] = hwnd, area
        return True

    user32.EnumWindows(enum, 0)
    return best[0]


_HWND_CACHE = [0, 0.0]


def game_window_rect() -> dict | None:
    """Клиентская область окна игры в пикселях экрана {left, top, width, height}
    (оконный режим, любой монитор) или None — игры нет/свёрнута."""
    try:
        import ctypes
        import time
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        now = time.monotonic()
        hwnd = _HWND_CACHE[0]
        if not hwnd or not user32.IsWindow(hwnd) or now - _HWND_CACHE[1] > 10:
            hwnd = _game_hwnd()
            _HWND_CACHE[:] = [hwnd, now]
        if not hwnd or user32.IsIconic(hwnd):
            return None
        r = wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(r))
        pt = wintypes.POINT(0, 0)
        user32.ClientToScreen(hwnd, ctypes.byref(pt))
        if r.right < 320 or r.bottom < 200:
            return None
        return {"left": pt.x, "top": pt.y, "width": r.right, "height": r.bottom}
    except Exception:  # noqa: BLE001 — не Windows
        return None


def game_monitor_name() -> str:
    """Имя монитора с окном игры — то же, что QScreen.name() (вида DISPLAY1)."""
    try:
        import ctypes
        from ctypes import wintypes

        class MONITORINFOEXW(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
                        ("szDevice", wintypes.WCHAR * 32)]

        hwnd = _HWND_CACHE[0] or _game_hwnd()
        if not hwnd:
            return ""
        user32 = ctypes.windll.user32
        user32.MonitorFromWindow.restype = wintypes.HMONITOR
        mon = user32.MonitorFromWindow(hwnd, 2)      # MONITOR_DEFAULTTONEAREST
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(info)
        if user32.GetMonitorInfoW(mon, ctypes.byref(info)):
            return info.szDevice
    except Exception:  # noqa: BLE001 — не Windows
        return ""
    return ""


if __name__ == "__main__":
    # Быстрая ручная проверка: python -m genshinmap.detector.process_watcher
    proc = find_genshin_process()
    if proc:
        print(f"Genshin запущен: PID={proc.pid}, name={proc.info['name']}")
    else:
        print("Genshin не запущен.")
    print("окно игры:", game_window_rect(), game_monitor_name())
