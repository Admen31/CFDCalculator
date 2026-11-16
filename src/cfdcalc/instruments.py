"""Instrument catalogue: Trading 212 display names -> Twelve Data symbols.

Mapping checked against Twelve Data symbol search (scripts/verify_symbols.py, runs in CI): forex pairs and
XAU/XAG/WTI/XBR are listed as expected; stocks are pinned to their US exchange. Index symbols (SPX, NDX, DAX,
FTSE) are listed by Twelve Data as ETFs or unrelated companies and DJI/NG/USD do not exist, so those
instruments are recognised but marked td_verified=False and never analysed (WAIT).
`spread` is only a rough default the user must overwrite with the spread Trading 212 actually shows.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    name: str                      # display name
    symbol: str                    # Twelve Data symbol
    kind: str                      # forex | index | commodity | stock
    currencies: tuple[str, ...]    # currencies whose economic news matter
    decimals: int                  # price precision used for SL/TP rounding
    spread: float                  # rough default spread in price units (user overrides)
    aliases: tuple[str, ...] = ()  # how Trading 212 labels it
    exchange: str = ""             # Twelve Data exchange, pinned where the ticker exists on several exchanges
    td_verified: bool = True       # False: Twelve Data lists something else under this symbol -> always WAIT


def _fx(a: str, b: str, spread: float, decimals: int = 5) -> Instrument:
    return Instrument(f"{a}/{b}", f"{a}/{b}", "forex", (a, b), decimals, spread, (f"{a}/{b}", f"{a}{b}"))


def _stock(name: str, ticker: str, exchange: str, *aliases: str) -> Instrument:
    return Instrument(name, ticker, "stock", ("USD",), 2, 0.05, (name, ticker, *aliases), exchange)


CATALOG: tuple[Instrument, ...] = (
    _fx("EUR", "USD", 0.00008), _fx("GBP", "USD", 0.00012), _fx("USD", "JPY", 0.012, 3),
    _fx("USD", "CHF", 0.00015), _fx("AUD", "USD", 0.00012), _fx("USD", "CAD", 0.00016),
    _fx("NZD", "USD", 0.00018), _fx("EUR", "GBP", 0.00012), _fx("EUR", "JPY", 0.018, 3),
    _fx("GBP", "JPY", 0.025, 3), _fx("EUR", "CHF", 0.00018),
    Instrument("Gold", "XAU/USD", "commodity", ("USD",), 2, 0.35, ("Gold", "XAU/USD", "XAUUSD", "Zlato")),
    Instrument("Silver", "XAG/USD", "commodity", ("USD",), 3, 0.03, ("Silver", "XAG/USD", "XAGUSD", "Stříbro")),
    Instrument("Oil (WTI)", "WTI/USD", "commodity", ("USD",), 2, 0.03, ("Oil", "Crude Oil", "WTI", "US Oil")),
    Instrument("Brent Oil", "XBR/USD", "commodity", ("USD",), 2, 0.03, ("Brent Oil", "Brent", "UK Oil")),
    Instrument("Natural Gas", "NG/USD", "commodity", ("USD",), 3, 0.005, ("Natural Gas", "Nat Gas"),
               td_verified=False),
    Instrument("US 500", "SPX", "index", ("USD",), 1, 0.6, ("US 500", "US500", "S&P 500", "SPX500"),
               td_verified=False),
    Instrument("US 100", "NDX", "index", ("USD",), 1, 1.8, ("US 100", "US100", "US Tech 100", "NASDAQ 100"),
               td_verified=False),
    Instrument("US 30", "DJI", "index", ("USD",), 1, 3.0, ("US 30", "US30", "Wall Street 30", "Dow Jones"),
               td_verified=False),
    Instrument("Germany 40", "DAX", "index", ("EUR",), 1, 1.5, ("Germany 40", "DE40", "DAX", "GER40"),
               td_verified=False),
    Instrument("UK 100", "FTSE", "index", ("GBP",), 1, 1.5, ("UK 100", "UK100", "FTSE 100"), td_verified=False),
    _stock("Apple", "AAPL", "NASDAQ", "Apple Inc"), _stock("Microsoft", "MSFT", "NASDAQ", "Microsoft Corp"),
    _stock("Tesla", "TSLA", "NASDAQ", "Tesla Inc"),
    _stock("NVIDIA", "NVDA", "NASDAQ", "NVIDIA Corp", "Nvidia Corporation"),
    _stock("Amazon", "AMZN", "NASDAQ", "Amazon.com"), _stock("Meta Platforms", "META", "NASDAQ", "Meta", "Facebook"),
    _stock("Alphabet", "GOOGL", "NASDAQ", "Google", "Alphabet (Class A)"), _stock("Netflix", "NFLX", "NASDAQ"),
    _stock("AMD", "AMD", "NASDAQ", "Advanced Micro Devices"), _stock("Intel", "INTC", "NASDAQ"),
    _stock("Coca-Cola", "KO", "NYSE"), _stock("JPMorgan Chase", "JPM", "NYSE", "JPMorgan", "JP Morgan"),
    _stock("Boeing", "BA", "NYSE"), _stock("Palantir", "PLTR", "NASDAQ"),
    _stock("Walt Disney", "DIS", "NYSE", "Disney"), _stock("Alibaba", "BABA", "NYSE"),
)

BY_SYMBOL = {i.symbol: i for i in CATALOG}


def labels(inst: Instrument) -> tuple[str, ...]:
    """Every text that identifies the instrument: name, Twelve Data symbol and Trading 212 aliases."""
    return tuple(dict.fromkeys((inst.name, inst.symbol, *inst.aliases)))
