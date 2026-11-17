"""CSV + HTML report of the research protocol (validation.research results). Plain HTML, no external assets."""
from __future__ import annotations

import csv
import html
from datetime import datetime, timezone
from pathlib import Path

from .validation import CONFIGS_TRIED, PARTS

STRATEGIES = ("v2.1", "v2.0", "náhodný")
VERD = ("BUY", "SELL", "WAIT", "NO DATA", "ERROR")
NO_NEWS = "historický kalendář nebyl k dispozici – filtr zpráv NETESTOVÁN"


def _f(x, fmt="{:+.2f}", none="–"):
    return none if x is None else fmt.format(x)


def _pct(x):
    return "–" if x is None else f"{100 * x:.0f} %"


def _row(cells, tag="td"):
    return "<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>"


def _metric_cells(m):
    return [m["n"], _pct(m["win"]), _f(m["pf"], "{:.2f}"), _f(m["exp"]), _f(m["median"]), _f(m["total"], "{:+.1f}"),
            _f(m["dd"], "{:.1f}"), m["streak"]]


MHEAD = ["obchodů", "zisk.", "PF", "očekávání R", "medián R", "Σ R", "max. pokles R", "ztráty v řadě"]


def research_text(r: dict) -> str:
    """Plain-text summary of one validation.research result (in-app backtest dialog)."""
    f, ci = r["final"], r["final"]["ci"]
    p = r["periods"]
    lines = [f"Období {p.start:%Y-%m-%d} – {p.end:%Y-%m-%d}; vývoj do {p.dev_end:%Y-%m-%d}, validace do "
             f"{p.val_end:%Y-%m-%d}, pak závěrečný test.",
             f"ZÁVĚREČNÝ TEST v2.1: {f['metrics']['n']} obchodů, očekávání {_f(f['metrics']['exp'])} R "
             f"(95% interval {_f(ci['lo'])} až {_f(ci['hi'])}), upravené p = {_f(f['p_adjusted'], '{:.3f}')} → "
             f"{'výhoda doložena' if f['edge'] else 'výhoda NEDOLOŽENA'}. {r['parts']['v2.1']['test']['note']}", ""]
    for strat in STRATEGIES:
        lines.append(f"=== {strat} ===")
        for part in (*PARTS, "celkem"):
            s = r["parts"][strat][part]
            m, v = s["net"], s["verdicts"]
            lines.append(f"  {part:8} BUY {v.get('BUY', 0)} SELL {v.get('SELL', 0)} WAIT {v.get('WAIT', 0)} NO DATA "
                         f"{v.get('NO DATA', 0)} | {m['n']} obch., zisk. {_pct(m['win'])}, PF {_f(m['pf'], '{:.2f}')},"
                         f" ⌀ {_f(m['exp'])} R (bez nákladů {_f(s['gross']['exp'])}), medián {_f(m['median'])}, "
                         f"max. pokles {_f(m['dd'], '{:.1f}')} R, ztráty v řadě {m['streak']}")
    sel = r["selection"]
    lines += ["", f"Citlivost: nejlepší na vývoji {sel['best_on_dev']} ({_f(sel['dev']['exp'])} R) → validace "
              f"{_f(sel['validation']['exp'])} R; výchozí v2.1 na validaci {_f(sel['baseline_validation']['exp'])} R.",
              "Zamítnuté obchody: " + "; ".join(f"{k} {n}×" for k, n in r["rejected"].most_common(5)),
              "Bez historického filtru zpráv. Krátká historie není důkaz ziskovosti."]
    return "\n".join(lines)


