"""Real rendered width of every Counter Sale entry-bar widget (polished)."""
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
window.resize(1366, 768)
window.show()
app.processEvents()

bar = page._sale_panel._entry_bar
print(f"bar width={bar.width()} height={bar.height()} "
      f"layout={type(bar.layout()).__name__} "
      f"spacing={bar.layout().spacing()} "
      f"margins={bar.layout().contentsMargins().left()}/"
      f"{bar.layout().contentsMargins().right()}")

total = 0
print("--- labels (rendered) ---")
for lbl in bar.findChildren(type(bar.cno_label)):
    if lbl is bar.cno_label:
        continue
    print(f"  {lbl.text():6s} w={lbl.width():3d} h={lbl.height():2d}")
    total += lbl.width()
print(f"label rendered total = {total}")

print("--- controls (rendered) ---")
ct = 0
for name in ("cno_label", "item_combo", "batch_combo", "pack_edit",
             "location_edit", "expiry_edit", "mrp_edit", "stock_edit",
             "qty_edit", "discount_edit", "amount_edit", "add_btn"):
    w = getattr(bar, name)
    print(f"  {name:15s} x={w.x():4d} w={w.width():4d} h={w.height():2d} "
          f"min={w.minimumWidth():3d} max={w.maximumWidth():6d}")
    ct += w.width()
print(f"control rendered total = {ct}")
print(f"grand total (labels+controls) = {total + ct}")

window.close()
