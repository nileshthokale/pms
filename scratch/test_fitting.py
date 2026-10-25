from PySide6.QtWidgets import QApplication
import sys
app = QApplication.instance() or QApplication(sys.argv)
from PySide6.QtGui import QFont, QFontMetricsF

MM_TO_PT = 72.0 / 25.4

for weight in [QFont.Weight.Bold, QFont.Weight.ExtraBold]:
    font = QFont('Arial', -1)
    font.setWeight(weight)
    font.setPointSizeF(8.0)
    fm = QFontMetricsF(font)
    print(f'=== Testing Arial weight={weight.value} ===')
    tests = [
        ('QTY', '100', 8.0),
        ('UNIT', 'TABLET', 15.0),
        ('DESCRIPTION', 'BIO D3 PLUS', 38.0),
        ('COMP.', 'MCL', 12.0),
        ('BATCH', 'KBC2402A', 28.0),
        ('BATCH LONG', 'AC26040089', 28.0),
        ('EXP. DT', '31/12/2026', 19.0),
        ('AMT', '1500.00', 20.0),
        ('JURISDICTION', 'E & O E. Subject to AHMEDNAGAR Jurisdiction', 81.2),
        ('NET AMT', 'Net Amt : 25000', 58.8),
    ]
    for label, text, w_mm in tests:
        w_needed_pt = fm.horizontalAdvance(text)
        w_needed_mm = w_needed_pt / MM_TO_PT
        fits = w_needed_mm <= w_mm
        print(f'{label:15}: text="{text}" needs {w_needed_mm:.2f} mm / {w_mm} mm -> Fits: {fits}')

