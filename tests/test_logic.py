"""Логика без экрана: подсказки, выбор сундука, путь, версии."""
import json

import numpy as np
import pytest

from genshinmap.automark import AutoMarker, name_stem
from genshinmap.mapindex import MapIndex
from genshinmap.navigation import NavGrid, lookahead, nearest_index
from genshinmap.updater import parse_version
from genshinmap.vision.prompt_detector import parse_prompt_lines

LABELS = [
    {"id": 17, "name": "Обычный сундук", "group": "Сундуки"},
    {"id": 44, "name": "Богатый сундук", "group": "Сундуки"},
    {"id": 3, "name": "Анемокулы", "group": "Ценные предметы"},
]


@pytest.fixture
def marker(tmp_path):
    pts = [
        {"id": 1, "label_id": 17, "x": 100.0, "y": 100.0},     # обычный — ближе к игроку
        {"id": 2, "label_id": 44, "x": 110.0, "y": 100.0},     # богатый — чуть дальше
        {"id": 3, "label_id": 3, "x": 300.0, "y": 300.0},
    ]
    f = tmp_path / "points.json"
    f.write_text(json.dumps(pts), encoding="utf-8")
    return AutoMarker(MapIndex(f), LABELS)


# ---------- подсказки ----------
@pytest.mark.parametrize("lines,rarity", [
    (["Богатый сундук"], "богат"),
    (["Морковь", "Обычный сундук"], "обычн"),
    (["Драгоценный сундук"], "драгоц"),
    (["Сундук"], ""),
    (["Oбычный cундук"], "обычн"),            # латиница вместо кириллицы (ошибка OCR)
])
def test_prompt_chest(lines, rarity):
    assert parse_prompt_lines(lines) == {"open": 1.0, "rarity": rarity}


@pytest.mark.parametrize("lines", [["Морковь", "Капуста"], ["Обычная руда"], []])
def test_prompt_not_chest(lines):
    assert parse_prompt_lines(lines) == {}


# ---------- выбор сундука ----------
def test_chest_by_prompt_prefers_rarity(marker):
    near = marker.chest_near(102, 100, set())
    assert near.point_id == "1"
    assert marker.chest_by_prompt(102, 100, set(), "богат").point_id == "2"
    assert marker.chest_by_prompt(102, 100, set(), "").point_id == "1"
    # богатый уже собран — берём, что есть
    assert marker.chest_by_prompt(102, 100, {"2"}, "богат").point_id == "1"


def test_chest_memory_uses_rarity(marker):
    acts = marker.update(108, 100, set(), prompts={"open": 1.0, "rarity": "обычн"})
    assert [(a.action, a.cand.point_id) for a in acts] == [("seen", "1")]


def test_name_stem():
    assert name_stem("Геокулы") == "геокул"
    assert name_stem("Анемокулы") == "анемокул"
    assert name_stem("Фея") == ""


# ---------- путь ----------
def test_lookahead_and_nearest():
    path = [(0, 0), (100, 0), (100, 100)]
    assert nearest_index(path, 90, 50) == 1
    (ax, ay), rest, dev = lookahead(path, 50, 5, ahead=35)
    assert (ax, ay) == pytest.approx((85, 0))
    assert rest == pytest.approx(150)
    assert dev == pytest.approx(5)


def test_astar_goes_around_wall():
    cost = np.ones((20, 20), np.float32)
    cost[0:15, 10] = np.inf                      # стена с проходом внизу
    cells = NavGrid._astar(cost, (2, 2), (2, 17))
    assert cells[0] == (2, 2) and cells[-1] == (2, 17)
    assert all(np.isfinite(cost[c]) for c in cells)
    assert max(c[0] for c in cells) >= 15        # обошёл снизу


def test_parse_version():
    assert parse_version("v1.0.10") > parse_version("1.0.9")
    assert parse_version("мусор") == (0,)


# ---------- язык ----------
def test_tr_english():
    from genshinmap import i18n

    i18n.set_lang("en")
    try:
        assert i18n.tr("📍 Отслеживать") == "📍 Track"
        assert i18n.tr("  Журнал ") == "  Log "
        # фраза внутри строки с числами
        assert i18n.tr("Точек: 12 · Собрано: 3") == "Points: 12 · Collected: 3"
        assert i18n.tr("already English") == "already English"
    finally:
        i18n.set_lang("ru")
    assert i18n.tr("📍 Отслеживать") == "📍 Отслеживать"


