import sys, os
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from PySide6.QtGui import QFont, QFontMetricsF, QPixmap, QPainter, QColor, QPen
from PySide6.QtCore import QRectF, Qt, QPointF
from PIL import Image
import numpy as np

# Load user uploaded image:
im_user = Image.open(r"C:/Users/savan/.gemini/antigravity/brain/47acb2ce-bf28-4452-bd3e-7c17d1743d4f/.user_uploaded/media_1792915620627_5c37c577.png").convert("RGB")
w_u, h_u = im_user.size
print(f"Target User Image: {w_u} x {h_u}")

# The user image is 701 x 498.
# 148 mm x 105 mm -> 701 / 148 = 4.7365 px/mm (120.3 DPI)
# 498 / 105 = 4.7428 px/mm (120.5 DPI)

# Let's inspect how the user image was rendered in Qt:
# Look at the code in scratch/test_full_super_bold.py!
# In test_full_super_bold.py, scale was 300.0 / 25.4 (~11.811 px/mm).
# Pixmap was 1748 x 1240.
# The fonts used in test_full_super_bold.py:
# shop_name: 11.5 pt (or 13.5 pt)
# address: 7.5 pt (or 9.0 pt)
# etc.

