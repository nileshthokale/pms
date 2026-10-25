import sys, os
sys.path.insert(0, os.getcwd())
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from PySide6.QtGui import QFont, QFontMetricsF, QPixmap, QPainter, QColor, QPen, QTransform
from PySide6.QtCore import QRectF, Qt, QPointF
from PIL import Image
import numpy as np

import database.duplicate_a6_cash_memo as memo_a6

# Test bill from user screenshot
head = {
    'voucher_no': '2',
    'customer_name': 'NILESH',
    'address': 'GGU',
    'doctor_name': 'DR. K.N. GHORPADE',
    'sale_date': '2026-10-23',
    'sale_type': 'Cash',
    'net_amount': 341.0
}
items = [
    {
        'sales_qty': 1,
        'unit': '15',
        'item_name': 'BIO D3 PLUS',
        'comp': '',
        'batch_no': '14261266A',
        'expiry': '28/02/2029',
        'amount': 341.34
    }
]

# Let's inspect how QPainter font drawing behaves with scale
# If scale = dpi / 25.4 (e.g. 11.811 at 300 DPI):
# In Qt, if painter is drawing on a QPixmap/QImage, device logicalDpi is 96.
# If we set font.setPointSizeF(pt_size * (dpi / 96.0)), then:
# pixel_size = (pt_size * dpi / 96.0) * 96 / 72 = pt_size * dpi / 72.
# This gives the exact physical font size in pixels!

# Let's test this!
print("Testing DPI-scaled font drawing...")

