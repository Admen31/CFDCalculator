"""Out-of-sample validation of the strategy on one instrument.

Protocol (fixed before looking at results):
  * time split of the evaluated period: development 50 %, validation 25 %, final test 25 % (chronological);
  * the live rules (v2.1, default Params) are the pre-registered strategy; v2.0 and a random-entry benchmark with
    the same SL/TP/costs are references;
  * parameter variants are run on development + validation ONLY; the variant that is best on development is shown
    on validation to make selection bias visible; the final test is never used to choose anything;
  * walk-forward: the whole period in 6 consecutive segments shows stability over time;
  * uncertainty: bootstrap 95 % interval of expectancy (seeded) and a one-sided p-value for "expectancy > 0",
    Bonferroni-adjusted for the number of strategy configurations tried.
"""
from __future__ import annotations

import random
import zlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from statistics import mean, median

from .analysis import BASE, BUY, DEFAULTS, NO_DATA, SELL, Params, Settings
from .engine import Costs, Market, RandomEntries, Run, Trade, run, v20, v21

SENSITIVITY = [("SL 1,0×ATR", Params(sl_atr=1.0)), ("SL 2,0×ATR", Params(sl_atr=2.0)),
               ("TP 1,5 R", Params(tp_r=1.5)), ("TP 3 R", Params(tp_r=3.0)),
               ("shoda ≥ 50 %", Params(min_share=0.5)), ("shoda ≥ 80 %", Params(min_share=0.8))]
CONFIGS_TRIED = 1 + len(SENSITIVITY)       # for the multiple-testing adjustment
PARTS = ("vývoj", "validace", "test")
SEED = 20261117


def metrics(rs: list[float]) -> dict:
    """Trades, win rate, profit factor, expectancy (mean R), median R, total R, max drawdown (R),
    longest losing streak."""
    if not rs:
        return {"n": 0, "win": None, "pf": None, "exp": None, "median": None, "total": 0.0, "dd": 0.0,
                "streak": 0}
    wins, losses = sum(x for x in rs if x > 0), -sum(x for x in rs if x <= 0)
    equity = peak = dd = 0.0
    streak = longest = 0
    for x in rs:
        equity += x
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
        streak = streak + 1 if x <= 0 else 0
        longest = max(longest, streak)
    return {"n": len(rs), "win": sum(1 for x in rs if x > 0) / len(rs), "pf": wins / losses if losses > 0 else None,
            "exp": mean(rs), "median": median(rs), "total": equity, "dd": dd, "streak": longest}


def bootstrap(rs: list[float], seed: int = SEED, n: int = 2000) -> dict:
    """95 % percentile interval of the mean and the share of resampled means <= 0 (one-sided p-value)."""
    if len(rs) < 2:
        return {"lo": None, "hi": None, "p": None}
    rng = random.Random(seed)
    k = len(rs)
    means = sorted(sum(rng.choice(rs) for _ in range(k)) / k for _ in range(n))
    return {"lo": means[int(0.025 * n)], "hi": means[int(0.975 * n) - 1],
            "p": sum(1 for x in means if x <= 0) / n}


def sample_note(n: int) -> str:
    if n < 30:
        return "nedostatečný vzorek (< 30 obchodů) – nelze interpretovat"
    if n < 100:
        return "malý vzorek (< 100 obchodů) – jen orientačně"
    return "vzorek ≥ 100 obchodů"


@dataclass
class Periods:
    start: datetime
    dev_end: datetime
    val_end: datetime
    end: datetime

    def part(self, t: datetime) -> str:
        return "vývoj" if t < self.dev_end else "validace" if t < self.val_end else "test"