def write_csv(results: list[dict], provenance: list[dict], out: Path):
    out.mkdir(parents=True, exist_ok=True)
    with (out / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["instrument", "zdroj", "strategie", "část", "BUY", "SELL", "WAIT", "NO DATA", "ERROR", "obchodů",
                    "win", "PF", "expectancy_R", "median_R", "total_R", "max_dd_R", "max_losing_streak",
                    "gross_expectancy_R", "spread_only_expectancy_R", "ci95_lo", "ci95_hi", "p_one_sided", "poznámka"])
        for r in results:
            for strat in STRATEGIES:
                for part in (*PARTS, "celkem"):
                    s = r["parts"][strat][part]
                    m, g, so, ci = s["net"], s["gross"], s["spread_only"], s["ci"]
                    w.writerow([r["symbol"], r["source"], strat, part, *(s["verdicts"].get(v, 0) for v in VERD),
                                m["n"], m["win"], m["pf"], m["exp"], m["median"], m["total"], m["dd"], m["streak"],
                                g["exp"], so["exp"], ci["lo"], ci["hi"], ci["p"], s["note"]])
    with (out / "trades.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["instrument", "zdroj", "strategie", "signál_utc", "vstup_utc", "výstup_utc", "směr", "vstup", "sl",
                    "tp", "výstup", "způsob", "riziko", "net_R", "gross_R", "spread_R", "slippage_R", "ostatní_R",
                    "režim", "volatilita", "hodina_místní", "zprávy_testovány"])
        for r in results:
            for strat, run in r["runs"].items():
                for t in run.trades:
                    w.writerow([r["symbol"], r["source"], strat, t.signal_time.isoformat(), t.entry_time.isoformat(),
                                t.exit_time.isoformat() if t.exit_time else "", t.direction, t.entry, t.sl, t.tp,
                                t.exit, t.how, t.risk, t.net_r, t.gross_r, t.spread_r, t.slippage_r, t.other_r,
                                t.regime, t.volatility, t.hour, t.news_tested])
    with (out / "rejected.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["instrument", "zdroj", "strategie", "čas_utc", "směr", "důvod"])
        for r in results:
            for strat, run in r["runs"].items():
                for t, d, why in run.rejected:
                    w.writerow([r["symbol"], r["source"], strat, t.isoformat(), d, why])
    with (out / "folds.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["instrument", "zdroj", "od", "do", "strategie", "obchodů", "expectancy_R", "total_R"])
        for r in results:
            for fold in r["folds"]:
                for strat in STRATEGIES:
                    m = fold[strat]
                    w.writerow([r["symbol"], r["source"], fold["od"].isoformat(), fold["do"].isoformat(), strat,
                                m["n"], m["exp"], m["total"]])
    with (out / "sensitivity.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["instrument", "zdroj", "varianta", "část", "obchodů", "expectancy_R", "PF"])
        for r in results:
            for label, parts in r["sensitivity"].items():
                for part, m in parts.items():
                    w.writerow([r["symbol"], r["source"], label, part, m["n"], m["exp"], m["pf"]])
    with (out / "data.csv").open("w", newline="", encoding="utf-8") as f:
        keys = list(provenance[0].keys()) if provenance else []
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(provenance)


def _equity_svg(r: dict, width=640, height=160) -> str:
    series = {s: r["runs"][s].trades for s in STRATEGIES}
    pts = {s: [] for s in STRATEGIES}
    for s, trades in series.items():
        eq = 0.0
        for t in trades:
            eq += t.net_r
            pts[s].append((t.signal_time.timestamp(), eq))
    allp = [p for v in pts.values() for p in v]
    if len(allp) < 2:
        return ""
    x0, x1 = min(p[0] for p in allp), max(p[0] for p in allp)
    y0, y1 = min(0, min(p[1] for p in allp)), max(0, max(p[1] for p in allp))
    sx = lambda x: 40 + (width - 50) * (x - x0) / ((x1 - x0) or 1)  # noqa: E731
    sy = lambda y: 10 + (height - 30) * (1 - (y - y0) / ((y1 - y0) or 1))  # noqa: E731
    colors = {"v2.1": "#2563eb", "v2.0": "#9333ea", "náhodný": "#9ca3af"}
    lines = [f'<line x1="40" x2="{width - 10}" y1="{sy(0):.1f}" y2="{sy(0):.1f}" stroke="#cbd5e1"/>']
    for s, p in pts.items():
        if p:
            path = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in p)
            lines.append(f'<polyline fill="none" stroke="{colors[s]}" stroke-width="1.5" points="{path}"/>')
    for when, label in ((r["periods"].dev_end, "validace"), (r["periods"].val_end, "test")):
        x = sx(when.timestamp())
        lines.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="10" y2="{height - 20}" stroke="#f59e0b" '
                     f'stroke-dasharray="4 3"/><text x="{x + 3:.1f}" y="20" font-size="10">{label}</text>')
    legend = " ".join(f'<tspan fill="{colors[s]}">■ {s}</tspan>' for s in STRATEGIES)
    return (f'<svg width="{width}" height="{height}" role="img" aria-label="Kumulativní R">'
            f'<text x="40" y="{height - 4}" font-size="10">{legend} – kumulativní R po nákladech</text>'
            f'<text x="2" y="{sy(y1):.0f}" font-size="10">{y1:+.0f}</text>'
            f'<text x="2" y="{sy(y0):.0f}" font-size="10">{y0:+.0f}</text>' + "".join(lines) + "</svg>")


def write_html(results: list[dict], provenance: list[dict], meta: dict, out: Path) -> Path:
    e = html.escape
    edge_any = any(r["final"]["edge"] for r in results)
    total_test = sum(r["final"]["metrics"]["n"] for r in results)
    head = (
        "<!doctype html><html lang='cs'><head><meta charset='utf-8'><title>CFD Signal Calculator – výzkumný report"
        "</title><style>body{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#0f172a;max-width:1100px}"
        "table{border-collapse:collapse;margin:8px 0 16px;font-size:12px}td,th{border:1px solid #e2e8f0;"
        "padding:3px 7px;text-align:right}th{background:#f1f5f9}td:first-child,th:first-child{text-align:left}"
        ".bad{color:#b91c1c;font-weight:600}.good{color:#15803d;font-weight:600}.note{color:#475569;font-size:12px}"
        "h2{margin-top:32px;border-bottom:1px solid #e2e8f0}</style></head><body>")
    verdict = ("<p class='good'>Na závěrečném testu je u některého instrumentu statisticky doložené kladné "
               "očekávání po nákladech – viz detail; to samo o sobě není doporučení k reálnému obchodování.</p>"
               if edge_any else
               "<p class='bad'>Obchodní výhoda strategie v2.1 po nákladech NEBYLA prokázána na žádném "
               "testovaném instrumentu (závěrečný test, 95% interval očekávání, korekce na vícenásobné testování).</p>")
    parts = [head, "<h1>CFD Signal Calculator – výzkumný backtest v2.2</h1>",
             f"<p class='note'>Vytvořeno {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC · commit "
             f"{e(meta.get('commit', '?'))} · seed {meta.get('seed')} · obchodů v závěrečných testech celkem "
             f"{total_test}</p>", verdict,
             "<h2>Protokol</h2><ul>"
             "<li>Signály počítá stejná funkce jako aplikace (<code>analysis.evaluate</code>, pravidla v2.1, výchozí "
             "parametry stanovené předem). Signál vidí jen svíčky uzavřené v okamžiku rozhodnutí.</li>"
             "<li>Vstup na otevírací ceně <b>následující</b> 5m svíčky: BUY za ask, SELL za bid; spread nejméně "
             "typický spread Trading 212 (z katalogu); výstup long na bid, short na ask (spread jen jednou); skluz "
             "0,1× spreadu na tržních příkazech; mezera přes SL = horší otevírací cena; SL a TP v jedné svíčce = SL; "
             "nucené ukončení na časovém limitu trhu; vždy jen jedna pozice.</li>"
             "<li>Časové rozdělení: vývoj 50 %, validace 25 %, <b>závěrečný test 25 %</b> – použit jen jednou pro "
             "předem stanovenou strategii. Varianty parametrů pouze na vývoji a validaci.</li>"
             f"<li>Nejistota: bootstrap 95% interval očekávání (seed), jednostranné p pro očekávání > 0, korekce "
             f"Bonferroni ×{CONFIGS_TRIED} (počet zkoušených konfigurací). Výhoda se uzná jen při ≥ 30 obchodech, "
             "dolní mez intervalu > 0 a upraveném p < 0,05.</li>"
             f"<li>Ekonomické zprávy: {e(meta.get('news', NO_NEWS))}"
             "</li><li>Srovnání: v2.0 (zmrazená původní pravidla) a náhodné vstupy se stejnými SL/TP, náklady a "
             "frekvencí obchodů.</li></ul>",
             "<h2>Data a jejich kvalita</h2><table>" + _row(
                 ["instrument", "zdroj", "produkt", "strana", "interval", "od", "do", "svíček", "kvalita: vážné",
                  "mezery", "otisk dat", "licence / poznámka"], "th")]
    for p in provenance:
        parts.append(_row([e(p["symbol"]), e(p["source"]), e(p["kind"]), e(p["side"]), e(p["interval"]),
                           e(p["start"]), e(p["end"]), p["bars"], p["severe"], p["gaps"], e(p["digest"]),
                           e(p["licence"] + (" · " + p["notes"] if p["notes"] else ""))]))
    parts.append("</table>")
    for r in results:
        f = r["final"]
        ci = f["ci"]
        parts.append(f"<h2>{e(r['name'])} ({e(r['symbol'])}) – {e(r['source'])}</h2>")
        parts.append(f"<p class='note'>Období {r['periods'].start:%Y-%m-%d} – {r['periods'].end:%Y-%m-%d}; test od "
                     f"{r['periods'].val_end:%Y-%m-%d}. Náklady: spread min. {r['costs'].spread_floor:g}, skluz "
                     f"{r['costs'].slippage:g} na tržní plnění. Zprávy testovány u "
                     f"{100 * r['news_tested_share']:.0f} % obchodů.</p>")
        cls = "good" if f["edge"] else "bad"
        parts.append(f"<p class='{cls}'>Závěrečný test v2.1: {f['metrics']['n']} obchodů, očekávání "
                     f"{_f(f['metrics']['exp'])} R (95% interval {_f(ci['lo'])} až {_f(ci['hi'])}), upravené p = "
                     f"{_f(f['p_adjusted'], '{:.3f}')} → {'výhoda doložena' if f['edge'] else 'výhoda NEDOLOŽENA'}."
                     f" {e(r['parts']['v2.1']['test']['note'])}</p>")
        parts.append(_equity_svg(r))
        parts.append("<table>" + _row(["strategie / část", *VERD, *MHEAD, "bez nákladů ⌀R", "jen spread ⌀R",
                                       "95% interval ⌀R"], "th"))
        for strat in STRATEGIES:
            for part in (*PARTS, "celkem"):
                s = r["parts"][strat][part]
                parts.append(_row([f"{strat} – {part}", *(s["verdicts"].get(v, 0) for v in VERD),
                                   *_metric_cells(s["net"]), _f(s["gross"]["exp"]), _f(s["spread_only"]["exp"]),
                                   f"{_f(s['ci']['lo'])} … {_f(s['ci']['hi'])}"]))
        parts.append("</table><h3>Walk-forward (6 časových úseků, očekávání R / obchodů)</h3><table>"
                     + _row(["úsek", *STRATEGIES], "th"))
        for fold in r["folds"]:
            parts.append(_row([f"{fold['od']:%Y-%m-%d} – {fold['do']:%Y-%m-%d}",
                               *(f"{_f(fold[s]['exp'])} / {fold[s]['n']}" for s in STRATEGIES)]))
        sel = r["selection"]
        parts.append("</table><h3>Citlivost parametrů (jen vývoj a validace)</h3><table>"
                     + _row(["varianta", "vývoj ⌀R / obchodů", "validace ⌀R / obchodů"], "th"))
        for label, ps in r["sensitivity"].items():
            parts.append(_row([e(label), f"{_f(ps['vývoj']['exp'])} / {ps['vývoj']['n']}",
                               f"{_f(ps['validace']['exp'])} / {ps['validace']['n']}"]))
        parts.append(f"</table><p class='note'>Nejlepší na vývoji: <b>{e(sel['best_on_dev'])}</b> "
                     f"({_f(sel['dev']['exp'])} R) → na validaci {_f(sel['validation']['exp'])} R; výchozí v2.1 na "
                     f"validaci {_f(sel['baseline_validation']['exp'])} R. Výběr podle vývoje se nepřenáší "
                     f"automaticky; závěrečný test se k výběru nepoužil.</p>")
        parts.append("<h3>Podle hodiny vstupu (místní čas, celé období – popisné)</h3><table>"
                     + _row(["hodina", *MHEAD], "th"))
        for h, m in r["by_hour"].items():
            parts.append(_row([h, *_metric_cells(m)]))
        parts.append("</table><h3>Podle tržního režimu (celé období – popisné)</h3><table>"
                     + _row(["režim", *MHEAD], "th"))
        for k, m in r["by_regime"].items():
            parts.append(_row([e(k), *_metric_cells(m)]))
        parts.append("</table><h3>Zamítnuté obchody a důvody WAIT / NO DATA (v2.1)</h3><p class='note'>"
                     + "; ".join(f"{e(k)}: {n}×" for k, n in r["rejected"].most_common()) + "</p><p class='note'>"
                     + "; ".join(f"{e(k)}: {n}×" for k, n in r["reasons"].most_common(10)) + "</p>")
    parts.append("<h2>Omezení interpretace</h2><ul>"
                 "<li>Ceny zdrojů (Dukascopy, Yahoo) nejsou ceny CFD Trading 212; spread je modelován spodní mezí "
                 "z katalogu, skutečné plnění se může lišit.</li>"
                 "<li>Krátká historie a málo obchodů → široké intervaly; walk-forward ukazuje stabilitu, ne jistotu."
                 "</li><li>Bez historického kalendáře není otestován filtr zpráv; obchody kolem zpráv mohou být horší."
                 "</li><li>Výsledky na minulosti nezaručují budoucí výsledky. Report není investiční doporučení.</li>"
                 "</ul></body></html>")
    path = out / "report.html"
    out.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(parts), encoding="utf-8")
    return path
