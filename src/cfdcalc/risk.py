"""v2.4 risk management: the largest CFD quantity whose planned stop-loss loss fits the account's risk budget.

Pure functions, Decimal money, no network, no clock (all injected). Three different quantities are kept apart:
  * planned loss at the stop-loss   = qty x contract x (|entry - SL| + spread) x FX   (the RISK)
  * notional value of the position  = qty x contract x entry x FX                     (the EXPOSURE)
  * required margin                 = notional x margin %                             (the COLLATERAL)

Nothing is invented: contract size, quantity step, minimum quantity and margin come from the user (Trading 212
instrument details), the FX rate from Twelve Data or the user. Anything missing -> NEDOSTATEK DAT, no quantity.
The result never opens a trade.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_FLOOR, Decimal, InvalidOperation

from .instruments import Instrument

OK, ORIENTATION, LIMIT, NODATA = "V RÁMCI LIMITU", "ORIENTAČNÍ", "PŘEKROČENÍ LIMITU", "NEDOSTATEK DAT"
TOO_RISKY = "POZICE JE PŘÍLIŠ RIZIKOVÁ – NEOTVÍRAT PODLE TOHOTO PLÁNU"
CURRENCIES = ("CZK", "EUR", "USD", "GBP", "PLN", "CHF")
QUICK_RISK = ("0.5", "1", "1.5", "2")
DEFAULT_RISK = Decimal("2")
MAX_DATA_AGE = timedelta(minutes=15)      # a plan from older market data is not sized
MAX_FX_AGE = timedelta(hours=1)           # FX rate from Twelve Data
MAX_MANUAL_FX_AGE = timedelta(hours=24)   # FX rate typed in by the user
WARNING = ("Výpočet stanovuje plánované riziko při předpokládaném provedení stop-lossu. Skutečná ztráta může být "
           "vyšší kvůli skluzu, cenovým gapům, nákladům nebo podmínkám trhu.")


def num(text) -> Decimal | None:
    """User input -> positive finite Decimal ('50 000', '1,5', '0.25'), else None."""
    if text is None:
        return None
    s = str(text).replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        d = Decimal(s)
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() and d > 0 else None


def quote_currency(inst: Instrument) -> str:
    """Currency the price is quoted in: the second leg of a pair (EUR/USD -> USD, XAU/USD -> USD), otherwise the
    market's currency from the catalogue (US stocks and indices USD, Germany 40 EUR, UK 100 GBP)."""
    return inst.symbol.split("/")[1] if "/" in inst.symbol else inst.currencies[0]


@dataclass(frozen=True)
class Account:
    equity: Decimal | None
    currency: str = "CZK"
    risk_pct: Decimal = DEFAULT_RISK
    max_notional_pct: Decimal | None = None     # optional exposure limit (e.g. 10 % of equity)
    free_margin: Decimal | None = None          # optional
    open_risk: Decimal | None = None            # v2.8: planned loss of positions already open (account currency)
    max_total_pct: Decimal | None = None        # v2.8: limit of all open risk incl. this trade, % of equity
    reserve_pct: Decimal = Decimal("0")         # v2.8: extra stop distance for slippage, % of |entry - SL|

    @property
    def budget(self) -> Decimal | None:
        """Risk budget of ONE trade = equity x risk %."""
        return None if self.equity is None else self.equity * self.risk_pct / 100

    @property
    def total_room(self) -> Decimal | None:
        """What is left of the total open-risk limit for a new trade (None = no total limit set)."""
        if self.equity is None or self.max_total_pct is None:
            return None
        return self.equity * self.max_total_pct / 100 - (self.open_risk or Decimal(0))

    @property
    def allowed(self) -> Decimal | None:
        """The planned loss this trade may have: the smaller of the trade budget and the remaining total room."""
        room = self.total_room
        return self.budget if room is None or self.budget is None else min(self.budget, max(room, Decimal(0)))


@dataclass(frozen=True)
class Spec:
    """Trading 212 instrument specification, typed in by the user. None = unknown."""
    contract: Decimal | None = None      # units of the underlying per 1 CFD quantity (stock CFD: usually 1 share)
    min_qty: Decimal | None = None
    step: Decimal | None = None
    max_qty: Decimal | None = None       # optional
    margin_pct: Decimal | None = None    # optional, e.g. 20 (= leverage 1:5)

    def missing(self) -> list[str]:
        return [name for name, v in (("velikost kontraktu", self.contract), ("minimální množství", self.min_qty),
                                     ("krok množství", self.step)) if v is None]


