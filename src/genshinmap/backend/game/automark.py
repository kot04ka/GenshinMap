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

import math
import time
from dataclasses import dataclass

from genshinmap.backend.maps.mapindex import Candidate, MapIndex

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
# Сундуки, которые появляются только после условия (загадка, испытание) — их
# отсутствие ничего не значит, по «нет на месте» не отмечаем.
CONDITIONAL_GROUPS = ("Сокровища с загадкой",)
CONDITIONAL_NAMES = ("3 сундука",)

# Окулусы/ценности: значок на мини-карте (оценка 0..1 из PositionTracker).
ICON_PRESENT = 0.8    # выше — значок есть
ICON_ABSENT = 0.35    # ниже — значка нет
ICON_PRESENT_N = 2    # сколько кадров значок должен быть виден
ICON_ABSENT_N = 3     # сколько кадров подряд его нет, чтобы засчитать сбор
ICON_NEAR = 25        # игрок должен был подойти хотя бы на столько
WATCH_RADIUS = 170    # за значками каких точек следим (≈ радиус мини-карты)
VALUABLE_OCR_NEAR = 40  # окулус «Получено» сверяем с точками в этом радиусе
# Окулус собирается касанием: прошёл через его место, а «Получено» не пришло — его уже
# нет. Высоты мы не знаем (окулус бывает на крыше над тобой) — поэтому «вероятно».
VALUABLE_TOUCH = 2.5    # прошёл так близко к месту окулуса
VALUABLE_LEAVE = 8.0    # и отошёл дальше этого
VALUABLE_WAIT_S = 3.0   # «Получено» за это время не пришло


