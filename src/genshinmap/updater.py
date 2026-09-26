"""Автообновление программы из GitHub Releases.

Раз в UPDATE_EVERY_H (и при запуске) спрашиваем последний релиз репозитория.
Если версия новее — сигнал `available`. По кнопке «Обновить»: скачиваем
GenshinMap.zip, распаковываем во временную папку и запускаем маленький
скрипт, который ждёт закрытия приложения, копирует новые файлы поверх и
запускает его снова. Личные файлы (data/progress.json, settings.json и т.п.)
в архиве релиза отсутствуют — поэтому не затираются.

Из исходников (python main.py) обновление не ставится — только сообщение.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import urllib.request
import zipfile
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from .paths import FROZEN, PROJECT_ROOT
from .version import UPDATE_REPO, __version__

API = "https://api.github.com/repos/{repo}/releases/latest"
ASSET_NAME = "GenshinMap.zip"
HEADERS = {"User-Agent": "GenshinMap-updater", "Accept": "application/vnd.github+json"}


def parse_version(v: str) -> tuple[int, ...]:
    """'v1.2.10' -> (1, 2, 10); мусор -> (0,)."""
    parts = []
    for p in v.strip().lstrip("vV").split("."):
        num = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts) or (0,)


class Updater(QObject):
    available = pyqtSignal(str, str, str)   # версия, описание, URL архива
    progress = pyqtSignal(int)              # 0..100 при скачивании
    failed = pyqtSignal(str)
    ready = pyqtSignal()                    # скачано — сейчас закроемся и обновимся

    def __init__(self) -> None:
        super().__init__()
        self.latest: tuple[str, str, str] | None = None

    # ---------- проверка ----------
    def check_async(self) -> None:
        threading.Thread(target=self._check, daemon=True).start()

    def _check(self) -> None:
        try:
            req = urllib.request.Request(API.format(repo=UPDATE_REPO), headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15) as r:
                rel = json.load(r)
        except Exception:  # noqa: BLE001 — нет сети / нет релизов: просто молчим
            return
        tag = rel.get("tag_name") or ""
        if parse_version(tag) <= parse_version(__version__):
            return
        url = next((a["browser_download_url"] for a in rel.get("assets", [])
                    if a.get("name") == ASSET_NAME), "")
        if url:
            self.latest = (tag, rel.get("body") or "", url)
            self.available.emit(tag, rel.get("body") or "", url)

    # ---------- установка ----------
    def install_async(self, url: str) -> None:
        if not FROZEN:
            self.failed.emit("Запущено из исходников — обнови через git pull.")
            return
        threading.Thread(target=self._install, args=(url,), daemon=True).start()

    def _install(self, url: str) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="genshinmap_upd_"))
        archive = tmp / ASSET_NAME
        try:
            req = urllib.request.Request(url, headers={"User-Agent": HEADERS["User-Agent"]})
            with urllib.request.urlopen(req, timeout=60) as r, open(archive, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                while chunk := r.read(1 << 20):
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        self.progress.emit(int(done * 100 / total))
            with zipfile.ZipFile(archive) as z:
                z.extractall(tmp / "new")
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"Не удалось скачать обновление: {e}")
            return
        src = tmp / "new" / "GenshinMap"
        if not (src / "GenshinMap.exe").exists():
            self.failed.emit("В архиве обновления нет GenshinMap.exe")
            return
        self._write_and_run_script(src, tmp)
        self.ready.emit()

    @staticmethod
    def _write_and_run_script(src: Path, tmp: Path) -> None:
        """Скрипт: дождаться закрытия, скопировать поверх, запустить, прибрать."""
        app_dir = PROJECT_ROOT
        exe = app_dir / "GenshinMap.exe"
        pid = os.getpid()
        script = tmp / "update.cmd"
        # ждём закрытия не дольше ~30 с, потом завершаем старую версию сами;
        # всё скрыто: консоль и её дочерние tasklist/find окна не показывают
        # системные утилиты — полными путями: в PATH бывает чужой find (из Git и т.п.)
        sysdir = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
        tl, fd, tk, to, rc = (f'"{sysdir / n}"' for n in
                              ("tasklist.exe", "find.exe", "taskkill.exe", "timeout.exe", "robocopy.exe"))
        lines = [
            "@echo off",
            "chcp 65001 >nul",
            "set n=0",
            ":wait",
            f'{tl} /FI "PID eq {pid}" | {fd} "{pid}" >nul',
            "if errorlevel 1 goto copy",
            "set /a n+=1",
            f"if %n% GEQ 30 ({tk} /PID {pid} /F >nul 2>&1 & {to} /t 2 >nul & goto copy)",
            f"{to} /t 1 >nul",
            "goto wait",
            ":copy",
            f'{rc} "{src}" "{app_dir}" /E /R:3 /W:1 /NFL /NDL /NJH /NJS >nul',
            f'start "" "{exe}"',
            # самоудаление: (goto) выходит из скрипта, и его папку можно стереть
            f'(goto) 2>nul & rmdir /S /Q "{tmp}"',
        ]
        script.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
        # CREATE_NO_WINDOW без DETACHED_PROCESS: скрытая консоль наследуется
        # tasklist/find/timeout — никаких всплывающих окон
        subprocess.Popen(["cmd", "/c", str(script)],
                         creationflags=subprocess.CREATE_NO_WINDOW
                         | subprocess.CREATE_NEW_PROCESS_GROUP,
                         close_fds=True)
