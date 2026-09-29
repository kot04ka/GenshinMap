"""Сундуки, связанные с заданиями, и где эти задания начинаются.

Готовой пометки «квестовый сундук» в данных нет — определяем по тексту:
описание точки HoYoLAB и советы игроков (appsample) часто говорят «появляется во
время задания „…“» / «only during the quest “…”». Из текста берём название
задания, а точку начала ищем среди меток HoYoLAB «Задания мира» (их описания —
тоже текст игроков, поэтому сравнение нестрогое).

Индекс заданий: data/maps/<id>/quests.json  [{"pid", "x", "y", "names": [...]}, ...]
(строится один раз в фоне — описания точек «Задания мира» грузятся по одной).
"""
from __future__ import annotations

import difflib
import json
import re
import threading
import time
from pathlib import Path

QUEST_LABEL_NAMES = ("Задания мира",)
_QUEST_WORD = re.compile(r"задани|квест|quest", re.IGNORECASE)
_QUOTED = re.compile(r"[«\"“„]([^«»\"“”„]{3,60})[»\"”“]")
# «квеста не требуется», «не из квеста», «no quest needed» — это как раз НЕ квестовый
_NEGATION = re.compile(r"(не\s+(требует|нужен|нужно|из)\S*\s+(квест|задани))|"
                       r"((квест|задани)\S*\s+не\s+(требует|нужен|нужно))|"
                       r"(без\s+(квест|задани))|(no\s+quest)|(quest\s+(is\s+)?not\s+(required|needed))|"
                       r"(not\s+(part\s+of|from)\s+(a|the)?\s*quest)", re.IGNORECASE)
MATCH_MIN = 0.72              # похожесть названий (0..1), ниже — «не нашли»


def norm_name(name: str) -> str:
    n = name.lower().replace("ё", "е")
    n = re.sub(r"[^\w\s-]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def quest_mention(texts: list[str]) -> dict | None:
    """Текст про сундук -> {"names": [...], "quote": "..."} если он про задание."""
    for text in texts:
        if not text or not _QUEST_WORD.search(text) or _NEGATION.search(text):
            continue
        names = []
        for m in _QUOTED.finditer(text):
            # название в кавычках рядом со словом «задание/квест» (до 60 символов перед ним)
            before = text[max(0, m.start() - 60):m.start()]
            if _QUEST_WORD.search(before) or _QUEST_WORD.search(text[m.end():m.end() + 20]):
                names.append(m.group(1).strip())
        i = _QUEST_WORD.search(text).start()
        quote = text[max(0, i - 60): i + 120].strip()
        return {"names": names, "quote": ("…" if i > 60 else "") + quote}
    return None


class QuestIndex:
    """Точки начала мировых заданий (из описаний HoYoLAB) и поиск по названию."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.items: list[dict] = []
        self._building = False

    def path(self, map_id: int) -> Path:
        return self.data_dir / str(map_id) / "quests.json"

    def load(self, map_id: int) -> bool:
        f = self.path(map_id)
        try:
            self.items = json.loads(f.read_text(encoding="utf-8"))
            return True
        except (OSError, json.JSONDecodeError):
            self.items = []
            return False

    def build_async(self, map_id: int, points: list[dict], labels: list[dict], fetch, done=None) -> None:
        """Скачать описания точек «Задания мира» (по одной, бережно) и сохранить индекс.
        fetch(point_id) -> текст описания или ""."""
        if self._building:
            return
        ids = {l["id"] for l in labels if l["name"] in QUEST_LABEL_NAMES}
        todo = [p for p in points if p["label_id"] in ids]
        if not todo:
            return
        self._building = True

        def work() -> None:
            items = []
            for p in todo:
                try:
                    text = fetch(p["id"]) or ""
                except Exception:  # noqa: BLE001 — одна точка не должна срывать сборку
                    text = ""
                names = [m.group(1).strip() for m in _QUOTED.finditer(text)]
                if not names and text and len(text) <= 60:
                    names = [text.strip()]          # описание — просто название задания
                if names:
                    items.append({"pid": str(p["id"]), "x": p["x"], "y": p["y"], "names": names})
                time.sleep(0.15)                      # не грузим HoYoLAB
            f = self.path(map_id)
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
            self.items = items
            self._building = False
            if done:
                done()

        threading.Thread(target=work, daemon=True).start()

    def find(self, name: str) -> dict | None:
        """Точка начала задания по названию (нестрого)."""
        want = norm_name(name)
        if not want:
            return None
        best, best_r = None, 0.0
        for it in self.items:
            for n in it["names"]:
                have = norm_name(n)
                if not have:
                    continue
                r = 1.0 if (want in have or have in want) and min(len(want), len(have)) >= 5 \
                    else difflib.SequenceMatcher(None, want, have).ratio()
                if r > best_r:
                    best, best_r = it, r
        return best if best_r >= MATCH_MIN else None
