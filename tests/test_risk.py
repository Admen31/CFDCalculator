"""v2.4 risk management: position size from the account's risk budget. Hand-calculated expectations.

The specifications used here are test values chosen for the arithmetic, not Trading 212 specifications.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from cfdcalc import risk
from cfdcalc.instruments import BY_SYMBOL
from cfdcalc.risk import LIMIT, NODATA, OK, ORIENTATION, TOO_RISKY, Account, Fx, Plan, Spec, size

NOW = datetime(2026, 11, 17, 15, 0, tzinfo=timezone.utc)
SAME = Fx(D(1), NOW, "stejná měna")


def fx(rate):
    return Fx(D(rate), NOW - timedelta(minutes=5), "Twelve Data")


STOCK = Spec(D(1), D("0.01"), D("0.01"))          # 1 CFD = 1 share, fractional quantities
FOREX = Spec(D(1), D(1), D(1))                      # quantity in units of the base currency (test values)
GOLD = Spec(D(1), D("0.01"), D("0.01"), margin_pct=D(5))
INDEX = Spec(D(1), D("0.1"), D("0.1"))


def plan(entry, sl, tp=None, confirmed=True):
    return Plan(D(entry), D(sl), D(tp) if tp else None, confirmed, "potvrzený signál", NOW - timedelta(minutes=1))


def test_budget_example_from_the_brief():
    acc = Account(D(50000), "CZK", D(2))
    assert acc.budget == D(1000)


@pytest.mark.parametrize("pct, budget", [("0.5", 250), ("1", 500), ("1.5", 750), ("2", 1000)])
def test_risk_levels_czk_stock(pct, budget):
    # NVIDIA 180 USD, SL 176 (4 USD) + spread 0.05, 1 USD = 23 CZK -> 4.05 * 23 = 93.15 CZK per share
    acc = Account(D(50000), "CZK", D(pct))
    r = size(acc, STOCK, plan("180", "176", "188"), D("0.05"), fx("23"), NOW, "USD")
    expect = risk.floor_step(D(budget) / (D("4.05") * 23), D("0.01"))
    assert r.state == OK and r.qty == expect and r.loss_sl <= D(budget)
    assert r.loss_sl == expect * D("4.05") * 23 and r.notional == expect * 180 * 23
    assert r.risk_pct <= D(pct) and r.rr == 2


def test_quantity_is_rounded_down_to_the_step():
    acc = Account(D(1000), "USD", D(1))                       # budget 10 USD
    r = size(acc, Spec(D(1), D(1), D(1)), plan("100", "97"), D(0), SAME, NOW)   # 3.33 -> 3
    assert r.qty == 3 and r.loss_sl == 9
    r = size(acc, Spec(D(1), D("0.1"), D("0.1")), plan("100", "97"), D(0), SAME, NOW)   # 3.3
    assert r.qty == D("3.3")


def test_eur_account_forex_pair_quoted_in_usd():
    # EUR/USD 1.0850 SL 1.0820 (30 pips) + spread 0.00008, account EUR, 1 USD = 0.92 EUR
    acc = Account(D(10000), "EUR", D(1))                      # budget 100 EUR
    r = size(acc, FOREX, plan("1.0850", "1.0820", "1.0910"), D("0.00008"), fx("0.92"), NOW, "USD")
    per_unit = D("0.00308") * D("0.92")
    assert r.qty == risk.floor_step(D(100) / per_unit, D(1)) and r.qty == 35290   # 100 / 0.0028336 = 35 290.8
    assert r.loss_sl <= 100 and r.direction == "BUY"


def test_contract_size_changes_the_quantity():
    acc = Account(D(10000), "USD", D(1))
    one = size(acc, Spec(D(1), D("0.01"), D("0.01")), plan("2000", "1990"), D(0), SAME, NOW)
    hundred = size(acc, Spec(D(100), D("0.01"), D("0.01")), plan("2000", "1990"), D(0), SAME, NOW)
    assert one.qty == 10 and hundred.qty == D("0.1")          # same money risk, 100x fewer contracts


def test_sell_commodity_with_margin_and_usd_to_czk():
    # Gold SELL 2000, SL 2010, TP 1980, spread 0.35; 1 USD = 23 CZK; margin 5 %
    acc = Account(D(50000), "CZK", D(2))
    r = size(acc, GOLD, plan("2000", "2010", "1980"), D("0.35"), fx("23"), NOW, "USD")
    per = D("10.35") * 23
    assert r.direction == "SELL" and r.qty == risk.floor_step(D(1000) / per, D("0.01"))
    assert r.margin == r.notional * D("0.05") and r.profit_tp == r.qty * D("19.65") * 23


def test_index_in_usd_with_usd_account():
    acc = Account(D(20000), "USD", D("0.5"))                  # budget 100 USD
    r = size(acc, INDEX, plan("18000", "17950"), D("1.8"), SAME, NOW)
    assert r.qty == risk.floor_step(D(100) / D("51.8"), D("0.1")) == D("1.9")


def test_both_limits_must_hold():
    acc = Account(D(50000), "CZK", D(2), max_notional_pct=D(10))   # exposure max 5 000 CZK
    r = size(acc, STOCK, plan("180", "176"), D("0.05"), fx("23"), NOW, "USD")
    assert r.binding == "limit expozice" and r.notional <= 5000 and r.loss_sl < 1000
    assert r.qty == risk.floor_step(D(5000) / (180 * 23), D("0.01"))


def test_insufficient_margin_reduces_then_refuses():
    acc = Account(D(50000), "CZK", D(2), free_margin=D(500))
    r = size(acc, GOLD, plan("2000", "2010"), D("0.35"), fx("23"), NOW, "USD")
    assert r.binding == "volná marže" and r.margin <= 500
    acc = Account(D(50000), "CZK", D(2), free_margin=D(10))
    r = size(acc, GOLD, plan("2000", "2010"), D("0.35"), fx("23"), NOW, "USD")
    assert r.state == LIMIT and r.qty is None and r.headline == "NEDOSTATEČNÁ MARŽE"


def test_too_small_account_never_raises_the_risk():
    acc = Account(D(500), "CZK", D(2))                         # budget 10 CZK, one share risks 93 CZK
    r = size(acc, Spec(D(1), D(1), D(1)), plan("180", "176"), D("0.05"), fx("23"), NOW, "USD")
    assert r.state == LIMIT and r.qty is None and r.messages[0] == TOO_RISKY
    assert "18.63 % účtu" in r.messages[1]


@pytest.mark.parametrize("spec, plan_, fx_, missing", [
    (Spec(), plan("180", "176"), fx("23"), "specifikace instrumentu"),
    (STOCK, Plan(None, None), fx("23"), "vstupní cena a stop-loss"),
    (STOCK, plan("180", "176"), None, "kurz USD → CZK"),
    (STOCK, plan("180", "176"), Fx(D(23), NOW - timedelta(hours=3), "Twelve Data"), "aktuální kurz"),
    (STOCK, Plan(D(180), D(176), None, True, "x", NOW - timedelta(hours=1)), fx("23"), "aktuální tržní data"),
])
def test_missing_or_stale_inputs_give_no_quantity(spec, plan_, fx_, missing):
    r = size(Account(D(50000), "CZK"), spec, plan_, D("0.05"), fx_, NOW, "USD")
    assert r.state == NODATA and r.qty is None and r.headline == "NELZE SPOČÍTAT" and missing in r.messages[0]


def test_missing_equity_and_spread():
    r = size(Account(None), STOCK, plan("180", "176"), None, fx("23"), NOW, "USD")
    assert r.state == NODATA and "hodnota účtu" in r.messages[0] and "spread" in r.messages[0]


def test_invalid_stop_loss():
    acc = Account(D(50000), "CZK")
    assert size(acc, STOCK, plan("180", "180"), D("0.05"), fx("23"), NOW, "USD").headline == "NEPLATNÝ STOP-LOSS"
    r = size(acc, STOCK, plan("180", "176", "170"), D("0.05"), fx("23"), NOW, "USD")   # BUY with TP below
    assert r.state == LIMIT and r.qty is None and "take-profit" in r.messages[0]


def test_unconfirmed_plan_is_only_orientational():
    r = size(Account(D(50000), "CZK"), STOCK, plan("180", "176", confirmed=False), D("0.05"), fx("23"), NOW, "USD")
    assert r.state == ORIENTATION and "nejde o potvrzený vstup" in r.messages[0]


def test_manual_fx_lasts_a_day_and_input_parsing():
    acc = Account(D(50000), "CZK")
    manual = Fx(D(23), NOW - timedelta(hours=20), "ruční zadání")
    assert size(acc, STOCK, plan("180", "176"), D("0.05"), manual, NOW, "USD").state == OK
    assert risk.num("50 000") == 50000 and risk.num("1,5") == D("1.5") and risk.num("0") is None
    assert risk.num("abc") is None and risk.num("-3") is None and risk.num("nan") is None


def test_quote_currency_from_the_catalogue():
    q = {s: risk.quote_currency(BY_SYMBOL[s]) for s in ("EUR/USD", "USD/JPY", "XAU/USD", "NVDA", "DAX", "FTSE")}
    assert q == {"EUR/USD": "USD", "USD/JPY": "JPY", "XAU/USD": "USD", "NVDA": "USD", "DAX": "EUR", "FTSE": "GBP"}


def test_money_format():
    assert risk.money(D("1000"), "CZK") == "1 000,00 CZK" and risk.fmt_qty(D("3.30")) == "3,3"


def test_exchange_rate_direct_inverse_and_invalid(monkeypatch):
    from test_data_errors import KEY, http_error, install

    from cfdcalc.data import DataError, TwelveData
    seen = install(monkeypatch, lambda p: {"symbol": "USD/CZK", "rate": 23.1, "timestamp": 1794927600}
                   if p["symbol"] == "USD/CZK" else http_error(404, {"code": 404, "status": "error",
                                                                      "message": "**symbol** not found"}))
    rate, when = TwelveData(KEY).exchange_rate("USD", "CZK")
    assert rate == D("23.1") and when.tzinfo and KEY not in seen[0][0]
    rate, _ = TwelveData(KEY).exchange_rate("CZK", "USD")            # only USD/CZK listed -> inverted
    assert abs(rate - 1 / D("23.1")) < D("1e-20")
    install(monkeypatch, lambda p: {"symbol": p["symbol"], "rate": 0, "timestamp": 1794927600})
    with pytest.raises(DataError, match="neplatný kurz"):
        TwelveData(KEY).exchange_rate("USD", "CZK")
    install(monkeypatch, lambda p: {"symbol": p["symbol"]})
    with pytest.raises(DataError, match="bez hodnoty"):
        TwelveData(KEY).exchange_rate("USD", "CZK")
