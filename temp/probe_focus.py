"""Offscreen probe: where does focus land after Item and Batch selection?"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def log(msg):
    print(msg, flush=True)


from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from screens.counter_sale import CounterSalePage  # noqa: E402

page = CounterSalePage()
page.resize(1366, 768)
page.show()
app.processEvents()

entry = page._sale_panel._entry_bar
item_line = entry.item_combo.lineEdit()
batch_line = entry.batch_combo.lineEdit()

log(f"items loaded: {entry.item_combo.count()}")

# Emulate: click item field, type, Down, Enter
item_line.setFocus()
item_line.clear()
QTest.mouseClick(item_line, Qt.LeftButton)
app.processEvents()
QTest.keyClicks(item_line, "BIO")
app.processEvents()
QTest.keyClick(item_line, Qt.Key_Down)
app.processEvents()
QTest.keyClick(item_line, Qt.Key_Return)
app.processEvents()
time.sleep(0.1)
app.processEvents()

fw = page.focusWidget()
log(f"after item Enter: focusWidget={type(fw).__name__} "
    f"is_batch_combo={fw is entry.batch_combo} "
    f"is_batch_line={fw is batch_line} batch_line.hasFocus={batch_line.hasFocus()}")

# Type into whatever widget currently holds focus; does it reach the batch field?
before = batch_line.text()
QTest.keyClicks(fw if fw is not None else batch_line, "ZZZ")
app.processEvents()
log(f"typed into focus widget -> batch line text: {before!r} -> {batch_line.text()!r}")
batch_line.clear()

# Now select the batch with Down/Enter
target = fw if fw is not None else batch_line
QTest.keyClick(target, Qt.Key_Down)
app.processEvents()
QTest.keyClick(target, Qt.Key_Return)
app.processEvents()
time.sleep(0.1)
app.processEvents()

fw2 = page.focusWidget()
log(f"after batch Enter: focusWidget={type(fw2).__name__} "
    f"is_qty={fw2 is entry.qty_edit} qty.hasFocus={entry.qty_edit.hasFocus()}")
log(f"batch count={entry.batch_combo.count()} currentData={entry.batch_combo.currentData()}")

# Tab chain
QTest.keyClick(entry.qty_edit, Qt.Key_Tab)
app.processEvents()
log(f"Tab from qty -> focusWidget={type(page.focusWidget()).__name__} "
    f"is_discount={page.focusWidget() is entry.discount_edit}")

# Does Enter in discount trigger Add?
entry.qty_edit.setText("1")
QTest.keyClick(entry.discount_edit, Qt.Key_Return)
app.processEvents()
log(f"rows after Enter-in-discount: {page._sale_panel._table.rowCount()}")
log(f"dialogs-free add: {page._sale_panel._table.rowCount() == 1}")
