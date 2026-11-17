"""v2.3 WAIT diagnostics: why does the v2.1 rule set say WAIT, which conditions block, and would the blocked trades
have been any better than the ones it takes?

Decisions use only bars closed at decision time (engine.windows). The "hypothetical trade" of a bar - entry on the
next bar's open in the 1h trend direction with the live SL/TP construction, full execution costs - is computed
AFTERWARDS from later bars only to grade the filters; it never feeds a decision. Hypothetical trades of
neighbouring bars overlap, so their averages describe the filter, they are not independent samples.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from statistics import mean

from .analysis import BUY, DEFAULTS, ERROR, NO_DATA, PROFILES, SELL, WAIT, Settings, evaluate
from .engine import Costs, Market, _execute, _reason_key, _regime, quotes, windows
from .strategies import BEARISH, BULLISH, bias, context, scan

VERDICTS = (BUY, SELL, WAIT, NO_DATA, ERROR)
GATES = ("Trend 1h", "Shoda indikátorů", "RSI extrém", "Volatilita (ATR)", "Prostor k cíli", "Ekonomické zprávy",
         "Spread", "Časový limit", "Stop-loss")


@dataclass
class _Stub:
    verdict: str
    sl: Decimal
    tp: Decimal


def diagnose(m: Market, costs: Costs, cfg: Settings = DEFAULTS, horizon: int = 12) -> dict:
    inst = m.inst
    bid, ask = quotes(m)
    verdicts, reasons, kind_regime = Counter(), Counter(), defaultdict(Counter)
    blocks, sole = Counter(), Counter()
    hyp = defaultdict(list)                    # gate -> hypothetical net R of bars where it was the ONLY blocker
    taken: list[float] = []                    # hypothetical net R of bars v2.1 actually signalled
    clear = Counter()                          # v2.1 verdicts on bars with a strong bias (all three parts agree)
    clear_blocks = Counter()
    bias_hits = defaultdict(lambda: [0, 0])    # bias -> [price moved its way after `horizon` bars, total]
    setup_states = defaultdict(Counter)
    opportunity = Counter()
    n = 0
    for w in windows(m, costs):
        n += 1
        if w.problem:
            verdicts[NO_DATA] += 1
            reasons[w.problem.split(" – ")[0].split(":")[0]] += 1
            continue
        try:
            r = evaluate(inst, w.s5, w.s15, w.s1, w.events, w.spread, w.now, cfg)
        except Exception as e:  # noqa: BLE001 - counted, never hidden
            verdicts[ERROR] += 1
            reasons[type(e).__name__] += 1
            continue
        verdicts[r.verdict] += 1
        x = context(w.s5, w.s15, w.s1)
        b = bias(x)
        trend, _vol = _regime(w.s15, w.s1)
        kind_regime[f"{PROFILES[inst.kind].name} / {trend}"][r.verdict] += 1
        failed = [name for name, status, _ in r.filters if status == "fail" and name in GATES]
        if r.verdict == WAIT:
            reasons[_reason_key(r.reasons[0] if r.reasons else "")] += 1
            blocks.update(failed)
            if len(failed) == 1:
                sole[failed[0]] += 1
        if abs(b.score) == 4:
            clear[r.verdict] += 1
            if r.verdict == WAIT:
                clear_blocks.update(failed)
        if b.direction in (BULLISH, BEARISH) and w.i + horizon < len(m.mid5):
            sign = 1 if b.direction == BULLISH else -1
            bias_hits[b.direction][0] += sign * (m.mid5[w.i + horizon].c - m.mid5[w.i].c) > 0
            bias_hits[b.direction][1] += 1
        has_volume = all(bar.v is not None for bar in w.s5[-21:]) and sum(bar.v for bar in w.s5[-21:]) > 0
        setups = scan(x, inst.decimals, has_volume)
        for s in setups:
            setup_states[s.key][s.state] += 1
        opportunity["trigger" if any(s.state == "trigger" for s in setups) else
                    "watch" if any(s.state == "watch" for s in setups) else "nic"] += 1
        # hypothetical trade in the 1h trend direction, graded afterwards
        direction = r.direction
        if direction in (BUY, SELL) and x.atr15 and r.verdict in (BUY, SELL, WAIT):
            sign = 1 if direction == BUY else -1
            dist, close = 1.5 * x.atr15, w.s5[-1].c
            t = _execute(m, w.i, _Stub(direction, Decimal(repr(close - sign * dist)),
                                       Decimal(repr(close + sign * 2 * dist))), w.now, costs, cfg, "hyp", bid, ask)
            if not isinstance(t, str):
                if r.verdict in (BUY, SELL):
                    taken.append(t.net_r)
                elif len(failed) == 1:
                    hyp[failed[0]].append(t.net_r)
    return {"symbol": inst.symbol, "name": inst.name, "kind": inst.kind, "bars": n, "verdicts": verdicts,
            "reasons": reasons, "blocks": blocks, "sole": sole,
            "hyp": {k: (len(v), mean(v)) for k, v in hyp.items() if v},
            "taken": (len(taken), mean(taken) if taken else None), "clear": clear, "clear_blocks": clear_blocks,
            "bias_hits": {k: tuple(v) for k, v in bias_hits.items()}, "kind_regime": kind_regime,
            "setups": setup_states, "opportunity": opportunity}


def _pct(a: float, b: float) -> str:
    return f"{100 * a / b:.1f} %" if b else "–"


def merge(results: list[dict]) -> dict:
    tot: dict = {"symbol": "CELKEM", "name": "všechny instrumenty", "bars": 0}
    for key in ("verdicts", "reasons", "blocks", "sole", "clear", "clear_blocks", "opportunity"):
        tot[key] = sum((r[key] for r in results), Counter())
    tot["kind_regime"] = defaultdict(Counter)
    tot["setups"] = defaultdict(Counter)
    hyp, taken, hits = defaultdict(lambda: [0, 0.0]), [0, 0.0], defaultdict(lambda: [0, 0])
    for r in results:
        tot["bars"] += r["bars"]
        for k, c in r["kind_regime"].items():
            tot["kind_regime"][k] += c
        for k, c in r["setups"].items():
            tot["setups"][k] += c
        for k, (cnt, avg) in r["hyp"].items():
            hyp[k][0] += cnt
            hyp[k][1] += cnt * avg
        if r["taken"][0]:
            taken[0] += r["taken"][0]
            taken[1] += r["taken"][0] * r["taken"][1]
        for k, (a, b) in r["bias_hits"].items():
            hits[k][0] += a
            hits[k][1] += b
    tot["hyp"] = {k: (c, s / c) for k, (c, s) in hyp.items() if c}
    tot["taken"] = (taken[0], taken[1] / taken[0] if taken[0] else None)
    tot["bias_hits"] = {k: tuple(v) for k, v in hits.items()}
    return tot


def markdown(results: list[dict]) -> str:
    """Report section per instrument plus the total."""
    rows = []
    for r in results + ([merge(results)] if len(results) > 1 else []):
        v, n = r["verdicts"], sum(r["verdicts"].values())
        rows.append(f"### {r['name']} ({r['symbol']}) – {n} rozhodnutí")
        rows.append("| " + " | ".join(VERDICTS) + " |\n|" + "---|" * len(VERDICTS))
        rows.append("| " + " | ".join(f"{v[k]} ({_pct(v[k], n)})" for k in VERDICTS) + " |")
        rows.append("")
        rows.append("Nejčastější první důvod WAIT/NO DATA: "
                    + "; ".join(f"{k} {c}×" for k, c in r["reasons"].most_common(6)))
        waits = v[WAIT]
        rows.append("")
        rows.append("| podmínka | blokuje (podíl WAIT) | jediná blokující | hypotetický obchod, když blokovala "
                    "jen ona: počet, ⌀ R po nákladech |\n|---|---|---|---|")
        for g in GATES:
            if r["blocks"][g] or r["sole"][g]:
                cnt, avg = r["hyp"].get(g, (0, None))
                rows.append(f"| {g} | {r['blocks'][g]} ({_pct(r['blocks'][g], waits)}) | {r['sole'][g]} | "
                            f"{cnt}, {'–' if avg is None else f'{avg:+.3f}'} |")
        tc, ta = r["taken"]
        rows.append(f"| *signály v2.1 (pro srovnání)* | | | {tc}, {'–' if ta is None else f'{ta:+.3f}'} |")
        cl = r["clear"]
        cn = sum(cl.values())
        rows.append("")
        rows.append(f"Jasný směr (bias se všemi třemi částmi ve shodě): {cn} rozhodnutí, z toho WAIT "
                    f"{cl[WAIT]} ({_pct(cl[WAIT], cn)}), BUY/SELL {cl[BUY] + cl[SELL]}. Blokovalo: "
                    + ("; ".join(f"{k} {c}×" for k, c in r["clear_blocks"].most_common(4)) or "–"))
        hits = r["bias_hits"]
        rows.append("Bias ex post (cena o hodinu později ve směru biasu): " + "; ".join(
            f"{k} {a}/{b} ({_pct(a, b)})" for k, (a, b) in sorted(hits.items())))
        op = r["opportunity"]
        on = sum(op.values())
        rows.append(f"Nové stavy: WATCH v {_pct(op['watch'], on)} rozhodnutí, splněný setup v {_pct(op['trigger'], on)}"
                    "; podle strategie: " + "; ".join(
                        f"{k}: watch {c['watch']}, trigger {c['trigger']}, zaniklý {c['invalid']}"
                        for k, c in sorted(r["setups"].items())))
        rows.append("")
        rows.append("| trh / režim | BUY | SELL | WAIT | NO DATA | ERROR |\n|---|---|---|---|---|---|")
        for k, c in sorted(r["kind_regime"].items()):
            t = sum(c.values())
            rows.append(f"| {k} | " + " | ".join(f"{_pct(c[x], t)}" for x in VERDICTS) + " |")
        rows.append("")
    return "\n".join(rows)
