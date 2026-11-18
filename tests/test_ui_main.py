"""v2.8: the minimal main screen driven ONLY by the M15 signal: START -> BUY/SELL, VSTUP, TP, SL, POZICE.

Deterministic 15min test data (random walks whose signal is known), a controllable clock and a counting provider.
"""
import os
import threading
import time
from datetime import timedelta

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtCore")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QLabel, QPushButton  # noqa: E402
from test_m15 import CONDITIONAL_SELL_STOP, CONFIRMED_BUY, CONFIRMED_SELL, INVALID_SELL, walk  # noqa: E402
from test_ui_auto import Reader, settle  # noqa: E402
from test_ui_smooth import app, make  # noqa: E402,F401

from cfdcalc.data import DataError  # noqa: E402
from cfdcalc.instruments import BY_SYMBOL  # noqa: E402

BASE = {"XAU/USD": 2000.0, "EUR/USD": 1.1}
SEEDS = {"up": CONFIRMED_BUY, "down": CONFIRMED_SELL, "conditional": CONDITIONAL_SELL_STOP, "invalid": INVALID_SELL,
         "flat": 2}


class Script:
    """15min market chosen by the test before each click: up (confirmed BUY), down (confirmed SELL), direction (BUY
    or SELL without a confirmed entry), flat (NEUTRAL) or a failing API. Optional gate = slow network."""

    name = "Twelve Data"

    def __init__(self, clock):
        self.clock, self.mode, self.calls, self.intervals = clock, "up", 0, []
        self.lock, self.gate = threading.Lock(), None

    def bars(self, symbol, interval, n, **kw):
        with self.lock:
            self.calls += 1
            self.intervals.append(interval)
        if self.gate is not None:
            self.gate.wait(10)
        if self.mode == "fail":
            raise DataError(f"{symbol}: Twelve Data neposkytla data pro interval {interval}. HTTP 500.", "server")
        return walk(self.clock.now(), seed=SEEDS[self.mode], base=BASE[symbol])[-n:]


@pytest.fixture
def live(app, make, monkeypatch):  # noqa: F811
    from datetime import datetime

    from conftest import T0

    from cfdcalc import ui, ui_risk

    class Clock(datetime):
        t = T0

        @classmethod
        def now(cls, tz=None):
            return cls.t
    monkeypatch.setattr(ui, "datetime", Clock)
    monkeypatch.setattr(ui_risk, "datetime", Clock)
    script = Script(Clock)
    w = make(Reader("Gold"))
    w.providers = lambda: script
    w.m15.set_events([])
    w.bar.set_mode("manual")
    w.set_instrument(BY_SYMBOL["XAU/USD"])
    return w, script, Clock


def later(clock, seconds):
    clock.t = clock.t + timedelta(seconds=seconds)


def click(app, w, timeout=5.0):  # noqa: F811
    n = len(w.latencies)
    QTest.mouseClick(w.big, Qt.MouseButton.LeftButton)
    end = time.monotonic() + timeout
    while len(w.latencies) == n and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.003)
    settle(app, w)
    for _ in range(20):
        app.processEvents()
    return w.big.text(), values(w)


def values(w):
    return [lab.text().split(": ", 1)[1] for lab in (w.entry_lbl, w.tp_lbl, w.sl_lbl, w.pos_lbl)]


def new_market(w, script, clock, mode):
    script.mode = mode
    w.m15.feed.clear()
    later(clock, 120)


def test_main_screen_shows_only_the_button_values_and_navigation(app, live):  # noqa: F811
    w, _, _ = live
    page = w.pages.currentWidget()
    labels = [x.text() for x in page.findChildren(QLabel) if x.isVisibleTo(page) and x.text()]
    buttons = [x.text() for x in page.findChildren(QPushButton) if x.isVisibleTo(page)]
    assert labels == ["VSTUP: –", "TP: –", "SL: –", "POZICE: –"] and w.big.text() == "START"
    assert sorted(buttons) == sorted(["START", "Portfolio a riziko ▸", "Podrobnosti ▸"])
    assert not w.gauge.isVisibleTo(w) and not w.result.isVisibleTo(w)


def test_m15_only_one_request_per_click_and_every_click_recomputes(app, live):  # noqa: F811
    w, script, clock = live
    seen = []
    for mode, want in (("up", "BUY"), ("down", "SELL"), ("up", "BUY")):
        new_market(w, script, clock, mode)
        before = script.calls
        state, (entry, tp, sl, _pos) = click(app, w)
        assert state == want and script.calls - before == 1          # ONE request, and only 15min
        e, t, s_ = float(entry), float(tp), float(sl)
        assert (s_ < e < t) if want == "BUY" else (t < e < s_)
        seen.append((state, entry, tp, sl))
    assert set(script.intervals) == {"15min"}
    assert seen[0][1:] != seen[1][1:] and not w.m15_busy() and len(w.latencies) == 3


