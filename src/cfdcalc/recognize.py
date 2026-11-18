"""Instrument recognition: OCR text lines -> catalogue match with a confidence and a reason.

Matching works on whole words only (no substrings inside longer words: "AMD" never matches "AMDOCS")
and never across unrelated lines, so similar names are not silently swapped. Two different instruments
found in one reading are ambiguous; the caller then must not trade (WAIT) until the user confirms.

v2.8 (OCR regression fixes):
  * words of DIFFERENT lines were combined for multi-word labels ("Euro / US Dollar" + "Leverage 1:30" became the
    index "US 30", so EUR/USD was reported as ambiguous). Only two ADJACENT lines may now be joined.
  * prices, quantities, margins, percentages and trade-panel words (BUY, SELL, Quantity, Margin, ...) are removed
    before matching, so they can never be read as an instrument.
  * typical OCR confusions in currency pairs are repaired only when the result is a known pair
    ("EURIUSD", "EUR|USD", "EUR1USD" -> EUR/USD, "XAU/USO" -> XAU/USD).
  * locate(): whole-window fallback - picks the instrument written in the LARGEST font (the instrument header),
    and refuses (ambiguous) when another instrument is written almost as large (watchlist, news).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from .instruments import CATALOG, Instrument, labels

CONFIDENT = 0.85   # below this the user confirms the instrument
MARGIN = 0.08      # a runner-up this close makes the reading ambiguous

_ocr = None


def warm_up():
    """Load the OCR model (imports onnxruntime/OpenCV, ~1-2 s); called once in a worker thread at start-up."""
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    return _ocr


def ocr_lines(rgb) -> list[str]:
    """Text lines in an RGB numpy array (RapidOCR, offline)."""
    result, _ = warm_up()(rgb)
    return [line[1] for line in result or []]


# trade-panel and navigation words of Trading 212 (EN / CS) that are never an instrument name
UI_WORDS = {
    "BUY", "SELL", "KOUPIT", "PRODAT", "NAKOUPIT", "NÁKUP", "NAKUP", "PRODEJ", "QUANTITY", "QTY", "MNOŽSTVÍ",
    "MNOZSTVI", "MARGIN", "MARŽE", "MARZE", "LEVERAGE", "PÁKA", "PAKA", "SPREAD", "VALUE", "HODNOTA", "TOTAL",
    "CELKEM", "MARKET", "LIMIT", "STOP", "TAKE", "PROFIT", "LOSS", "ORDER", "ORDERS", "POKYN", "POKYNY", "TRŽNÍ",
    "TRZNI", "CLOSE", "OPEN", "HIGH", "LOW", "POSITION", "POSITIONS", "POZICE", "CHART", "GRAF", "OVERVIEW",
    "PŘEHLED", "PREHLED", "PENDING", "ALERTS", "WATCHLIST", "PORTFOLIO", "LIVE", "PRACTICE", "SEARCH", "HLEDAT",
    "RESULT", "RETURN", "VÝNOS", "INVESTED", "FREE", "FUNDS", "VOLNÉ", "PROSTŘEDKY", "CFD", "SHORT", "LONG",
    "AMOUNT", "ČÁSTKA", "UNITS", "LOT", "LOTS", "CONFIRM", "POTVRDIT", "SWAP", "CHANGE", "ZMĚNA"}
_NUMERIC = re.compile(r"^[+\-−–]?[$€£¥₿%]?[\d.,:%+\-−–/'’ ]*\d[\d.,:%+\-−–/'’ ]*[$€£¥₿%KMBkmb]?$")
_PAIR = re.compile(r"(?<![A-Za-z])([A-Za-z0]{3})\s*[/|Il1\\]\s*([A-Za-z0]{3})(?![A-Za-z])")
_CODE_FIX = {"0": "O"}
_CODE_ALT = {"O": "D", "D": "O", "Q": "O", "I": "L", "L": "I"}


def _pairs() -> set[str]:
    return {i.symbol for i in CATALOG if "/" in i.symbol and len(i.symbol) == 7}


def _repair_pairs(line: str, pairs: set[str]) -> str:
    """Repair OCR confusions inside 3+3 letter pairs, but only into a pair that exists in the catalogue."""
    def fix(m: re.Match) -> str:
        a, b = ("".join(_CODE_FIX.get(ch, ch) for ch in g.upper()) for g in m.groups())
        for x in _variants(a):
            for y in _variants(b):
                if f"{x}/{y}" in pairs:
                    return f"{x}/{y}"
        return m.group(0)
    return _PAIR.sub(fix, line)


def _variants(code: str) -> list[str]:
    out = [code]
    for i, ch in enumerate(code):
        if ch in _CODE_ALT:
            out.append(code[:i] + _CODE_ALT[ch] + code[i + 1:])
    return out


def clean(lines: list[str]) -> list[str]:
    """OCR lines without prices, quantities and trade-panel words; pairs repaired. Empty lines are dropped."""
    pairs, names = _pairs(), _label_norms()
    out = []
    for line in lines:
        line = _repair_pairs(line.strip(), pairs)
        if line.isdigit():                    # "40" of "Germany 40" split into two OCR boxes: keep for joining
            out.append(line)
            continue
        if not line or _NUMERIC.match(line):
            continue
        if _norm(line) in names:              # a whole catalogue label is kept as written ("... Total Stock ...")
            out.append(line)
            continue
        kept = []
        for tok in line.split():
            if tok.upper().strip(".:,") in UI_WORDS:
                continue
            if re.search(r"\d", tok) and re.search(r"[.,:%$€£¥₿+\-−–]", tok.strip(".:")):
                continue                      # 4,083.45 / €38.41 / +0.02% / 1:30 - a number, never a name
            kept.append(tok)
        text = " ".join(kept).strip(" -–|·")
        if text and not text.isdigit():
            out.append(text)
    return out


_NAMES: tuple[int, set[str]] = (0, set())


def _label_norms() -> set[str]:
    global _NAMES
    if _NAMES[0] != len(CATALOG):             # the catalogue grows when the user adds instruments
        _NAMES = (len(CATALOG), {_norm(a) for i in CATALOG for a in labels(i)})
    return _NAMES[1]


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9&]", "", s.upper())


def _words(s: str) -> list[str]:
    return [w for w in (_norm(x) for x in re.split(r"[\s|,;:()\-–]+", s)) if w]


def _contains(seq: list[str], part: list[str]) -> bool:
    n = len(part)
    return any(seq[i:i + n] == part for i in range(len(seq) - n + 1))


def _adjacent(lines: list[str]) -> list[str]:
    """Two neighbouring OCR boxes joined (OCR may split "Germany 40" into "Germany" + "40")."""
    return [f"{a} {b}" for a, b in zip(lines, lines[1:], strict=False)]


def score(alias: str, lines: list[str], tokens: set[str], joined: list[str] | None = None) -> float:
    """1.0 = a whole line equals the alias, 0.95 = the alias words appear as whole words in ONE line (or in two
    adjacent lines), otherwise a fuzzy similarity (only for labels of 4+ characters; short tickers must match
    exactly)."""
    a, words = _norm(alias), _words(alias)
    if not a:
        return 0.0
    best = 0.0
    for line in lines:
        if _norm(line) == a:
            return 1.0
        if _contains(_words(line), words):
            best = 0.95
    if len(words) > 1 and best == 0.0:
        if any(_contains(_words(x), words) for x in (joined if joined is not None else _adjacent(lines))):
            best = 0.95
    if best == 0.0 and len(a) >= 4:
        best = max((0.9 * SequenceMatcher(None, a, _norm(x)).ratio() for x in lines + list(tokens)), default=0.0)
    return best


@dataclass(frozen=True)
class Recognition:
    best: Instrument | None
    score: float
    candidates: tuple[Instrument, ...]
    text: str
    competing: tuple[Instrument, ...] = ()   # other instruments found with (almost) the same certainty
    top: float = 0.0                         # score of the best candidate, even when it was not accepted
    via: str = ""                            # "oblast" | "celé okno" (how the reading was obtained)

    @property
    def confident(self) -> bool:
        return self.best is not None and self.score >= CONFIDENT

    @property
    def reason(self) -> str:
        """Why the reading is not usable (Czech, shown in the UI); empty when confident."""
        if self.confident:
            return ""
        if not self.text.strip():
            return "instrument nerozpoznán – v oblasti není žádný text"
        if len(self.competing) > 1:
            return "nejednoznačné – v oblasti je více instrumentů: " + ", ".join(i.name for i in self.competing[:3])
        if not self.candidates or max(self.score, self.top) < 0.6:
            return f"instrument nerozpoznán – text „{self.text[:40]}“ neodpovídá podporovanému instrumentu"
        return f"instrument nerozpoznán – nízká jistota (text „{self.text[:40]}“)"


def _best_label(inst: Instrument, lines: list[str], tokens: set[str], joined: list[str]) -> tuple[float, list[str]]:
    return max(((score(a, lines, tokens, joined), _words(a)) for a in labels(inst)), key=lambda x: (x[0], len(x[1])))


def match(lines: list[str], catalog: tuple[Instrument, ...] = CATALOG) -> Recognition:
    raw = " | ".join(x for x in lines if x.strip())
    lines = clean(lines)
    tokens = {w for x in lines for w in _words(x)}
    joined = _adjacent(lines)
    if not lines:
        return Recognition(None, 0.0, (), raw)
    scored = sorted(((*_best_label(i, lines, tokens, joined), i) for i in catalog), key=lambda x: -x[0])
    s1, words1, i1 = scored[0]
    # rivals: other instruments matched (almost) as strongly; a shorter label inside the winning label is not
    # a rival ("Oil" inside "Brent Oil")
    floor = CONFIDENT if s1 >= CONFIDENT else 0.0
    rivals = [i for s, w, i in scored[1:] if s >= max(s1 - MARGIN, floor) and s > 0 and not _contains(words1, w)]
    candidates = tuple(i for s, _, i in scored[:6] if s >= 0.5)
    best = i1 if s1 > 0 and not rivals else None
    competing = (i1, *rivals) if rivals and floor else ()
    return Recognition(best, s1 if best else 0.0, candidates, raw, competing, s1, "oblast")


# ---------------------------------------------------------------- whole-window fallback

@dataclass(frozen=True)
class Box:
    text: str
    height: float            # text height in pixels (font size)
    x: float = 0.0
    y: float = 0.0


def ocr_boxes(rgb) -> list[Box]:
    """Text boxes with their height (RapidOCR, offline)."""
    result, _ = warm_up()(rgb)
    out = []
    for item in result or []:
        pts, text = item[0], item[1]
        ys, xs = [p[1] for p in pts], [p[0] for p in pts]
        out.append(Box(text, float(max(ys) - min(ys)), float(min(xs)), float(min(ys))))
    return out


SAME_SIZE = 0.85      # another instrument written at >= 85 % of the largest height -> ambiguous


def _exact(line: str, catalog) -> list[tuple[Instrument, float]]:
    """Instruments named in ONE cleaned line by a whole label (no fuzzy guessing on a whole window)."""
    lw, ln = _words(line), _norm(line)
    hits = []
    for inst in catalog:
        best = 0.0
        for a in labels(inst):
            if _norm(a) == ln:
                best = 1.0
                break
            if _contains(lw, _words(a)):
                best = 0.95
        if best:
            hits.append((inst, best))
    if len(hits) > 1:      # a shorter label inside a longer one ("Oil" in "Brent Oil") is not a second instrument
        top = max(hits, key=lambda h: (h[1], max(len(_words(a)) for a in labels(h[0]) if _contains(lw, _words(a))
                                                 or _norm(a) == ln)))
        hits = [top] if all(h is top or h[1] < top[1] or _inside(h[0], top[0], line) for h in hits) else hits
    return hits


def _inside(small: Instrument, big: Instrument, line: str) -> bool:
    lw = _words(line)
    sw = [_words(a) for a in labels(small) if _contains(lw, _words(a))]
    bw = [_words(a) for a in labels(big) if _contains(lw, _words(a))]
    return bool(sw) and all(any(_contains(b, s) for b in bw) for s in sw)


def locate(boxes: list[Box], catalog: tuple[Instrument, ...] = CATALOG) -> Recognition:
    """The instrument written in the largest font in the window. Never guesses: two different instruments of
    (almost) the same size, or only small mentions, -> not confident."""
    raw = " | ".join(b.text for b in boxes if b.text.strip())
    found: dict[Instrument, tuple[float, float]] = {}       # inst -> (largest height, score)
    for b in boxes:
        for line in clean([b.text]):
            for inst, sc in _exact(line, catalog):
                h, s0 = found.get(inst, (0.0, 0.0))
                found[inst] = (max(h, b.height), max(s0, sc))
    if not found:
        return Recognition(None, 0.0, (), raw, via="celé okno")
    ranked = sorted(found.items(), key=lambda kv: -kv[1][0])
    (top, (h1, s1)) = ranked[0]
    rivals = tuple(i for i, (h, _) in ranked[1:] if h >= SAME_SIZE * h1)
    cands = tuple(i for i, _ in ranked[:6])
    if rivals:
        return Recognition(None, 0.0, cands, raw, (top, *rivals), s1, "celé okno")
    return Recognition(top, s1, cands, raw, (), s1, "celé okno")
