"""Is the zero-timer in _focus_quantity firing at all?"""
import os
import sys
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import Qt, QTimer  # noqa: E402
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

    original = e._focus_quantity

    def traced():
        print("     _focus_quantity called")
        try:
            original()
        except Exception as exc:  # pragma: no cover - diagnostics
            print("     _focus_quantity raised:", repr(exc))
        marker = []
        QTimer.singleShot(0, lambda: marker.append(1))
        app.processEvents()
        print("     marker timer fired inside handler:", bool(marker))

    e._focus_quantity = traced
    batch.completionAccepted.connect(traced)

    item.setFocus()
    app.processEvents()
    QTest.keyClicks(item.lineEdit(), "Test")
    QTest.keyClick(item.lineEdit(), Qt.Key_Down)
    QTest.keyClick(item.lineEdit(), Qt.Key_Return)
    app.processEvents()
    print("focus after item Enter:", "BATCH" if app.focusWidget() is batch
          else type(app.focusWidget()).__name__)

    QTest.keyClick(batch.lineEdit(), Qt.Key_Down)
    QTest.keyClick(batch.lineEdit(), Qt.Key_Return)
    print("focus right after batch Enter:",
          "QTY" if app.focusWidget() is qty
          else ("BATCH" if app.focusWidget() is batch
                else type(app.focusWidget()).__name__))

    marker = []
    QTimer.singleShot(0, lambda: marker.append(1))
    app.processEvents()
    print("fresh zero-timer after Enter fired:", bool(marker))
    print("focus now:", "QTY" if app.focusWidget() is qty
          else ("BATCH" if app.focusWidget() is batch
                else type(app.focusWidget()).__name__))

case.tearDown()
