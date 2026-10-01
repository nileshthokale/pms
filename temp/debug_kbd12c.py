"""Focus identity through the TYPE -> Down -> Enter -> batch path."""
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
app.focusChanged.connect(
    lambda old, new: print("     focusChanged ->",
                           type(new).__name__ if new else None))

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
        lambda: print("     batch completionAccepted emitted"))
    batch.currentIndexChanged.connect(
        lambda i: print("     batch currentIndexChanged ->", i))
    item.completionAccepted.connect(
        lambda: print("     item completionAccepted emitted"))

    def who(tag):
        f = app.focusWidget()
        name = type(f).__name__
        tag_ids = []
        if f is item:
            tag_ids.append("ITEM")
        if f is item.lineEdit():
            tag_ids.append("ITEM.lineEdit")
        if f is batch:
            tag_ids.append("BATCH")
        if f is batch.lineEdit():
            tag_ids.append("BATCH.lineEdit")
        if f is qty:
            tag_ids.append("QTY")
        print(f"{tag:32s} focus={name} {'/'.join(tag_ids) or '?'}")

    item.setFocus()
    app.processEvents()
    QTest.keyClicks(item.lineEdit(), "Test")
    who("typed")
    QTest.keyClick(item.lineEdit(), Qt.Key_Down)
    who("item Down")
    QTest.keyClick(item.lineEdit(), Qt.Key_Return)
    who("item Enter (raw)")
    app.processEvents()
    who("item Enter + processEvents")

    QTest.keyClick(batch.lineEdit(), Qt.Key_Down)
    who("batch Down")
    QTest.keyClick(batch.lineEdit(), Qt.Key_Return)
    who("batch Enter (raw)")
    app.processEvents()
    who("batch Enter + processEvents")
    app.processEvents()
    who("second processEvents")

case.tearDown()
