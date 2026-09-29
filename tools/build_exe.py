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

# Лишнее в сборке (карте нужны только Widgets + WebEngine): модули Qt для 3D,
# QML-контролов, PDF, мультимедиа и т.п., переводы на все языки, видеокодек OpenCV.
QT_DROP_PREFIXES = (
    "Qt6Quick3D", "Qt6QuickControls2", "Qt6QuickDialogs2", "Qt6QuickEffects",
    "Qt6QuickParticles", "Qt6QuickTest", "Qt6QuickTimeline", "Qt6QuickVectorImage",
    "Qt6Pdf", "Qt6Multimedia", "Qt6SpatialAudio", "Qt6RemoteObjects", "Qt6Sensors",
    "Qt6Bluetooth", "Qt6Nfc", "Qt6SerialPort", "Qt6Test", "Qt6Designer", "Qt6Help",
    "Qt6Charts", "Qt6DataVisualization", "Qt6Graphs", "Qt6Lottie", "Qt63D",
    "Qt6TextToSpeech", "Qt6ShaderTools",
)
KEEP_LOCALES = ("en-US.pak", "ru.pak")
ICON_MAX_PX = 64          # иконки на карте ~32 px; 64 — с запасом для чётких экранов

README = """Genshin Interactive Map — оверлей-карта для Genshin Impact
=========================================================

Запуск: GenshinMap.exe (папку целиком не разделять — рядом лежат данные).
При запуске Windows спросит права администратора (как у самой игры) — «Да»:
так горячие клавиши и отметки работают, пока активна игра. Можно «Нет» —
всё, кроме части хоткеев, работать будет. Отключается в ⚙ Настройках.

Первый запуск
  1. Игра — в ОКОННОМ или БЕЗРАМОЧНОМ режиме (в полноэкранном оверлей не виден).
     Любое разрешение и формат (1080p, 1440p, 4K, 21:9, 16:10), любой монитор.
  2. Кнопка «📍 Отслеживать» — позиция по мини-карте (включается сама с игрой).
  3. Если точка на карте «не там» — «🎯 Калибровка»: снимок окна игры, обвести
     круг мини-карты и список «Получено» слева.
  4. Окно карты не ставь поверх мини-карты, списка «Получено» слева и подсказок
     у персонажа — Ctrl+Alt+O = компактный оверлей, тяни за полосу сверху.

Что отмечается само
  • сундук — нажал F, когда у персонажа была подсказка «F ▶ Богатый сундук»
    (отмечается сундук той же редкости), и в «Получено» пришла награда;
  • окулус/кристалл и т.п. — его название появилось в «Получено»;
  • телепорт/статуя — подошёл вплотную.
  После отметки поверх игры всплывает сообщение; ошиблось — Ctrl+Alt+Z.
  Клик по маркеру — подсказка и фото; правый клик — отметить/снять вручную.

Куда идти
  • «Вести сюда» в карточке точки или 🗺 маршрут по сундукам региона: путь
    рисуется прямо на мини-карте игры, собрал — ведёт к следующему сундуку.
  • 🧹 → «🔥 Где остались сундуки» — сколько несобранного в каждом месте.

Горячие клавиши: Ctrl+Alt+O — мини-оверлей, Ctrl+Alt+H — скрыть/показать,
Ctrl+Alt+M — отметить ближайшее, Ctrl+Alt+Z — отменить отметку,
Ctrl+Alt+B — закладка (меняются в ⚙).

Ничего не читает из памяти игры и ничего в игре не нажимает — только смотрит
на окно игры (мини-карта, «Получено», подсказки у персонажа), и только когда
игра активна. Рисунок поверх игры скрыт от захвата экрана и записи.
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
    # эталоны интерфейса игры (есть ли на экране мини-карта)
    shutil.copytree(ROOT / "assets" / "ui", OUT / "assets" / "ui", dirs_exist_ok=True)
    for m in sorted((ROOT / "assets" / "maps").iterdir()):
        if not m.is_dir():
            continue
        dst = OUT / "assets" / "maps" / m.name
        if (m / "icons").exists():
            copy_icons(m / "icons", dst / "icons")
        for ref in [*m.glob("ref_*_z1.png"), *m.glob("water_*_z2.png"), *m.glob("road_*_z2.png")]:
            dst.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ref, dst / ref.name)
    # страница карты (mapdata_*.js приложение создаёт само при запуске)
    web_src = ROOT / "src" / "genshinmap" / "frontend" / "web"
    web_dst = OUT / "src" / "genshinmap" / "frontend" / "web"
    web_dst.mkdir(parents=True, exist_ok=True)
    shutil.copy2(web_src / "map.html", web_dst / "map.html")
    for f in web_src.glob("i18n_*.json"):                 # словари языков интерфейса
        shutil.copy2(f, web_dst / f.name)
    shutil.copytree(web_src / "vendor", web_dst / "vendor", dirs_exist_ok=True)
    (OUT / "README.txt").write_text(README, encoding="utf-8-sig")


def copy_icons(src: Path, dst: Path) -> None:
    """Иконки категорий, уменьшенные до ICON_MAX_PX (оригиналы бывают по 3 МБ)."""
    from PIL import Image

    dst.mkdir(parents=True, exist_ok=True)
    for f in src.glob("*.png"):
        try:
            with Image.open(f) as img:
                img.thumbnail((ICON_MAX_PX, ICON_MAX_PX), Image.LANCZOS)
                img.save(dst / f.name, optimize=True)
        except OSError:
            shutil.copy2(f, dst / f.name)


def slim() -> None:
    """Убрать из сборки то, что приложению не нужно."""
    internal = OUT / "_internal"
    qt = internal / "PyQt6" / "Qt6"
    removed = 0
    for dll in (qt / "bin").glob("*.dll"):
        if dll.name.startswith(QT_DROP_PREFIXES):
            removed += dll.stat().st_size
            dll.unlink()
    for pyd in (internal / "PyQt6").glob("*.pyd"):          # их обёртки для Python
        if ("Qt6" + pyd.stem.removeprefix("Qt")).startswith(QT_DROP_PREFIXES):
            removed += pyd.stat().st_size
            pyd.unlink()
    if (qt / "qml").exists():
        removed += sum(f.stat().st_size for f in (qt / "qml").rglob("*") if f.is_file())
        shutil.rmtree(qt / "qml")
    tr = qt / "translations"
    for f in tr.rglob("*"):
        if f.is_file() and not (f.name in KEEP_LOCALES or f.name.endswith("_ru.qm")):
            removed += f.stat().st_size
            f.unlink()
    for f in (internal / "cv2").glob("opencv_videoio_ffmpeg*.dll"):
        removed += f.stat().st_size
        f.unlink()
    print(f"Убрано лишнего: {removed / 1e6:.0f} МБ")


def make_zip() -> Path:
    archive = shutil.make_archive(str(DIST / APP), "zip", root_dir=DIST, base_dir=APP)
    return Path(archive)


def main() -> None:
    run_pyinstaller()
    slim()
    copy_data()
    z = make_zip()
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file()) / 1e6
    print(f"\nГотово: {OUT} ({size:.0f} МБ)\nАрхив: {z} ({z.stat().st_size / 1e6:.0f} МБ)")


if __name__ == "__main__":
    main()
