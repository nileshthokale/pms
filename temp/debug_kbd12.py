"""Debug the item->batch->qty keyboard step in the one-row entry bar."""
import os
import sys
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication(sys.argv)

import test_counter_sale_input as tsi  # noqa: E402

tsi._DBBase.setUpClass()


class Probe(tsi._DBBase):
    def runTest(self):
        pass


case = Probe()
case.setUp()
with mock.patch.multiple(QMessageBox, warning=mock.DEFAULT,
                         information=mock.DEFAULT, critical=mock.DEFAULT,
                         question=mock.DEFAULT):
    from screens.counter_sale import CounterSalePage
    page = CounterSalePage()
    page.resize(1366, 768)
    page.show()
    app.processEvents()
    entry = page._sale_panel._entry_bar
    item, batch, qty = entry.item_combo, entry.batch_combo, entry.qty_edit

    def state(tag):
        popup = item.completer().popup()
        bpopup = batch.completer().popup()
        print(f"{tag:28s} focus={type(app.focusWidget()).__name__}"
              f" item_idx={item.currentIndex()} item_data={item.currentData()}"
              f" batch_count={batch.count()} batch_idx={batch.currentIndex()}"
              f" batch_data={batch.currentData()}"
              f" item_popup={popup.isVisible()}"
              f" batch_popup={bpopup.isVisible()}")

    item.setFocus()
    app.processEvents()
    QTest.keyClicks(item.lineEdit(), "Test")
    state("after typing Test")
    QTest.keyClick(item.lineEdit(), Qt.Key_Down)
    state("after Down")
    QTest.keyClick(item.lineEdit(), Qt.Key_Return)
    app.processEvents()
    state("after Enter (item)")

    QTest.keyClick(batch.lineEdit(), Qt.Key_Down)
    state("after Down (batch)")
    model = batch.completer().completionModel()
    print("  batch completion rows:", model.rowCount(),
          [model.index(r, 0).data() for r in range(model.rowCount())])
    QTest.keyClick(batch.lineEdit(), Qt.Key_Return)
    app.processEvents()
    state("after Enter (batch)")
    print("  focus is qty?", app.focusWidget() is qty)

    # try a second event-loop turn for the singleShot focus timer
    app.processEvents()
    state("after 2nd processEvents")

case.tearDown()