@dataclass(frozen=True)
class Fx:
    rate: Decimal                 # 1 unit of the quote currency in the account currency
    time: datetime
    source: str                   # "Twelve Data" | "ruční zadání" | "stejná měna"


@dataclass(frozen=True)
class Plan:
    entry: Decimal | None
    sl: Decimal | None
    tp: Decimal | None = None
    confirmed: bool = False       # a confirmed BUY/SELL of the analysis, unchanged by the user
    origin: str = ""              # "potvrzený signál" | "výzkumné nastavení" | "ruční zadání"
    data_time: datetime | None = None   # close time of the market data behind entry/SL (None = typed in)

    @property
    def direction(self) -> str | None:
        if self.entry is None or self.sl is None or self.entry == self.sl:
            return None
        return "BUY" if self.sl < self.entry else "SELL"


@dataclass
class Sizing:
    state: str = NODATA
    headline: str = "NELZE SPOČÍTAT"
    messages: list[str] = field(default_factory=list)
    budget: Decimal | None = None
    qty: Decimal | None = None
    notional: Decimal | None = None
    margin: Decimal | None = None
    loss_sl: Decimal | None = None
    profit_tp: Decimal | None = None
    rr: Decimal | None = None
    risk_pct: Decimal | None = None      # planned loss / equity in %
    binding: str = ""                    # the limit that decided the quantity
    direction: str | None = None
    fx: Fx | None = None


def floor_step(x: Decimal, step: Decimal) -> Decimal:
    return (x / step).to_integral_value(rounding=ROUND_FLOOR) * step


