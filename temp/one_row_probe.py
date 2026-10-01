"""Geometry check for the one-row Counter Sale entry bar."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMainWindow  # noqa: E402

app = QApplication(sys.argv)
from screens.counter_sale import CounterSalePage  # noqa: E402

ORDER = ["cno_label", "item_combo", "batch_combo", "pack_edit",
         "location_edit", "expiry_edit", "mrp_edit", "stock_edit",
         "qty_edit", "discount_edit", "amount_edit", "add_btn"]

window = QMainWindow()
page = CounterSalePage()
window.setCentralWidget(page)
window.show()

for w, h in ((1366, 768), (1600, 900), (1920, 1080)):
    window.resize(w, h)
    app.processEvents()
    page._apply_history_height()
    app.processEvents()

    bar = page._sale_panel._entry_bar
    lay = bar.layout()
    print(f"\n=== {w}x{h} ===")
    print(f"bar {bar.width()}x{bar.height()}  layout="
          f"{type(lay).__name__} direction={lay.direction()} "
          f"items={lay.count()} spacing={lay.spacing()}")

    # 1. one row: every child on the same vertical centre line
    centres = {n: getattr(bar, n).mapTo(bar, getattr(bar, n).rect().center()).y()
               for n in ORDER}
    spread = max(centres.values()) - min(centres.values())
    print(f"vertical centre spread = {spread}px  "
          f"({'ONE ROW' if spread <= 4 else 'MULTIPLE ROWS!'})")

    # 2. horizontal order + fit + no overlap
    xs = [(n, getattr(bar, n).x(), getattr(bar, n).width()) for n in ORDER]
    ok_order = [n for n, _, _ in xs]
    print("order ok:", ok_order == ORDER)
    overlaps = []
    for i in range(len(xs) - 1):
        end = xs[i][1] + xs[i][2]
        if end > xs[i + 1][1] + 1:
            overlaps.append((xs[i][0], xs[i + 1][0], end - xs[i + 1][1]))
    right_edge = xs[-1][1] + xs[-1][2]
    print(f"right edge={right_edge} bar width={bar.width()} "
          f"slack={bar.width() - right_edge}")
    print("overlaps:", overlaps or "none")

    below_min = [(n, getattr(bar, n).width(), getattr(bar, n).minimumWidth())
                 for n, _, _ in xs
                 if getattr(bar, n).width() + 1 < getattr(bar, n).minimumWidth()]
    print("below minimum:", below_min or "none")

    min_needed = lay.minimumSize().width()
    usable = bar.width() - lay.contentsMargins().left() - lay.contentsMargins().right()
    verdict = "FITS" if min_needed <= usable else "OVERFLOW"
    print(f"layout.minimumSize().width()={min_needed} "
          f"vs available={usable} -> {verdict}")

    # 3. per-field widths
    print("  " + " | ".join(
        f"{n.split('_')[0]}:{getattr(bar, n).width()}" for n in ORDER))
    print(f"  item is widest: "
          f"{bar.item_combo.width() == max(getattr(bar, n).width() for n in ORDER)}")

    # 4. vertical fit inside the fixed-height bar
    tall = [(n, getattr(bar, n).height()) for n in ORDER
            if getattr(bar, n).height() > bar.height()
            - lay.contentsMargins().top() - lay.contentsMargins().bottom() + 1]
    print("  vertically clipped:", tall or "none")

window.close()
