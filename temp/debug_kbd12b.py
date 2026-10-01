"""Why does batch Enter not move focus to Qty in the no-typing path?"""
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

    batch.completionAccepted.connect(
        lambda: print("   completionAccepted; focus at emit time:",
                      type(app.focusWidget()).__name__))
    app.focusChanged.connect(
        lambda old, new: print("   focusChanged ->",
                               type(new).__name__ if new else None))

    item.setCurrentIndex(item.findData(case.item_id))
    app.processEvents()
    print("after item select: focus is batch?", app.focusWidget() is batch)

    batch.setCurrentIndex(0)
    app.processEvents()
    QTest.keyClick(batch.lineEdit(), Qt.Key_Down)
    popup = batch.completer().popup()
    print("popup visible:", popup.isVisible(),
          "popup currentIndex row:", popup.currentIndex().row())

    QTest.keyClick(batch.lineEdit(), Qt.Key_Return)
    print("immediately after Return: focus is qty?", app.focusWidget() is qty,
          "| focus:", type(app.focusWidget()).__name__)

    app.processEvents()
    print("after processEvents: focus is qty?", app.focusWidget() is qty)

    fired = []
    QTimer.singleShot(0, lambda: fired.append(1))
    app.processEvents()
    print("zero timer fired:", bool(fired))

    QTimer.singleShot(1, lambda: fired.append(2))
    for _ in range(5):
        app.processEvents()
    print("1ms timer fired:", len(fired) > 1)

case.tearDown()
