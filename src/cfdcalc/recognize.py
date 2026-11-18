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


# ---------------------------------------------------------------- whole-window / region reading (v2.9)

@dataclass(frozen=True)
class Box:
    """One OCR text box with its geometry (pixels of the captured image) and look."""
    text: str
    height: float                 # text height = font size
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    bg: float | None = None       # luminance (0-255) around the text = background of a tab / button
    fg: float | None = None       # luminance of the text itself (bright text on dark, or dark on light)

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.height / 2


def make_box(lum, text: str, x0: int, y0: int, x1: int, y1: int) -> Box:
    """One OCR box measured on the image: OCR boxes are loose, so the INK of the text is found first (pixels that
    differ from the box border). Font size and position come from the ink (exact whatever the OCR padding), the
    background from a thin ring around the ink, the text luminance from the ink itself."""
    import numpy as np
    h, w = lum.shape
    x0, y0, x1, y1 = max(0, int(x0)), max(0, int(y0)), min(w, int(x1)), min(h, int(y1))
    if x1 - x0 < 3 or y1 - y0 < 3:
        return Box(text, float(max(1, y1 - y0)), float(x0), float(y0), float(max(1, x1 - x0)))
    box = lum[y0:y1, x0:x1]
    border = np.concatenate([box[0], box[-1], box[:, 0], box[:, -1]])
    bg0 = float(np.median(border))
    ink = np.abs(box - bg0) > 40
    if not ink.any():
        return Box(text, float(y1 - y0), float(x0), float(y0), float(x1 - x0), bg0, bg0)
    ys, xs = np.nonzero(ink)
    iy0, iy1, ix0, ix1 = int(ys.min()), int(ys.max()) + 1, int(xs.min()), int(xs.max()) + 1
    ih = max(2, iy1 - iy0)
    pad = max(2, int(ih * 0.35))
    ry0, ry1 = max(0, y0 + iy0 - pad), min(h, y0 + iy1 + pad)
    rx0, rx1 = max(0, x0 + ix0 - pad), min(w, x0 + ix1 + pad)
    ring = lum[ry0:ry1, rx0:rx1].astype(np.float32).copy()
    ring[(y0 + iy0 - ry0):(y0 + iy1 - ry0), (x0 + ix0 - rx0):(x0 + ix1 - rx0)] = np.nan
    vals = ring[~np.isnan(ring)]
    bg = float(np.median(vals)) if vals.size else bg0
    t = box[ink]
    fg = float(np.percentile(t, 90)) if np.median(t) > bg else float(np.percentile(t, 10))
    return Box(text, float(ih), float(x0 + ix0), float(y0 + iy0), float(ix1 - ix0), bg, fg)


def ocr_boxes(rgb) -> list[Box]:
    """Text boxes measured on the image (RapidOCR, offline)."""
    import numpy as np
    result, _ = warm_up()(rgb)
    lum = (0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]).astype(np.float32)
    out = []
    for item in result or []:
        pts, text = item[0], item[1]
        ys, xs = [p[1] for p in pts], [p[0] for p in pts]
        out.append(make_box(lum, text, int(min(xs)), int(min(ys)), int(max(xs)) + 1, int(max(ys)) + 1))
    return out


SAME_SIZE = 0.85        # another candidate written at >= 85 % of the largest height is not "clearly larger"
TRADE_WORDS = {"BUY", "SELL", "KOUPIT", "PRODAT", "NÁKUP", "NAKUP", "PRODEJ"}
ACTIVE_DIFF = 18.0      # luminance difference that marks the active tab / row against the others
UNIFORM = 10.0          # the other tabs must look alike (spread of their look below this)


@dataclass
class _Hit:
    inst: Instrument
    box: Box
    score: float


def _hits(boxes: list[Box], catalog) -> list[_Hit]:
    out = []
    for b in boxes:
        for line in clean([b.text]):
            for inst, sc in _exact(line, catalog):
                out.append(_Hit(inst, b, sc))
    return out


def _collections(hits: list[_Hit]) -> list[list[_Hit]]:
    """Groups of DIFFERENT instruments written alike in one row (tabs) or one column (watchlist)."""
    groups: list[list[_Hit]] = []
    for kind in ("row", "column"):
        used: set[int] = set()
        for i, a in enumerate(hits):
            if i in used:
                continue
            g = [a]
            for j, b in enumerate(hits):
                if j == i or j in used:
                    continue
                hmax = max(a.box.height, b.box.height)
                alike = min(a.box.height, b.box.height) >= 0.6 * hmax      # OCR box heights vary
                if kind == "row":
                    near = abs(a.box.cy - b.box.cy) <= 0.5 * hmax
                else:
                    near = abs(a.box.x - b.box.x) <= 1.2 * hmax and abs(a.box.cy - b.box.cy) <= 12 * hmax
                if alike and near:
                    g.append(b)
            if len({h.inst for h in g}) >= 2:
                used.update(hits.index(h) for h in g)
                groups.append(g)
    return groups


