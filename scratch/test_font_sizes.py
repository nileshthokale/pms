from PySide6.QtWidgets import QApplication
import sys
app = QApplication.instance() or QApplication(sys.argv)
from PySide6.QtGui import QFont, QFontMetricsF

MM_TO_PT = 72.0 / 25.4

for weight_val, wname in [(800, 'ExtraBold'), (750, '750'), (700, 'Bold')]:
    print(f'=== Testing {wname} ===')
    for pt in [8.0, 7.5, 7.0]:
        font = QFont('Arial', -1)
        font.setWeight(QFont.Weight(weight_val))
        font.setPointSizeF(pt)
        fm = QFontMetricsF(font)
        w_tablet = fm.horizontalAdvance("TABLET") / MM_TO_PT
        w_exp = fm.horizontalAdvance("31/12/2026") / MM_TO_PT
        w_exp_my = fm.horizontalAdvance("12/2026") / MM_TO_PT
        w_batch = fm.horizontalAdvance("KBC2402A") / MM_TO_PT
        print(f'  pt={pt:.1f}: TABLET={w_tablet:.2f}mm (<=15: {w_tablet<=15}), 31/12/2026={w_exp:.2f}mm (<=19: {w_exp<=19}), 12/2026={w_exp_my:.2f}mm, BATCH={w_batch:.2f}mm')

