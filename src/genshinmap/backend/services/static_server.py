"""Локальный http-сервер для страницы карты.

Страница должна иметь http-origin, иначе Chromium блокирует тайлы CDN (v2-карты).
Сервер отдаёт файлы проекта (страница, assets/, data/point_info) только на 127.0.0.1.
"""
from __future__ import annotations

import functools
import http.server
import socketserver
import threading

from genshinmap.backend.core.paths import PROJECT_ROOT

# --- Локальный http-сервер: страница должна иметь http-origin, иначе Chromium
#     блокирует загрузку тайлов CDN (v2-карты). Плюс отдаёт assets/иконки. ---
_SERVER_PORT: int | None = None


def ensure_server() -> int:
    global _SERVER_PORT
    if _SERVER_PORT is not None:
        return _SERVER_PORT

    class _QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args) -> None:  # без спама в консоль
            pass

        def end_headers(self) -> None:
            # map.html и mapdata_*.js меняются — не даём Chromium брать их из кеша
            if self.path.split("?")[0].endswith((".html", ".js")):
                self.send_header("Cache-Control", "no-store")
            super().end_headers()

    handler = functools.partial(_QuietHandler, directory=str(PROJECT_ROOT))
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    _SERVER_PORT = httpd.server_address[1]
    return _SERVER_PORT
