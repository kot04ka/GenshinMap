"""Подробности точки: подсказка HoYoLAB + советы игроков с appsample.

  - HoYoLAB map/point/info: описание «как найти», фото места, видео;
  - genshin-impact-map.appsample.com: комментарии игроков (текст, фото, лайки,
    дата) и краткая сводка — как на их сайте. Соответствие точек их меткам —
    data/maps/<id>/appsample.json (строит tools/fetch_appsample.py).

Грузим в фоне, кешируем на диск (data/point_info/<map_id>/<point_id>.json,
для английского — data/point_info/en/…) на CACHE_DAYS — повторно открывается
мгновенно и без сети.

Язык: советы игроков пишутся на разных языках (большинство — по-английски), у
каждого есть готовый перевод (поле trans). Показываем только текст на языке
интерфейса: свой или перевод; без перевода — только фото.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.request
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

BASE = "https://sg-public-api.hoyolab.com/common/map_user/ys_obc/v1/map"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://act.hoyolab.com/"}
COMMENTS = ("https://cache-v2.lemonapi.com/comments/v2?app=gim&ttl=7000"
            "&collection={type}&docId={id}&lang={lang}&page=1&pageSize=8")
CARD_VERSION = 2          # формат/язык карточки (старый кеш с английскими советами — заново)
_CYR = re.compile("[А-Яа-яЁё]")
APPSAMPLE_CDN = "https://game-cdn.appsample.com"
CACHE_DAYS = 7
MAX_TIPS = 6
_URL_RE = re.compile(r"https?://\S+")


def _get_json(url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


class PointInfoService(QObject):
    loaded = pyqtSignal(str, str)      # point_id, JSON карточки ({"error": true} при ошибке)

    def __init__(self, cache_root: Path, maps_root: Path) -> None:
        super().__init__()
        self.cache_root = Path(cache_root)
        self.maps_root = Path(maps_root)
        self.map_id = 2
        self.lang = "ru"
        self._appsample: dict[int, dict] = {}

    def _cache(self, point_id: str, map_id: int | None = None) -> Path:
        root = self.cache_root / "en" if self.lang == "en" else self.cache_root
        return root / str(self.map_id if map_id is None else map_id) / f"{point_id}.json"

    def _appsample_map(self, map_id: int) -> dict:
        if map_id not in self._appsample:
            f = self.maps_root / str(map_id) / "appsample.json"
            try:
                self._appsample[map_id] = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self._appsample[map_id] = {}
        return self._appsample[map_id]

    def request(self, point_id: str) -> None:
        path = self._cache(point_id)
        if path.exists() and time.time() - path.stat().st_mtime < CACHE_DAYS * 86400:
            text = path.read_text(encoding="utf-8")
            if f'"v": {CARD_VERSION}' in text:
                self.loaded.emit(point_id, text)
                return
        threading.Thread(target=self._fetch, args=(point_id, self.map_id), daemon=True).start()

    def _fetch(self, point_id: str, map_id: int) -> None:
        card: dict = {}
        try:
            info = _get_json(f"{BASE}/point/info?point_id={point_id}&map_id={map_id}"
                             f"&app_sn=ys_obc&lang={'en-us' if self.lang == 'en' else 'ru-ru'}",
                             HEADERS)["data"]["info"]
            video = info.get("video")
            if isinstance(video, dict):
                video = video.get("url") or ""
            elif not isinstance(video, str):
                video = ""
            card = {
                "content": (info.get("content") or "").strip(),
                "img": info.get("img") or "",
                "video": video,
            }
        except Exception:  # noqa: BLE001 — нет сети/точки: попробуем хотя бы советы
            card = {}
        card.update(self._tips(point_id, map_id))
        if not card:
            card = {"error": True}
        else:
            card["v"] = CARD_VERSION
            path = self._cache(point_id, map_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
        self.loaded.emit(point_id, json.dumps(card, ensure_ascii=False))

    def _tips(self, point_id: str, map_id: int) -> dict:
        """Советы игроков с appsample: {"summary": str, "tips": [...]} или {}."""
        ref = self._appsample_map(map_id).get(point_id)
        if not ref:
            return {}
        aid, typ = ref
        try:
            data = _get_json(COMMENTS.format(type=typ, id=aid, lang=self.lang),
                             {"User-Agent": "Mozilla/5.0"})["data"]
        except Exception:  # noqa: BLE001 — советы необязательны
            return {}
        tips = []
        for c in sorted(data.get("comments", []), key=lambda c: -(c.get("vote") or 0)):
            # текст — на языке интерфейса: свой или готовый перевод
            own = c.get("content") or ""
            text = own if c.get("lang") == self.lang else (c.get("trans") or {}).get(self.lang, "")
            text = _URL_RE.sub("", text or "").strip()
            img = c.get("image") or ""
            if not text and not img:
                continue
            tips.append({
                "text": text,
                "img": f"{APPSAMPLE_CDN}{img}?height=600&quality=85" if img else "",
                "thumb": f"{APPSAMPLE_CDN}{img}?aspect_ratio=1:1&height=90&quality=85" if img else "",
                "votes": c.get("vote") or 0,
                "date": (c.get("time") or "")[:10],
            })
            if len(tips) >= MAX_TIPS:
                break
        summary = ((data.get("summary") or {}).get("content") or "").strip()
        # сводка приходит только по-английски — в русском интерфейсе её не показываем
        if bool(_CYR.search(summary)) != (self.lang == "ru"):
            summary = ""
        return {"summary": summary, "tips": tips} if (tips or summary) else {}
