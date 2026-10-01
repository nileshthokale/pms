"""Exact rendered text widths for the one-row entry bar budget."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtGui import QFont, QFontMetrics  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

field_font = QFont("Segoe UI", 11)          # what _make_edit applies
fm = QFontMetrics(field_font)
print("--- field text (Segoe UI 11pt) + 8px padding ---")
for text in ("2029-02-28", "14261266A", "Shelf A", "10x10", "341.34",
             "477.88", "21.0", "0.00", "1", "2026-2027-Cash-0008",
             "BIO D3 PLUS TAB"):
    w = fm.horizontalAdvance(text)
    print(f"  {text:22s} -> {w:4d}px  (+8 pad = {w + 8})")

label_font = QFont()
label_font.setPixelSize(10)
lm = QFontMetrics(label_font)
print("--- labels (pixel size 10) ---")
labels = ["CNo", "Item", "Batch", "Pack", "Loc", "Exp", "MRP",
          "Avail", "Qty", "Disc", "Amt"]
total = 0
for text in labels:
    w = lm.horizontalAdvance(text)
    total += w
    print(f"  {text:6s} -> {w:3d}px")
print(f"label total with pixel-size font = {total}")

label_font_11 = QFont()
label_font_11.setPixelSize(11)
lm11 = QFontMetrics(label_font_11)
print(f"CNo label at 11px = {lm11.horizontalAdvance('CNo')}px")
