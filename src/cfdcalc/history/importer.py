"""Import pipeline: provider -> aggregation -> quality checks -> store, and store -> engine.Market."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from ..engine import Market
from ..instruments import BY_SYMBOL
from . import quality, sources
from .store import Store

INTERVALS = ("5min", "15min", "1h")
DUKA_LICENCE = "Dukascopy historický datafeed – jen osobní analýza, data se nepublikují ani neukládají do repozitáře"


def _store_series(st: Store, source: str, symbol: str, provider: str, kind: str, side: str, interval: str,
                  bars, **meta):
    s = st.series(source, symbol, provider, kind, side, interval, **meta)
    st.put_bars(s, bars)
    return s


def import_dukascopy(st: Store, symbol: str, start: datetime, end: datetime, http: sources.Http,
                     deadline: float | None = None) -> dict:
    """Download 1m bid/ask, aggregate to 5m/15m/1h, build mid, run quality checks. Returns a summary."""
    provider, _, kind = sources.DUKASCOPY[symbol]
    raw = sources.dukascopy(symbol, start, end, http, deadline)
    if not raw["bid"] or not raw["ask"]:
        raise sources.SourceError(f"{symbol}: Dukascopy nevrátil žádná data ({provider})")
    meta = {"licence": DUKA_LICENCE, "volume_kind": "tick", "adjusted": "no",
            "notes": "1m svíčky bez ticků vynechány; mid = průměr bid/ask"}
    summary = {}
    for interval in INTERVALS:
        sides = {side: sources.aggregate(raw[side], interval) for side in ("bid", "ask")}
        sides["mid"] = sources.mid(sides["bid"], sides["ask"])
        for side, bars in sides.items():
            s = _store_series(st, "dukascopy", symbol, provider, kind, side, interval, bars, **meta)
            findings = quality.check(st.bars(s), interval, "stock" if BY_SYMBOL[symbol].kind == "stock" else kind)
            if side == "bid":
                ask_s = st.find("dukascopy", provider, "ask", interval)
                if ask_s:
                    findings += quality.check_pair(st.bars(s), st.bars(ask_s))
            st.put_quality(s, findings)
        summary[interval] = len(sides["mid"])
    return summary


def import_yahoo(st: Store, symbol: str, http: sources.Http) -> dict:
    summary = {}
    for interval in INTERVALS:
        f = sources.yahoo(symbol, interval, http)
        m = f.meta
        s = _store_series(st, "yahoo", symbol, m["provider_symbol"], m["kind"], m["side"], interval, f.bars,
                          exchange=m["exchange"], adjusted=m["adjusted"], volume_kind=m["volume_kind"],
                          licence=m["licence"], notes=m["notes"])
        st.put_quality(s, quality.check(st.bars(s), interval, m["kind"]))
        summary[interval] = len(f.bars)
    return summary


def verify_level(st: Store, symbol: str, provider: str, reference: list, tolerance: float = 0.05) -> str | None:
    """Compare the stored mid price level with an independent reference (e.g. Yahoo 1h closes) at common hours.
    Returns a problem description or None. Catches a wrong price divisor or a wrong instrument mapping."""
    s = st.find("dukascopy", provider, "mid", "1h")
    if not s or not reference:
        return "nelze ověřit (chybí data nebo reference)"
    mine = {b.t: b.c for b in st.bars(s)}
    pairs = [(mine[b.t], b.c) for b in reference if b.t in mine]
    if len(pairs) < 20:
        return f"nelze ověřit (jen {len(pairs)} společných hodin)"
    ratios = sorted(a / b for a, b in pairs)
    med = ratios[len(ratios) // 2]
    if abs(med - 1) > tolerance:
        return f"cenová hladina neodpovídá referenci (medián poměru {med:.3f})"
    return None


def market(st: Store, symbol: str, source: str, start: datetime | None = None, use_volume: bool = True) -> Market:
    """Engine input from the store. Quality problems become exclusion times; volume only where it is real
    exchange volume and requested."""
    inst = BY_SYMBOL[symbol]
    provider = {"dukascopy": lambda: sources.DUKASCOPY[symbol][0], "yahoo": lambda: sources.YAHOO[symbol][0]}.get(
        source, lambda: symbol)()
    side = "mid" if source == "dukascopy" else "last"
    frames, severe = {}, []
    for interval in INTERVALS:
        s = st.find(source, provider, side, interval)
        if s is None:
            raise sources.SourceError(f"{symbol}/{source}: chybí řada {interval}")
        bars = st.bars(s, start)
        if not (use_volume and s.volume_kind == "exchange"):
            bars = [replace(b, v=None) for b in bars]
        frames[interval] = bars
        severe += quality.severe_times(st.quality(s))
    bid = ask = None
    if source == "dukascopy":
        bid, ask = (st.bars(st.find(source, provider, x, "5min"), start) for x in ("bid", "ask"))
        severe += quality.severe_times(st.quality(st.find(source, provider, "bid", "5min")))
    return Market(inst, frames["5min"], frames["15min"], frames["1h"], bid, ask, sorted(set(severe)))


def attach_calendar(m: Market, st: Store, currencies: tuple[str, ...]):
    """Point-in-time events; the news filter counts as tested only where every currency is fully covered."""
    def covered(t: datetime) -> bool:
        return all(st.covered(c, t - timedelta(hours=1), t + timedelta(hours=1)) for c in currencies)
    m.events = lambda t: st.events_known_at(currencies, t)
    m.news_covered = covered
    return m
