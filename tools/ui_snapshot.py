"""Проверка страницы карты без игры: открывает map.html в QWebEngine, собирает
ошибки консоли JS и сохраняет скриншот.

    python tools/ui_snapshot.py                       # 1400x860, карта 2
    python tools/ui_snapshot.py --size 420x520 --compact --js "openCard('...')"

Код выхода 1, если в консоли были ошибки (для проверки после правок).
Мост к Python не подключается — проверяется только сама страница.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication

from genshinmap.backend.core.paths import PROJECT_ROOT, WEB_DIR
from genshinmap.backend.maps.mapdata import load_map_index, write_bundle
from genshinmap.backend.services.static_server import ensure_server


class _Page(QWebEnginePage):
    def __init__(self, errors: list[str]) -> None:
        super().__init__()
        self.errors = errors

    def javaScriptConsoleMessage(self, level, message, line, source) -> None:
        tag = level.name.replace("JavaScriptConsoleMessageLevel", "").replace("Level", "")
        text = f"[{tag}] {Path(source).name}:{line} {message}"
        print(text)
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            self.errors.append(text)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", type=int, default=2)
    ap.add_argument("--size", default="1400x860")
    ap.add_argument("--compact", action="store_true", help="мини-режим (как оверлей поверх игры)")
    ap.add_argument("--js", default="", help="выполнить после загрузки (открыть карточку и т.п.)")
    ap.add_argument("--wait", type=float, default=4.0, help="секунд ждать после загрузки")
    ap.add_argument("--out", default=str(PROJECT_ROOT / "scratch" / "ui_snapshot.png"))
    a = ap.parse_args()

    app = QApplication(sys.argv)
    names = {m["id"]: m["name"] for m in load_map_index()}
    write_bundle(a.map, names.get(a.map, "Карта"))
    errors: list[str] = []
    view = QWebEngineView()
    page = _Page(errors)
    view.setPage(page)
    w, h = (int(v) for v in a.size.lower().split("x"))
    view.resize(w, h)
    view.show()
    rel = (WEB_DIR / "map.html").relative_to(PROJECT_ROOT).as_posix()
    view.setUrl(QUrl(f"http://127.0.0.1:{ensure_server()}/{rel}#map={a.map}"))

    def after_load(ok: bool) -> None:
        if not ok:
            errors.append("страница не загрузилась")
        if a.compact:
            page.runJavaScript("window.setCompact && window.setCompact(true);")
        if a.js:
            page.runJavaScript(a.js)
        QTimer.singleShot(int(a.wait * 1000), shoot)

    def shoot() -> None:
        page.runJavaScript("typeof map !== 'undefined' && map !== null", 0, report)

    def report(built) -> None:
        if not built:
            errors.append("карта не построена (map == null)")
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        view.grab().save(str(out))
        print(f"скриншот: {out}")
        print("ОШИБКИ:\n  " + "\n  ".join(errors) if errors else "ошибок нет")
        app.exit(1 if errors else 0)

    view.loadFinished.connect(after_load)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
