import sys, os
sys.path.insert(0, os.getcwd())
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from PySide6.QtGui import QFont, QPixmap, QPainter, QColor, QPen
from PySide6.QtCore import QPointF, QRectF, Qt
from PIL import Image
import numpy as np

import database.duplicate_a6_cash_memo as memo_a6

# Test bill matching user's photo
head = {
    'voucher_no': '1',
    'sale_type': 'Cash',
    'sale_date': '2026-10-24',
    'customer_name': 'WALKIN',
    'doctor_name': '',
    'net_amount': 20.0
}
items = [
    {'sales_qty': 1, 'unit': 'TABLET', 'item_name': 'BIO D3 PLUS', 'comp': 'MCL', 'batch_no': 'KBC2402A', 'expiry': '31/12/2026', 'amount': 20.0}
]

scale = 300.0 / 25.4
w_px = int(round(memo_a6.PAGE_WIDTH_MM * scale))
h_px = int(round(memo_a6.PAGE_HEIGHT_MM * scale))

pix = QPixmap(w_px, h_px)
pix.fill(QColor('#ffffff'))
p = QPainter(pix)
p.setRenderHint(QPainter.Antialiasing, True)
p.setRenderHint(QPainter.TextAntialiasing, True)

# Proposed font sizes:
# Shop Name: 13.5 pt
# Shop Address: 9.0 pt
# Meta rows: 9.5 pt
# Headings: 9.5 pt (shrink-to-fit min 8.0)
# Items: 9.5 pt (shrink-to-fit min 6.5)
# Footer Left:
#   Jurisdiction: 9.5 pt
#   Licences: 9.0 pt
#   GSTIN: 9.0 pt
# Footer Right:
#   Net Amt: 12.0 pt
#   Shop Name: 9.5 pt
#   Pharmacist/Sign: 9.5 pt

print("Testing proposed font sizes...")

