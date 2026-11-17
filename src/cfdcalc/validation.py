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
from .engine import Costs, Market, RandomEntries, Run, Trade, run, v20, v21, windows

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


# ---------------------------------------------------------------- v2.3: new strategies, pre-registered promotion

RELAXED = "v21_max1"                        # v2.1 with one voter allowed against the trend (tests the "0 proti" rule)
STRATEGY_KEYS = ("pullback", "breakout", "meanrev", RELAXED)
NEW_CONFIGS = len(STRATEGY_KEYS)            # Bonferroni factor: candidates tested, parameters fixed in advance
PROMOTION = ("souhrnně přes instrumenty na závěrečném testu: ≥ 100 obchodů, dolní mez 95% intervalu ⌀ R po "
             "nákladech > 0, p × 4 < 0,05, ⌀ R na validaci > 0, ≥ 4 ze 6 walk-forward úseků s ⌀ R > 0 "
             "a lepší než náhodné vstupy")


def strategy_study(m: Market, costs: Costs, cfg: Settings = DEFAULTS, progress=lambda msg: None) -> dict:
    """v2.1, the three v2.3 strategies and a random-entry benchmark on one instrument, same periods and costs."""
    from .strategies import backtest_strategy
    times = [b.t for b in m.mid5]
    p = periods(times[249:]) if len(times) > 600 else periods(times)
    runs = {}
    progress(f"{m.inst.symbol}: v2.1")
    runs["v2.1"] = run(m, v21, "v2.1", costs, cfg)
    for key in STRATEGY_KEYS:
        progress(f"{m.inst.symbol}: {key}")
        runs[key] = (run(m, v21, key, costs, cfg, params=Params(max_against=1)) if key == RELAXED
                     else run(m, backtest_strategy(key), key, costs, cfg))
    with_data = sum(1 for _, v, _ in runs["v2.1"].outcomes if v != NO_DATA) or 1
    rate = mean(len(runs[k].trades) for k in STRATEGY_KEYS) / with_data
    runs["náhodný"] = run(m, RandomEntries(rate, SEED ^ zlib.crc32(m.inst.symbol.encode())), "náhodný", costs, cfg)
    out = {"symbol": m.inst.symbol, "name": m.inst.name, "kind": m.inst.kind, "periods": p, "runs": runs}
    out["parts"] = {k: {part: summarize(r, p, part) for part in PARTS} | {"celkem": summarize(r, p)}
                    for k, r in runs.items()}
    fl = folds(p)
    out["folds"] = {k: [_net([t for t in r.trades if a <= t.signal_time < b]) for a, b in fl] for k, r in runs.items()}
    out["by_regime"] = {k: {g: metrics(rs) for g, rs in sorted(_group(r.trades).items())} for k, r in runs.items()}
    return out


def _group(trades: list[Trade]) -> dict[str, list[float]]:
    g = defaultdict(list)
    for t in trades:
        g[f"{t.regime} / volatilita {t.volatility}"].append(t.net_r)
    return g


def promotion(studies: list[dict]) -> dict:
    """Pooled out-of-sample verdict per strategy (the only way a strategy may leave research mode)."""
    out = {}
    for key in ("v2.1",) + STRATEGY_KEYS + ("náhodný",):
        def pool(part, key=key):
            return [t.net_r for s in studies for t in s["runs"][key].trades
                    if t.net_r is not None and s["periods"].part(t.signal_time) == part]
        test, val = pool("test"), pool("validace")
        folds_ = [sum((s["folds"][key][n] for s in studies), []) for n in range(6)]
        positive = sum(1 for f in folds_ if f and mean(f) > 0)
        ci = bootstrap(test)
        p_adj = None if ci["p"] is None else min(1.0, ci["p"] * NEW_CONFIGS)
        out[key] = {"test": metrics(test), "validation": metrics(val), "ci": ci, "p_adjusted": p_adj,
                    "folds_positive": positive, "folds": [metrics(f) for f in folds_],
                    "by_instrument": {s["symbol"]: s["parts"][key]["test"]["net"] for s in studies}}
    rnd = out["náhodný"]["test"]["exp"]
    for key in STRATEGY_KEYS:
        o = out[key]
        checks = {"≥ 100 obchodů v testu": o["test"]["n"] >= 100,
                  "dolní mez intervalu > 0": o["ci"]["lo"] is not None and o["ci"]["lo"] > 0,
                  "p × 4 < 0,05": o["p_adjusted"] is not None and o["p_adjusted"] < 0.05,
                  "validace ⌀ R > 0": (o["validation"]["exp"] or 0) > 0,
                  "≥ 4/6 úseků kladných": o["folds_positive"] >= 4,
                  "lepší než náhodné vstupy": o["test"]["exp"] is not None and (rnd is None or o["test"]["exp"] > rnd)}
        o["checks"] = checks
        o["validated"] = all(checks.values())
    return out


