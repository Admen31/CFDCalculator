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

pytest.importorskip("rapidocr_onnxruntime")
PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from cfdcalc.recognize import locate, match, ocr_boxes, ocr_lines  # noqa: E402

OUT = Path(os.environ.get("CFD_E2E_OUT", "e2e-out")) / "ocr-panels"
WATCHLIST = [("Gold", "4,083.45"), ("NVIDIA", "182.40"), ("Germany 40", "23,950.1"), ("GBP/USD", "1.31842")]
FONTS = {False: ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"), True: ("segoeuib.ttf", "arialbd.ttf",
                                                                        "DejaVuSans-Bold.ttf")}


def font(size: int, bold: bool):
    """A real TrueType font (Windows: Segoe UI / Arial). The offscreen Qt platform has no fonts at all, so the
    screenshots are drawn with Pillow."""
    for name in FONTS[bold]:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    pytest.skip("no TrueType font available")


@pytest.fixture(scope="module")
def app():
    OUT.mkdir(parents=True, exist_ok=True)


def render(header, subtitle, sell, buy, scale=1.0, watch=WATCHLIST, second_header=None, name="panel"):
    """RGB numpy screenshot (physical pixels at `scale`) of a dark trading screen."""
    w, h = int(980 * scale), int(560 * scale)
    img = Image.new("RGB", (w, h), "#14181f")
    d = ImageDraw.Draw(img)

    def text(x, y, s, size, color="#e6e6e6", bold=False):
        d.text((x * scale, y * scale), s, fill=color, font=font(int(size * scale), bold))

    text(16, 20, "Watchlist", 12, "#9aa3b2")
    for i, (n, px) in enumerate(watch):
        text(16, 52 + 34 * i, n, 13)
        text(140, 52 + 34 * i, px, 13, "#9aa3b2")
    text(260, 24, header, 28, bold=True)
    text(260, 72, subtitle, 13, "#9aa3b2")
    if second_header:
        text(620, 24, second_header, 28, bold=True)
    text(260, 150, "SELL", 14, "#f87171", True)
    text(260, 176, sell, 20, "#f87171", True)
    text(470, 150, "BUY", 14, "#4ade80", True)
    text(470, 176, buy, 20, "#4ade80", True)
    text(260, 240, "Quantity", 13, "#9aa3b2")
    text(470, 240, "1,000", 13)
    text(260, 272, "Margin", 13, "#9aa3b2")
    text(470, 272, "€38.41", 13)
    text(260, 304, "Leverage 1:30", 13, "#9aa3b2")
    text(260, 336, "Take profit   Stop loss   Market order", 13, "#9aa3b2")
    img.save(OUT / f"{name}_{int(scale * 100)}.png")
    return np.asarray(img).copy()


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


# ---------------------------------------------------------------- v2.9: several instrument tabs open in Trading 212

TABS = ["Silver", "NVIDIA", "Gold", "EUR/USD"]


def dump(boxes):
    """Measured OCR boxes for the failure message (text, x, y, font height, background, text luminance)."""
    return [(b.text, round(b.x), round(b.y), round(b.height), b.bg and round(b.bg), b.fg and round(b.fg))
            for b in boxes]
WATCH = [("Silver", "51.84"), ("NVIDIA", "182.40"), ("Gold", "4,083.45"), ("EUR/USD", "1.15242"),
         ("GBP/USD", "1.31842")]


def render_t212(active, tabs=TABS, scale=1.0, header=None, mark="background", watch=WATCH, name="t212"):
    """Representative Trading 212 web screen (NOT a real screenshot): a row of instrument tabs at the top (the
    active one marked by `mark`: background | text | none), a watchlist on the left with the same instruments,
    the chart area with SELL / BUY buttons and prices, optionally a chart header with the instrument name."""
    w, h = int(1280 * scale), int(720 * scale)
    img = Image.new("RGB", (w, h), "#101319")
    d = ImageDraw.Draw(img)
    s = scale

    def text(x, y, t, size, color="#e6e6e6", bold=False):
        d.text((x * s, y * s), t, fill=color, font=font(int(size * s), bold))

    d.rectangle([0, 0, w, int(48 * s)], fill="#161a22")                       # tab bar
    x = 250
    for t in tabs:
        on = t == active
        if on and mark == "background":
            d.rectangle([int((x - 14) * s), int(6 * s), int((x + 118) * s), int(44 * s)], fill="#2e3a52")
        if on and mark == "text":
            d.rectangle([int((x - 14) * s), int(42 * s), int((x + 118) * s), int(45 * s)], fill="#3b82f6")
        color = "#ffffff" if on and mark != "none" else "#8b93a1"
        if mark == "background":
            color = "#ffffff" if on else "#c9ced6"
        text(x, 14, t, 15, color, bold=on and mark == "text")
        x += 150
    text(16, 60, "Watchlist", 12, "#8b93a1")
    for i, (n, px) in enumerate(watch):
        text(16, 92 + 36 * i, n, 13)
        text(150, 92 + 36 * i, px, 13, "#8b93a1")
    if header:
        text(260, 70, header, 24, bold=True)
        text(260, 104, "15m · Trading 212 CFD", 12, "#8b93a1")
    d.rectangle([int(260 * s), int(140 * s), int(380 * s), int(196 * s)], fill="#3b1d22")
    d.rectangle([int(392 * s), int(140 * s), int(512 * s), int(196 * s)], fill="#16341f")
    text(272, 146, "SELL", 13, "#f87171", True)
    text(272, 166, "1.15234" if "EUR" in (active or "") else "4,083.10", 16, "#f87171", True)
    text(404, 146, "BUY", 13, "#4ade80", True)
    text(404, 166, "1.15242" if "EUR" in (active or "") else "4,083.45", 16, "#4ade80", True)
    for i in range(6):                                                         # chart grid labels (numbers)
        text(1180, 220 + 70 * i, f"{1.1530 - 0.0005 * i:.4f}", 11, "#5b6270")
    img.save(OUT / f"{name}_{int(scale * 100)}.png")
    return np.asarray(img).copy()


