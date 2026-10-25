import sys
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from PySide6.QtGui import QFont, QFontMetricsF

dpi = 300.0
scale = dpi / 25.4

col_widths_mm = {
    "QTY": 8.0,
    "UNIT": 15.0,
    "DESCRIPTION": 38.0,
    "COMP.": 12.0,
    "BATCH": 28.0,
    "EXP. DT": 19.0,
    "AMT": 20.0
}

samples = {
    "QTY": ["QTY", "1", "15", "100"],
    "UNIT": ["UNIT", "15", "TABLET", "10'S"],
    "DESCRIPTION": ["DESCRIPTION", "BIO D3 PLUS", "AMOXICILLIN 500MG"],
    "COMP.": ["COMP.", "MCL", "ALKEM"],
    "BATCH": ["BATCH", "14261266A", "KBC2402A", "AC26040089"],
    "EXP. DT": ["EXP. DT", "28/02/2029", "31/12/2026", "12/26"],
    "AMT": ["AMT", "341.34", "20.00", "1250.00"]
}

for pt in [9.5, 9.0, 8.5]:
    font = QFont("Arial", -1)
    font.setPixelSize(int(round(pt * (dpi / 72.0))))
    font.setWeight(QFont.Weight.Black)
    fm = QFontMetricsF(font)
    print("=== Testing pt =", pt, "(px =", font.pixelSize(), ") ===")
    for col, width_mm in col_widths_mm.items():
        w_px = width_mm * scale
        for text in samples[col]:
            adv = fm.horizontalAdvance(text)
            if adv > w_px:
                print("  OVERFLOW in", col, "(", width_mm, "mm =", round(w_px, 1), "px): '", text, "' needs", round(adv, 1), "px")

