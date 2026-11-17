"""v2.2.1 UI: a data source failure (XAG/USD HTTP 404) ends cleanly as NO DATA with full diagnostics."""
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtCore")
from test_data_errors import KEY, http_error, install  # noqa: E402
from test_ui_auto import Reader, settle, ticks  # noqa: E402
from test_ui_smooth import app, make  # noqa: E402,F401


def test_silver_404_gives_no_data_with_source_details(app, make, monkeypatch, tmp_path):  # noqa: F811
    calls = install(monkeypatch, lambda p: http_error(404, {"code": 404, "status": "error",
                                                            "message": "**symbol** not found: XAG/USD"}))
    w = make(Reader("Silver"))
    w.s.setValue("api_key", KEY)
    w.s.setValue("td_plan", "Grow")                 # a plan that includes XAG/USD: the 404 path itself
    w.start()
    settle(app, w)
    assert w.inst.symbol == "XAG/USD" and w.result.verdict.text() == "NO DATA" and not w.running()
    assert w.gauge.isEnabled() and w.gauge.target == 5                                     # 1/20 steps, not stuck
    reason = w.result.reason.text()
    assert "Silver (XAG/USD)" in reason and "interval 5min" in reason and "HTTP 404" in reason
    html = w.result.detail.toPlainText()
    assert "Zdroj dat: Twelve Data | Symbol: XAG/USD | Interval: 5min | Stav: nedostupné" in html
    assert KEY not in html and KEY not in reason
    record = json.loads((tmp_path / "availability.json").read_text(encoding="utf-8"))
    assert record["Twelve Data|XAG/USD"]["5min"]["state"] == "not_found"
    n = len(calls)
    w.set_instrument(w.bar.tracker.confirmed)            # recognising silver again: status from the local record
    w.on_instrument_changed(w.inst)
    assert "nedostupné" in w.step.text() and len(calls) == n                                 # no network request


def test_eur_and_gold_still_analyse_after_silver_fails(app, make, monkeypatch):  # noqa: F811
    from datetime import datetime

    from conftest import T0
    from test_data_errors import bars_json

    from cfdcalc import ui

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return T0
    monkeypatch.setattr(ui, "datetime", Clock)

    def behaviour(p):
        if p["symbol"] == "XAG/USD":
            return http_error(404, {"code": 404, "status": "error", "message": "**symbol** not found"})
        return bars_json(p["symbol"], 300)
    install(monkeypatch, behaviour)
    reader = Reader("Silver")
    w = make(reader)
    w.s.setValue("api_key", KEY)
    w.s.setValue("td_per_minute", 60)       # a paid plan: 9 requests in a minute are allowed (free plan: see below)
    w.s.setValue("td_plan", "Grow")
    w.start()
    settle(app, w)
    detail = w.result.detail.toPlainText()          # silver: exact source fails -> labelled reference ETF
    assert "Symbol: XAG/USD | Interval: 5min | Stav: nedostupné" in detail and "REFERENČNÍ" in detail
    for name, symbol in (("Gold", "XAU/USD"), ("EUR/USD", "EUR/USD")):
        reader.set(name)
        ticks(app, w)
        w.start()
        settle(app, w)
        detail = w.result.detail.toPlainText()
        assert w.analysed.symbol == symbol and w.result.verdict.text() in ("WAIT", "BUY", "SELL"), detail
        for interval in ("5min", "15min", "1h"):
            assert f"Symbol: {symbol} | Interval: {interval} | Stav: dostupné" in detail


def test_basic_plan_never_requests_silver_and_uses_the_labelled_reference(app, make, monkeypatch):  # noqa: F811
    from datetime import datetime

    from conftest import T0
    from test_data_errors import bars_json

    from cfdcalc import ui

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return T0
    monkeypatch.setattr(ui, "datetime", Clock)
    seen = install(monkeypatch, lambda p: bars_json(p["symbol"], 300))
    w = make(Reader("Silver"))
    w.s.setValue("api_key", KEY)
    w.s.setValue("td_plan", "Basic")
    w.start()
    settle(app, w)
    symbols = {q["symbol"] for _, _, q in seen if "symbol" in q}
    detail = w.result.detail.toPlainText()
    assert "XAG/USD" not in symbols and symbols == {"SLV"}            # no request the plan would refuse
    assert "vyžaduje tarif Twelve Data Grow" in detail and "REFERENČNÍ TRŽNÍ DATA" in detail
    assert w.result.levels.text() == "" and not w.result.verdict.text().startswith("NO DATA")
