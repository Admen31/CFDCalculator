"""v2.3 UI: colour of the result card, WATCH / bias pills, ERROR vs SELL, reduced motion, cached provider."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtCore")
from test_ui_auto import Reader, settle  # noqa: E402
from test_ui_smooth import app, gated, make  # noqa: E402,F401

from cfdcalc import strategies as st  # noqa: E402
from cfdcalc import widgets  # noqa: E402
from cfdcalc.analysis import BUY, ERROR, SELL, WAIT  # noqa: E402


@pytest.fixture
def still(monkeypatch):
    monkeypatch.setattr(widgets, "REDUCED_MOTION", True)


@pytest.mark.parametrize("verdict, color, icon", [(BUY, widgets.GREEN, "▲"), (SELL, widgets.RED, "▼"),
                                                  (WAIT, widgets.YELLOW, "■"), (ERROR, widgets.RED, "⚠")])
def test_card_colour_icon_and_error_is_dashed(app, make, monkeypatch, verdict, color, icon):  # noqa: F811
    gate, _ = gated(monkeypatch, verdict)
    w = make(Reader("Gold"))
    w.s.setValue("reduced_motion", True)
    widgets.REDUCED_MOTION = True
    gate.set()
    w.start()
    settle(app, w)
    res = w.result
    assert res.verdict.text() == verdict and res.icon.text() == icon
    assert res._color.name() == color and w.gauge._color.name() == color        # no animation: final colour now
    assert res._dashed == (verdict == ERROR)                                      # ERROR never looks like SELL
    widgets.REDUCED_MOTION = False


def test_watch_and_bias_pills(app, make, monkeypatch, still):  # noqa: F811
    from cfdcalc.analysis import Result
    w = make(Reader("Gold"))
    w.analysed = w.inst or w.bar.tracker.confirmed
    r = Result(verdict=WAIT, summary="shoda indikátorů nesplněna", completed=20, total=20)
    r.bias = st.Bias(st.BEARISH, -3, "střední", ["a", "b", "c"])
    r.opportunity = st.Setup("breakout", "SELL", "watch", "konsolidace", ["uzavření 5m pod 2001.5"])
    from cfdcalc.instruments import BY_SYMBOL
    w.set_instrument(BY_SYMBOL["XAU/USD"])
    w.analysed = BY_SYMBOL["XAU/USD"]
    w.on_result(r)
    res = w.result
    assert "BEARISH" in res.bias.text() and "▼" in res.bias.text() and widgets.RED in res.bias.styleSheet()
    assert "WATCH" in res.opportunity.text() and widgets.YELLOW in res.opportunity.styleSheet()
    assert res.waiting.text() == "Čeká se na: uzavření 5m pod 2001.5" and res.lower.currentIndex() == 0
    assert "BREAKOUT" in res.strategy.text() and "výzkum" in res.strategy.text()


def test_reduced_motion_jumps_to_final_values(app, still):  # noqa: F811
    g = widgets.Gauge()
    g.show_state(60, "60 %", "x", widgets.GREEN, busy=True)
    assert g._pct == 60 and g._color.name() == widgets.GREEN and g._spinner.state().name == "Stopped"


def test_live_provider_is_one_cached_client(app, make):  # noqa: F811
    from cfdcalc.data import CachedProvider
    w = make(Reader("Gold"))
    a, b = w.provider(), w.provider()
    assert isinstance(a, CachedProvider) and a is b and a.provider.per_minute == 8
    w.s.setValue("td_per_minute", 55)
    assert w.provider() is not a and w.provider().provider.per_minute == 55
