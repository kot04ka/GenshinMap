"""Пещеры: границы этажей из таблицы appsample, входы, путь по картинке этажа."""
import json

import cv2
import numpy as np

from genshinmap.backend.maps import floors as fl

KX, KY, BY = fl.KX, fl.KY, fl.BY
B = 0.25                    # сдвиг appsample по долготе для этой «части карты»


def _bounds(x0, y0, x1, y1):
    return {"west": KX * x0 + B, "east": KX * x1 + B, "north": KY * y0 + BY, "south": KY * y1 + BY}


def _world():
    labels = [{"id": 1, "name": "Богатый сундук"}, {"id": 410, "name": "Пещера"}]
    points = [
        {"id": 10, "label_id": 1, "x": 50, "y": 50, "floor": 100},     # в маленькой пещере
        {"id": 20, "label_id": 1, "x": 500, "y": 500, "floor": 200},   # в большой зоне
        {"id": 30, "label_id": 410, "x": 5, "y": 50},                  # вход маленькой пещеры
        {"id": 40, "label_id": 410, "x": 900, "y": 900},               # вход большой зоны
    ]
    appsample = {"10": [1010, "o1"], "20": [2020, "o1"]}
    lng = {1010: KX * 50 + B, 2020: KX * 500 + B}
    table = {"2": [
        {"id": 100, "sid": 1, "name": "B1", "img": "u1", "bounds": _bounds(0, 0, 100, 100)},
        {"id": 200, "sid": 2, "name": "B1", "img": "u2", "bounds": _bounds(-100, -100, 1000, 1000)},
        {"id": 300, "sid": 3, "name": "B1", "img": "u3", "bounds": _bounds(0, 0, 10, 10)},  # без точек
    ]}
    return table, points, labels, appsample, lng


def test_build_floors_bounds_and_entrances():
    out = {f["id"]: f for f in fl.build_floors(2, *_world())}
    assert set(out) == {100, 200}                      # этаж без наших точек пропущен
    assert out[100]["bbox"] == [0.0, 0.0, 100.0, 100.0]
    # вход 30 стоит и в маленькой пещере, и в большой зоне — достаётся маленькой
    assert out[100]["entrances"] == ["30"]
    assert out[200]["entrances"] == ["40"]


def _floor_image(tmp_path):
    """Этаж 100×100 ед.: проход буквой «Г» — слева сверху вниз, затем вправо."""
    a = np.zeros((200, 200), np.uint8)
    a[0:200, 0:40] = 255
    a[160:200, 0:200] = 255
    img = np.dstack([np.full_like(a, 90)] * 3 + [a])
    path = tmp_path / "floor_img" / "100.png"
    path.parent.mkdir(parents=True)
    cv2.imwrite(str(path), img)
    return path


def test_floor_nav_follows_corridor(tmp_path):
    floor = {"id": 100, "bbox": [0, 0, 100, 100]}
    nav = fl.FloorNav(floor, _floor_image(tmp_path))
    path = nav.plan((10, 5), (95, 90))
    assert path[0] == (10, 5) and path[-1] == (95, 90)
    # путь не срезает угол через пустоту: все изломы — в нарисованной части
    for x, y in path[1:-1]:
        assert x <= 22 or y >= 78, (x, y)


def test_cave_route_is_json_ready(tmp_path):
    _floor_image(tmp_path)
    floor = {"id": 100, "group": 1, "name": "B1", "img": "", "bbox": [0, 0, 100, 100],
             "entrances": ["30"]}
    pts = {"10": (95.0, 90.0), "30": (10.0, 2.0)}
    r = fl.cave_route(tmp_path, [floor], pts, "10", 100)
    assert r and r["entrance"] == "30" and not r["approx"]
    json.dumps(r)                                     # numpy-числа в пути ломали отправку на карту
    assert r["length"] > 150                         # обходит угол, а не по прямой (~120)
