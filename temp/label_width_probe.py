"""Measure the exact width budget for a one-row Counter Sale entry bar."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

app = QApplication(sys.argv)

from screens.counter_sale import _BTN_GREEN_SM, _LABEL_DIM, _LABEL_STYLE  # noqa: E402

LABELS = ["CNo", "Item", "Batch", "Pack", "Loc", "Exp", "MRP",
          "Avail", "Qty", "Disc", "Amt"]

label_total = 0
for text in LABELS:
    lbl = QLabel(text)
    lbl.setStyleSheet(_LABEL_DIM)
    w = lbl.sizeHint().width()
    label_total += w
    print(f"  label {text:6s} w={w}")
print(f"label total = {label_total}")

cno = QLabel("--")
cno.setStyleSheet(_LABEL_STYLE)
print(f"cno '--' w={cno.sizeHint().width()}")

btn = QPushButton("+ Add")
btn.setStyleSheet(_BTN_GREEN_SM)
print(f"add button hint w={btn.sizeHint().width()} h={btn.sizeHint().height()}")

f = QFont("Segoe UI", 11)
print(f"QLineEdit/QComboBox typical height at 11pt: "
      f"{QLabel('Ag', font=f).sizeHint().height()}")

for spacing in (2, 3, 4):
    gaps = 22  # 11 labels + 11 fields/buttons ... 12 fields + 11 labels
    print(f"spacing={spacing}: gaps total={gaps * spacing}")
