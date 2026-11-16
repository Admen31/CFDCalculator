"""Window-relative region maths: follows the window, DPI 100/125/150 %, monitors left of the primary."""
from dataclasses import astuple

import pytest

from cfdcalc.window import Region, Win, blank, pick, to_region, to_screen


def win(left=100, top=50, width=1200, height=800, dpi=96, hwnd=1):
    return Win(hwnd, "Trading 212", left, top, width, height, dpi)


@pytest.mark.parametrize("dpi", [96, 120, 144])  # 100 %, 125 %, 150 %
def test_roundtrip_and_scale_independence(dpi):
    w = win(dpi=dpi)
    s = dpi / 96
    rect = (w.left + round(40 * s), w.top + round(90 * s), round(220 * s), round(30 * s))
    reg = to_region(rect, w)
    assert astuple(reg) == pytest.approx((40, 90, 220, 30), abs=1.0)  # physical pixels are whole numbers
    assert to_screen(reg, w) == rect
    # the same stored region on a 100 % window lands on the same logical spot
    x, y, w_, h = to_screen(reg, win(dpi=96))
    assert abs(x - 140) <= 1 and abs(y - 140) <= 1 and abs(w_ - 220) <= 1 and abs(h - 30) <= 1


def test_region_follows_moved_and_resized_window():
    reg = to_region((140, 140, 220, 30), win())
    moved = win(left=-1800, top=300, width=1500, height=900)  # now on a monitor left of the primary
    assert to_screen(reg, moved) == (-1760, 390, 220, 30)


def test_region_outside_or_window_too_small():
    assert to_region((5000, 5000, 100, 30), win()) is None
    assert to_region((90, 40, 100, 30), win()) == Region(0, 0, 90, 20)  # clipped to the window
    reg = to_region((900, 700, 300, 40), win())
    assert to_screen(reg, win(width=900, height=600)) is None  # window shrank below the region


def test_pick_prefers_foreground_then_topmost():
    a, b = win(hwnd=1), win(hwnd=2)
    assert pick([a, b], foreground=2) is b
    assert pick([a, b], foreground=99) is a


def test_blank_detection():
    import numpy as np
    assert blank(np.zeros((10, 10, 3), np.uint8))
    img = np.zeros((10, 10, 3), np.uint8)
    img[3:6, 2:8] = 255
    assert not blank(img)
