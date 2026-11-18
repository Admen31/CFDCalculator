"""v2.8 OCR regression tests on rendered screenshots of a Trading 212-like trade panel (real RapidOCR, no network).

Each screenshot has the instrument header in a large font, a sub-title, SELL/BUY prices, quantity, margin, leverage
and a watchlist with OTHER instruments in a small font. Rendered at 100, 125, 150 and 200 % (Windows scaling).
The instrument must be found by its identity - never from a price, a quantity, a margin or BUY/SELL - and a screen
with two equally large instrument names must NOT be guessed. The images are saved for inspection (CI artifact).

These are simulated screenshots, not the real Trading 212: the real layout is verified only by the user.
"""
import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtGui")
pytest.importorskip("rapidocr_onnxruntime")
from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from cfdcalc.recognize import locate, match, ocr_boxes, ocr_lines  # noqa: E402

OUT = Path(os.environ.get("CFD_E2E_OUT", "e2e-out")) / "ocr-panels"
WATCHLIST = [("Gold", "4,083.45"), ("NVIDIA", "182.40"), ("Germany 40", "23,950.1"), ("GBP/USD", "1.31842")]


@pytest.fixture(scope="module")
def app():
    OUT.mkdir(parents=True, exist_ok=True)
    return QApplication.instance() or QApplication([])


def render(header, subtitle, sell, buy, scale=1.0, watch=WATCHLIST, second_header=None, name="panel"):
    """RGB numpy screenshot (physical pixels at `scale`) of a dark trading screen."""
    w, h = int(980 * scale), int(560 * scale)
    img = QImage(w, h, QImage.Format.Format_RGB888)
    img.fill(QColor("#14181f"))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    def text(x, y, s, size, color="#e6e6e6", bold=False, ww=420):
        f = QFont("Segoe UI")
        f.setPixelSize(int(size * scale))
        f.setBold(bold)
        p.setFont(f)
        p.setPen(QColor(color))
        p.drawText(QRectF(x * scale, y * scale, ww * scale, size * 1.6 * scale),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, s)

    # watchlist (left, small)
    text(16, 20, "Watchlist", 12, "#9aa3b2")
    for i, (n, px) in enumerate(watch):
        text(16, 52 + 34 * i, n, 13)
        text(140, 52 + 34 * i, px, 13, "#9aa3b2")
    # instrument header (centre, large) + sub-title
    text(260, 24, header, 28, bold=True)
    text(260, 72, subtitle, 13, "#9aa3b2")
    if second_header:
        text(620, 24, second_header, 28, bold=True, ww=340)
    # trade panel
    text(260, 150, "SELL", 14, "#f87171", True)
    text(260, 176, sell, 20, "#f87171", True)
    text(470, 150, "BUY", 14, "#4ade80", True)
    text(470, 176, buy, 20, "#4ade80", True)
    text(260, 240, "Quantity", 13, "#9aa3b2")
    text(470, 240, "1,000", 13)
    text(260, 272, "Margin", 13, "#9aa3b2")
    text(470, 272, "€38.41", 13)
    text(260, 304, "Leverage 1:30", 13, "#9aa3b2")
    text(260, 336, "Take profit   Stop loss   Market order", 13, "#9aa3b2", ww=600)
    p.end()
    img.save(str(OUT / f"{name}_{int(scale * 100)}.png"))
    ptr = img.constBits()
    arr = np.frombuffer(ptr, np.uint8, img.sizeInBytes()).reshape(h, img.bytesPerLine())[:, :w * 3]
    return arr.reshape(h, w, 3).copy()


CASES = [
    ("EUR/USD", "Euro / US Dollar", "1.15234", "1.15242", "EUR/USD"),
    ("Gold", "Spot Gold / US Dollar", "4,083.10", "4,083.45", "XAU/USD"),
    ("XAG/USD", "Silver Spot / US Dollar", "51.812", "51.842", "XAG/USD"),
    ("NVIDIA", "NVIDIA Corp.", "182.31", "182.40", "NVDA"),
    ("US 500", "S&P 500 index", "7,561.2", "7,561.8", "SPX"),
    ("Germany 40", "DAX index", "23,949.5", "23,950.1", "DAX"),
]


@pytest.mark.parametrize("scale", [1.0, 1.25, 1.5, 2.0])
@pytest.mark.parametrize("header, subtitle, sell, buy, symbol", CASES)
def test_whole_window_finds_the_header_not_prices_or_watchlist(app, header, subtitle, sell, buy, symbol, scale):
    rgb = render(header, subtitle, sell, buy, scale, name=symbol.replace("/", ""))
    rec = locate(ocr_boxes(rgb))
    assert rec.confident and rec.best.symbol == symbol, (rec.text[:200], rec.reason)


@pytest.mark.parametrize("scale", [1.0, 1.5])
def test_region_on_the_header_reads_the_instrument_and_on_the_prices_reads_nothing(app, scale):
    rgb = render("EUR/USD", "Euro / US Dollar", "1.15234", "1.15242", scale, name="region")
    s = scale
    header = rgb[int(16 * s):int(110 * s), int(250 * s):int(700 * s)]
    prices = rgb[int(140 * s):int(320 * s), int(250 * s):int(700 * s)]
    assert match(ocr_lines(header)).best.symbol == "EUR/USD"
    rec = match(ocr_lines(prices))                         # SELL / BUY / prices / quantity / margin only
    assert not rec.confident and rec.best is None and "nerozpoznán" in rec.reason


def test_two_equally_large_instrument_names_are_not_guessed(app):
    rgb = render("EUR/USD", "Euro / US Dollar", "1.15234", "1.15242", second_header="Gold", name="ambiguous")
    rec = locate(ocr_boxes(rgb))
    assert not rec.confident and rec.best is None


def test_screen_without_a_known_instrument_is_not_guessed(app):
    rgb = render("Portfolio", "Overview", "0.00", "0.00", watch=[], name="noinstrument")
    rec = locate(ocr_boxes(rgb))
    assert not rec.confident and rec.best is None
