import sys, os
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from PySide6.QtGui import QFont, QFontMetricsF

MM_TO_PT = 72.0 / 25.4

headings = [
    ("QTY", 8.0),
    ("UNIT", 15.0),
    ("DESCRIPTION", 38.0),
    ("COMP.", 12.0),
    ("BATCH", 28.0),
    ("EXP. DT", 19.0),
    ("AMT", 20.0),
]

sample_items = [
    ("qty", "1", 8.0),
    ("qty_3dig", "100", 8.0),
    ("unit_tab", "TABLET", 15.0),
    ("unit_10s", "10'S", 15.0),
    ("desc", "BIO D3 PLUS", 38.0),
    ("comp", "MCL", 12.0),
    ("batch_normal", "KBC2402A", 28.0),
    ("batch_long", "AC26040089", 28.0),
    ("exp_iso", "31/12/2026", 19.0),
    ("exp_my", "12/26", 19.0),
    ("amt_short", "20.00", 20.0),
    ("amt_long", "12500.00", 20.0),
]

for weight_name, weight_val in [("ExtraBold (800)", 800), ("Bold (700)", 700)]:
    for pt in [9.0, 9.5, 10.0]:
        font = QFont("Arial", -1)
        font.setWeight(QFont.Weight(weight_val))
        font.setPointSizeF(pt)
        fm = QFontMetricsF(font)
        print(f"\n======== {weight_name} PT = {pt} ========")
        print("--- HEADINGS ---")
        for text, w_mm in headings:
            w_needed = fm.horizontalAdvance(text) / MM_TO_PT
            fits = w_needed <= w_mm
            print(f"  {text:12}: needed {w_needed:.2f}mm / {w_mm}mm -> fits={fits}")
        print("--- DATA ---")
        for label, text, w_mm in sample_items:
            w_needed = fm.horizontalAdvance(text) / MM_TO_PT
            fits = w_needed <= w_mm
            print(f"  {label:12} ('{text}'): needed {w_needed:.2f}mm / {w_mm}mm -> fits={fits}")