def name_stem(name: str, lang: str = "ru") -> str:
    """Основа названия для сверки с OCR: всё первое слово без окончания
    множественного числа: «Геокулы» -> «геокул», «Анемокулы» -> «анемокул»;
    по-английски «Anemoculi» -> «anemocul» (в «Получено» — «Anemoculus»).
    Короче нельзя: «анемо» совпало бы с «Печать Анемо» из сундука."""
    word = name.lower().replace("ё", "е").split()[0] if name.strip() else ""
    if lang == "en":
        if word.endswith("i") and len(word) > 5:
            word = word[:-1]
    elif word.endswith(("ы", "и")) and len(word) > 5:
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
        self.name_of: dict[int, str] = {}          # русские (логика, редкость сундука)
        self.group_of: dict[int, str] = {l["id"]: l.get("group", "") for l in labels}
        self.display_of: dict[int, str] = {}       # на языке интерфейса (журнал, HUD)
        self.match_of: dict[int, str] = {}         # на языке игры (сверка с OCR)
        self.game_lang = "ru"
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
        self._passed: dict[str, float] = {}  # окулус: point_id -> когда прошли через его место

    def register_label(self, label_id: int, name: str, kind: str) -> None:
        """Дополнительная категория (свои точки) с заданным типом."""
        self.name_of[label_id] = name
        self.display_of[label_id] = self.match_of[label_id] = name
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
        name = self.display_of.get(label_id) or self.name_of.get(label_id, label_id)
        return f"{emoji} {name}"

    def set_names(self, display: dict[int, str], match: dict[int, str], game_lang: str) -> None:
        """Имена категорий для показа и для сверки с текстом игры."""
        self.display_of.update(display)
        self.match_of.update(match)
        self.game_lang = game_lang

    def reset(self) -> None:
        self._since.clear()
        self._chest.clear()
        self._icon.clear()
        self._passed.clear()

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

    def chest_by_prompt(self, x: float, y: float, collected: set[str], rarity: str,
                        radius: float = CHEST_INTERACT) -> Candidate | None:
        """Сундук перед игроком по подсказке «F ▶ Богатый сундук»: ближайший той же
        редкости; если такого рядом нет — просто ближайший."""
        if "chest" not in self.rules:
            return None
        cands = self.index.candidates(self.labels_by_kind.get("chest", ()), x, y, collected, radius)
        if rarity:
            same = [c for c in cands if self._rarity_ok(c.label_id, rarity)]
            if same:
                return same[0]
        return cands[0] if cands else None

    def _rarity_ok(self, label_id: int, rarity: str) -> bool:
        return self.name_of.get(label_id, "").lower().startswith(rarity)

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
            stem = name_stem(self.match_of.get(c.label_id) or self.name_of.get(c.label_id, ""),
                             self.game_lang)
            if stem and stem in line:
                return c
        return None

    def update(self, x: float, y: float, collected: set[str],
               prompts: dict | None = None, probable: set[str] | None = None,
               icons: dict | None = None, now: float | None = None,
               valuables_by_pickup: bool = False, absence: bool = True,
               absence_marked: set[str] | None = None) -> list[Action]:
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
        if valuables_by_pickup and absence and "valuable" in self.rules:
            self._valuable_absence(x, y, collected, now, out)
        if prompts is not None and "chest" in self.rules:
            # отмеченные «по отсутствию» проверяем снова: подсказка есть — сундук на месте
            recheck = (probable or set()) | (absence_marked or set())
            self._chest_memory(x, y, collected, recheck, prompts, now, out, absence)
        return out

    def _valuable_absence(self, x, y, collected, now, out) -> None:
        """Окулус: прошёл через его место, «Получено» не пришло — вероятно, собран раньше."""
        labels = self.labels_by_kind.get("valuable", ())
        for c in self.index.candidates(labels, x, y, collected, VALUABLE_TOUCH):
            if not self.index.layer_of.get(str(c.point_id), 0):   # в пещерах уровень не знаем
                self._passed.setdefault(c.point_id, now)
        for pid, t0 in list(self._passed.items()):
            if pid in collected:
                del self._passed[pid]
                continue
            pt = self.index.by_id.get(pid)
            if pt is None:
                del self._passed[pid]
                continue
            if math.hypot(pt[1] - x, pt[2] - y) >= VALUABLE_LEAVE and now - t0 >= VALUABLE_WAIT_S:
                del self._passed[pid]
                out.append(Action("probable", Candidate(pid, pt[0], math.hypot(pt[1] - x, pt[2] - y)),
                                  "valuable", "прошёл через место — «Получено» не было"))

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

    def absence_counts(self, point_id: str, label_id: int) -> bool:
        """Можно ли по отсутствию подсказки у этой точки судить, что сундук собран:
        только поверхность и только сундуки, которые стоят всегда (не после загадки)."""
        if self.index.layer_of.get(str(point_id), 0):
            return False                  # пещера/под водой/этаж: стоим не на том уровне
        return (self.group_of.get(label_id, "") not in CONDITIONAL_GROUPS
                and self.name_of.get(label_id, "") not in CONDITIONAL_NAMES)

    def _chest_memory(self, x, y, collected, probable, prompts, now, out, absence=True) -> None:
        """Сундуки по подсказке «Открыть»: на месте / вероятно собран."""
        labels = self.labels_by_kind.get("chest", ())
        open_now = "open" in prompts
        near_all = self.index.candidates(labels, x, y, set(), CHEST_NEAR)
        if open_now and near_all:
            rarity = prompts.get("rarity") or ""
            same = [c for c in near_all if rarity and self._rarity_ok(c.label_id, rarity)]
            c = (same or near_all)[0]
            if c.point_id in probable:
                out.append(Action("present", c, "chest", "подсказка «Открыть» — сундук на месте"))
            elif c.point_id not in collected and c.point_id not in self._seen_present:
                self._seen_present.add(c.point_id)
                out.append(Action("seen", c, "chest", "сундук на месте"))
        # «нет на месте» — только если подсказки в этой сессии точно читались (absence),
        # только для подходящих сундуков; «вероятно собранный» — проверяем повторно
        close = [c for c in near_all
                 if absence and c.dist <= CHEST_CLOSE and self.absence_counts(c.point_id, c.label_id)
                 and (c.point_id not in collected or c.point_id in probable)]
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
