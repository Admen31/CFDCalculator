"""v2 recognition: names, tickers, aliases; whole-word matching; ambiguity -> no instrument."""
import re

import pytest

from cfdcalc.instruments import CATALOG, labels
from cfdcalc.recognize import match


@pytest.mark.parametrize("lines, symbol", [
    (["NVIDIA"], "NVDA"), (["NVDA"], "NVDA"), (["NVIDIA Corp", "NVDA", "182.40"], "NVDA"),
    (["Apple"], "AAPL"), (["AAPL"], "AAPL"), (["Tesla"], "TSLA"), (["Tesla Inc", "+1.2%"], "TSLA"),
    (["EUR/USD"], "EUR/USD"), (["EURUSD"], "EUR/USD"), (["Germany 40"], "DAX"), (["Germany", "40"], "DAX"),
    (["US 500"], "SPX"), (["S&P 500"], "SPX"), (["Gold"], "XAU/USD"), (["Silver"], "XAG/USD"),
    (["Brent Oil"], "XBR/USD"), (["Oil"], "WTI/USD"), (["Coca-Cola"], "KO"), (["Meta Platforms"], "META"),
])
def test_names_tickers_aliases(lines, symbol):
    r = match(lines)
    assert r.confident and r.best.symbol == symbol, (lines, r)


@pytest.mark.parametrize("lines, why", [
    (["NVIDIA", "Apple"], "více instrumentů"),        # two instruments in the region
    (["Gold", "Silver"], "více instrumentů"),
    (["EUR/USD", "GBP/USD"], "více instrumentů"),
    (["AMDOCS"], "neodpovídá"),                        # ticker inside another word is not a match
    (["Portfolio", "History"], "neodpovídá"),
    ([], "žádný text"),
    (["US 50O"], "nízká jistota"),                     # OCR typo: suggest, never auto-confirm
    (["EUR/U5D"], "nízká jistota"),
])
def test_unclear_readings_are_never_confident(lines, why):
    r = match(lines)
    assert not r.confident and r.best is None or not r.confident, r
    assert why in r.reason


def test_typo_offers_the_right_candidate_first():
    assert match(["EUR/U5D"]).candidates[0].symbol == "EUR/USD"
    assert match(["US 50O"]).candidates[0].symbol == "SPX"


def test_catalogue_labels_are_unique_and_symbols_well_formed():
    """No text may identify two instruments - otherwise a reading could silently swap them."""
    seen = {}
    for inst in CATALOG:
        for a in labels(inst):
            key = re.sub(r"[^A-Z0-9&]", "", a.upper())
            assert seen.setdefault(key, inst.symbol) == inst.symbol, (a, seen[key], inst.symbol)
    for inst in CATALOG:
        pattern = r"[A-Z]{3}/[A-Z]{3}" if inst.kind == "forex" else r"[A-Z0-9]{1,5}(/[A-Z]{3})?" \
            if inst.kind != "crypto" else r"[A-Z]{3,4}/USD"
        assert re.fullmatch(pattern, inst.symbol), inst.symbol
        assert inst.kind in ("forex", "index", "commodity", "stock", "etf", "crypto")


def test_every_catalogue_name_recognises_itself():
    for inst in CATALOG:
        for a in labels(inst):
            r = match([a])
            assert r.confident and r.best == inst, (a, r)
