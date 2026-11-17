"""History layer: store provenance, quality checks, Dukascopy decoding, aggregation, HTTP retry/cache."""
import io
import lzma
import struct
import urllib.error
from datetime import datetime, timedelta, timezone

import pytest

from cfdcalc.data import Bar
from cfdcalc.history import quality, sources
from cfdcalc.history.store import Store

T = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)   # Tuesday


def bars(n, start=T, minutes=5, price=100.0):
    return [Bar(start + timedelta(minutes=minutes * k), price, price + 0.1, price - 0.1, price, 1.0) for k in range(n)]


def test_store_provenance_no_rewrite_and_digest(tmp_path):
    st = Store(tmp_path / "h.sqlite")
    s = st.series("dukascopy", "EUR/USD", "EURUSD", "spot", "bid", "5min", licence="osobní", volume_kind="tick")
    assert s.kind == "spot" and s.side == "bid" and s.licence == "osobní" and s.adjusted == "unknown"
    assert st.put_bars(s, bars(10)) == 10
    changed = [Bar(b.t, 999, 999, 999, 999, 1) for b in bars(10)]
    st.put_bars(s, changed)                                       # re-import never rewrites stored history
    assert all(b.c == 100.0 for b in st.bars(s))
    a, b, n = st.span(s)
    assert (a, b, n) == (T, T + timedelta(minutes=45), 10)
    d = st.digest(s)
    assert d == st.digest(s) and len(d) == 16
    with pytest.raises(AssertionError):
        st.series("x", "X", "X", "crypto", "bid", "5min")          # unknown product kinds are rejected


def test_point_in_time_calendar_and_coverage(tmp_path):
    st = Store(tmp_path / "h.sqlite")
    nfp = {"event_id": "nfp", "release": T + timedelta(hours=1), "known_since": T - timedelta(days=30),
           "scheduled": True, "currency": "USD", "title": "Non-Farm Payrolls", "impact": "High"}
    surprise = {"event_id": "x", "release": T + timedelta(minutes=30), "known_since": T + timedelta(minutes=30),
                "scheduled": False, "currency": "USD", "title": "Mimořádné zasedání", "impact": "High"}
    st.put_events("csv", [nfp, surprise], [("USD", T - timedelta(days=1), T + timedelta(days=1))])
    known = [e.title for e in st.events_known_at(("USD",), T)]
    assert known == ["Non-Farm Payrolls"]                              # the surprise was not known yet
    assert "Mimořádné zasedání" in [e.title for e in st.events_known_at(("USD",), T + timedelta(hours=1))]
    assert st.covered("USD", T, T + timedelta(hours=2)) and not st.covered("EUR", T, T + timedelta(hours=2))


def test_quality_findings():
    ok = bars(30)
    assert quality.check(ok, "5min", "spot") == []
    broken = ok[:10] + [ok[9]] + ok[10:20] + ok[22:]                 # duplicate + 2 missing bars
    broken.append(Bar(broken[-1].t + timedelta(minutes=7), 100, 100.1, 99.9, 100, 1))   # misaligned
    broken.append(Bar(broken[-1].t + timedelta(minutes=3), 100, 99, 101, 100, 1))       # high < low
    kinds = {p for _, p, _ in quality.check(broken, "5min", "spot")}
    assert {"duplicate", "gap", "misaligned", "invalid_ohlc"} <= kinds
    jump = ok[:25] + [Bar(ok[25].t, 103, 103.1, 102.9, 103, 1)]
    assert "jump" in {p for _, p, _ in quality.check(jump, "5min", "spot")}


def test_weekend_is_not_a_gap_but_a_weekday_hole_is():
    fri = datetime(2026, 11, 20, 21, 55, tzinfo=timezone.utc)
    sun = datetime(2026, 11, 22, 22, 0, tzinfo=timezone.utc)
    assert quality.check(bars(1, fri) + bars(3, sun), "5min", "spot") == []
    tue = bars(1, T) + bars(3, T + timedelta(hours=3))
    assert [p for _, p, _ in quality.check(tue, "5min", "spot")] == ["gap"]


def test_split_and_crossed_quotes():
    day1 = bars(5, datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc), price=400.0)
    day2 = bars(5, datetime(2026, 11, 17, 15, 0, tzinfo=timezone.utc), price=100.0)   # 4:1 split overnight
    assert "split" in {p for _, p, _ in quality.check(day1 + day2, "5min", "stock")}
    bid, ask = bars(3), bars(3, price=99.9)
    assert [p for _, p, _ in quality.check_pair(bid, ask)] == ["crossed"] * 3
    assert quality.severe_times([(T, "gap", ""), (T, "jump", "")]) == [T]