@pytest.mark.parametrize("scale", [1.0, 1.25, 1.5, 2.0])
def test_active_eurusd_among_silver_nvidia_gold_tabs(app, scale):
    """Scenario A (representative image): Silver, NVIDIA, Gold and EUR/USD open, EUR/USD active -> EUR/USD."""
    boxes = ocr_boxes(render_t212("EUR/USD", scale=scale, name="tabs_eurusd_active"))
    rec = locate(boxes)
    assert rec.confident and rec.best.symbol == "EUR/USD", (rec.via, rec.reason, dump(boxes))
    assert rec.via == "aktivní záložka"


@pytest.mark.parametrize("scale", [1.0, 1.5])
def test_active_tab_marked_only_by_text_colour_and_underline(app, scale):
    boxes = ocr_boxes(render_t212("EUR/USD", scale=scale, mark="text", name="tabs_text_marked"))
    rec = locate(boxes)
    assert rec.confident and rec.best.symbol == "EUR/USD", (rec.via, rec.reason, dump(boxes))


@pytest.mark.parametrize("scale", [1.0, 1.5])
def test_chart_header_wins_over_tabs(app, scale):
    boxes = ocr_boxes(render_t212("EUR/USD", scale=scale, header="EUR/USD", mark="none", name="tabs_header"))
    rec = locate(boxes)            # tabs WITHOUT a mark: only the chart header can decide
    assert rec.confident and rec.best.symbol == "EUR/USD", (rec.via, rec.reason, dump(boxes))
    assert rec.via in ("graf / nadpis", "obchodní panel")


@pytest.mark.parametrize("scale", [1.0, 1.25])
def test_switch_to_gold_is_recognised(app, scale):
    """Scenario B (representative image): the user clicks the Gold tab -> XAU/USD."""
    boxes = ocr_boxes(render_t212("Gold", scale=scale, name="tabs_gold_active"))
    rec = locate(boxes)
    assert rec.confident and rec.best.symbol == "XAU/USD", (rec.via, rec.reason, dump(boxes))


def test_two_tabs_only(app):
    boxes = ocr_boxes(render_t212("EUR/USD", tabs=["Silver", "EUR/USD"], name="two_tabs"))
    rec = locate(boxes)
    assert rec.confident and rec.best.symbol == "EUR/USD", (rec.via, rec.reason, dump(boxes))


def test_tabs_without_any_visible_mark_are_not_guessed(app):
    rec = locate(ocr_boxes(render_t212("EUR/USD", mark="none", name="tabs_unmarked")))
    assert not rec.confident and rec.best is None
    assert {i.symbol for i in rec.competing} >= {"EUR/USD", "XAU/USD"}       # offered for the manual choice


def test_loose_and_shifted_ocr_boxes_never_pick_a_wrong_instrument(app, monkeypatch):
    """Robustness without the OCR engine: the exact text boxes of the rendered screen are randomly enlarged and
    shifted (as RapidOCR boxes are) before measuring them. A wrong instrument is never chosen; the marked tab or
    the chart header is always found; an unmarked row of tabs stays undecided."""
    import random

    from cfdcalc.recognize import make_box
    drawn = []
    orig = ImageDraw.ImageDraw.text

    def spy(self, xy, t, fill=None, font=None, **kw):
        drawn.append((t, self.textbbox(xy, t, font=font)))
        return orig(self, xy, t, fill=fill, font=font, **kw)
    monkeypatch.setattr(ImageDraw.ImageDraw, "text", spy)
    cases = (("EUR/USD", "background", None, "EUR/USD"), ("EUR/USD", "text", None, "EUR/USD"),
             ("Gold", "background", None, "XAU/USD"), ("EUR/USD", "none", "EUR/USD", "EUR/USD"),
             ("EUR/USD", "none", None, None))
    for seed in range(12):
        rnd = random.Random(seed)
        for scale in (1.0, 1.25, 1.5, 2.0):
            for active, mark, header, want in cases:
                drawn.clear()
                rgb = render_t212(active, scale=scale, mark=mark, header=header, name="stress")
                lum = (0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]).astype(np.float32)
                boxes = []
                for t, (x0, y0, x1, y1) in drawn:
                    px, py = rnd.randint(1, int(8 * scale)), rnd.randint(1, int(7 * scale))
                    ox, oy = rnd.randint(-2, 2), rnd.randint(-2, 2)
                    boxes.append(make_box(lum, t, x0 - px + ox, y0 - py + oy, x1 + px + ox, y1 + py + oy))
                rec = locate(boxes)
                got = rec.best.symbol if rec.best else None
                assert got == want, (seed, scale, active, mark, header, got, rec.via)
