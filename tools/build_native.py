"""Сборка Rust-модуля genshinmap_native (native/) и установка в текущий Python.

    python tools/build_native.py

Нужны Rust (rustup, тулчейн stable-x86_64-pc-windows-gnu или msvc) и maturin
(`pip install maturin`). Без модуля приложение работает так же, только A* считается
на Python (медленнее примерно в 30 раз).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native"
WHEELS = NATIVE / "target" / "wheels"


def _cargo_on_path() -> bool:
    cargo_bin = Path.home() / ".cargo" / "bin"
    if cargo_bin.is_dir() and str(cargo_bin) not in os.environ.get("PATH", ""):
        os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + str(cargo_bin)
    return shutil.which("cargo") is not None


def build() -> bool:
    """Собирает и ставит модуль. False — Rust/maturin недоступны или сборка упала."""
    if not _cargo_on_path():
        print("Rust не найден (cargo) — модуль не собран, A* будет на Python.")
        return False
    for old in WHEELS.glob("genshinmap_native-*.whl"):
        old.unlink()
    r = subprocess.run([sys.executable, "-m", "maturin", "build", "--release", "-o", str(WHEELS)],
                       cwd=NATIVE, check=False)
    wheels = sorted(WHEELS.glob("genshinmap_native-*.whl"))
    if r.returncode != 0 or not wheels:
        print("Сборка Rust-модуля не удалась — A* будет на Python.")
        return False
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--force-reinstall",
                    str(wheels[-1])], check=True)
    print(f"Rust-модуль установлен: {wheels[-1].name}")
    return True


if __name__ == "__main__":
    sys.exit(0 if build() else 1)
