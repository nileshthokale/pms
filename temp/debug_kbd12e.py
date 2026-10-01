"""Why is qty.setFocus() a no-op after keyboard batch acceptance?"""
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
    e = page._sale_panel._entry_bar
    item, batch, qty = e.item_combo, e.batch_combo, e.qty_edit

    real_set_focus = qty.setFocus

    def traced_set_focus(*args, **kwargs):
        print("     qty.setFocus called; isVisible =", qty.isVisible(),
              "enabled =", qty.isEnabled(),
              "focusPolicy =", qty.focusPolicy(),
              "same window:", qty.window() is batch.window())
        result = real_set_focus(*args, **kwargs)
        print("       -> focusWidget now:",
              type(app.focusWidget()).__name__,
              "(is qty:", app.focusWidget() is qty, ")")
        return result

    qty.setFocus = traced_set_focus

    item.setFocus()
    app.processEvents()
    QTest.keyClicks(item.lineEdit(), "Test")
    QTest.keyClick(item.lineEdit(), Qt.Key_Down)
    QTest.keyClick(item.lineEdit(), Qt.Key_Return)
    app.processEvents()

    QTest.keyClick(batch.lineEdit(), Qt.Key_Down)
    QTest.keyClick(batch.lineEdit(), Qt.Key_Return)
    app.processEvents()

    print("focus after batch Enter:", "QTY" if app.focusWidget() is qty
          else type(app.focusWidget()).__name__)
    print("qty.isVisible():", qty.isVisible(), " qty.hasFocus():",
          qty.hasFocus(), " item popup:",
          item.completer().popup().isVisible(),
          " batch popup:", batch.completer().popup().isVisible())

    print("manual setFocus now:")
    real_set_focus()
    app.processEvents()
    print("focus after manual setFocus:", "QTY" if app.focusWidget() is qty
          else type(app.focusWidget()).__name__)

    print("focusInEvent probe: qty focusPolicy", qty.focusPolicy())

case.tearDown()