@pytest.mark.parametrize("lines,rarity", [
    (["Exquisite Chest"], "богат"),
    (["Carrot", "Common Chest"], "обычн"),
    (["Remarkable Chest"], "удивит"),
])
def test_prompt_chest_english(lines, rarity):
    assert parse_prompt_lines(lines, "en") == {"open": 1.0, "rarity": rarity}
    assert parse_prompt_lines(["Carrot", "Radish"], "en") == {}


def test_name_stem_english():
    assert name_stem("Anemoculi", "en") == "anemocul"
    assert name_stem("Anemoculus", "en") == "anemoculus"


# ---------- «нет на месте» ----------
def test_absence_only_for_plain_surface_chests(tmp_path):
    pts = [
        {"id": 1, "label_id": 17, "x": 0.0, "y": 0.0},
        {"id": 2, "label_id": 17, "x": 50.0, "y": 0.0, "layer": 1},        # пещера
        {"id": 3, "label_id": 69, "x": 100.0, "y": 0.0},                   # зарытый — после загадки
    ]
    f = tmp_path / "points.json"
    f.write_text(json.dumps(pts), encoding="utf-8")
    labels = LABELS + [{"id": 69, "name": "Зарытый сундук", "group": "Сокровища с загадкой"}]
    m = AutoMarker(MapIndex(f), labels)
    assert m.absence_counts("1", 17)
    assert not m.absence_counts("2", 17)
    assert not m.absence_counts("3", 69)
    # без проверенного чтения подсказок «нет на месте» не выводим совсем
    acts = m.update(1, 0, set(), prompts={}, now=0.0, absence=False)
    acts += m.update(1, 0, set(), prompts={}, now=10.0, absence=False)
    assert not [a for a in acts if a.action == "probable"]
    acts = m.update(1, 0, set(), prompts={}, now=20.0)
    acts += m.update(1, 0, set(), prompts={}, now=30.0)
    assert [a.cand.point_id for a in acts if a.action == "probable"] == ["1"]


# ---------- что сейчас в игре ----------
def test_classify_scene():
    from genshinmap.vision.position_service import classify_scene

    assert classify_scene(np.full((135, 240), 5, np.uint8)) == "loading"
    rng = np.random.default_rng(0)
    frame = rng.integers(40, 200, (135, 240)).astype(np.uint8)
    assert classify_scene(frame) == "menu"
    frame[:17] = 2
    frame[-17:] = 2                                   # чёрные полосы (~12%) — катсцена
    assert classify_scene(frame) == "cutscene"


# ---------- фоновый поиск позиции ----------
def test_slow_search_runs_in_background():
    import time as _t

    from genshinmap.vision.position_service import PositionService
    from genshinmap.vision.position_tracker import Position

    class FakeTracker:
        last, last_t = None, 0.0

        def locate_slow(self, sq, ui_h, bgr, hint):
            _t.sleep(0.3)
            return Position(10.0, 20.0, 0.8, 1.66, margin=0.2)

    ps = PositionService()
    tr = FakeTracker()
    sq = np.zeros((20, 20), np.uint8)
    bgr = np.zeros((20, 20, 3), np.uint8)
    t0 = _t.monotonic()
    assert ps._slow_step(tr, sq, 1080, bgr) is None          # запустили — сразу вернулись
    assert _t.monotonic() - t0 < 0.1
    assert ps._slow_step(tr, sq, 1080, bgr) is None          # ещё ищет
    _t.sleep(0.4)
    pos = ps._slow_step(tr, sq, 1080, bgr)                   # готово — забрали
    assert pos is not None and (pos.x, pos.y) == (10.0, 20.0)
    # результат для другой карты (другого трекера) не используется
    ps._slow_step(tr, sq, 1080, bgr)
    _t.sleep(0.4)
    assert ps._slow_step(FakeTracker(), sq, 1080, bgr) is None


# ---------- задания у сундуков ----------
def test_quest_mention_and_find():
    from genshinmap.quests import QuestIndex, quest_mention

    m = quest_mention(["Сундук появится после прохождения квеста «Мечта Сохейля»."])
    assert m and m["names"] == ["Мечта Сохейля"]
    assert quest_mention(["Убивайте врагов — квеста не требуется"]) is None
    assert quest_mention(["Под водой у телепорта"]) is None
    qi = QuestIndex(".")
    qi.items = [{"pid": "5", "x": 0, "y": 0, "names": ["Мечта Сохейля"]}]
    assert qi.find("мечта сохейля")["pid"] == "5"
    assert qi.find("Совсем другое задание") is None
