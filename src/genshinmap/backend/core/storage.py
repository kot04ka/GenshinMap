"""Хранилище прогресса: какие маркеры уже собраны.

Прогресс — это просто множество id маркеров. Храним в JSON рядом с проектом,
чтобы не терять между запусками.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

# data/progress.json в корне проекта
from genshinmap.backend.core.paths import PROJECT_ROOT

PROGRESS_PATH = PROJECT_ROOT / "data" / "progress.json"
UI_STATE_PATH = PROJECT_ROOT / "data" / "ui_state.json"
SETTINGS_PATH = PROJECT_ROOT / "data" / "settings.json"
OBSERVATIONS_PATH = PROJECT_ROOT / "data" / "observations.json"

# Значения настроек по умолчанию.
DEFAULT_SETTINGS: dict = {
    "hotkeys": {
        "mark_nearest": "<ctrl>+<alt>+m",
        "toggle_overlay": "<ctrl>+<alt>+o",
        "toggle_visible": "<ctrl>+<alt>+h",
        "bookmark": "<ctrl>+<alt>+b",
        "undo": "<ctrl>+<alt>+z",
        "stop_nav": "<ctrl>+<alt>+x",
        "toggle_hud": "<ctrl>+<alt>+g",
        "toggle_path": "<ctrl>+<alt>+p",
    },
    "max_markers": 1200,
    "overlay_opacity": 0.9,
    "overlay_size": [460, 320],
    # область мини-карты в ДОЛЯХ экрана (игрок = центр области); калибруется
    # в окне «Калибровка»
    "minimap": {                       # 62, 20, 210x210 при 1920x1080
        "left": 0.032292,
        "top": 0.018519,
        "width": 0.109375,
        "height": 0.194444,
    },
    # где всплывают подобранные предметы (доли экрана); по умолчанию — левая
    # середина экрана, уточняется в окне «Калибровка»
    "pickup_region": {
        "left": 0.0,
        "top": 0.30,
        "width": 0.32,
        "height": 0.45,
    },
    # масштаб мини-карты по картам {map_id: мир. единиц на пиксель @1080p};
    # подбирается автоматически при первом успешном определении позиции
    "minimap_scale": {},
    # радиус (мировые единицы), в котором авто-отметка ищет подобранную точку
    "auto_mark_radius": 60,
    # как часто обновлять позицию игрока, секунд
    "track_interval": 0.4,
    # где появляются подсказки взаимодействия («F Открыть») — правее центра
    "prompt_region": {
        "left": 0.55,
        "top": 0.35,
        "width": 0.30,
        "height": 0.40,
    },
    # авто-отметка по позиции (правила по типам — см. automark.DEFAULT_RULES)
    "auto_mark_enabled": True,
    "auto_rules": {},
    # клавиши взаимодействия (открыть сундук): нажатие рядом с сундуком = открыт
    "interact_keys": ["F"],
    # лёгкая запись отладки, пока идёт игра (debug/, ротация 5 сессий / 1 ГБ)
    "auto_record": True,
    # HUD навигации поверх игры (стрелка у мини-карты, подсказка, звук) — тест
    "hud_enabled": True,
    # что рисовать поверх игры (каждое можно выключить)
    "hud_path": True,          # путь на мини-карте
    "hud_ground": True,        # путь под ногами (примерно)
    "hud_compass": True,       # компас вверху экрана
    "hud_card": True,          # карточка с подсказкой и фото у цели
    "hud_toasts": True,        # всплывашки «отмечено»
    "auto_next": True,         # собрал сундук — вести к следующему самому
    "absence_mark": True,      # нет на месте во второй заход — считать собранным
    "absence_instant": True,   # сундука нет на месте — сразу собран
    "route_teleports": True,   # маршрут может предлагать телепорты
    "onboarded": False,        # окно первого запуска уже показано
    # язык интерфейса и язык игры (что читает OCR: «Получено», подсказки у сундука)
    "ui_lang": "ru",
    "game_lang": "ru",
    # аккаунт, чей прогресс сейчас активен (UID читается с экрана игры; None — ещё не видели)
    "active_uid": None,
    # запускать приложение с правами администратора (как Genshin) — см. main.py
    "run_as_admin": True,
    # примогемы за сундуки {категория: число или [типично, мин, макс]}; пусто —
    # значения по умолчанию из rewards.DEFAULT_PRIMOGEMS
    "primogems": {},
}


class ProgressStore:
    """Собранные точки.

    collected — всё, что считается собранным (скрывается «Скрыть собранные»);
    probable  — подмножество collected: «вероятно собрано» (приложение пришло
                к точке, а объекта там нет) — показывается со знаком «?», пока
                не подтвердишь.
    """

    def __init__(self, path: Path = PROGRESS_PATH) -> None:
        self.path = path
        self.collected: set[str] = set()
        self.probable: set[str] = set()
        self.load()

    def load(self) -> None:
        self.collected, self.probable = set(), set()
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.collected = set(data.get("collected", []))
                self.probable = set(data.get("probable", [])) & self.collected
            except (json.JSONDecodeError, OSError):
                pass

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"collected": sorted(self.collected), "probable": sorted(self.probable)}
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def unmark(self, marker_id: str) -> None:
        self.collected.discard(marker_id)
        self.probable.discard(marker_id)
        self.save()

    def toggle(self, marker_id: str) -> bool:
        """Клик по маркеру. «Вероятно» -> подтверждено; собрано -> снять.

        Возвращает новое состояние (True = собрано).
        """
        if marker_id in self.probable:
            self.probable.discard(marker_id)      # подтверждение
            collected = True
        elif marker_id in self.collected:
            self.collected.discard(marker_id)
            collected = False
        else:
            self.collected.add(marker_id)
            collected = True
        self.save()
        return collected

    def mark_collected(self, marker_id: str) -> None:
        self.collected.add(marker_id)
        self.probable.discard(marker_id)
        self.save()

    def mark_probable(self, marker_id: str) -> None:
        if marker_id in self.collected:          # уже точно собрано — не понижаем
            return
        self.collected.add(marker_id)
        self.probable.add(marker_id)
        self.save()

    def is_collected(self, marker_id: str) -> bool:
        return marker_id in self.collected


class ObservationStore:
    """Память наблюдений: что и когда приложение видело у каждой точки.

    {point_id: {"state": "present"|"opened"|"absent", "t": unix-время,
                "n": сколько раз, "src": откуда вывод}}
      present — объект на месте (видели подсказку «Открыть»);
      opened  — видели, как объект открыли/подобрали;
      absent  — пришли, а объекта нет.
    """

    def __init__(self, path: Path = OBSERVATIONS_PATH) -> None:
        self.path = path
        self.data: dict[str, dict] = {}
        if path.exists():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self.data = {}

    def record(self, point_id: str, state: str, src: str = "") -> None:
        import time as _time

        rec = self.data.get(point_id, {})
        n = rec.get("n", 0) + 1 if rec.get("state") == state else 1
        self.data[point_id] = {"state": state, "t": int(_time.time()), "n": n, "src": src}
        self.save()

    def get(self, point_id: str) -> dict | None:
        return self.data.get(point_id)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")


class UIStateStore:
    """Сохраняет состояние интерфейса между запусками.

    Хранит: текущую карту, включённые категории по каждой карте, позицию/зум
    просмотра по каждой карте, геометрию окна. Это и удобно, и разгружает комп —
    ничего не пересчитывается заново, восстанавливается ровно как было.
    """

    def __init__(self, path: Path = UI_STATE_PATH) -> None:
        self.path = path
        self.data: dict = {
            "current_map_id": None,
            "enabled": {},   # {map_id: [label_id, ...]}
            "view": {},      # {map_id: {"lat":..,"lng":..,"zoom":..}}
            "window": None,  # [x, y, w, h]
        }
        self.load()

    def load(self) -> None:
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                self.data.update(loaded)
            except (json.JSONDecodeError, OSError):
                pass

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # --- удобные аксессоры ---
    def get_current_map(self, default: int | None = None) -> int | None:
        return self.data.get("current_map_id") or default

    def set_current_map(self, map_id: int) -> None:
        self.data["current_map_id"] = map_id
        self.save()

    def get_enabled(self, map_id: int) -> list[int]:
        return self.data.get("enabled", {}).get(str(map_id), [])

    def get_view(self, map_id: int) -> dict | None:
        return self.data.get("view", {}).get(str(map_id))

    def set_map_state(self, map_id: int, enabled: list[int], view: dict | None,
                      extra: dict | None = None) -> None:
        self.data.setdefault("enabled", {})[str(map_id)] = enabled
        if view:
            self.data.setdefault("view", {})[str(map_id)] = view
        if extra is not None:
            self.data.setdefault("extra", {})[str(map_id)] = extra
        self.save()

    def get_extra(self, map_id: int) -> dict:
        """Прочее состояние карты: выбранный регион, «скрыть собранные», слежение."""
        return self.data.get("extra", {}).get(str(map_id), {})

    def set_window(self, geom: list[int]) -> None:
        self.data["window"] = geom
        self.save()

    def get_window(self) -> list[int] | None:
        return self.data.get("window")


class SettingsStore:
    """Настройки приложения (хоткеи, лимиты, оверлей, мини-карта).

    Хранятся в data/settings.json. Отсутствующие ключи берутся из DEFAULT_SETTINGS.
    """

    def __init__(self, path: Path = SETTINGS_PATH) -> None:
        self.path = path
        self.data: dict = copy.deepcopy(DEFAULT_SETTINGS)
        self.load()

    def load(self) -> None:
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return
            # аккуратно сливаем, чтобы новые ключи умолчаний не терялись
            for key, default in DEFAULT_SETTINGS.items():
                if key not in loaded:
                    continue
                if isinstance(default, dict) and isinstance(loaded[key], dict):
                    merged = dict(default)
                    merged.update(loaded[key])
                    self.data[key] = merged
                else:
                    self.data[key] = loaded[key]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value) -> None:
        self.data[key] = value
        self.save()

    def update(self, values: dict) -> None:
        self.data.update(values)
        self.save()

    def reset(self) -> None:
        self.data = copy.deepcopy(DEFAULT_SETTINGS)
        self.save()
