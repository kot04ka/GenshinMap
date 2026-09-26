"""Выпуск новой версии: версия -> сборка exe -> коммит -> релиз на GitHub.

    python tools/release.py 1.0.1 "Что нового: ..."

После этого у всех, кто запускает GenshinMap.exe, появится кнопка
«⬇ Обновить до v1.0.1». Нужен вход в GitHub CLI (gh auth login).
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "src" / "genshinmap" / "version.py"
GH = shutil.which("gh") or r"C:\Program Files\GitHub CLI\gh.exe"


def run(*cmd: str) -> None:
    print("›", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)


def main() -> None:
    if len(sys.argv) < 2 or not re.fullmatch(r"\d+\.\d+\.\d+", sys.argv[1]):
        sys.exit('Использование: python tools/release.py 1.0.1 "что нового"')
    version, notes = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "")
    text = VERSION_FILE.read_text(encoding="utf-8")
    VERSION_FILE.write_text(re.sub(r'__version__ = "[^"]+"', f'__version__ = "{version}"', text),
                            encoding="utf-8")
    run(sys.executable, "tools/build_exe.py")
    run("git", "add", "-A")
    run("git", "commit", "-m", f"GenshinMap {version}")
    run("git", "push")
    run(GH, "release", "create", f"v{version}", "dist/GenshinMap.zip",
        "--title", f"GenshinMap {version}", "--notes", notes or f"Версия {version}")
    print(f"\nГотово: v{version} опубликована — копии обновятся сами.")


if __name__ == "__main__":
    main()