def test_repeated_click_without_new_data_is_instant_and_identical(app, live):  # noqa: F811
    w, script, clock = live
    state, first = click(app, w)
    n = script.calls
    later(clock, 20)                                       # 20 s later: no new 15m bar, price still fresh
    state2, second = click(app, w)
    assert script.calls == n and (state2, second) == (state, first)
    assert w.latency_kinds[-1] == "cache" and w.latencies[-1] < 1.0 and "z cache" in w.info.text()
    assert "M15 svíčka" in w.info.text()                   # the real time of the data is shown
    later(clock, 61)                                       # price older than 60 s: one small request
    click(app, w)
    assert script.calls == n + 1


def test_conditional_plan_shows_its_levels_marked_and_invalid_plan_and_neutral_show_none(app, live):  # noqa: F811
    """Scenario E + the v2.9 fix of "SELL and four dashes"."""
    w, script, clock = live
    setup_portfolio(w)
    new_market(w, script, clock, "conditional")
    state, (entry, tp, sl, pos) = click(app, w)
    sig = w.m15_last["XAU/USD"]
    assert state == "SELL" and sig.plan == "PODMÍNĚNÝ" and "(podmíněný – stop)" in entry
    assert float(tp) < float(entry.split()[0]) < float(sl) and pos.endswith("(množství T212)")
    assert "PODMÍNĚNÝ plán – vstup zatím nenastal" in w.info.text() and "Podmínka vstupu" in w.m15_text.toHtml()
    new_market(w, script, clock, "invalid")
    state, vals = click(app, w)
    assert state == "SELL" and vals == ["–", "–", "–", "–"] and "plán neplatný" in w.info.text()
    assert "Plán NEPLATNÝ" in w.m15_text.toHtml()
    new_market(w, script, clock, "flat")
    state, vals = click(app, w)
    assert state == "NEUTRAL" and vals == ["–", "–", "–", "–"]


def test_api_error_then_repeat_succeeds(app, live):  # noqa: F811
    w, script, clock = live
    new_market(w, script, clock, "fail")
    state, vals = click(app, w)
    assert state == "NO DATA" and vals == ["–", "–", "–", "–"] and not w.m15_busy()
    assert "Výpadek na straně poskytovatele" in w.m15_text.toPlainText() or "HTTP 500" in w.m15_text.toPlainText()
    new_market(w, script, clock, "up")
    state, vals = click(app, w)
    assert state == "BUY" and "–" not in vals[:3]


def test_instrument_change_never_shows_old_prices(app, live):  # noqa: F811
    w, script, clock = live
    state, gold = click(app, w)
    assert state == "BUY" and float(gold[0]) > 1000
    w.set_instrument(BY_SYMBOL["EUR/USD"])
    app.processEvents()
    assert w.big.text() == "START" and values(w) == ["–", "–", "–", "–"]
    state, eur = click(app, w)
    assert w.shown_m15.symbol == "EUR/USD" and state == "BUY" and float(eur[0]) < 2       # EUR/USD prices only
    w.set_instrument(BY_SYMBOL["XAU/USD"])                 # back to gold: no stale EUR/USD values either
    app.processEvents()
    assert values(w) == ["–", "–", "–", "–"]


def test_clicks_during_a_request_never_start_a_second_one(app, live):  # noqa: F811
    w, script, clock = live
    script.gate = threading.Event()
    QTest.mouseClick(w.big, Qt.MouseButton.LeftButton)
    for _ in range(3):
        QTest.mouseClick(w.big, Qt.MouseButton.LeftButton)
        app.processEvents()
    assert script.calls == 1 and w.big.text() == "ANALYZUJI…" and w.m15_busy()
    script.gate.set()
    end = time.monotonic() + 5
    while w.m15_busy() and time.monotonic() < end:
        app.processEvents()
    for _ in range(20):
        app.processEvents()
    assert w.big.text() == "BUY" and script.calls == 1
    script.gate = None
    later(clock, 90)
    state, _ = click(app, w)                               # the shown BUY starts the next analysis
    assert state == "BUY" and script.calls == 2


