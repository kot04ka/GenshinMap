"""Области интерфейса при разных разрешениях и форматах экрана."""
import pytest

from genshinmap.backend.vision.layout import (
    frac_from_region,
    region_from_frac,
    ui_scale,
)

MINIMAP = {"left": 0.032292, "top": 0.018519, "width": 0.109375, "height": 0.194444}


def rect(w, h, x=0, y=0):
    return {"left": x, "top": y, "width": w, "height": h}


def test_1080p_matches_old_fractions():
    for anchor in ("lt", "lc", "cc", "rb"):
        r = region_from_frac(MINIMAP, rect(1920, 1080), anchor)
        assert (r["left"], r["top"], r["width"], r["height"]) == (62, 20, 210, 210)


def test_1440p_scales_proportionally():
    r = region_from_frac(MINIMAP, rect(2560, 1440), "lt")
    assert (r["left"], r["top"], r["width"]) == (83, 27, 280)


def test_ultrawide_minimap_keeps_size_and_corner():
    r = region_from_frac(MINIMAP, rect(2560, 1080), "lt")
    assert (r["left"], r["top"], r["width"], r["height"]) == (62, 20, 210, 210)


def test_ultrawide_center_and_right_anchors():
    prompt = {"left": 0.55, "top": 0.35, "width": 0.30, "height": 0.40}
    r = region_from_frac(prompt, rect(2560, 1080), "cc")
    assert r["left"] == 1280 + round(0.05 * 1920)          # от центра, а не от доли ширины
    uid = {"left": 0.84, "top": 0.955, "width": 0.16, "height": 0.045}
    r = region_from_frac(uid, rect(2560, 1080), "rb")
    assert r["left"] + r["width"] == 2560                   # прижат к правому краю


def test_windowed_offset_on_second_monitor():
    r = region_from_frac(MINIMAP, rect(1280, 720, x=1920 + 100, y=50), "lt")
    assert r["left"] == 1920 + 100 + round(0.032292 * 1280)
    assert r["top"] == 50 + round(0.018519 * 720)


def test_16_10_scales_by_width():
    assert ui_scale(1920, 1200) == pytest.approx(1.0)
    r = region_from_frac(MINIMAP, rect(1920, 1200), "lt")
    assert r["width"] == 210


@pytest.mark.parametrize("anchor", ["lt", "lc", "cc", "rb"])
@pytest.mark.parametrize("size", [(1920, 1080), (2560, 1080), (1280, 720), (1920, 1200)])
def test_roundtrip(anchor, size):
    w, h = size
    r = region_from_frac(MINIMAP, rect(w, h), anchor)
    back = frac_from_region(r["left"], r["top"], r["width"], r["height"], w, h, anchor)
    for k, v in MINIMAP.items():
        assert back[k] == pytest.approx(v, abs=2e-3)
