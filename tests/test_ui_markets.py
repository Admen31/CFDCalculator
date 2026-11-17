"""v2.5 UI: DOSTUPNOST TRŽNÍCH DAT page, search/filter, adding an instrument from the symbol directory."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtCore")
from test_ui_auto import Reader  # noqa: E402
from test_ui_smooth import app, make  # noqa: E402,F401

from cfdcalc.instruments import BY_SYMBOL, CATALOG  # noqa: E402
from cfdcalc.ui_markets import AddInstrumentDialog, MarketsDialog  # noqa: E402

ROW = {"symbol": "RHM", "instrument_name": "Rheinmetall AG", "exchange": "XETR", "mic_code": "XETR",
       "currency": "EUR", "instrument_type": "Common Stock", "country": "Germany", "plan": "Grow"}


@pytest.fixture
def cleanup():
    yield
    for inst in [i for i in CATALOG if i.custom]:
        CATALOG.remove(inst)
        BY_SYMBOL.pop(inst.symbol, None)


def test_markets_page_lists_filters_and_counts(app, make):  # noqa: F811
    w = make(Reader("Gold"))
    d = MarketsDialog(w.s, "Basic", w.availability(), "dnes 0/800", None, w)
    assert d.table.rowCount() == len(CATALOG) and "plná analýza" in d.summary.text()
    d.category.setCurrentIndex(d.category.findData("crypto"))
    assert d.table.rowCount() == 12
    d.category.setCurrentIndex(0)
    d.filter.setText("silver")
    names = {d.table.item(r, 0).text() for r in range(d.table.rowCount())}
    assert names == {"Silver", "iShares Silver Trust"}


def test_add_instrument_is_stored_and_reloaded(app, make, cleanup):  # noqa: F811
    w = make(Reader("Gold"))
    dlg = AddInstrumentDialog(w.s, lambda q: [ROW], w)
    dlg.query.setText("Rheinmetall")
    dlg.run()
    dlg.table.selectRow(0)
    dlg.t212.setText("Rheinmetall")
    dlg.add()
    assert dlg.added and BY_SYMBOL["RHM"].custom and BY_SYMBOL["RHM"].exchange == "XETR"
    CATALOG.remove(BY_SYMBOL.pop("RHM"))                    # simulate a restart: only the stored row remains
    w2 = make(Reader("Gold"))
    assert "RHM" in BY_SYMBOL and not w2.custom_problems
    assert any("Rheinmetall" in k for k in w2.bar._entries)  # searchable in the instrument bar


def test_unsafe_directory_row_is_refused(app, make, cleanup):  # noqa: F811
    w = make(Reader("Gold"))
    dlg = AddInstrumentDialog(w.s, lambda q: [dict(ROW, mic_code="XTKS", exchange="TSE")], w)
    dlg.query.setText("x")
    dlg.run()
    dlg.table.selectRow(0)
    dlg.add()
    assert dlg.added is None and "obchodní hodiny" in dlg.note.text() and "RHM" not in BY_SYMBOL
