"""AUTO reading pipeline with a fake Windows backend, and the instrument confirmation rules."""
from types import SimpleNamespace

import numpy as np
import pytest

from cfdcalc import auto
from cfdcalc.instruments import BY_SYMBOL
from cfdcalc.recognize import match
from cfdcalc.tracker import Tracker
from cfdcalc.window import CaptureError, Region, Win

REGION = Region(40, 90, 220, 30)
TEXT = np.zeros((30, 220, 3), np.uint8)
TEXT[10:20, 10:100] = 255


def backend(wins=(), capture=None):
    calls = []

    def cap(win, rect):
        calls.append(rect)
        if isinstance(capture, Exception):
            raise capture
        return TEXT if capture is None else capture
    return SimpleNamespace(SUPPORTED=True, list_t212=lambda: list(wins), foreground=lambda: 0,
                           pick=lambda ws, fg=0: ws[0], capture=cap, calls=calls)


W = Win(7, "NVIDIA – Trading 212 – Google Chrome", 100, 50, 1200, 800)


class OCR:
    def __init__(self, *lines):
        self.lines, self.calls = list(lines), 0

    def __call__(self, rgb):
        self.calls += 1
        return self.lines


def test_reads_instrument_from_window_region():
    b, ocr = backend([W]), OCR("NVIDIA", "182.40")
    r = auto.read(REGION, b, ocr)
    assert r.status == auto.OK and r.recognition.best.symbol == "NVDA"
    assert b.calls == [(140, 140, 220, 30)] and ocr.calls == 1  # only the region is captured


@pytest.mark.parametrize("wins, region, cap, status", [
    ([], REGION, None, auto.NO_WINDOW),
    ([Win(7, "Trading 212", 0, 0, 800, 600, minimized=True)], REGION, None, auto.MINIMIZED),
    ([W], None, None, auto.NO_REGION),
    ([Win(7, "Trading 212", 0, 0, 200, 100)], REGION, None, auto.UNREADABLE),       # window too small
    ([W], REGION, CaptureError("okno je zakryté"), auto.UNREADABLE),               # covered, no content
])
def test_no_ocr_without_a_safely_readable_window(wins, region, cap, status):
    ocr = OCR("NVIDIA")
    r = auto.read(region, backend(wins, cap), ocr)
    assert r.status == status and r.message and ocr.calls == 0


def test_unsupported_platform():
    r = auto.read(REGION, SimpleNamespace(SUPPORTED=False), OCR())
    assert r.status == auto.UNSUPPORTED


def test_blank_region_skips_ocr():
    ocr = OCR("NVIDIA")
    r = auto.read(REGION, backend([W], np.zeros((30, 220, 3), np.uint8)), ocr)
    assert r.status == auto.OK and not r.recognition.text and ocr.calls == 0


def ok(*lines):
    return auto.Reading(auto.OK, "", W, match(list(lines)))


def test_tracker_needs_two_equal_readings_to_switch():
    t = Tracker(stable=2)
    assert not t.feed(ok("NVIDIA")) and t.confirmed is None
    assert t.feed(ok("NVIDIA")) and t.confirmed.symbol == "NVDA"
    assert not t.feed(ok("EUR/USD")) and t.confirmed.symbol == "NVDA"   # one glitch does not switch
    assert not t.feed(ok("NVIDIA"))
    assert not t.feed(ok("EUR/USD"))
    assert t.feed(ok("EUR/USD")) and t.confirmed.symbol == "EUR/USD"


def test_one_shot_reading_confirms_immediately():
    t = Tracker()
    assert t.feed(ok("Tesla"), stable=1) and t.confirmed.symbol == "TSLA"


def test_unknown_or_ambiguous_reading_drops_confirmation():
    t = Tracker()
    t.set_manual(BY_SYMBOL["AAPL"])
    assert not t.feed(ok("NVIDIA", "Apple"))
    assert t.feed(ok("NVIDIA", "Apple")) and t.confirmed is None       # ambiguous -> nothing confirmed
    t.set_manual(BY_SYMBOL["AAPL"])
    t.feed(ok("Rolls-Royce"))
    assert t.feed(ok("Rolls-Royce")) and t.confirmed is None            # unknown instrument shown


def test_no_information_keeps_confirmation():
    t = Tracker()
    t.set_manual(BY_SYMBOL["AAPL"])
    for r in (auto.Reading(auto.NO_WINDOW, "x"), auto.Reading(auto.MINIMIZED, "x", W), ok()):
        assert not t.feed(r) and not t.feed(r) and t.confirmed.symbol == "AAPL"


def test_user_confirmation_teaches_the_uncertain_text():
    t = Tracker()
    t.set_manual(BY_SYMBOL["SPX"], ocr_text="US 50O")
    for _ in range(3):
        assert not t.feed(ok("US 50O")) and t.confirmed.symbol == "SPX"
