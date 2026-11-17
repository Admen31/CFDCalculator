"""v2.5 UI: DOSTUPNOST TRŽNÍCH DAT (every instrument with its data source and state) and adding instruments from
the Twelve Data symbol directory with a verified identity. No network unless the user presses a button."""
from __future__ import annotations

import json

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from .analysis import PROFILES
from .availability import Availability
from .instruments import (BY_SYMBOL, CATALOG, COINBASE, TWELVE, Instrument, from_directory, plan_ok, register,
                          sources)

PROVIDER_NAMES = {TWELVE: "Twelve Data", COINBASE: "Coinbase Exchange"}
DELAY = {TWELVE: "dle tarifu – stáří kontroluje každá analýza", COINBASE: "reálný čas (veřejné API)"}
COLUMNS = ("Název", "Typ trhu", "Poskytovatel", "Časové rámce", "Zpoždění", "Stav API", "Poslední ověření",
           "Přesný / referenční", "Plná analýza")
CUSTOM_KEY = "custom/instruments"


def row_for(inst: Instrument, plan: str, av: Availability) -> list[str]:
    """One table row. Local information only (catalogue, plan setting, availability record)."""
    srcs = sources(inst)
    usable = [s for s in srcs if plan_ok(s, plan)]
    if not srcs:
        return [inst.name, PROFILES[inst.kind].name, "–", "–", "–", "bez zdroje", "–", "–", "ne – není namapován"]
    s = usable[0] if usable else srcs[0]
    prov = PROVIDER_NAMES[s.provider] + (f" ({s.plan})" if s.provider == TWELVE else "")
    if len(usable) > 1:
        prov += " + " + ", ".join(PROVIDER_NAMES[x.provider] + ("" if x.exact else f" ref. {x.symbol}")
                                  for x in usable[1:])
    state, text = av.summary(PROVIDER_NAMES[s.provider], s.symbol)
    when = text.rsplit(" ", 2)[-2:] if state != "neověřeno" else ["–"]
    exact = "přesný" if s.exact else f"referenční: {s.label or s.symbol}"
    if not usable:
        full = f"ne – vyžaduje tarif {min(x.plan for x in srcs)} (nastaven {plan})"
    elif state == "nedostupné":
        full = "ne – " + text.split("–", 1)[-1].strip()
    elif not s.exact:
        full = "jen směr (referenční data, bez vstupu/SL)"
    else:
        full = "ano" if state == "ověřeno" else "ano (zatím neověřeno)"
    return [inst.name, PROFILES[inst.kind].name, prov, "5m · 15m · 1h", DELAY[s.provider], state, " ".join(when),
            exact, full]


def load_custom(s: QSettings) -> list[str]:
    """Register the user's instruments (validated again); returns problems for the ones that were skipped."""
    problems = []
    try:
        rows = json.loads(str(s.value(CUSTOM_KEY, "[]")))
    except ValueError:
        rows = []
    for row in rows if isinstance(rows, list) else []:
        try:
            if row.get("symbol") not in BY_SYMBOL:
                register(from_directory(row, row.get("t212", "")))
        except (ValueError, AttributeError) as e:
            problems.append(f"{row.get('symbol', '?') if isinstance(row, dict) else '?'}: {e}")
    return problems


