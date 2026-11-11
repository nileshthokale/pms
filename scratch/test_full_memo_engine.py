import sys, os
sys.path.insert(0, os.getcwd())
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from PySide6.QtGui import QFont, QPixmap, QPainter, QColor, QPen, QFontMetricsF
from PySide6.QtCore import QPointF, QRectF, Qt

import database.duplicate_a6_cash_memo as memo_a6

# Test A5 rendering
head = {
    "voucher_no": "2047",
    "sale_type": "Cash",
    "sale_date": "2026-10-23",
    "customer_name": "MR RAMDAS BAIRGI",
    "doctor_name": "DR. K.N. GHORPADE",
    "address": "SHIVAJINAGAR RAHURI",
    "net_amount": 993.0
}
items = [
    {"sales_qty": 15, "unit": "TABLET", "item_name": "UC-ROSE", "comp": "QUA", "batch_no": "JTF-2573", "expiry": "30/04/2027", "amount": 567.27},
    {"sales_qty": 15, "unit": "TABLET", "item_name": "DOLOXICAM", "comp": "TRO", "batch_no": "D125H129", "expiry": "31/03/2029", "amount": 245.60},
    {"sales_qty": 15, "unit": "CAPSULE", "item_name": "PROTONIX DSR", "comp": "FOH", "batch_no": "C-26056", "expiry": "30/06/2028", "amount": 180.00},
]

pages = memo_a6.paginate_duplicate_items(head, items, show_duplicate=False)
print("Paginated pages:", len(pages))

