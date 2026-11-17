"""Instrument catalogue: Trading 212 display names -> Twelve Data symbols.

Mapping checked against Twelve Data symbol search (scripts/verify_symbols.py, runs in CI): forex pairs and
XAU/XAG/WTI/XBR are listed as expected; stocks are pinned to their US exchange. Index symbols (SPX, NDX, DAX,
FTSE) are listed by Twelve Data as ETFs or unrelated companies and DJI/NG/USD do not exist, so those
instruments are recognised but marked td_verified=False and never analysed (WAIT).
`spread` is only a rough default the user must overwrite with the spread Trading 212 actually shows.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time

TWELVE, COINBASE = "twelvedata", "coinbase"


@dataclass(frozen=True)
class Source:
    """One way to get candles for an instrument. exact=False: a REFERENCE product (e.g. an index ETF for an index CFD)
    - its prices never become entry/SL/TP or a position size."""
    provider: str                  # TWELVE | COINBASE
    symbol: str                    # the provider's symbol
    exchange: str = ""             # pinned exchange (Twelve Data)
    exact: bool = True
    label: str = ""                # what the reference product is, shown to the user
    plan: str = "Basic"            # cheapest Twelve Data plan that includes the symbol (audit)


# exchange sessions (local time) for stocks/ETFs added from the symbol directory, by MIC code
SESSIONS = {"XNAS": ("America/New_York", time(9, 30), time(16, 0)),
            "XNGS": ("America/New_York", time(9, 30), time(16, 0)),
            "XNMS": ("America/New_York", time(9, 30), time(16, 0)),
            "XNCM": ("America/New_York", time(9, 30), time(16, 0)),
            "XNYS": ("America/New_York", time(9, 30), time(16, 0)),
            "ARCX": ("America/New_York", time(9, 30), time(16, 0)),
            "BATS": ("America/New_York", time(9, 30), time(16, 0)),
            "XETR": ("Europe/Berlin", time(9, 0), time(17, 30)),
            "XLON": ("Europe/London", time(8, 0), time(16, 30)),
            "XPAR": ("Europe/Paris", time(9, 0), time(17, 30)),
            "XAMS": ("Europe/Amsterdam", time(9, 0), time(17, 30)),
            "XBRU": ("Europe/Brussels", time(9, 0), time(17, 30)),
            "XMIL": ("Europe/Rome", time(9, 0), time(17, 30)),
            "XMAD": ("Europe/Madrid", time(9, 0), time(17, 30)),
            "XSWX": ("Europe/Zurich", time(9, 0), time(17, 20))}


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
    sources: tuple[Source, ...] = ()               # empty = Twelve Data under `symbol` (if td_verified)
    session: tuple[str, time, time] | None = None  # overrides the market profile's session (non-US stocks)
    currency: str = ""             # verified quote currency (instruments from the symbol directory)
    custom: bool = False           # added by the user from the symbol directory


PLANS = ("Basic", "Grow", "Pro", "Ultra")


def plan_ok(source: Source, plan: str) -> bool:
    """Is the source included in the user's Twelve Data plan? (other providers: always)"""
    if source.provider != TWELVE:
        return True
    return PLANS.index(source.plan) <= PLANS.index(plan if plan in PLANS else "Ultra")


def sources(inst: Instrument) -> tuple[Source, ...]:
    """Data sources in the order they are tried: exact ones first, then references."""
    own = inst.sources or ((Source(TWELVE, inst.symbol, inst.exchange),) if inst.td_verified else ())
    return tuple(sorted(own, key=lambda s: not s.exact))


def _fx(a: str, b: str, spread: float = 0.0, decimals: int | None = None) -> Instrument:
    d = decimals if decimals is not None else (3 if b in ("JPY", "HUF") else 4 if b in ("CZK", "MXN", "ZAR", "TRY",
                                                                                         "SEK", "NOK", "CNH", "HKD")
                                                 else 5)
    return Instrument(f"{a}/{b}", f"{a}/{b}", "forex", (a, b), d, spread, (f"{a}/{b}", f"{a}{b}"))


def _stock(name: str, ticker: str, exchange: str, *aliases: str, spread: float = 0.0, kind: str = "stock",
           plan: str = "Basic") -> Instrument:
    us = exchange in ("NASDAQ", "NYSE", "CBOE")
    session = None if us else SESSIONS[_MIC[exchange]]
    cur = "USD" if us else _CUR[exchange]
    return Instrument(name, ticker, kind, (cur.upper()[:3],), 2, spread, (name, *aliases), exchange,
                      sources=(Source(TWELVE, ticker, exchange, plan=plan),), session=session, currency=cur)