class AddInstrumentDialog(QDialog):
    """Search the Twelve Data directory and add one listing (identity shown and stored as returned)."""

    def __init__(self, s: QSettings, search, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Přidat instrument z adresáře symbolů")
        self.resize(760, 420)
        self.s, self.search_fn, self.rows, self.added = s, search, [], None
        self.query = QLineEdit(placeholderText="ticker nebo název, např. SAP, Rheinmetall, VWCE")
        self.t212 = QLineEdit(placeholderText="název v Trading 212 (pro rozpoznání z obrazovky, nepovinné)")
        go = QPushButton("Hledat")
        go.clicked.connect(self.run)
        self.query.returnPressed.connect(self.run)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(("Symbol", "Název", "Burza", "MIC", "Měna", "Typ", "Tarif TD"))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.note = QLabel("Hledání pošle 1 dotaz na Twelve Data. Přidat lze jen akcie, ADR a ETF z burz se známými "
                           "obchodními hodinami.", objectName="muted", wordWrap=True)
        add = QPushButton("Přidat vybraný")
        add.clicked.connect(self.add)
        top = QHBoxLayout()
        top.addWidget(self.query, 1)
        top.addWidget(go)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.t212)
        lay.addWidget(self.note)
        lay.addWidget(add, 0, Qt.AlignmentFlag.AlignRight)

    def run(self):
        q = self.query.text().strip()
        if not q:
            return
        try:
            self.rows = self.search_fn(q)
        except Exception as e:  # noqa: BLE001 - shown to the user (DataError text is already redacted)
            self.note.setText(f"Hledání selhalo: {e}")
            return
        self.table.setRowCount(len(self.rows))
        for r, row in enumerate(self.rows):
            for c, key in enumerate(("symbol", "instrument_name", "exchange", "mic_code", "currency",
                                     "instrument_type", "plan")):
                self.table.setItem(r, c, QTableWidgetItem(row.get(key, "")))
        self.note.setText(f"{len(self.rows)} výsledků. Vyberte přesný výpis (burza a měna musí odpovídat CFD "
                          "v Trading 212).")

    def add(self):
        r = self.table.currentRow()
        if r < 0 or r >= len(self.rows):
            self.note.setText("Vyberte řádek.")
            return
        row = dict(self.rows[r], t212=self.t212.text().strip())
        try:
            inst = from_directory(row, row["t212"])
        except ValueError as e:
            self.note.setText(f"Nelze přidat: {e}")
            return
        register(inst)
        try:
            stored = json.loads(str(self.s.value(CUSTOM_KEY, "[]")))
        except ValueError:
            stored = []
        stored.append(row)
        self.s.setValue(CUSTOM_KEY, json.dumps(stored, ensure_ascii=False))
        self.added = inst
        self.accept()


class MarketsDialog(QDialog):
    """DOSTUPNOST TRŽNÍCH DAT."""

    def __init__(self, s: QSettings, plan: str, av: Availability, usage: str, search=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dostupnost tržních dat")
        self.resize(1100, 560)
        self.s, self.plan, self.av, self.search_fn = s, plan, av, search
        self.filter = QLineEdit(placeholderText="Hledat instrument…")
        self.category = QComboBox()
        self.category.addItem("Všechny trhy", "")
        for key, prof in PROFILES.items():
            self.category.addItem(prof.name, key)
        self.filter.textChanged.connect(self.fill)
        self.category.currentIndexChanged.connect(self.fill)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.summary = QLabel("", objectName="muted", wordWrap=True)
        self.usage = QLabel(f"Twelve Data: tarif {plan} · {usage}", objectName="muted", wordWrap=True)
        add = QPushButton("Přidat instrument…")
        add.setEnabled(search is not None)
        add.setToolTip("Vyhledá v adresáři symbolů Twelve Data (potřebuje API klíč, 1 dotaz)")
        add.clicked.connect(self.add)
        top = QHBoxLayout()
        top.addWidget(self.filter, 1)
        top.addWidget(self.category)
        top.addWidget(add)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.summary)
        lay.addWidget(self.usage)
        self.fill()

    def fill(self):
        text, cat = self.filter.text().strip().lower(), self.category.currentData()
        items = [i for i in CATALOG if (not cat or i.kind == cat)
                 and (not text or text in i.name.lower() or text in i.symbol.lower()
                      or any(text in a.lower() for a in i.aliases))]
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(items))
        full = ref = 0
        for r, inst in enumerate(items):
            row = row_for(inst, self.plan, self.av)
            full += row[-1].startswith("ano")
            ref += row[-1].startswith("jen směr")
            for c, value in enumerate(row):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(r, c, item)
        self.table.setSortingEnabled(True)
        self.summary.setText(f"{len(items)} instrumentů · plná analýza {full} · jen směr z referenčních dat {ref} · "
                             f"bez dat v tarifu {len(items) - full - ref}. Stav API vychází z posledních analýz "
                             "a ručních ověření (bez nových dotazů).")

    def add(self):
        dlg = AddInstrumentDialog(self.s, self.search_fn, self)
        if dlg.exec() and dlg.added:
            QMessageBox.information(self, "Instrument přidán", f"{dlg.added.name} ({dlg.added.symbol}, "
                                    f"{dlg.added.exchange}, {dlg.added.currency}) je v katalogu. Spread a "
                                    "specifikaci pro Risk zadejte ručně.")
            self.fill()
