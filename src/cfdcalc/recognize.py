"""Instrument recognition: OCR text lines -> catalogue match with a confidence and a reason.

Matching works on whole words only (no substrings inside longer words: "AMD" never matches "AMDOCS")
and never across unrelated lines, so similar names are not silently swapped. Two different instruments
found in one reading are ambiguous; the caller then must not trade (WAIT) until the user confirms.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from .instruments import CATALOG, Instrument, labels

CONFIDENT = 0.85   # below this the user confirms the instrument
MARGIN = 0.08      # a runner-up this close makes the reading ambiguous

_ocr = None


def ocr_lines(rgb) -> list[str]:
    """Text lines in an RGB numpy array (RapidOCR, offline). Loaded lazily: first call takes ~1 s."""
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    result, _ = _ocr(rgb)
    return [line[1] for line in result or []]


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9&]", "", s.upper())


def _words(s: str) -> list[str]:
    return [w for w in (_norm(x) for x in re.split(r"[\s|,;:()\-–]+", s)) if w]


def _contains(seq: list[str], part: list[str]) -> bool:
    n = len(part)
    return any(seq[i:i + n] == part for i in range(len(seq) - n + 1))


def score(alias: str, lines: list[str], tokens: set[str]) -> float:
    """1.0 = a whole line equals the alias, 0.95 = the alias words appear as whole words,
    otherwise a fuzzy similarity (only for labels of 4+ characters; short tickers must match exactly)."""
    a, words = _norm(alias), _words(alias)
    if not a:
        return 0.0
    best = 0.0
    for line in lines:
        if _norm(line) == a:
            return 1.0
        if _contains(_words(line), words):
            best = 0.95
    if len(words) > 1 and all(w in tokens for w in words):  # OCR split "Germany 40" into separate boxes
        best = max(best, 0.95)
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

    @property
    def confident(self) -> bool:
        return self.best is not None and self.score >= CONFIDENT

    @property
    def reason(self) -> str:
        """Why the reading is not usable (Czech, shown in the UI); empty when confident."""
        if self.confident:
            return ""
        if not self.text.strip():
            return "v oblasti není žádný text"
        if len(self.competing) > 1:
            return "nejednoznačné – v oblasti je více instrumentů: " + ", ".join(i.name for i in self.competing[:3])
        if not self.candidates or self.score < 0.6:
            return f"text „{self.text[:40]}“ neodpovídá žádnému podporovanému instrumentu"
        return f"nízká jistota rozpoznání (text „{self.text[:40]}“)"


def _best_label(inst: Instrument, lines: list[str], tokens: set[str]) -> tuple[float, list[str]]:
    return max(((score(a, lines, tokens), _words(a)) for a in labels(inst)), key=lambda x: (x[0], len(x[1])))


def match(lines: list[str], catalog: tuple[Instrument, ...] = CATALOG) -> Recognition:
    lines = [x for x in lines if x.strip()]
    tokens = {w for x in lines for w in _words(x)}
    scored = sorted(((*_best_label(i, lines, tokens), i) for i in catalog), key=lambda x: -x[0])
    s1, words1, i1 = scored[0]
    # rivals: other instruments matched (almost) as strongly; a shorter label inside the winning label is not
    # a rival ("Oil" inside "Brent Oil")
    floor = CONFIDENT if s1 >= CONFIDENT else 0.0
    rivals = [i for s, w, i in scored[1:] if s >= max(s1 - MARGIN, floor) and s > 0 and not _contains(words1, w)]
    candidates = tuple(i for s, _, i in scored[:6] if s >= 0.5)
    best = i1 if s1 > 0 and not rivals else None
    competing = (i1, *rivals) if rivals and floor else ()
    return Recognition(best, s1 if best else 0.0, candidates, " | ".join(lines), competing)