def _crypto(name: str, base: str, decimals: int) -> Instrument:
    sym = f"{base}/USD"
    # Coinbase first: free, no key, real exchange volume, does not use Twelve Data credits
    return Instrument(name, sym, "crypto", ("USD",), decimals, 0.0, (name, sym, f"{base}USD"),
                      sources=(Source(COINBASE, sym), Source(TWELVE, sym)), currency="USD")


def _ref(symbol: str, exchange: str, label: str) -> Source:
    return Source(TWELVE, symbol, exchange, exact=False, label=label)


_MIC = {"XETR": "XETR", "Euronext": "XPAR", "LSE": "XLON", "SIX": "XSWX", "Euronext-AMS": "XAMS"}
_CUR = {"XETR": "EUR", "Euronext": "EUR", "Euronext-AMS": "EUR", "LSE": "GBp", "SIX": "CHF"}
_US_SESSION = ("America/New_York", time(9, 30), time(16, 0))

# Twelve Data access per symbol was checked with GET /symbol_search?show_plan=true (scripts/coverage_audit.py,
# run in CI, 17.11.2026). plan = the cheapest Twelve Data plan that includes the symbol.
CATALOG: list[Instrument] = [
    _fx("EUR", "USD", 0.00008), _fx("GBP", "USD", 0.00012), _fx("USD", "JPY", 0.012, 3),
    _fx("USD", "CHF", 0.00015), _fx("AUD", "USD", 0.00012), _fx("USD", "CAD", 0.00016),
    _fx("NZD", "USD", 0.00018), _fx("EUR", "GBP", 0.00012), _fx("EUR", "JPY", 0.018, 3),
    _fx("GBP", "JPY", 0.025, 3), _fx("EUR", "CHF", 0.00018),
    *[_fx(*pair.split("/")) for pair in (
        "AUD/JPY", "CAD/JPY", "CHF/JPY", "EUR/AUD", "EUR/CAD", "EUR/NZD", "GBP/AUD", "GBP/CAD", "GBP/CHF", "AUD/CAD",
        "AUD/CHF", "AUD/NZD", "NZD/JPY", "USD/SEK", "USD/NOK", "USD/PLN", "USD/CZK", "EUR/PLN", "EUR/CZK", "USD/MXN",
        "USD/ZAR", "USD/TRY", "USD/HUF", "EUR/HUF", "USD/SGD", "USD/HKD", "USD/CNH", "EUR/NOK", "EUR/SEK", "GBP/NZD",
        "NZD/CAD", "CAD/CHF")],
    Instrument("Gold", "XAU/USD", "commodity", ("USD",), 2, 0.35, ("Gold", "XAU/USD", "XAUUSD", "Zlato")),
    Instrument("Silver", "XAG/USD", "commodity", ("USD",), 3, 0.03, ("Silver", "XAG/USD", "XAGUSD", "Stříbro"),
               sources=(Source(TWELVE, "XAG/USD", plan="Grow"),
                        _ref("SLV", "NYSE", "ETF iShares Silver Trust (SLV, NYSE Arca)")), currency="USD"),
    Instrument("Oil (WTI)", "WTI/USD", "commodity", ("USD",), 2, 0.03, ("Oil", "Crude Oil", "WTI", "US Oil"),
               sources=(Source(TWELVE, "WTI/USD", plan="Grow"),
                        _ref("USO", "NYSE", "ETF United States Oil Fund (USO, NYSE Arca) – sleduje futures WTI")),
               currency="USD"),
    Instrument("Brent Oil", "XBR/USD", "commodity", ("USD",), 2, 0.03, ("Brent Oil", "Brent", "UK Oil"),
               sources=(Source(TWELVE, "XBR/USD", plan="Grow"),), currency="USD"),
    Instrument("Platinum", "XPT/USD", "commodity", ("USD",), 2, 0.0, ("Platinum", "XPT/USD", "XPTUSD", "Platina"),
               sources=(Source(TWELVE, "XPT/USD", plan="Grow"),), currency="USD"),
    Instrument("Palladium", "XPD/USD", "commodity", ("USD",), 2, 0.0, ("Palladium", "XPD/USD", "XPDUSD"),
               sources=(Source(TWELVE, "XPD/USD", plan="Grow"),), currency="USD"),
    Instrument("Natural Gas", "NG/USD", "commodity", ("USD",), 3, 0.005, ("Natural Gas", "Nat Gas"),
               td_verified=False, session=_US_SESSION,
               sources=(_ref("UNG", "NYSE", "ETF United States Natural Gas Fund (UNG, NYSE Arca) – sleduje futures"),)),
    # index CFDs: Twelve Data lists no matching index under these symbols -> reference ETFs (US session only)
    Instrument("US 500", "SPX", "index", ("USD",), 1, 0.6, ("US 500", "US500", "S&P 500", "SPX500"),
               td_verified=False, session=_US_SESSION,
               sources=(_ref("SPY", "NYSE", "ETF SPDR S&P 500 (SPY, NYSE Arca)"),)),
    Instrument("US 100", "NDX", "index", ("USD",), 1, 1.8, ("US 100", "US100", "US Tech 100", "NASDAQ 100"),
               td_verified=False, session=_US_SESSION,
               sources=(_ref("QQQ", "NASDAQ", "ETF Invesco QQQ (QQQ, NASDAQ)"),)),
    Instrument("US 30", "DJI", "index", ("USD",), 1, 3.0, ("US 30", "US30", "Wall Street 30", "Dow Jones"),
               td_verified=False, session=_US_SESSION,
               sources=(_ref("DIA", "NYSE", "ETF SPDR Dow Jones Industrial Average (DIA, NYSE Arca)"),)),
    Instrument("US 2000", "RUT", "index", ("USD",), 1, 0.0, ("US 2000", "US2000", "Russell 2000"),
               td_verified=False, session=_US_SESSION,
               sources=(_ref("IWM", "NYSE", "ETF iShares Russell 2000 (IWM, NYSE Arca)"),)),
    Instrument("Germany 40", "DAX", "index", ("EUR",), 1, 1.5, ("Germany 40", "DE40", "DAX", "GER40"),
               td_verified=False, session=_US_SESSION,
               sources=(_ref("DAX", "NASDAQ", "ETF Global X DAX Germany (DAX, NASDAQ, v USD, jen americká "
                                          "seance)"),)),
    Instrument("UK 100", "FTSE", "index", ("GBP",), 1, 1.5, ("UK 100", "UK100", "FTSE 100"), td_verified=False,
               session=_US_SESSION,
               sources=(_ref("EWU", "NYSE", "ETF iShares MSCI United Kingdom (EWU) – index MSCI UK, ne FTSE 100"),)),
    # US stocks (Basic)
    *[_stock(n, t, ex, *al) for n, t, ex, *al in (
        ("Apple", "AAPL", "NASDAQ", "Apple Inc"), ("Microsoft", "MSFT", "NASDAQ", "Microsoft Corp"),
        ("Tesla", "TSLA", "NASDAQ", "Tesla Inc"), ("NVIDIA", "NVDA", "NASDAQ", "NVIDIA Corp", "Nvidia Corporation"),
        ("Amazon", "AMZN", "NASDAQ", "Amazon.com"), ("Meta Platforms", "META", "NASDAQ", "Meta", "Facebook"),
        ("Alphabet", "GOOGL", "NASDAQ", "Google", "Alphabet (Class A)"), ("Netflix", "NFLX", "NASDAQ"),
        ("AMD", "AMD", "NASDAQ", "Advanced Micro Devices"), ("Intel", "INTC", "NASDAQ"), ("Coca-Cola", "KO", "NYSE"),
        ("JPMorgan Chase", "JPM", "NYSE", "JPMorgan", "JP Morgan"), ("Boeing", "BA", "NYSE"),
        ("Palantir", "PLTR", "NASDAQ"), ("Walt Disney", "DIS", "NYSE", "Disney"), ("Alibaba", "BABA", "NYSE"),
        ("Broadcom", "AVGO", "NASDAQ"), ("Costco", "COST", "NASDAQ", "Costco Wholesale"),
        ("PepsiCo", "PEP", "NASDAQ"), ("Adobe", "ADBE", "NASDAQ"), ("Salesforce", "CRM", "NYSE"),
        ("Oracle", "ORCL", "NYSE"), ("Cisco", "CSCO", "NASDAQ", "Cisco Systems"), ("Qualcomm", "QCOM", "NASDAQ"),
        ("Texas Instruments", "TXN", "NASDAQ"), ("Micron Technology", "MU", "NASDAQ", "Micron"),
        ("PayPal", "PYPL", "NASDAQ"), ("Shopify", "SHOP", "NASDAQ"), ("Uber", "UBER", "NYSE", "Uber Technologies"),
        ("Airbnb", "ABNB", "NASDAQ"), ("Coinbase Global", "COIN", "NASDAQ", "Coinbase"),
        ("Snowflake", "SNOW", "NYSE"), ("Pfizer", "PFE", "NYSE"), ("Johnson & Johnson", "JNJ", "NYSE"),
        ("Merck", "MRK", "NYSE", "Merck & Co"), ("AbbVie", "ABBV", "NYSE"), ("Eli Lilly", "LLY", "NYSE"),
        ("UnitedHealth", "UNH", "NYSE", "UnitedHealth Group"), ("Visa", "V", "NYSE"), ("Mastercard", "MA", "NYSE"),
        ("Bank of America", "BAC", "NYSE"), ("Wells Fargo", "WFC", "NYSE"), ("Goldman Sachs", "GS", "NYSE"),
        ("Morgan Stanley", "MS", "NYSE"), ("Citigroup", "C", "NYSE"), ("Exxon Mobil", "XOM", "NYSE", "ExxonMobil"),
        ("Chevron", "CVX", "NYSE"), ("Walmart", "WMT", "NASDAQ"), ("Home Depot", "HD", "NYSE"),
        ("McDonald's", "MCD", "NYSE"), ("Nike", "NKE", "NYSE"), ("Starbucks", "SBUX", "NASDAQ"),
        ("AT&T", "T", "NYSE"), ("Verizon", "VZ", "NYSE"), ("General Electric", "GE", "NYSE", "GE Aerospace"),
        ("Ford", "F", "NYSE", "Ford Motor"), ("General Motors", "GM", "NYSE"), ("Rivian", "RIVN", "NASDAQ"),
        ("Lucid", "LCID", "NASDAQ", "Lucid Group"), ("NIO", "NIO", "NYSE"),
        ("Super Micro Computer", "SMCI", "NASDAQ", "Supermicro"), ("Arm Holdings", "ARM", "NASDAQ"),
        ("MicroStrategy", "MSTR", "NASDAQ", "Strategy"), ("Robinhood", "HOOD", "NASDAQ", "Robinhood Markets"),
        ("SoFi Technologies", "SOFI", "NASDAQ", "SoFi"), ("Roblox", "RBLX", "NYSE"))],
    # US ETFs (Basic)
    *[_stock(n, t, ex, kind="etf") for n, t, ex in (
        ("SPDR S&P 500 ETF", "SPY", "NYSE"), ("Invesco QQQ", "QQQ", "NASDAQ"), ("SPDR Dow Jones ETF", "DIA", "NYSE"),
        ("iShares Russell 2000 ETF", "IWM", "NYSE"), ("SPDR Gold Shares", "GLD", "NYSE"),
        ("iShares Silver Trust", "SLV", "NYSE"), ("United States Oil Fund", "USO", "NYSE"),
        ("United States Natural Gas Fund", "UNG", "NYSE"), ("iShares 20+ Year Treasury Bond ETF", "TLT", "NASDAQ"),
        ("Vanguard Total Stock Market ETF", "VTI", "NYSE"), ("iShares MSCI Emerging Markets ETF", "EEM", "NYSE"),
        ("Energy Select Sector SPDR", "XLE", "NYSE"), ("Financial Select Sector SPDR", "XLF", "NYSE"),
        ("Technology Select Sector SPDR", "XLK", "NYSE"), ("ARK Innovation ETF", "ARKK", "CBOE"),
        ("iShares MSCI Germany ETF", "EWG", "NYSE"), ("iShares MSCI United Kingdom ETF", "EWU", "NYSE"),
        ("iShares China Large-Cap ETF", "FXI", "NYSE"))],
    # European stocks (Twelve Data: Grow, SIX: Pro; Volkswagen preferred: Basic)
    *[_stock(n, t, ex, *al, plan=plan) for n, t, ex, plan, *al in (
        ("SAP", "SAP", "XETR", "Grow", "SAP SE"), ("Siemens", "SIE", "XETR", "Grow", "Siemens AG"),
        ("Allianz", "ALV", "XETR", "Grow", "Allianz SE"), ("BMW", "BMW", "XETR", "Grow", "Bayerische Motoren Werke"),
        ("Mercedes-Benz", "MBG", "XETR", "Grow", "Mercedes-Benz Group"),
        ("Volkswagen (Vz)", "VOW3", "XETR", "Basic", "Volkswagen"), ("Deutsche Bank", "DBK", "XETR", "Grow"),
        ("Adidas", "ADS", "XETR", "Grow", "adidas AG"), ("LVMH", "MC", "Euronext", "Grow", "LVMH Moet Hennessy"),
        ("TotalEnergies", "TTE", "Euronext", "Grow"), ("Shell", "SHEL", "LSE", "Grow", "Shell plc"),
        ("BP", "BP", "LSE", "Grow", "BP plc"), ("HSBC", "HSBA", "LSE", "Grow", "HSBC Holdings"),
        ("Nestle", "NESN", "SIX", "Pro", "Nestlé"), ("Novartis", "NOVN", "SIX", "Pro"))],
    # crypto (Coinbase Exchange spot, Twelve Data as second source)
    *[_crypto(n, b, d) for n, b, d in (
        ("Bitcoin", "BTC", 2), ("Ethereum", "ETH", 2), ("Solana", "SOL", 2), ("XRP", "XRP", 4), ("Litecoin", "LTC", 2),
        ("Cardano", "ADA", 4), ("Dogecoin", "DOGE", 5), ("Bitcoin Cash", "BCH", 2), ("Polkadot", "DOT", 3),
        ("Chainlink", "LINK", 3), ("Avalanche", "AVAX", 2), ("Stellar", "XLM", 5))],
]
BY_SYMBOL = {i.symbol: i for i in CATALOG}
assert len(BY_SYMBOL) == len(CATALOG), "duplicate symbol in the catalogue"


