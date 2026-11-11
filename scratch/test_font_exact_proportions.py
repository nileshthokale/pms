import sys, os
sys.path.insert(0, os.getcwd())
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from PySide6.QtGui import QFont, QFontMetricsF, QPixmap, QPainter, QColor, QPen
from PySide6.QtCore import QRectF, Qt, QPointF
from PIL import Image
import numpy as np

# Load user target image
im_user = Image.open(r"C:/Users/savan/.gemini/antigravity/brain/47acb2ce-bf28-4452-bd3e-7c17d1743d4f/.user_uploaded/media_1792915620627_5c37c577.png").convert("RGB")
w_u, h_u = im_user.size
print(f"Target image: {w_u} x {h_u}")

# A6 at 300 DPI:
dpi = 300.0
scale = dpi / 25.4 # 11.811 px / mm
w_px = int(round(148.0 * scale)) # 1748 px
h_px = int(round(105.0 * scale)) # 1240 px

# Target font sizes in pixels at 300 DPI:
# Ratio from 300 DPI to target (1240 / 498):
ratio_300 = h_px / float(h_u) # 1240 / 498 = 2.48996

# In the user screenshot (height 498):
# Store Name was drawn with font pt=13.5 on 96 DPI -> 18 px.
# At 300 DPI, that is: 18 * ratio_300 = 44.8 px.
# Body text was drawn with font pt=9.5 on 96 DPI -> 12.67 px.
# At 300 DPI, that is: 12.67 * ratio_300 = 31.5 px.
# Net Amt was drawn with font pt=12.0 on 96 DPI -> 16 px.
# At 300 DPI, that is: 16 * ratio_300 = 39.8 px.
# Address was drawn with font pt=9.0 on 96 DPI -> 12 px.
# At 300 DPI, that is: 12 * ratio_300 = 29.9 px.

print(f"Calculated 300 DPI font pixel sizes:")
print(f"  Store Name: {18 * ratio_300:.1f} px (corresponds to pt {18 * ratio_300 * 72 / 300:.2f} pt at 300 DPI)")
print(f"  Body/Items: {12.67 * ratio_300:.1f} px (corresponds to pt {12.67 * ratio_300 * 72 / 300:.2f} pt at 300 DPI)")
print(f"  Net Amt:    {16 * ratio_300:.1f} px (corresponds to pt {16 * ratio_300 * 72 / 300:.2f} pt at 300 DPI)")
print(f"  Address:    {12 * ratio_300:.1f} px (corresponds to pt {12 * ratio_300 * 72 / 300:.2f} pt at 300 DPI)")

