"""v2.4 UI: "Můj účet" dialog, instrument specification dialog and the RISK MANAGEMENT page of the result card.

Everything the calculation needs is typed in by the user or comes from the analysis / Twelve Data; nothing is read
from Trading 212 and nothing is ordered anywhere. Settings live in the app's local INI file (QSettings).
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from . import risk
from .analysis import BUY, ERROR, NO_DATA, SELL, Result
from .instruments import Instrument
from .risk import LIMIT, NODATA, OK, ORIENTATION, Account, Fx, Plan, Spec
from .widgets import GREEN, RED, YELLOW, tint

STATE_COLORS = {OK: GREEN, ORIENTATION: YELLOW, NODATA: YELLOW, LIMIT: RED}
STATE_ICONS = {OK: "✓", ORIENTATION: "◆", NODATA: "○", LIMIT: "✕"}


def _key(symbol: str) -> str:
    return symbol.replace("/", "_")


def load_account(s: QSettings) -> Account:
    pct = risk.num(s.value("account/risk_pct", "2")) or risk.DEFAULT_RISK
    notional = risk.num(s.value("account/notional_pct", "")) if s.value("account/notional_on", False, type=bool) \
        else None
    total = risk.num(s.value("account/max_total_pct", "")) if s.value("account/total_on", False, type=bool) \
        else None
    return Account(risk.num(s.value("account/equity", "")), str(s.value("account/currency", "CZK")), pct, notional,
                   risk.num(s.value("account/free_margin", "")), risk.num(s.value("account/open_risk", "")), total,
                   risk.num(s.value("account/reserve_pct", "10")) or Decimal(0))


def load_spec(s: QSettings, inst: Instrument) -> Spec:
    k = f"spec/{_key(inst.symbol)}"
    return Spec(*(risk.num(s.value(f"{k}/{f}", "")) for f in ("contract", "min_qty", "step", "max_qty", "margin_pct")))


def manual_fx(s: QSettings, quote: str, acc: str) -> Fx | None:
    rate = risk.num(s.value(f"fx/{quote}{acc}/rate", ""))
    try:
        when = datetime.fromisoformat(str(s.value(f"fx/{quote}{acc}/time", "")))
    except ValueError:
        return None
    return Fx(rate, when, "ruční zadání") if rate else None


def _decimal_text(x) -> str:
    return "" if x is None else f"{Decimal(x).normalize():f}" if isinstance(x, Decimal) else str(x)


class AccountDialog(QDialog):
    """MŮJ ÚČET / RISK MANAGEMENT: equity, currency, risk per trade, optional exposure limit and free margin."""

    def __init__(self, s: QSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Můj účet / Risk management")
        self.s = s
        acc = load_account(s)
        self.equity = QLineEdit(_decimal_text(acc.equity), placeholderText="např. 50 000")
        self.currency = QComboBox()
        self.currency.addItems(risk.CURRENCIES)
        self.currency.setCurrentText(acc.currency)
        self.risk = QDoubleSpinBox(minimum=0.1, maximum=100.0, singleStep=0.1, decimals=2, suffix=" %",
                                   value=float(acc.risk_pct))
        quick = QHBoxLayout()
        for q in risk.QUICK_RISK:
            b = QPushButton(f"{q.replace('.', ',')} %")
            b.clicked.connect(lambda _=False, q=q: self.risk.setValue(float(q)))
            quick.addWidget(b)
        self.notional_on = QCheckBox("Omezit nominální hodnotu pozice na")
        self.notional_on.setChecked(s.value("account/notional_on", False, type=bool))
        self.notional = QDoubleSpinBox(minimum=1.0, maximum=10000.0, decimals=1, suffix=" % účtu",
                                       value=float(risk.num(s.value("account/notional_pct", "10")) or 10))
        self.margin = QLineEdit(_decimal_text(acc.free_margin), placeholderText="nepovinné")
        self.error = QLabel("", objectName="muted")
        form = QFormLayout(self)
        form.addRow("Hodnota účtu (equity)", self.equity)
        form.addRow("Měna účtu", self.currency)
        form.addRow("Max. riziko na obchod", self.risk)
        form.addRow("", quick)
        row = QHBoxLayout()
        row.addWidget(self.notional_on)
        row.addWidget(self.notional)
        form.addRow(row)
        form.addRow("Volná marže (v měně účtu)", self.margin)
        form.addRow(QLabel("Hodnotu účtu zadáváte ručně – aplikace se k Trading 212 nepřipojuje.\n"
                           f"Ukládá se jen lokálně do {s.fileName()}.", objectName="muted"))
        form.addRow(self.error)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def save(self):
        for field, text in ((self.equity, "Hodnota účtu"), (self.margin, "Volná marže")):
            if field.text().strip() and risk.num(field.text()) is None:
                self.error.setText(f"{text}: zadejte kladné číslo.")
                return
        s = self.s
        s.setValue("account/equity", str(risk.num(self.equity.text()) or ""))
        s.setValue("account/currency", self.currency.currentText())
        s.setValue("account/risk_pct", f"{self.risk.value():g}")
        s.setValue("account/notional_on", self.notional_on.isChecked())
        s.setValue("account/notional_pct", f"{self.notional.value():g}")
        s.setValue("account/free_margin", str(risk.num(self.margin.text()) or ""))
        self.accept()


class SpecDialog(QDialog):
    """Trading 212 specification of one instrument, typed in by the user (never filled in by the app)."""

    FIELDS = (("contract", "Velikost kontraktu (jednotek podkladu na 1 CFD)", True),
              ("min_qty", "Minimální množství", True), ("step", "Krok množství", True),
              ("max_qty", "Maximální množství", False), ("margin_pct", "Maržový požadavek (%)", False))

    def __init__(self, s: QSettings, inst: Instrument, account_ccy: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Specifikace – {inst.name} ({inst.symbol})")
        self.s, self.inst, self.acc = s, inst, account_ccy
        self.quote = risk.quote_currency(inst)
        spec = load_spec(s, inst)
        self.edits = {}
        form = QFormLayout(self)
        form.addRow(QLabel("Opište údaje z Trading 212 (detail instrumentu). Aplikace je nikdy nedoplňuje sama;\n"
                           "bez nich výpočet ukáže NELZE SPOČÍTAT.", objectName="muted"))
        for key, label, required in self.FIELDS:
            e = QLineEdit(_decimal_text(getattr(spec, key)), placeholderText="povinné" if required else "nepovinné")
            self.edits[key] = e
            form.addRow(label, e)
        form.addRow("Měna kotace", QLabel(f"{self.quote} (z kótování {inst.symbol})"))
        fx = manual_fx(s, self.quote, account_ccy)
        self.rate = QLineEdit(_decimal_text(fx.rate if fx else None), placeholderText="nepovinné – jinak Twelve Data")
        self.rate.setEnabled(self.quote != account_ccy)
        form.addRow(f"Ruční kurz: 1 {self.quote} = ? {account_ccy}", self.rate)
        if fx:
            form.addRow("", QLabel(f"zadáno {fx.time.astimezone():%d.%m.%Y %H:%M}, platí 24 h", objectName="muted"))
        self.error = QLabel("", objectName="muted")
        form.addRow(self.error)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def save(self):
        for key, label, _ in self.FIELDS:
            t = self.edits[key].text().strip()
            if t and risk.num(t) is None:
                self.error.setText(f"{label}: zadejte kladné číslo.")
                return
        if self.rate.text().strip() and risk.num(self.rate.text()) is None:
            self.error.setText("Kurz: zadejte kladné číslo.")
            return
        k = f"spec/{_key(self.inst.symbol)}"
        for key, _, _ in self.FIELDS:
            self.s.setValue(f"{k}/{key}", str(risk.num(self.edits[key].text()) or ""))
        self.s.setValue(f"{k}/updated", datetime.now(timezone.utc).isoformat())
        rate = risk.num(self.rate.text())
        old = manual_fx(self.s, self.quote, self.acc)
        if rate and (old is None or old.rate != rate):
            self.s.setValue(f"fx/{self.quote}{self.acc}/rate", str(rate))
            self.s.setValue(f"fx/{self.quote}{self.acc}/time", datetime.now(timezone.utc).isoformat())
        elif not rate:
            self.s.remove(f"fx/{self.quote}{self.acc}")
        self.accept()


def plan_from_result(r: Result | None) -> tuple[Plan, str]:
    """What the analysis hands to the risk page, and a note. Only a confirmed BUY/SELL is a confirmed plan."""
    if r is None:
        return Plan(None, None, origin="ruční zadání"), "Zadejte vstup a stop-loss."
    if r.verdict in (NO_DATA, ERROR):
        return Plan(None, None, origin="ruční zadání"), f"Výsledek {r.verdict} – údaje analýzy se nepoužijí."
    if r.reference:     # prices of another product never become CFD entry, SL or position size
        return Plan(None, None, origin="ruční zadání"), ("Analýza běžela na referenčních datech – vstup a SL "
                                                         "z ní nelze převzít; jen ruční orientační scénář.")
    if r.verdict in (BUY, SELL) and r.is_signal:
        return Plan(r.entry, r.sl, r.tp, True, "potvrzený signál", r.data_time), f"Potvrzený {r.verdict} z analýzy."
    o = r.opportunity
    if o and o.state == "trigger" and o.entry is not None and o.sl is not None:
        def dec(x):
            return Decimal(repr(x))
        return (Plan(dec(o.entry), dec(o.sl), dec(o.tp) if o.tp is not None else None, False,
                     f"výzkumné nastavení {o.name}", r.data_time),
                f"{o.name}: výzkumné nastavení, ne potvrzený signál.")
    what = "WATCH" if o and o.state == "watch" else r.verdict
    return Plan(None, None, origin="ruční zadání"), f"{what} – bez potvrzeného vstupu; jen ruční orientační scénář."


class RiskPage(QWidget):
    """RISK MANAGEMENT page. Recomputes on every input change; never opens a trade."""
    summary = Signal(str)          # one line for the main card ("max 12 ks · ztráta 980 CZK"), "" = nothing
    needs_fx = Signal(str, str)    # quote, account currency: ask the window to fetch a rate

    def __init__(self, s: QSettings, spread_of: Callable, fx_of: Callable, clock=lambda: datetime.now(timezone.utc)):
        super().__init__(objectName="page")
        self.s, self.spread_of, self.fx_of, self.clock = s, spread_of, fx_of, clock
        self.inst: Instrument | None = None
        self.base = Plan(None, None)
        self.note = ""
        self._loaded: tuple[str, ...] = ("", "", "")
        self.last: risk.Sizing | None = None
        title = QLabel("RISK MANAGEMENT", objectName="caption")
        self.state = QLabel("", objectName="pill")
        self.state.setFixedHeight(20)
        self.account = QLabel("", objectName="muted")
        self.instrument = QLabel("", objectName="muted")
        acc_btn, spec_btn = QPushButton("Účet…"), QPushButton("Specifikace…")
        for b in (acc_btn, spec_btn):
            b.setStyleSheet("padding: 1px 6px; font-size: 11px;")
        acc_btn.clicked.connect(self.edit_account)
        spec_btn.clicked.connect(self.edit_spec)
        self.entry, self.sl, self.tp = (QLineEdit(placeholderText=t) for t in ("vstup", "stop-loss", "take-profit"))
        for e in (self.entry, self.sl, self.tp):
            e.setFixedHeight(22)
            e.setStyleSheet("padding: 1px 4px; font-size: 11px;")
            e.textEdited.connect(lambda _=None: self.recompute())
        self.qty = QLabel("NELZE SPOČÍTAT")
        self.qty.setFixedHeight(26)
        self.values = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(0)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        for n, name in enumerate(("Nominální hodnota", "Požadovaná marže", "Ztráta při SL", "Zisk při TP",
                                  "Risk/reward", "Riziko účtu")):
            lab, val = QLabel(name, objectName="muted"), QLabel("–", objectName="value")
            lab.setStyleSheet("font-size: 10px; color: #94a3b8; background: transparent;")
            for w in (lab, val):
                w.setFixedHeight(15)
            col = 0 if n < 3 else 2              # left: exposure, margin, loss; right: profit, R:R, risk %
            grid.addWidget(lab, n % 3, col)
            grid.addWidget(val, n % 3, col + 1)
            self.values[name] = val
        self.message = QLabel("", wordWrap=True, objectName="reason")
        self.message.setFixedHeight(42)
        self.message.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        warn = QLabel(risk.WARNING, wordWrap=True, objectName="muted")
        warn.setStyleSheet("font-size: 9px; color: #94a3b8; background: transparent;")
        self.back = QPushButton("◂ Zpět")
        self.back.setStyleSheet("padding: 2px 8px; font-size: 11px;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 6)
        lay.setSpacing(2)
        top = QHBoxLayout()
        top.addWidget(title, 1)
        top.addWidget(self.state)
        lay.addLayout(top)
        for label, btn in ((self.account, acc_btn), (self.instrument, spec_btn)):
            row = QHBoxLayout()
            row.addWidget(label, 1)
            row.addWidget(btn)
            lay.addLayout(row)
        edits = QHBoxLayout()
        edits.setSpacing(4)
        for text, e in (("Vstup", self.entry), ("SL", self.sl), ("TP", self.tp)):
            lab = QLabel(text, objectName="muted")
            lab.setBuddy(e)
            edits.addWidget(lab)
            edits.addWidget(e, 1)
        lay.addLayout(edits)
        lay.addWidget(self.qty)
        lay.addLayout(grid)
        lay.addWidget(self.message)
        lay.addWidget(warn)
        lay.addWidget(self.back, 0, Qt.AlignmentFlag.AlignRight)

    # ---- inputs ----
    def load(self, inst: Instrument | None, r: Result | None):
        """New analysis result or instrument: refill entry/SL/TP from what the analysis may hand over."""
        self.load_plan(inst, *plan_from_result(r))

    def load_plan(self, inst: Instrument | None, plan: Plan, note: str):
        """v2.8: the M15 signal hands over its plan (only a confirmed entry is a confirmed plan)."""
        self.inst = inst
        self.base, self.note = plan, note
        d = inst.decimals if inst else 5
        for e, v in ((self.entry, self.base.entry), (self.sl, self.base.sl), (self.tp, self.base.tp)):
            e.setText("" if v is None else f"{v.quantize(Decimal(1).scaleb(-d)):f}")
        self._loaded = self._texts()
        if self.base.entry is not None:     # the plan uses exactly the rounded values shown
            entry, sl, tp = (risk.num(t) for t in self._loaded)
            self.base = replace(self.base, entry=entry, sl=sl, tp=tp)
        self.recompute()

    def _texts(self) -> tuple[str, ...]:
        return tuple(e.text().strip() for e in (self.entry, self.sl, self.tp))

    def plan(self) -> Plan:
        """The analysis plan while the fields are untouched; any edit makes it a manual (orientational) scenario."""
        if self.base.entry is not None and self._texts() == self._loaded:
            return self.base
        entry, sl, tp = (risk.num(t) for t in self._texts())
        return Plan(entry, sl, tp, False, "ruční úprava" if self.base.entry is not None else "ruční zadání")

    def edit_account(self):
        if AccountDialog(self.s, self).exec():
            self.recompute()

    def edit_spec(self):
        if self.inst and SpecDialog(self.s, self.inst, load_account(self.s).currency, self).exec():
            self.recompute()

    # ---- calculation + display ----
    def recompute(self):
        acc = load_account(self.s)
        inst = self.inst
        self.account.setText(
            "Účet: nezadán – klikněte na Účet…" if acc.equity is None else
            f"Účet {risk.money(acc.equity, acc.currency)} · riziko {acc.risk_pct.normalize():f} % = "
            f"{risk.money(acc.budget, acc.currency)}")
        if inst is None:
            self.instrument.setText("Instrument: nevybrán")
            self._show(risk.Sizing(messages=["Vyberte instrument."]), acc)
            return
        spec = load_spec(self.s, inst)
        quote = risk.quote_currency(inst)
        self.instrument.setText(f"{inst.name} ({inst.symbol}) · spec. "
                                + ("CHYBÍ" if spec.missing() else "zadána"))
        fx = self.fx_of(quote, acc.currency)
        plan = self.plan()
        spread = risk.num(f"{self.spread_of(inst)}")
        out = risk.size(acc, spec, plan, spread, fx, self.clock(), quote)
        # network only when the rate is the last missing piece (never on a mere instrument change)
        if out.state == NODATA and quote != acc.currency and acc.equity is not None and not spec.missing() \
                and plan.entry is not None and plan.sl is not None and spread is not None \
                and (fx is None or fx.source != "stejná měna" and "kurz" in out.messages[0]):
            self.needs_fx.emit(quote, acc.currency)
        self._show(out, acc)

    def _show(self, out: risk.Sizing, acc: Account):
        self.last = out
        color = STATE_COLORS[out.state]
        self.state.setText(f"{STATE_ICONS[out.state]} {out.state}")
        self.state.setStyleSheet(f"background: {tint(color, 34)}; color: {color}; border: 1px solid "
                                 f"{tint(color, 90)}; border-radius: 10px; padding: 0 8px; font-weight: 700; "
                                 "font-size: 10px;")
        big = f"MAX. MNOŽSTVÍ: {out.headline}" if out.qty is not None else out.headline
        self.qty.setText(big)
        self.qty.setStyleSheet(f"font-size: 17px; font-weight: 800; background: transparent; color: {color};")
        c = acc.currency
        rr = "–" if out.rr is None else f"1:{out.rr:.2f}".replace(".", ",")
        pct = "–" if out.risk_pct is None else f"{out.risk_pct:.2f} %".replace(".", ",")
        margin = "NEDOSTUPNÁ" if out.qty is not None and out.margin is None else risk.money(out.margin, c)
        for name, text in (("Nominální hodnota", risk.money(out.notional, c)), ("Požadovaná marže", margin),
                           ("Ztráta při SL", risk.money(out.loss_sl, c)), ("Zisk při TP", risk.money(out.profit_tp, c)),
                           ("Risk/reward", rr), ("Riziko účtu", pct)):
            self.values[name].setText(text)
        fx = f" Kurz: 1 {risk.quote_currency(self.inst)} = {out.fx.rate:.4f} {c} ({out.fx.source})." \
            if out.fx and out.fx.source != "stejná měna" and self.inst else ""
        self.message.setText(" ".join([self.note] + out.messages) + fx)
        self.message.setStyleSheet(f"color: {'#fca5a5' if out.state == LIMIT else '#e5e7eb'}; font-size: 10px; "
                                   "background: transparent;")
        line = ""
        if out.qty is not None and out.state == OK:
            line = f"max {out.headline}"
        self.summary.emit(line)



def plan_from_m15(sig) -> tuple[Plan, str]:
    """Plan of an M15 signal (v2.9): a confirmed or a conditional trade plan with all levels is sized; the
    conditional one is labelled - its entry has not happened yet."""
    if sig is None:
        return Plan(None, None, origin="ruční zadání"), "Zadejte vstup a stop-loss, nebo klikněte START."
    if sig.levels_ok:
        if sig.confirmed:
            return (Plan(sig.entry, sig.sl, sig.tp, True, "potvrzený plán M15", sig.price_time),
                    f"POTVRZENÝ {sig.side} (M15) – vstup nyní.")
        return (Plan(sig.entry, sig.sl, sig.tp, True, "podmíněný plán M15", sig.price_time),
                f"PODMÍNĚNÝ {sig.side} (M15) – vstup zatím nenastal: {sig.trigger}.")
    if sig.reference:
        return Plan(None, None, origin="ruční zadání"), "Referenční data – vstup a SL z nich nelze převzít."
    what = sig.side if sig.side in ("BUY", "SELL") else sig.side
    return Plan(None, None, origin="ruční zadání"), f"{what} bez potvrzeného vstupu – pozice se nepočítá."


class PortfolioPage(QWidget):
    """v2.8 tab PORTFOLIO A RIZIKO: the account (typed in, stored locally) and the position sizing of the current
    instrument (RiskPage). Nothing is read from Trading 212."""
    saved = Signal()

    def __init__(self, s: QSettings, risk_page: RiskPage):
        super().__init__(objectName="page")
        self.s, self.risk_page = s, risk_page
        acc = load_account(s)
        title = QLabel("PORTFOLIO A RIZIKO", objectName="caption")
        self.equity = QLineEdit(_decimal_text(acc.equity), placeholderText="např. 100 000")
        self.currency = QComboBox()
        self.currency.addItems(risk.CURRENCIES)
        self.currency.setCurrentText(acc.currency)
        self.risk = QDoubleSpinBox(minimum=0.1, maximum=100.0, singleStep=0.1, decimals=2, suffix=" %",
                                   value=float(acc.risk_pct))
        self.open_risk = QLineEdit(_decimal_text(acc.open_risk), placeholderText="nepovinné, v měně účtu")
        self.total_on = QCheckBox("Max. celkové otevřené riziko")
        self.total_on.setChecked(s.value("account/total_on", False, type=bool))
        self.total = QDoubleSpinBox(minimum=0.1, maximum=100.0, decimals=1, suffix=" %",
                                    value=float(risk.num(s.value("account/max_total_pct", "6")) or 6))
        self.reserve = QDoubleSpinBox(minimum=0.0, maximum=100.0, decimals=0, suffix=" % SL",
                                      value=float(acc.reserve_pct))
        self.reserve.setToolTip("Rezerva na skluz: o kolik % vzdálenosti SL může být skutečná ztráta větší")
        self.margin = QLineEdit(_decimal_text(acc.free_margin), placeholderText="nepovinné")
        self.status = QLabel("", objectName="muted", wordWrap=True)
        save = QPushButton("Uložit")
        save.clicked.connect(self.save)
        form = QFormLayout()
        form.setVerticalSpacing(3)
        form.addRow("Hodnota portfolia", self.equity)
        form.addRow("Měna účtu", self.currency)
        form.addRow("Riziko na obchod", self.risk)
        form.addRow("Riziko otevřených pozic", self.open_risk)
        row = QHBoxLayout()
        row.addWidget(self.total_on)
        row.addWidget(self.total)
        form.addRow(row)
        form.addRow("Rezerva na skluz", self.reserve)
        form.addRow("Volná marže", self.margin)
        inner = QWidget(objectName="page")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        lay.addWidget(title)
        lay.addLayout(form)
        btns = QHBoxLayout()
        btns.addWidget(self.status, 1)
        btns.addWidget(save)
        lay.addLayout(btns)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        lay.addWidget(line)
        self.spec = SpecForm(s)
        self.spec.saved.connect(risk_page.recompute)
        lay.addWidget(self.spec)
        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.HLine)
        lay.addWidget(line2)
        lay.addWidget(risk_page)
        lay.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(inner)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        self.status.setText(f"Ukládá se jen lokálně ({s.fileName()}). Aplikace se k Trading 212 nepřipojuje.")

    def showEvent(self, e):  # noqa: N802 - Qt API
        self.spec.show_instrument(self.risk_page.inst)
        super().showEvent(e)

    def save(self) -> bool:
        for field, text in ((self.equity, "Hodnota portfolia"), (self.open_risk, "Riziko otevřených pozic"),
                            (self.margin, "Volná marže")):
            if field.text().strip() and risk.num(field.text()) is None:
                self.status.setText(f"{text}: zadejte kladné číslo.")
                return False
        s = self.s
        s.setValue("account/equity", str(risk.num(self.equity.text()) or ""))
        s.setValue("account/currency", self.currency.currentText())
        s.setValue("account/risk_pct", f"{self.risk.value():g}")
        s.setValue("account/open_risk", str(risk.num(self.open_risk.text()) or ""))
        s.setValue("account/total_on", self.total_on.isChecked())
        s.setValue("account/max_total_pct", f"{self.total.value():g}")
        s.setValue("account/reserve_pct", f"{self.reserve.value():g}")
        s.setValue("account/free_margin", str(risk.num(self.margin.text()) or ""))
        s.sync()
        self.status.setText("Uloženo.")
        self.risk_page.recompute()
        self.saved.emit()
        return True


class SpecForm(QWidget):
    """v2.9: the CFD specification of the CURRENT instrument, typed in directly in the Portfolio tab (the same
    settings keys as SpecDialog). The app never guesses it: the unit of the Trading 212 quantity field differs by
    instrument, so the user copies it and can check it against the position value Trading 212 shows."""
    saved = Signal()

    def __init__(self, s: QSettings):
        super().__init__(objectName="page")
        self.s, self.inst = s, None
        self.title = QLabel("SPECIFIKACE CFD", objectName="caption")
        self.edits = {k: QLineEdit(placeholderText="povinné" if req else "nepovinné")
                      for k, _, req in SpecDialog.FIELDS}
        self.edits["contract"].setToolTip("Kolik jednotek podkladu (EUR, uncí, akcií…) představuje 1 kus v poli "
                                          "Množství v Trading 212")
        self.check = QLabel("", objectName="muted", wordWrap=True)
        self.status = QLabel("", objectName="muted", wordWrap=True)
        for e in self.edits.values():
            e.textChanged.connect(self.explain)
        save = QPushButton("Uložit specifikaci")
        save.clicked.connect(self.save)
        form = QFormLayout()
        form.setVerticalSpacing(3)
        labels = {"contract": "1 ks množství T212 = jednotek podkladu", "min_qty": "Minimální množství",
                  "step": "Krok množství", "max_qty": "Maximální množství", "margin_pct": "Marže (%)"}
        for k, _, _ in SpecDialog.FIELDS:
            form.addRow(labels[k], self.edits[k])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        lay.addWidget(self.title)
        lay.addLayout(form)
        lay.addWidget(self.check)
        row = QHBoxLayout()
        row.addWidget(self.status, 1)
        row.addWidget(save)
        lay.addLayout(row)

    def show_instrument(self, inst: Instrument | None):
        self.inst = inst
        self.setEnabled(inst is not None)
        self.title.setText(f"SPECIFIKACE CFD – {inst.name} ({inst.symbol})" if inst else "SPECIFIKACE CFD – "
                           "vyberte instrument")
        spec = load_spec(self.s, inst) if inst else Spec(None, None, None)
        for k, _, _ in SpecDialog.FIELDS:
            self.edits[k].blockSignals(True)
            self.edits[k].setText(_decimal_text(getattr(spec, k)))
            self.edits[k].blockSignals(False)
        self.status.setText("" if spec.contract else "Bez specifikace se POZICE nespočítá (NELZE SPOČÍTAT).")
        self.explain()

    def explain(self):
        """How to verify the quantity unit against Trading 212: position value of 1 000 units."""
        c = risk.num(self.edits["contract"].text())
        if self.inst is None or c is None:
            self.check.setText("Jak ověřit: v Trading 212 zadejte množství (např. 1 000) a porovnejte zobrazenou "
                               "hodnotu pozice s výpočtem zde.")
            return
        q = risk.quote_currency(self.inst)
        self.check.setText(f"Ověření: množství 1 000 v Trading 212 má odpovídat nominálu 1 000 × {c.normalize():f} "
                           f"× cena (v {q}). Pokud Trading 212 ukazuje jinou hodnotu pozice, je kontrakt jiný.")

    def save(self) -> bool:
        if self.inst is None:
            return False
        for key, label, _req in SpecDialog.FIELDS:
            t = self.edits[key].text().strip()
            if t and risk.num(t) is None:
                self.status.setText(f"{label}: zadejte kladné číslo.")
                return False
        k = f"spec/{_key(self.inst.symbol)}"
        for key, _, _ in SpecDialog.FIELDS:
            self.s.setValue(f"{k}/{key}", str(risk.num(self.edits[key].text()) or ""))
        self.s.setValue(f"{k}/updated", datetime.now(timezone.utc).isoformat())
        self.s.sync()
        self.status.setText("Specifikace uložena.")
        self.saved.emit()
        return True