# tickers that are too short or ordinary words to identify an instrument in OCR text on their own
_WEAK = {"COST", "SHOP", "SNOW", "HOOD", "ARM", "NIO", "MC", "BP"}


def labels(inst: Instrument) -> tuple[str, ...]:
    """Every text that identifies the instrument: name, symbol and Trading 212 aliases (very short or word-like
    tickers only when they are an explicit alias)."""
    sym = inst.symbol if len(inst.symbol) >= 3 and inst.symbol not in _WEAK else None
    return tuple(dict.fromkeys(x for x in (inst.name, sym, *inst.aliases) if x))


def from_directory(row: dict, t212_name: str = "") -> Instrument:
    """Instrument from a Twelve Data symbol-directory row. Raises ValueError for anything that cannot be analysed
    safely: unknown exchange hours, unsupported type, missing identity fields, symbol already in the catalogue."""
    sym, ex, mic, cur, typ = (row.get(k, "").strip() for k in ("symbol", "exchange", "mic_code", "currency",
                                                               "instrument_type"))
    if not (sym and ex and mic and cur):
        raise ValueError("chybí identita symbolu (burza, MIC nebo měna)")
    if mic not in SESSIONS:
        raise ValueError(f"obchodní hodiny burzy {ex} ({mic}) aplikace nezná – instrument nelze bezpečně analyzovat")
    t = typ.lower()
    kind = "etf" if "etf" in t or "fund" in t else "stock" if ("stock" in t or "depositary" in t) else ""
    if not kind:
        raise ValueError(f"typ „{typ}“ není podporován (jen akcie, ADR a ETF; forex a krypto jsou v katalogu)")
    if sym in BY_SYMBOL:
        raise ValueError(f"symbol {sym} už v katalogu je (možná jiná burza) – nelze přidat druhý se stejnou značkou")
    plan = row.get("plan") or "Basic"
    name = row.get("instrument_name") or sym
    aliases = tuple(dict.fromkeys(a for a in (name, t212_name.strip()) if a))
    return Instrument(t212_name.strip() or name, sym, kind, (cur.upper()[:3],), 2, 0.0, aliases, ex,
                      sources=(Source(TWELVE, sym, ex, plan=plan if plan in PLANS else "Ultra"),),
                      session=SESSIONS[mic], currency=cur, custom=True)


def register(inst: Instrument) -> None:
    """Add an instrument from the symbol directory (validated by the caller). The symbol must be new."""
    if inst.symbol in BY_SYMBOL:
        raise ValueError(f"symbol {inst.symbol} už v katalogu je")
    CATALOG.append(inst)
    BY_SYMBOL[inst.symbol] = inst
