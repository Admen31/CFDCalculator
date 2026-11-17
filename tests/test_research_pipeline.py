"""Integration: synthetic bid/ask minutes -> import -> quality -> market -> full protocol -> CSV + HTML report."""
import csv
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from cfdcalc.data import synthetic_bars
from cfdcalc.engine import Costs
from cfdcalc.history import importer, sources
from cfdcalc.history.store import Store
from cfdcalc.report import research_text, write_csv, write_html
from cfdcalc.validation import research

END = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


def fake_dukascopy(symbol, start, end, http):
    mid = synthetic_bars(END, 1, 60 * 24 * 14, drift=0.00002, amp=0.3, noise=0.02, seed=9)[:-1]
    half = 0.004
    return {"bid": [replace(b, o=b.o - half, h=b.h - half, l=b.l - half, c=b.c - half, v=5.0) for b in mid],
            "ask": [replace(b, o=b.o + half, h=b.h + half, l=b.l + half, c=b.c + half, v=5.0) for b in mid]}


def test_full_pipeline_offline(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "dukascopy", fake_dukascopy)
    st = Store(tmp_path / "h.sqlite")
    summary = importer.import_dukascopy(st, "EUR/USD", END - timedelta(days=14), END, http=None)
    assert summary["5min"] == 14 * 288 and summary["1h"] == 14 * 24
    s = st.find("dukascopy", "EURUSD", "mid", "5min")
    assert s.kind == "spot" and s.licence.startswith("Dukascopy") and st.quality(s) == []
    m = importer.market(st, "EUR/USD", "dukascopy")
    assert len(m.bid5) == len(m.ask5) == len(m.mid5) and all(b.v is None for b in m.mid5)   # tick volume unused
    res = research(m, Costs(spread_floor=0.01, slippage=0.001))
    res["source"] = "dukascopy"
    for strat in ("v2.1", "v2.0", "náhodný"):
        total = res["parts"][strat]["celkem"]["net"]["n"]
        assert total == sum(res["parts"][strat][p]["net"]["n"] for p in ("vývoj", "validace", "test"))
    assert set(res["sensitivity"]) >= {"výchozí (v2.1)", "SL 1,0×ATR", "TP 3 R"}
    assert res["selection"]["best_on_dev"] in res["sensitivity"]
    assert res["final"]["edge"] in (True, False) and res["news_tested_share"] == 0.0
    text = research_text(res)
    assert "ZÁVĚREČNÝ TEST v2.1" in text and "náhodný" in text and "Citlivost" in text
    prov = [{"symbol": "EUR/USD", "source": "dukascopy", "kind": "spot", "side": "mid", "interval": "5min",
             "start": "x", "end": "y", "bars": 1, "severe": 0, "gaps": 0, "digest": st.digest(s), "licence": "l",
             "notes": ""}]
    write_csv([res], prov, tmp_path / "out")
    path = write_html([res], prov, {"commit": "abc", "seed": 1}, tmp_path / "out")
    text = path.read_text(encoding="utf-8")
    assert "Závěrečný test v2.1" in text and st.digest(s) in text and "NETESTOVÁN" in text
    rows = list(csv.DictReader((tmp_path / "out" / "summary.csv").open(encoding="utf-8")))
    assert {r["strategie"] for r in rows} == {"v2.1", "v2.0", "náhodný"} and len(rows) == 3 * 4
    trades = list(csv.DictReader((tmp_path / "out" / "trades.csv").open(encoding="utf-8")))
    for t in trades:
        assert abs(float(t["gross_R"]) - (float(t["net_R"]) + float(t["spread_R"]) + float(t["slippage_R"])
                                          + float(t["ostatní_R"]))) < 1e-9


def test_level_verification_rejects_wrong_divisor(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "dukascopy", fake_dukascopy)
    st = Store(tmp_path / "h.sqlite")
    importer.import_dukascopy(st, "EUR/USD", END - timedelta(days=14), END, http=None)
    ref = st.bars(st.find("dukascopy", "EURUSD", "mid", "1h"))
    assert importer.verify_level(st, "EUR/USD", "EURUSD", ref) is None
    wrong = [replace(b, c=b.c * 10) for b in ref]                       # e.g. a price divisor off by 10
    assert "neodpovídá" in importer.verify_level(st, "EUR/USD", "EURUSD", wrong)
