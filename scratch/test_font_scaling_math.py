import sys
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from PySide6.QtGui import QFont, QFontMetricsF

MM_TO_PT = 72.0 / 25.4

# At user image scale (701 x 498, scale = 498 / 105 = 4.7428):
scale_u = 498.0 / 105.0
# At 300 DPI (1748 x 1240, scale = 300 / 25.4 = 11.811):
scale_300 = 300.0 / 25.4

for name, pt in [("Store Name", 13.5), ("Subtitle", 9.0), ("Body/Items", 9.5), ("Net Amt", 12.0)]:
    px_u = round(pt * scale_u / MM_TO_PT)
    px_300 = round(pt * scale_300 / MM_TO_PT)
    ratio = px_300 / px_u
    print(f"{name} ({pt} pt): user_px = {px_u}, 300dpi_px = {px_300}, ratio = {ratio:.2f} (expected {1240/498:.2f})")