# ---------------------------------------------------------------- v2.6: MARKET DIRECTION study

THRESHOLDS = (0.10, 0.20, 0.25, 0.30, 0.40, 0.50)
HORIZONS = {"5m": 1, "15m": 3, "1h": 12}       # bars of 5m after the decision
MIN_COVERAGE = 0.25
DIRECTION_RULE = ("práh |skóre| se vybírá jen na vývojovém období: nejvyšší podíl správných směrů na horizontu 1 h "
                  "mezi prahy, které dávají BUY/SELL aspoň v 25 % rozhodnutí; při shodě nižší práh. Váhy jsou pevné.")


def direction_rows(m: Market, costs: Costs, cfg: Settings = DEFAULTS) -> dict:
    """One row per decision time: direction score (all thresholds derive from it), confirmation before/after
    v2.6, forward moves (graded afterwards only), spread and ATR. Uses exactly the app's functions."""
    from . import direction as dr
    from . import indicators as ind
    from .analysis import ERROR, WAIT, evaluate
    times = [b.t for b in m.mid5]
    p = periods(times[249:]) if len(times) > 600 else periods(times)
    closes = [b.c for b in m.mid5]
    rows, causes = [], Counter()
    for w in windows(m, costs):
        ok = [x is None for x in w.problems]
        before = after = "NO DATA"
        score = quality = None
        if w.problem:
            causes[w.problem.split(" – ")[0].split(":")[0] + ": " + w.problem.split(":", 1)[-1].split("(")[0][:28]
                   .strip()] += 1
        if ok[0] and (ok[1] or ok[2]):                     # direction needs 5m + one higher timeframe
            d = dr.direction(w.s5, w.s15 if ok[1] else None, w.s1 if ok[2] else None, threshold=0.0)
            if d.side != dr.NO_DATA:
                score, quality = d.score, d.quality
        if not w.problem:
            try:
                r = evaluate(m.inst, w.s5, w.s15, w.s1, w.events, w.spread, w.now, cfg)
                after = r.verdict
                demoted = bool(r.reasons) and r.reasons[0].startswith("MARKET DIRECTION je")
                before = r.reasons[0].split("vstup ")[1].split(" ")[0] if demoted else after
            except Exception:  # noqa: BLE001 - counted as a technical error
                before = after = ERROR
        a15 = ind.atr([b.h for b in w.s15], [b.l for b in w.s15], [b.c for b in w.s15])[-1] if ok[1] else None
        fwd = {k: (closes[w.i + h] - closes[w.i]) if w.i + h < len(closes) else None for k, h in HORIZONS.items()}
        rows.append({"sym": m.inst.symbol, "t": w.now, "part": p.part(w.now), "score": score, "quality": quality,
                     "before": before, "after": after if after != WAIT else "WAIT", "fwd": fwd, "atr": a15,
                     "spread": w.spread, "day": w.now.date(),
                     "mom": closes[w.i] - closes[w.i - 12] if w.i >= 12 else None})
    return {"symbol": m.inst.symbol, "rows": rows, "causes": causes}


def _side(score, t):
    return None if score is None else "BUY" if score >= t else "SELL" if score <= -t else "NEUTRAL"