def periods(times: list[datetime]) -> Periods:
    n = len(times)
    return Periods(times[0], times[n // 2], times[(3 * n) // 4], times[-1])


def folds(p: Periods, k: int = 6) -> list[tuple[datetime, datetime]]:
    step = (p.end - p.start) / k
    return [(p.start + step * n, p.start + step * (n + 1)) for n in range(k)]


def _net(trades: list[Trade]) -> list[float]:
    return [t.net_r for t in trades if t.net_r is not None]


def summarize(r: Run, p: Periods, part: str | None = None) -> dict:
    trades = [t for t in r.trades if part is None or p.part(t.signal_time) == part]
    verdicts = Counter(v for t, v, _ in r.outcomes if part is None or p.part(t) == part)
    rs = _net(trades)
    return {"verdicts": verdicts, "net": metrics(rs), "gross": metrics([t.gross_r for t in trades]),
            "spread_only": metrics([t.gross_r - t.spread_r for t in trades]), "ci": bootstrap(rs),
            "note": sample_note(len(rs))}


def research(m: Market, costs: Costs, cfg: Settings = DEFAULTS, progress=lambda msg: None) -> dict:
    """Run the full protocol for one instrument. Returns plain data for the report."""
    times = [b.t for b in m.mid5]
    p = periods(times[249:]) if len(times) > 600 else periods(times)
    out: dict = {"symbol": m.inst.symbol, "name": m.inst.name, "periods": p, "costs": costs}
    progress(f"{m.inst.symbol}: v2.1")
    base = run(m, v21, "v2.1", costs, cfg)
    progress(f"{m.inst.symbol}: v2.0")
    old = run(m, v20, "v2.0", costs, cfg)
    with_data = sum(1 for _, v, _ in base.outcomes if v != NO_DATA)
    rate = len(base.trades) / with_data if with_data else 0.0
    progress(f"{m.inst.symbol}: náhodný model")
    rnd = run(m, RandomEntries(rate, SEED ^ zlib.crc32(m.inst.symbol.encode())), "náhodný", costs, cfg)
    out["runs"] = {"v2.1": base, "v2.0": old, "náhodný": rnd}
    out["parts"] = {name: {part: summarize(r, p, part) for part in PARTS} | {"celkem": summarize(r, p)}
                    for name, r in out["runs"].items()}
    out["folds"] = [{name: metrics(_net([t for t in r.trades if a <= t.signal_time < b]))
                     for name, r in out["runs"].items()} | {"od": a, "do": b} for a, b in folds(p)]
    # sensitivity on development + validation only
    sens = {}
    for label, params in SENSITIVITY:
        progress(f"{m.inst.symbol}: citlivost {label}")
        rv = run(m, v21, f"v2.1 {label}", costs, cfg, params=params, end=p.val_end)
        sens[label] = {part: metrics(_net([t for t in rv.trades if p.part(t.signal_time) == part]))
                       for part in ("vývoj", "validace")}
    sens["výchozí (v2.1)"] = {part: out["parts"]["v2.1"][part]["net"] for part in ("vývoj", "validace")}
    out["sensitivity"] = sens
    ranked = sorted(sens.items(), key=lambda kv: (kv[1]["vývoj"]["exp"] if kv[1]["vývoj"]["exp"] is not None
                                                  else -9e9), reverse=True)
    best, best_res = ranked[0]
    out["selection"] = {"best_on_dev": best, "dev": best_res["vývoj"], "validation": best_res["validace"],
                        "baseline_validation": sens["výchozí (v2.1)"]["validace"]}
    test = out["parts"]["v2.1"]["test"]
    pval = test["ci"]["p"]
    out["final"] = {"metrics": test["net"], "ci": test["ci"],
                    "p_adjusted": None if pval is None else min(1.0, pval * CONFIGS_TRIED),
                    "edge": bool(test["net"]["n"] >= 30 and test["ci"]["lo"] is not None and test["ci"]["lo"] > 0
                                 and pval is not None and pval * CONFIGS_TRIED < 0.05)}
    by_hour, by_regime = defaultdict(list), defaultdict(list)
    for t in base.trades:
        by_hour[t.hour].append(t.net_r)
        by_regime[f"{t.regime} / volatilita {t.volatility}"].append(t.net_r)
    out["by_hour"] = {h: metrics(rs) for h, rs in sorted(by_hour.items())}
    out["by_regime"] = {k: metrics(rs) for k, rs in sorted(by_regime.items())}
    out["rejected"] = Counter(reason for _, _, reason in base.rejected)
    out["reasons"] = Counter(reason for _, v, reason in base.outcomes if v not in (BUY, SELL))
    out["news_tested_share"] = (sum(1 for t in base.trades if t.news_tested) / len(base.trades)
                                if base.trades else 0.0)
    out["params"] = BASE
    return out
