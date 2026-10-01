"""Does an inactive/offscreen focus window block setFocus after a popup?"""
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


def report(tag, page, qty):
    fw = app.focusWindow()
    print(f"{tag}: focusWindow={type(fw).__name__ if fw else None} "
          f"pageActive={page.isActiveWindow()} "
          f"focusWidget={type(app.focusWidget()).__name__} "
          f"qtyHasFocus={qty.hasFocus()}")


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
    e = page._sale_panel._entry_bar
    item, batch, qty = e.item_combo, e.batch_combo, e.qty_edit

    # --- path A: item popup used -------------------------------------
    item.setFocus()
    app.processEvents()
    QTest.keyClicks(item.lineEdit(), "Test")
    QTest.keyClick(item.lineEdit(), Qt.Key_Down)
    QTest.keyClick(item.lineEdit(), Qt.Key_Return)
    app.processEvents()
    report("after item Enter   ", page, qty)

    qty.setFocus()
    app.processEvents()
    report("A: qty.setFocus    ", page, qty)

    page.activateWindow()
    app.processEvents()
    report("A: after activate   ", page, qty)
    qty.setFocus()
    app.processEvents()
    report("A: qty.setFocus 2  ", page, qty)

    # --- path B: no item popup ---------------------------------------
    item.setCurrentIndex(item.findData(case.item_id))
    app.processEvents()
    report("after programmatic ", page, qty)
    qty.setFocus()
    app.processEvents()
    report("B: qty.setFocus    ", page, qty)

case.tearDown()
