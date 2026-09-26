"""Автоматическая отметка собранного — по факту сбора, а не «пробежал мимо».

Что именно собрано, понимаем по данным карты: у каждой точки HoYoLAB есть
категория, а категория говорит, что это за объект (сундук, окулус, фея…).
Отмечаем независимо от того, включён ли слой на карте.

Когда объект считается собранным:
  - сундук — игрок НАЖАЛ клавишу взаимодействия (F) рядом с неоткрытым сундуком
    (если есть эталон подсказки «Открыть» — она ещё и должна была быть на экране);
  - окулус и прочие «ценные предметы» — их значок был на мини-карте и ПРОПАЛ,
    пока игрок был рядом (подобрал касанием);
  - телепорт / статуя — активируются касанием: игрок подошёл вплотную;
  - фея / испытание — по хоткею Ctrl+Alt+M (их точка — старт, а не награда).

Плюс «память» по подсказке «Открыть»: стоишь вплотную к точке сундука, а
подсказки нет — «вероятно собран»; подсказка у «вероятного» — отметка снимается.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from .mapindex import Candidate, MapIndex

# kind -> (эмодзи, название для журнала)
KINDS = {
    "chest": ("🧰", "сундук"),
    "valuable": ("🔮", "окулус/ценность"),
    "seelie": ("🧚", "фея"),
    "challenge": ("⏱", "испытание"),
    "teleport": ("📍", "телепорт"),
    "statue": ("🗿", "статуя"),
}

# Сундуки (мировые единицы / секунды).
CHEST_INTERACT = 20   # нажал F в этом радиусе от сундука — открыл его
CHEST_OCR_NEAR = 25   # у несобранного сундука ближе этого — читаем плашку подбора
PROMPT_RECENT_S = 3.0 # подсказка «Открыть» должна была быть не раньше, чем столько назад
CHEST_NEAR = 12       # в этом радиусе подсказка относится к сундуку
CHEST_CLOSE = 6       # вплотную: если тут долго нет подсказки — сундука нет
ABSENT_S = 4.0        # сколько стоять вплотную без подсказки, чтобы решить «нет»

# Окулусы/ценности: значок на мини-карте (оценка 0..1 из PositionTracker).
ICON_PRESENT = 0.8    # выше — значок есть
ICON_ABSENT = 0.35    # ниже — значка нет
ICON_PRESENT_N = 2    # сколько кадров значок должен быть виден
ICON_ABSENT_N = 3     # сколько кадров подряд его нет, чтобы засчитать сбор
ICON_NEAR = 25        # игрок должен был подойти хотя бы на столько
WATCH_RADIUS = 170    # за значками каких точек следим (≈ радиус мини-карты)
VALUABLE_OCR_NEAR = 40  # окулус «Получено» сверяем с точками в этом радиусе


def name_stem(name: str) -> str:
    """Основа названия для сверки с OCR: всё первое слово без окончания
    множественного числа: «Геокулы» -> «геокул», «Анемокулы» -> «анемокул».
    Короче нельзя: «анемо» совпало бы с «Печать Анемо» из сундука."""
    word = name.lower().replace("ё", "е").split()[0] if name.strip() else ""
    if word.endswith(("ы", "и")) and len(word) > 5:
        word = word[:-1]
    return word if len(word) >= 5 else ""


@dataclass
class Action:
    action: str       # collected | probable | present | seen
    cand: Candidate
    kind: str
    reason: str


@dataclass
class Rule:
    radius: float     # мировые единицы
    dwell_s: float    # сколько нужно пробыть в радиусе


# Правила по умолчанию (включение — settings["auto_rules"][kind]["on"]).
# radius/dwell_s — для правил «по касанию»: телепорты, статуи и окулусы, у
# которых значок на мини-карте не удалось отследить.
DEFAULT_RULES: dict[str, dict] = {
    "teleport": {"on": True, "radius": 25, "dwell_s": 0.0},
    "statue": {"on": True, "radius": 25, "dwell_s": 0.0},
    "valuable": {"on": True, "radius": 8, "dwell_s": 0.8},
    "chest": {"on": True, "radius": CHEST_INTERACT, "dwell_s": 0.0},
    "seelie": {"on": False, "radius": 15, "dwell_s": 2.0},
    "challenge": {"on": False, "radius": 15, "dwell_s": 3.0},
}


def classify(name: str, group: str) -> str | None:
    """Категория HoYoLAB -> тип собираемого объекта (или None — не собирается)."""
    n = name.lower()
    if n == "точка телепортации":
        return "teleport"
    if n == "статуя семи архонтов":
        return "statue"
    if "сундук" in n:
        return "chest"
    if n in ("фея", "тёплая фея", "фея электро"):
        return "seelie"
    if n in ("испытание на время", "испытание воина", "мини-загадка",
             "загадка с факелами", "элементальный монумент"):
        return "challenge"
    if group == "Ценные предметы":
        return "valuable"
    return None


class AutoMarker:
    def __init__(self, index: MapIndex, labels: list[dict], rules: dict | None = None) -> None:
        self.index = index
        self.kind_of: dict[int, str] = {}
        self.name_of: dict[int, str] = {}
        for l in labels:
            self.name_of[l["id"]] = l["name"]
            k = classify(l["name"], l.get("group", ""))
            if k:
                self.kind_of[l["id"]] = k
        self.labels_by_kind: dict[str, tuple[int, ...]] = {}
        for lid, k in self.kind_of.items():
            self.labels_by_kind[k] = self.labels_by_kind.get(k, ()) + (lid,)
        self.set_rules(rules)
        self._since: dict[str, float] = {}   # point_id -> когда игрок вошёл в радиус
        self._chest: dict[str, float] = {}   # point_id -> с какого момента стоим вплотную
        self._seen_present: set[str] = set()
        self._icon: dict[str, dict] = {}     # point_id -> история значка на мини-карте

    def register_label(self, label_id: int, name: str, kind: str) -> None:
        """Дополнительная категория (свои точки) с заданным типом."""
        self.name_of[label_id] = name
        self.kind_of[label_id] = kind
        if label_id not in self.labels_by_kind.get(kind, ()):
            self.labels_by_kind[kind] = self.labels_by_kind.get(kind, ()) + (label_id,)

    def set_rules(self, rules: dict | None) -> None:
        merged = {k: dict(v) for k, v in DEFAULT_RULES.items()}
        for k, v in (rules or {}).items():
            if k in merged and isinstance(v, dict):
                merged[k].update(v)
        self.rules = {k: Rule(float(v["radius"]), float(v["dwell_s"]))
                      for k, v in merged.items() if v.get("on")}

    def kind(self, label_id: int) -> str | None:
        return self.kind_of.get(label_id)

    def describe(self, label_id: int) -> str:
        k = self.kind_of.get(label_id)
        emoji = KINDS[k][0] if k else "✓"
        return f"{emoji} {self.name_of.get(label_id, label_id)}"

    def reset(self) -> None:
        self._since.clear()
        self._chest.clear()
        self._icon.clear()

    # ---------- сундук: нажатие F ----------
    def on_interact(self, x: float, y: float, collected: set[str],
                    prompt_recent: bool | None) -> Action | None:
        """Игрок нажал клавишу взаимодействия. Открыл сундук рядом?

        prompt_recent: None — эталона подсказки нет (верим нажатию рядом);
        True/False — была ли подсказка «Открыть» только что.
        """
        if "chest" not in self.rules or prompt_recent is False:
            return None
        labels = self.labels_by_kind.get("chest", ())
        cands = self.index.candidates(labels, x, y, collected, self.rules["chest"].radius)
        if not cands:
            return None
        return Action("collected", cands[0], "chest", "открыт (F)")

    def chest_near(self, x: float, y: float, collected: set[str],
                   radius: float = CHEST_OCR_NEAR) -> Candidate | None:
        """Ближайший несобранный сундук в радиусе (для чтения плашки подбора)."""
        if "chest" not in self.rules:
            return None
        cands = self.index.candidates(self.labels_by_kind.get("chest", ()), x, y, collected, radius)
        return cands[0] if cands else None

    # ---------- окулусы: за какими значками следить ----------
    def watch_points(self, x: float, y: float, collected: set[str]) -> list[tuple[str, float, float]]:
        """Несобранные ценности в пределах мини-карты — где проверять значок."""
        if "valuable" not in self.rules:
            return []
        labels = self.labels_by_kind.get("valuable", ())
        out = []
        for c in self.index.candidates(labels, x, y, collected, WATCH_RADIUS):
            _, px, py = self.index.by_id[c.point_id]
            out.append((c.point_id, px, py))
        return out

    # ---------- каждая позиция ----------
    def valuables_near(self, x: float, y: float, collected: set[str],
                       radius: float = VALUABLE_OCR_NEAR) -> list[Candidate]:
        """Несобранные окулусы/ценности рядом — для сверки со списком «Получено»."""
        if "valuable" not in self.rules:
            return []
        return self.index.candidates(self.labels_by_kind.get("valuable", ()), x, y,
                                     collected, radius)

    def match_pickup(self, line: str, cands: list[Candidate]) -> Candidate | None:
        """Строка «Получено» ↔ точка рядом: «Геокул ×1» -> ближайший «Геокулы»."""
        for c in cands:                               # ближайшие первыми
            stem = name_stem(self.name_of.get(c.label_id, ""))
            if stem and stem in line:
                return c
        return None

    def update(self, x: float, y: float, collected: set[str],
               prompts: dict | None = None, probable: set[str] | None = None,
               icons: dict | None = None, now: float | None = None,
               valuables_by_pickup: bool = False) -> list[Action]:
        """Вызывать на каждую надёжную позицию. Возвращает, что сделать с точками.

        prompts — подсказки в кадре ({"open": 0.9}) или None (эталона нет);
        icons   — {point_id: 0..1} наличие значков на мини-карте или None.
        """
        now = time.monotonic() if now is None else now
        out: list[Action] = []
        # окулусы по списку «Получено» (OCR) надёжнее: «коснулся» не знает высоты
        # (окулус над головой), значок мини-карты — ненадёжен
        self._touch(x, y, collected, icons, now, out, skip_valuable=valuables_by_pickup)
        if icons is not None and not valuables_by_pickup:
            self._icons(x, y, collected, icons, out)
        if prompts is not None and "chest" in self.rules:
            self._chest_memory(x, y, collected, probable or set(), prompts, now, out)
        return out

    def _touch(self, x, y, collected, icons, now, out, skip_valuable=False) -> None:
        """Телепорты/статуи — подошёл; окулусы — только если нет OCR и значка."""
        inside: set[str] = set()
        for kind, rule in self.rules.items():
            if kind == "chest" or (kind == "valuable" and skip_valuable):
                continue                          # сундуки — по F; окулусы — по «Получено»
            labels = self.labels_by_kind.get(kind)
            if not labels:
                continue
            cands = self.index.candidates(labels, x, y, collected, rule.radius)
            if kind == "valuable" and icons is not None:
                # значок этой точки виден на мини-карте — решает правило значков;
                # если игра значок не показывает — работает правило касания
                cands = [c for c in cands
                         if self._icon.get(c.point_id, {}).get("present", 0) < ICON_PRESENT_N]
            ready = None
            for c in cands:                      # ближайшие первыми
                inside.add(c.point_id)
                t0 = self._since.setdefault(c.point_id, now)
                if ready is None and now - t0 >= rule.dwell_s:
                    ready = c
            if ready is not None:
                out.append(Action("collected", ready, kind, "подошёл"))
                for c in cands:                  # за раз — один объект типа
                    self._since[c.point_id] = now
        for pid in list(self._since):
            if pid not in inside:
                del self._since[pid]

    def _icons(self, x, y, collected, icons, out) -> None:
        """Окулус: значок был на мини-карте и пропал, пока игрок рядом."""
        for pid in set(icons) | set(self._icon):
            if pid in collected:
                self._icon.pop(pid, None)
                continue
            lid, px, py = self.index.by_id[pid]
            dist = ((px - x) ** 2 + (py - y) ** 2) ** 0.5
            if pid not in icons:
                # под стрелкой игрока / у края мини-карты оценки нет: помним
                # историю, пока точка не ушла за пределы мини-карты
                if dist > WATCH_RADIUS:
                    del self._icon[pid]
                else:
                    self._icon[pid]["min_d"] = min(self._icon[pid]["min_d"], dist)
                continue
            score = icons[pid]
            st = self._icon.setdefault(pid, {"present": 0, "absent": 0, "min_d": dist})
            st["min_d"] = min(st["min_d"], dist)
            if score >= ICON_PRESENT:
                st["present"] += 1
                st["absent"] = 0
            elif score <= ICON_ABSENT:
                st["absent"] += 1
            # между порогами — неясно, счётчики не трогаем
            if (st["present"] >= ICON_PRESENT_N and st["absent"] >= ICON_ABSENT_N
                    and st["min_d"] <= ICON_NEAR):
                out.append(Action("collected", Candidate(pid, lid, dist), "valuable",
                                  "значок пропал с мини-карты"))
                del self._icon[pid]

    def _chest_memory(self, x, y, collected, probable, prompts, now, out) -> None:
        """Сундуки по подсказке «Открыть»: на месте / вероятно собран."""
        labels = self.labels_by_kind.get("chest", ())
        open_now = "open" in prompts
        near_all = self.index.candidates(labels, x, y, set(), CHEST_NEAR)
        if open_now and near_all:
            c = near_all[0]
            if c.point_id in probable:
                out.append(Action("present", c, "chest", "подсказка «Открыть» — сундук на месте"))
            elif c.point_id not in collected and c.point_id not in self._seen_present:
                self._seen_present.add(c.point_id)
                out.append(Action("seen", c, "chest", "сундук на месте"))
        close = [c for c in near_all if c.point_id not in collected and c.dist <= CHEST_CLOSE]
        close_ids = {c.point_id for c in close}
        for pid in list(self._chest):
            if pid not in close_ids or open_now or pid in self._seen_present:
                del self._chest[pid]
        if open_now:
            return
        for c in close:
            if c.point_id in self._seen_present:
                continue                          # видели на месте — не «пропал»
            t0 = self._chest.setdefault(c.point_id, now)
            if now - t0 >= ABSENT_S:
                out.append(Action("probable", c, "chest", "не найден на месте"))
                del self._chest[c.point_id]
                return

    # ---------- по хоткею ----------
    def all_collectible_labels(self) -> tuple[int, ...]:
        return tuple(self.kind_of)