def test_timeout_then_repeat(app, live):  # noqa: F811
    w, script, clock = live
    script.gate = threading.Event()
    QTest.mouseClick(w.big, Qt.MouseButton.LeftButton)
    app.processEvents()
    w._m15_timeout(w._m15_gen)                             # the watchdog fires
    assert w.big.text() == "NO DATA" and not w.m15_busy() and "neodpověděl" in w.info.text()
    script.gate.set()                                      # the abandoned worker ends, its result is ignored
    for t in list(w._retired):
        t.wait(5000)
    for _ in range(20):
        app.processEvents()
    assert w.big.text() == "NO DATA"
    script.gate = None
    state, _ = click(app, w)
    assert state == "BUY"


def setup_portfolio(w, symbol="XAU_USD", contract="1", min_qty="0.01", step="0.01", rate="21"):
    from datetime import datetime, timezone
    w.s.setValue("account/equity", "100000")
    w.s.setValue("account/currency", "CZK")
    w.s.setValue("account/risk_pct", "2")
    w.s.setValue("account/reserve_pct", "0")
    for k, v in (("contract", contract), ("min_qty", min_qty), ("step", step)):
        w.s.setValue(f"spec/{symbol}/{k}", v)
    w.s.setValue("fx/USDCZK/rate", rate)
    w.s.setValue("fx/USDCZK/time", datetime(2026, 11, 17, 14, 0, tzinfo=timezone.utc).isoformat())


def test_position_on_the_main_screen_from_the_risk_calculation(app, live):  # noqa: F811
    from decimal import Decimal as D

    from cfdcalc import risk
    w, script, clock = live
    setup_portfolio(w)
    state, (entry, _tp, sl, pos) = click(app, w)
    out = w.risk_page.last
    assert state == "BUY" and out.state == risk.OK and pos == f"{risk.fmt_qty(out.qty)} (množství T212)"
    unit = (abs(D(entry) - D(sl)) + D(str(w.spread_of(w.inst)))) * D(21)
    assert out.loss_sl <= D(2000) and out.qty == risk.floor_step(D(2000) / unit, D("0.01"))


def test_position_cannot_be_computed_without_a_spec_and_too_risky_minimum(app, live):  # noqa: F811
    w, script, clock = live
    setup_portfolio(w, contract="")
    state, vals = click(app, w)
    assert state == "BUY" and vals[3] == "NELZE SPOČÍTAT (chybí specifikace)"
    assert "specifikace" in w.risk_page.message.text()
    setup_portfolio(w, min_qty="1000", step="1")
    w.risk_page.recompute()
    app.processEvents()
    assert values(w)[3] == "PŘÍLIŠ RIZIKOVÉ"


def test_historical_mode_never_changes_the_main_screen(app, live, monkeypatch):  # noqa: F811
    from cfdcalc.analysis import SELL, Result
    w, script, clock = live
    state, vals = click(app, w)
    from cfdcalc import ui
    monkeypatch.setattr(ui, "run_analysis", lambda inst, *a: Result(verdict=SELL, reasons=["x"], summary="x"))
    w.start()                                              # details page: the old multi-timeframe analysis
    settle(app, w)
    assert (w.big.text(), values(w)) == (state, vals) and w.risk_page.entry.text() == vals[0]


def test_portfolio_tab_saves_locally(app, live):  # noqa: F811
    from cfdcalc.ui_risk import load_account
    w, _, _ = live
    w.to_portfolio.click()
    assert w.pages.currentWidget() is w.portfolio
    p = w.portfolio
    p.equity.setText("100 000")
    p.currency.setCurrentText("EUR")
    p.risk.setValue(2)
    p.open_risk.setText("500")
    p.total_on.setChecked(True)
    p.total.setValue(5)
    assert p.save()
    acc = load_account(w.s)
    assert (str(acc.equity), acc.currency, str(acc.open_risk), str(acc.max_total_pct)) == ("100000", "EUR", "500", "5")
    p.equity.setText("abc")
    assert not p.save() and "kladné číslo" in p.status.text()


def test_spec_typed_in_the_portfolio_tab_makes_the_position_available(app, live):  # noqa: F811
    """v2.9: the CFD specification of the current instrument is typed directly in Portfolio a riziko."""
    w, script, clock = live
    setup_portfolio(w, contract="")
    state, vals = click(app, w)
    assert vals[3] == "NELZE SPOČÍTAT (chybí specifikace)"
    w.to_portfolio.click()
    app.processEvents()
    f = w.portfolio.spec
    f.show_instrument(w.inst)                                  # what opening the tab does (showEvent)
    assert f.inst.symbol == "XAU/USD" and f.isEnabled()
    f.edits["contract"].setText("1")
    assert "1 000 × 1" in f.check.text()                       # how to verify the unit against Trading 212
    assert f.save()
    for _ in range(10):
        app.processEvents()
    assert values(w)[3].endswith("(množství T212)")