def size(acc: Account, spec: Spec, plan: Plan, spread: Decimal | None, fx: Fx | None, now: datetime,
         quote: str = "") -> Sizing:
    out = Sizing(budget=acc.budget, fx=fx, direction=plan.direction)
    miss = []
    if acc.equity is None:
        miss.append("hodnota účtu")
    if not (Decimal("0") < acc.risk_pct <= Decimal("100")):
        miss.append("platné riziko v %")
    if spec.missing():
        miss.append("specifikace instrumentu (" + ", ".join(spec.missing()) + ")")
    if plan.entry is None or plan.sl is None:
        miss.append("vstupní cena a stop-loss")
    if fx is None:
        miss.append(f"kurz {quote or 'měny instrumentu'} → {acc.currency}")
    elif fx.source != "stejná měna" and now - fx.time > (MAX_MANUAL_FX_AGE if fx.source == "ruční zadání"
                                                          else MAX_FX_AGE):
        miss.append(f"aktuální kurz (poslední {fx.time.astimezone():%d.%m. %H:%M}, {fx.source})")
    if plan.data_time is not None and now - plan.data_time > MAX_DATA_AGE:
        miss.append(f"aktuální tržní data (poslední {plan.data_time.astimezone():%H:%M}, spusťte analýzu znovu)")
    if spread is None:
        miss.append("spread z Trading 212")
    if miss:
        out.messages = ["Chybí: " + "; ".join(miss) + "."]
        return out

    # stop-loss / target on the right side
    d, sign = plan.direction, (1 if plan.direction == "BUY" else -1)
    bad = []
    if d is None:
        bad.append("stop-loss je rovný vstupu")
    if plan.tp is not None and d and sign * (plan.tp - plan.entry) <= 0:
        bad.append(f"take-profit je na špatné straně vstupu pro {d}")
    if bad:
        out.state, out.headline, out.messages = LIMIT, "NEPLATNÝ STOP-LOSS", bad
        return out

    room = acc.total_room
    if room is not None and room <= 0:
        out.state, out.headline = LIMIT, "PŘEKROČENO CELKOVÉ RIZIKO"
        out.messages = [f"Otevřené pozice už mají riziko {money(acc.open_risk, acc.currency)}, limit všech pozic je "
                        f"{acc.max_total_pct.normalize():f} % účtu = "
                        f"{money(acc.equity * acc.max_total_pct / 100, acc.currency)}."
                        " Další obchod nelze otevřít bez překročení limitu."]
        return out
    contract, rate = spec.contract, fx.rate
    dist = abs(plan.entry - plan.sl)
    reserve = dist * acc.reserve_pct / 100                  # slippage reserve beyond the stop
    risk_unit = (dist + spread + reserve) * contract * rate  # spread paid once (half at entry, half at exit)
    notional_unit = plan.entry * contract * rate
    out.budget = acc.allowed
    caps = {"riziko": acc.budget / risk_unit}
    if room is not None and room < acc.budget:
        caps["celkové otevřené riziko"] = room / risk_unit
    if acc.max_notional_pct is not None:
        caps["limit expozice"] = acc.equity * acc.max_notional_pct / 100 / notional_unit
    margin_unit = notional_unit * spec.margin_pct / 100 if spec.margin_pct is not None else None
    if acc.free_margin is not None and margin_unit:
        caps["volná marže"] = acc.free_margin / margin_unit
    if spec.max_qty is not None:
        caps["maximální množství"] = spec.max_qty
    out.binding = min(caps, key=caps.get)
    qty = floor_step(caps[out.binding], spec.step)

    if qty < spec.min_qty:
        q = spec.min_qty
        min_loss = q * risk_unit
        out.state, out.qty = LIMIT, None
        if out.binding == "maximální množství":
            out.headline = "NEPLATNÁ SPECIFIKACE"
            out.messages = ["Maximální množství je menší než minimální – zkontrolujte specifikaci instrumentu."]
        elif out.binding in ("riziko", "celkové otevřené riziko"):
            out.headline = "PŘÍLIŠ RIZIKOVÉ"
            out.messages = [TOO_RISKY, f"Minimální množství {fmt_qty(q)} by při SL znamenalo ztrátu "
                                       f"{money(min_loss, acc.currency)} = {min_loss / acc.equity * 100:.2f} % účtu "
                                       + (f"(limit {acc.risk_pct.normalize():f} %)." if out.binding == "riziko" else
                                          f"(zbývá z limitu všech pozic {money(out.budget, acc.currency)}).")]
        elif out.binding == "volná marže":
            out.headline = "NEDOSTATEČNÁ MARŽE"
            out.messages = [f"Minimální množství {fmt_qty(q)} vyžaduje marži {money(q * margin_unit, acc.currency)},"
                            f" volná marže je {money(acc.free_margin, acc.currency)}."]
        else:
            out.headline = "PŘEKROČEN LIMIT EXPOZICE"
            out.messages = [f"Minimální množství {fmt_qty(q)} má nominální hodnotu "
                            f"{money(q * notional_unit, acc.currency)}, limit je {acc.max_notional_pct.normalize():f}"
                            f" % účtu."]
        return out

    if qty * risk_unit > out.budget:          # re-check after rounding (never more than the allowed loss)
        out.state, out.headline = LIMIT, "PŘÍLIŠ RIZIKOVÉ"
        out.messages = [TOO_RISKY, "Po zaokrouhlení na krok množství by ztráta při SL překročila rozpočet."]
        return out
    out.qty = qty
    out.notional = qty * notional_unit
    out.margin = qty * margin_unit if margin_unit is not None else None
    out.loss_sl = qty * risk_unit
    out.risk_pct = out.loss_sl / acc.equity * 100
    if plan.tp is not None:
        out.profit_tp = qty * (abs(plan.tp - plan.entry) - spread) * contract * rate
        out.rr = abs(plan.tp - plan.entry) / dist
    out.state = OK if plan.confirmed else ORIENTATION
    out.headline = f"{fmt_qty(qty)} ks"
    out.messages = [f"Množství určuje: {out.binding}."]
    if acc.reserve_pct:
        out.messages.append(f"Rezerva na skluz {acc.reserve_pct.normalize():f} % vzdálenosti SL je započtena.")
    if not plan.confirmed:
        out.messages.insert(0, f"Orientační scénář ({plan.origin or 'ruční zadání'}) – nejde o potvrzený vstup.")
    if margin_unit is None:
        out.messages.append("Maržový požadavek není zadán – marže NEDOSTUPNÁ, kontrola volné marže neproběhla.")
    elif acc.free_margin is None:
        out.messages.append("Volná marže není zadána – kontrola marže neproběhla.")
    return out


def fmt_qty(q: Decimal) -> str:
    s = f"{q.normalize():f}"
    return s.replace(".", ",")


def money(x: Decimal | None, ccy: str) -> str:
    if x is None:
        return "–"
    s = f"{x.quantize(Decimal('0.01')):,.2f}".replace(",", " ").replace(".", ",")
    return f"{s} {ccy}"