def direction_metrics(rows: list[dict], t: float, horizon: str, side_of=None, cost: float = 1.0) -> dict:
    """Coverage and quality of the direction on `rows` (pooled). Hit = the price moved the indicated way;
    net hit = it moved further than the spread; edge = mean signed move in ATR(15m), gross and after the spread."""
    side_of = side_of or (lambda r: _side(r["score"], t))
    valid = [r for r in rows if r["score"] is not None]
    sides = [(r, side_of(r)) for r in valid]
    calls = [(r, s) for r, s in sides if s in ("BUY", "SELL") and r["fwd"][horizon] is not None and r["atr"]]
    moved = [(r, s) for r, s in calls if r["fwd"][horizon] != 0]
    hits = [(r["fwd"][horizon] > 0) if s == "BUY" else (r["fwd"][horizon] < 0) for r, s in moved]
    signed = [(1 if s == "BUY" else -1) * r["fwd"][horizon] for r, s in calls]
    net = [x - cost * r["spread"] for x, (r, _) in zip(signed, calls, strict=True)]
    edge = [x / r["atr"] for x, (r, _) in zip(signed, calls, strict=True)]
    edge_net = [x / r["atr"] for x, (r, _) in zip(net, calls, strict=True)]
    n = len(rows)
    return {"n": n, "valid": len(valid) / n if n else 0.0, "coverage": len(calls) / len(valid) if valid else 0.0,
            "calls": len(calls), "hit": mean(hits) if hits else None,
            "net_hit": mean(1.0 if x > 0 else 0.0 for x in net) if net else None,
            "edge": mean(edge) if edge else None, "edge_net": mean(edge_net) if edge_net else None,
            "_clusters": [((r["sym"], r["day"]), h) for (r, _), h in zip(moved, hits, strict=True)]}


def cluster_ci(pairs: list[tuple], seed: int = SEED, n: int = 1000) -> tuple[float | None, float | None]:
    """95 % interval of the hit rate, resampling whole instrument-days (neighbouring decisions overlap)."""
    groups = defaultdict(list)
    for key, h in pairs:
        groups[key].append(1.0 if h else 0.0)
    keys = list(groups)
    if len(keys) < 5:
        return None, None
    rng = random.Random(seed)
    stats = []
    for _ in range(n):
        pick = [groups[rng.choice(keys)] for _ in keys]
        tot = sum(len(g) for g in pick)
        stats.append(sum(sum(g) for g in pick) / tot if tot else 0.5)
    stats.sort()
    return stats[int(0.025 * n)], stats[int(0.975 * n) - 1]


def direction_study(all_rows: list[dict]) -> dict:
    """Pooled over instruments: threshold chosen on development data only, then validation and untouched test."""
    part = {k: [r for r in all_rows if r["part"] == k] for k in PARTS}
    grid = {t: {k: {h: direction_metrics(part[k], t, h) for h in HORIZONS} for k in PARTS} for t in THRESHOLDS}
    eligible = [t for t in THRESHOLDS if grid[t]["vývoj"]["1h"]["coverage"] >= MIN_COVERAGE
                and grid[t]["vývoj"]["1h"]["hit"] is not None]
    chosen = max(eligible, key=lambda t: (round(grid[t]["vývoj"]["1h"]["hit"], 4), -t)) if eligible else THRESHOLDS[1]
    out = {"grid": grid, "chosen": chosen, "rule": DIRECTION_RULE}
    test = grid[chosen]["test"]
    out["test_ci"] = {h: cluster_ci(test[h]["_clusters"]) for h in HORIZONS}
    mom = lambda r: None if r["mom"] is None else "BUY" if r["mom"] > 0 else "SELL" if r["mom"] < 0 else None  # noqa
    out["momentum_test"] = {h: direction_metrics(part["test"], 0, h, side_of=mom) for h in HORIZONS}
    out["cost_test"] = {c: direction_metrics(part["test"], chosen, "1h", cost=c) for c in (0.0, 1.0, 2.0, 3.0)}
    out["dist"] = {}
    for k in PARTS + ("celkem",):
        rows = all_rows if k == "celkem" else part[k]
        out["dist"][k] = {"před (v2.1)": Counter(r["before"] for r in rows),
                          "směr v2.6": Counter(_side(r["score"], chosen) or "NO DATA" for r in rows),
                          "vstup v2.6": Counter(r["after"] for r in rows)}
    return out
