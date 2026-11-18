"""v2.4 UI: RISK MANAGEMENT page fed by the analysis, dialogs, FX fetch only when needed, no orders anywhere."""
import os
from decimal import Decimal as D

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtCore")
from test_ui_auto import Reader, settle, ticks  # noqa: E402
from test_ui_smooth import app, gated, make  # noqa: E402,F401

from cfdcalc import risk  # noqa: E402
from cfdcalc.analysis import BUY, ERROR, NO_DATA, SELL, WAIT  # noqa: E402
from cfdcalc.ui_risk import AccountDialog, SpecDialog, load_account, load_spec  # noqa: E402


def setup_account(w, ccy="USD", equity="50 000", pct="2"):
    w.s.setValue("account/equity", equity.replace(" ", ""))
    w.s.setValue("account/currency", ccy)
    w.s.setValue("account/risk_pct", pct)
    for k, v in (("contract", "1"), ("min_qty", "0.01"), ("step", "0.01"), ("margin_pct", "5")):
        w.s.setValue(f"spec/XAU_USD/{k}", v)


def m15_signal(verdict):
    """v2.8: the risk page is fed by the M15 signal of the main screen (never by the historical mode)."""
    from datetime import datetime, timezone

    from cfdcalc import m15
    now = datetime.now(timezone.utc)
    if verdict in (BUY, SELL):
        sign = 1 if verdict == BUY else -1
        return m15.Signal(side=verdict, confirmed=True, plan=m15.CONFIRMED, entry=D("100"), sl=D(100 - sign),
                          tp=D(100 + 2 * sign), price_time=now, data_time=now, summary="test")
    side = {WAIT: "NEUTRAL", NO_DATA: "NO DATA", ERROR: "NO DATA"}[verdict]
    return m15.Signal(side=side, summary="test", note="test")


def click_m15(app, w, sig):  # noqa: F811
    w.m15.analyze_cached = lambda *a, **k: sig
    n = len(w.latencies)
    w.analyze()
    for _ in range(200):
        app.processEvents()
        if len(w.latencies) > n:
            break
    settle(app, w)


def run(app, make, monkeypatch, verdict, **kw):  # noqa: F811
    w = make(Reader("Gold"))
    setup_account(w)
    w.s.setValue("account/reserve_pct", "0")
    w.bar.set_mode("manual")
    w.set_instrument(w.inst or __import__("cfdcalc.instruments").instruments.BY_SYMBOL["XAU/USD"])
    click_m15(app, w, m15_signal(verdict))
    return w


def test_confirmed_buy_is_sized_and_shown_on_the_card(app, make, monkeypatch):  # noqa: F811
    w = run(app, make, monkeypatch, BUY)       # entry 100, SL 99, TP 102, spread 0.35 (gated + catalogue)
    page = w.risk_page
    out = page.last
    assert out.state == risk.OK and out.qty == risk.floor_step(D(1000) / D("1.35"), D("0.01"))
    assert page.entry.text() == "100.00" and page.sl.text() == "99.00" and page.tp.text() == "102.00"
    assert out.margin == out.notional * D("0.05")
    assert w.pos_lbl.text() == f"POZICE: {risk.fmt_qty(out.qty)} (množství T212)"
    assert "V RÁMCI LIMITU" in page.state.text() and "MAX. MNOŽSTVÍ" in page.qty.text()


def test_editing_a_confirmed_plan_makes_it_orientational(app, make, monkeypatch):  # noqa: F811
    w = run(app, make, monkeypatch, BUY)
    w.risk_page.sl.setText("98")
    w.risk_page.recompute()
    assert w.risk_page.last.state == risk.ORIENTATION and "ruční úprava" in w.risk_page.message.text()


@pytest.mark.parametrize("verdict", [WAIT, NO_DATA, ERROR])
def test_no_confirmed_signal_no_prefilled_plan(app, make, monkeypatch, verdict):  # noqa: F811
    w = run(app, make, monkeypatch, verdict)
    page = w.risk_page
    assert page.entry.text() == page.sl.text() == "" and page.last.qty is None
    assert page.last.state == risk.NODATA and "NELZE SPOČÍTAT" in page.qty.text()
    page.entry.setText("100")
    page.sl.setText("101")                       # manual SELL scenario
    page.recompute()
    assert page.last.state == risk.ORIENTATION and page.last.direction == SELL


def test_instrument_change_clears_the_plan(app, make, monkeypatch):  # noqa: F811
    reader = Reader("Gold")
    w = make(reader)
    setup_account(w)
    ticks(app, w)
    assert w.inst.symbol == "XAU/USD"
    click_m15(app, w, m15_signal(BUY))
    assert w.risk_page.last.qty is not None and w.pos_lbl.text() != "POZICE: –"
    reader.set("EUR/USD")
    ticks(app, w)
    assert w.risk_page.inst.symbol == "EUR/USD" and w.risk_page.entry.text() == "" and w.risk_page.last.qty is None
    assert w.pos_lbl.text() == "POZICE: –" and w.entry_lbl.text() == "VSTUP: –"


def test_fx_is_fetched_only_when_it_is_the_last_missing_piece(app, make, monkeypatch):  # noqa: F811
    calls = []

    class TD:
        def exchange_rate(self, base, quote):
            calls.append((base, quote))
            from datetime import datetime, timezone
            return D("23"), datetime.now(timezone.utc)

        def redact(self, t):
            return t
    w = make(Reader("Gold"))
    monkeypatch.setattr(type(w), "provider", lambda self: type("P", (), {"provider": TD()})())
    w.s.setValue("account/currency", "CZK")
    w.bar.set_mode("manual")
    from cfdcalc.instruments import BY_SYMBOL
    w.set_instrument(BY_SYMBOL["XAU/USD"])
    w.risk_page.load(w.inst, None)
    assert not calls                              # no equity / spec / plan yet: no request
    setup_account(w, "CZK")
    w.s.setValue("account/reserve_pct", "0")
    click_m15(app, w, m15_signal(BUY))
    for _ in range(50):
        app.processEvents()
        if w.risk_page.last.state == risk.OK:
            break
        import time
        time.sleep(0.02)
    assert calls == [("USD", "CZK")] and w.risk_page.last.state == risk.OK
    assert w.risk_page.last.fx.source == "Twelve Data" and "1 USD = 23" in w.risk_page.message.text()


def test_account_and_spec_dialogs(app, make):  # noqa: F811
    w = make(Reader("Gold"))
    d = AccountDialog(w.s, w)
    d.equity.setText("50 000")
    d.currency.setCurrentText("EUR")
    d.risk.setValue(0.5)
    d.save()
    acc = load_account(w.s)
    assert acc.equity == 50000 and acc.currency == "EUR" and acc.risk_pct == D("0.5") and acc.budget == 250
    d = AccountDialog(w.s, w)
    d.equity.setText("padesát")
    d.save()
    assert "kladné číslo" in d.error.text() and load_account(w.s).equity == 50000      # invalid input not saved
    from cfdcalc.instruments import BY_SYMBOL
    sd = SpecDialog(w.s, BY_SYMBOL["NVDA"], "EUR", w)
    sd.edits["contract"].setText("1")
    sd.edits["min_qty"].setText("0,01")
    sd.edits["step"].setText("0.01")
    sd.rate.setText("0,92")
    sd.save()
    spec = load_spec(w.s, BY_SYMBOL["NVDA"])
    assert spec.min_qty == D("0.01") and spec.margin_pct is None and not spec.missing()
    assert w.fx_for("USD", "EUR").rate == D("0.92") and w.fx_for("USD", "EUR").source == "ruční zadání"
