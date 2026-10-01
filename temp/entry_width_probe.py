"""Measure the Counter Sale entry-bar geometry at the three target sizes."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication, QMainWindow  # noqa: E402

app = QApplication(sys.argv)

from screens.counter_sale import CounterSalePage  # noqa: E402

window = QMainWindow()
page = CounterSalePage()
window.setCentralWidget(page)
window.setWindowTitle("probe")

for w, h in ((1366, 768), (1600, 900), (1920, 1080)):
    window.resize(w, h)
    window.show()
    app.processEvents()
    bar = page._sale_panel._entry_bar if hasattr(page, "_sale_panel") else None
    if bar is None:
        for attr in ("_panel", "_sale", "_bill_panel", "sale_panel"):
            if hasattr(page, attr):
                print("candidate attr:", attr, type(getattr(page, attr)))
        break
    print(f"\n=== window {w}x{h} ===")
    print(f"entry bar: width={bar.width()} height={bar.height()}")
    print(f"bar layout rows: {bar.layout().count()}")
    total_min = 0
    for name in ("cno_label", "item_combo", "batch_combo", "pack_edit",
                 "location_edit", "expiry_edit", "mrp_edit", "stock_edit",
                 "qty_edit", "discount_edit", "amount_edit", "add_btn"):
        wid = getattr(bar, name)
        print(f"  {name:15s} w={wid.width():4d} min={wid.minimumWidth():4d} "
              f"max={wid.maximumWidth():4d} hint={wid.sizeHint().width():4d}")
        total_min += wid.minimumWidth()
    print(f"  sum of minimums (fields only) = {total_min}")
    parent = bar.parentWidget()
    print(f"  parent {parent.objectName()!r} width={parent.width()}")

window.close()
