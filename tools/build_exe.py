"""Сборка GenshinMap.exe для передачи другому человеку (Windows, PyInstaller).

    python tools/build_exe.py

Результат:
    build/release/GenshinMap/      папка с GenshinMap.exe и данными
    build/release/GenshinMap.zip   то же, архивом — его и отправлять

Запускать программу из build/ НЕ нужно: распакуй архив в свою папку.

В сборку идут только общие данные (карты, иконки, референсы позиции, страница
карты). Личные файлы — прогресс, настройки, записи отладки — НЕ копируются:
у нового человека всё начинается с нуля.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Собираем ТОЛЬКО в служебную папку build/: её никто не запускает. Раньше сборка
# шла в dist/ и перезаписывала программу, запущенную оттуда (терялся прогресс).
BUILD = ROOT / "build"
DIST = BUILD / "release"
APP = "GenshinMap"
OUT = DIST / APP

HIDDEN = [
    "winrt.windows.media.ocr",
    "winrt.windows.globalization",
    "winrt.windows.graphics.imaging",
    "winrt.windows.storage.streams",
    "winrt.windows.foundation",
    "winrt.windows.foundation.collections",
    "pynput.keyboard._win32",
    "pynput.mouse._win32",
]

README = """Genshin Interactive Map — оверлей-карта для Genshin Impact
=========================================================

Запуск: GenshinMap.exe (папку целиком не разделять — рядом лежат данные).
При запуске Windows спросит права администратора (как у самой игры) — «Да»:
так горячие клавиши и отметки работают, пока активна игра. Можно «Нет» —
всё, кроме части хоткеев, работать будет. Отключается в ⚙ Настройках.

Первый запуск
  1. Игра — в ОКОННОМ или БЕЗРАМОЧНОМ режиме (в полноэкранном оверлей не виден).
  2. Кнопка «📍 Отслеживать» — позиция по мини-карте (включается сама с игрой).
  3. Если разрешение экрана не 16:9 или точка на карте «не там» — «🎯 Калибровка»:
     снимок экрана, обвести круг мини-карты и список «Получено» слева.
  4. Окно карты не ставь поверх мини-карты и списка «Получено» слева —
     Ctrl+Alt+O = компактный оверлей, тяни за полосу сверху.

Что отмечается само
  • сундук — нажал F у сундука и в списке «Получено» появился «Опыт приключений»;
  • окулус/кристалл и т.п. — его название появилось в «Получено»;
  • телепорт/статуя — подошёл вплотную.
  Клик по маркеру — подсказка и фото; правый клик — отметить/снять вручную.

Горячие клавиши: Ctrl+Alt+O — мини-оверлей, Ctrl+Alt+H — скрыть/показать,
Ctrl+Alt+M — отметить ближайшее, Ctrl+Alt+B — закладка (меняются в ⚙).

Ничего не читает из памяти игры и ничего в игре не нажимает — только смотрит
на экран (картинка мини-карты и текст «Получено»), и только когда активна игра.
Прогресс и настройки хранятся в папке data/ рядом с exe.
"""


def run_pyinstaller() -> None:
    icon = BUILD / "logo.ico"
    BUILD.mkdir(exist_ok=True)
    from PIL import Image

    Image.open(ROOT / "assets" / "logo.png").save(icon, sizes=[(256, 256), (64, 64), (32, 32), (16, 16)])
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
           "--onedir", "--name", APP, "--icon", str(icon),
           "--paths", str(ROOT / "src"),
           "--distpath", str(DIST), "--workpath", str(BUILD / "pyi"),
           "--specpath", str(BUILD)]
    for h in HIDDEN:
        cmd += ["--hidden-import", h]
    cmd.append(str(ROOT / "main.py"))
    subprocess.run(cmd, check=True)


def copy_data() -> None:
    # данные карт (без кеша подсказок)
    for d in sorted((ROOT / "data" / "maps").iterdir()):
        if d.is_dir():
            shutil.copytree(d, OUT / "data" / "maps" / d.name, dirs_exist_ok=True)
    shutil.copy2(ROOT / "data" / "maps" / "index.json", OUT / "data" / "maps" / "index.json")
    # ассеты: логотип, иконки категорий, референсы позиции (старые тайлы не нужны)
    (OUT / "assets").mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "assets" / "logo.png", OUT / "assets" / "logo.png")
    for m in sorted((ROOT / "assets" / "maps").iterdir()):
        if not m.is_dir():
            continue
        dst = OUT / "assets" / "maps" / m.name
        if (m / "icons").exists():
            shutil.copytree(m / "icons", dst / "icons", dirs_exist_ok=True)
        for ref in [*m.glob("ref_*_z1.png"), *m.glob("water_*_z2.png")]:
            dst.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ref, dst / ref.name)
    # страница карты (mapdata_*.js приложение создаёт само при запуске)
    web_src = ROOT / "src" / "genshinmap" / "web"
    web_dst = OUT / "src" / "genshinmap" / "web"
    web_dst.mkdir(parents=True, exist_ok=True)
    shutil.copy2(web_src / "map.html", web_dst / "map.html")
    shutil.copytree(web_src / "vendor", web_dst / "vendor", dirs_exist_ok=True)
    (OUT / "README.txt").write_text(README, encoding="utf-8-sig")


def make_zip() -> Path:
    archive = shutil.make_archive(str(DIST / APP), "zip", root_dir=DIST, base_dir=APP)
    return Path(archive)


def main() -> None:
    run_pyinstaller()
    copy_data()
    z = make_zip()
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file()) / 1e6
    print(f"\nГотово: {OUT} ({size:.0f} МБ)\nАрхив: {z} ({z.stat().st_size / 1e6:.0f} МБ)")


if __name__ == "__main__":
    main()
