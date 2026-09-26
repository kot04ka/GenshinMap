"""Точка входа приложения.

Запуск:
    python main.py
Сборка exe для передачи другому человеку:
    python tools/build_exe.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Делаем пакет genshinmap импортируемым из src/
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from genshinmap.overlay.window import OverlayWindow
from genshinmap.paths import FROZEN
from genshinmap.paths import PROJECT_ROOT as ROOT

LOGO = ROOT / "assets" / "logo.png"


def _relaunch_as_admin() -> bool:
    """Genshin работает от администратора — запускаемся с теми же правами, чтобы
    хоткеи и чтение клавиш из игры работали надёжно. Настройка run_as_admin.

    Возвращает True, если запущен повышенный экземпляр (этот нужно закрыть).
    Отказ в окне UAC — просто работаем дальше без прав администратора.
    """
    if sys.platform != "win32" or os.environ.get("GENSHINMAP_NO_ELEVATE"):
        return False
    from genshinmap.overlay.hotkeys import is_admin
    from genshinmap.storage import SettingsStore

    if is_admin() or not SettingsStore().get("run_as_admin", True):
        return False
    import ctypes

    exe = Path(sys.executable)
    if FROZEN:                                      # собранный GenshinMap.exe
        program, argv = exe, sys.argv[1:]
    else:
        pythonw = exe.with_name("pythonw.exe")      # без лишнего окна консоли
        program = pythonw if pythonw.exists() else exe
        argv = [str(ROOT / "main.py"), *sys.argv[1:]]
    args = " ".join(f'"{a}"' for a in argv)
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", str(program), args, str(ROOT), 1)
    return rc > 32


def main() -> int:
    if _relaunch_as_admin():
        return 0
    app = QApplication(sys.argv)
    app.setApplicationName("Genshin Interactive Map")
    if LOGO.exists():
        app.setWindowIcon(QIcon(str(LOGO)))
    window = OverlayWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
