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


if __name__ == "__main__":
    # Быстрая ручная проверка: python -m genshinmap.detector.process_watcher
    proc = find_genshin_process()
    if proc:
        print(f"Genshin запущен: PID={proc.pid}, name={proc.info['name']}")
    else:
        print("Genshin не запущен.")