def _look(h: _Hit) -> tuple[float, float] | None:
    b = h.box
    return None if b.bg is None or b.fg is None else (b.bg, abs(b.fg - b.bg))


def _active(group: list[_Hit], screen_bg: float | None = None) -> _Hit | None:
    """The one member that LOOKS different (highlighted background or text) while all others look alike.
    With only two tabs, the active one is the one whose background differs from the screen background."""
    looks = [_look(h) for h in group]
    if any(x is None for x in looks) or len(group) < 2:
        return None
    if len(group) == 2:
        if screen_bg is None:
            return None
        off = [abs(lk[0] - screen_bg) for lk in looks]
        i = 0 if off[0] > off[1] else 1
        return group[i] if off[i] >= ACTIVE_DIFF and off[1 - i] <= UNIFORM else None
    best = None
    for i, h in enumerate(group):
        others = [looks[j] for j in range(len(group)) if j != i]
        mb = sorted(o[0] for o in others)[len(others) // 2]
        mc = sorted(o[1] for o in others)[len(others) // 2]
        spread = max(max(abs(o[0] - mb), abs(o[1] - mc)) for o in others)
        diff = max(abs(looks[i][0] - mb), abs(looks[i][1] - mc))
        if diff >= ACTIVE_DIFF and spread <= UNIFORM:
            if best is not None and best.inst != h.inst:
                return None          # two different "active" members: no decision
            best = h
    return best


def _near_trade(h: _Hit, anchors: list[Box]) -> bool:
    """The instrument name of a trade panel sits right at its SELL / BUY buttons (a few lines above / beside)."""
    for a in anchors:
        ha = a.height
        if abs(h.box.cy - a.cy) <= 4 * ha and abs(h.box.cx - a.cx) <= 8 * ha:
            return True
    return False


def locate(boxes: list[Box], catalog: tuple[Instrument, ...] = CATALOG) -> Recognition:
    """Which instrument is ACTIVE in a Trading 212 screen. Hierarchy:
      1. the name at the SELL / BUY trade panel (one instrument only),
      2. a stand-alone instrument name (chart header) that is not part of a row of tabs / column of a watchlist,
         clearly larger than any other stand-alone name,
      3. the visually marked tab / row of a row of tabs or a watchlist (different background or text),
      4. other tabs / watchlist rows are only offered as candidates - never counted as equal rivals.
    Nothing decisive -> not confident (the user picks)."""
    raw = " | ".join(b.text for b in boxes if b.text.strip())
    hits = _hits(boxes, catalog)
    if not hits:
        return Recognition(None, 0.0, (), raw, via="celé okno")
    groups = _collections(hits)
    grouped = {id(h) for g in groups for h in g}
    alone = [h for h in hits if id(h) not in grouped]
    order = sorted(hits, key=lambda h: -h.box.height)
    cands = tuple(dict.fromkeys(h.inst for h in order))[:6]

    def ok(h: _Hit, via: str) -> Recognition:
        return Recognition(h.inst, h.score, cands, raw, (), h.score, via)

    anchors = [b for b in boxes if any(t.upper().strip(".:") in TRADE_WORDS for t in b.text.split())]
    near = [h for h in alone if _near_trade(h, anchors)] if 0 < len(anchors) <= 4 else []
    if near and len({h.inst for h in near}) == 1:          # one trade panel (SELL + BUY), one name at it
        return ok(max(near, key=lambda h: h.box.height), "obchodní panel")
    if alone:
        med = sorted(h.box.height for h in hits)[len(hits) // 2]
        tabs = max((h.box.height for g in groups for h in g), default=0.0)
        big = [h for h in alone if h.box.height >= med and h.box.height >= 1.15 * tabs]
        ranked = sorted(big, key=lambda h: -h.box.height)
        if ranked:
            top = ranked[0]
            rivals = [h for h in ranked[1:] if h.inst != top.inst and h.box.height >= SAME_SIZE * top.box.height]
            if not rivals:
                return ok(top, "graf / nadpis")
    bgs = sorted(b.bg for b in boxes if b.bg is not None)
    screen_bg = bgs[len(bgs) // 2] if bgs else None
    actives = [a for a in (_active(g, screen_bg) for g in groups) if a is not None]
    if len({a.inst for a in actives}) == 1:
        return ok(actives[0], "aktivní záložka")
    rivals = tuple(dict.fromkeys(h.inst for h in (actives or order)))
    top = rivals[0] if rivals else None
    return Recognition(None, 0.0, cands, raw, rivals if len(rivals) > 1 else (), 0.0 if top is None else 0.95,
                       "celé okno")


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