def bi5(records, alone=True):
    raw = b"".join(struct.pack(">IIIIIf", *r) for r in records)
    return lzma.compress(raw, format=lzma.FORMAT_ALONE if alone else lzma.FORMAT_XZ)


def test_dukascopy_decoding_drops_tickless_minutes_and_fails_closed():
    day = datetime(2026, 11, 17, tzinfo=timezone.utc)
    rec = [(0, 108450, 108460, 108440, 108470, 1.5), (60, 108460, 108460, 108460, 108460, 0.0),
           (120, 108460, 108455, 108450, 108465, 2.0)]
    out = sources.parse_bi5(bi5(rec), day, 1e5)
    assert [b.t for b in out] == [day, day + timedelta(minutes=2)]           # zero-volume minute dropped
    assert out[0].o == pytest.approx(1.0845) and out[0].c == pytest.approx(1.0846)
    assert out[0].l == pytest.approx(1.0844) and out[0].h == pytest.approx(1.0847)
    assert sources.parse_bi5(b"", day, 1e5) == []
    wrong_order = [(k * 60, 108470, 108440, 108460, 108450, 1.0) for k in range(10)]   # high/low swapped
    with pytest.raises(sources.SourceError, match="formát neodpovídá"):
        sources.parse_bi5(bi5(wrong_order), day, 1e5)
    with pytest.raises(sources.SourceError):
        sources.parse_bi5(b"not lzma at all", day, 1e5)


def test_aggregate_and_mid():
    one = [Bar(T + timedelta(minutes=k), 100 + k, 100.5 + k, 99.5 + k, 100.2 + k, 1.0) for k in range(10)]
    five = sources.aggregate(one, "5min")
    assert len(five) == 2 and five[0].o == 100 and five[0].c == pytest.approx(104.2)
    assert five[0].h == pytest.approx(104.5) and five[0].l == pytest.approx(99.5) and five[0].v == 5.0
    bid = [Bar(T, 1, 2, 0.5, 1.5, None)]
    ask = [Bar(T, 1.2, 2.2, 0.7, 1.7, None), Bar(T + timedelta(minutes=5), 1, 1, 1, 1, None)]
    m = sources.mid(bid, ask)
    assert len(m) == 1 and m[0].o == pytest.approx(1.1) and m[0].c == pytest.approx(1.6)


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_http_retries_only_transient_errors_and_caches(tmp_path, monkeypatch):
    calls = []

    def urlopen(req, timeout):
        calls.append(req.full_url)
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 429, "busy", {}, None)
        return Resp(b"payload")
    monkeypatch.setattr(sources.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(sources.time, "sleep", lambda s: None)
    http = sources.Http(tmp_path, min_interval=0)
    assert http.get("https://example.invalid/a") == b"payload" and len(calls) == 2
    assert http.get("https://example.invalid/a") == b"payload" and len(calls) == 2      # served from cache

    def not_found(req, timeout):
        calls.append(req.full_url)
        raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)
    monkeypatch.setattr(sources.urllib.request, "urlopen", not_found)
    n = len(calls)
    assert http.get("https://example.invalid/b", missing_ok=True) == b"" and len(calls) == n + 1
    with pytest.raises(sources.SourceError, match="HTTP 404"):
        http.get("https://example.invalid/c")
    assert len(calls) == n + 2                                                          # 404 is never retried


def test_dukascopy_import_stops_at_the_time_budget_and_backoff_grows(monkeypatch, tmp_path):
    import time as clock
    with pytest.raises(sources.SourceError, match="časový rozpočet"):
        sources.dukascopy("EUR/USD", T, T + timedelta(days=3), sources.Http(tmp_path), deadline=clock.monotonic() - 1)
    waits = []
    monkeypatch.setattr(sources.time, "sleep", waits.append)

    def busy(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, None)
    monkeypatch.setattr(sources.urllib.request, "urlopen", busy)
    with pytest.raises(sources.SourceError, match="HTTP 503"):
        sources.Http(None, min_interval=0, retries=3, backoff=10.0).get("https://example.invalid/x")
    assert waits == [10.0, 20.0, 40.0]
