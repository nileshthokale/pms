import sys, os
sys.path.insert(0, os.getcwd())
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from PySide6.QtGui import QFont, QPixmap, QPainter, QColor, QPen, QFontMetricsF
from PySide6.QtCore import QPointF, QRectF, Qt
from PIL import Image
import numpy as np

import database.duplicate_a6_cash_memo as memo_a6

# Let's test with a 4-item bill
head = {
    'voucher_no': '2043',
    'sale_type': 'Cash',
    'sale_date': '2026-10-24',
    'customer_name': 'RAHUL PATIL',
    'doctor_name': 'DR. K.N. GHORPADE',
    'address': 'RAHURI',
    'net_amount': 890.0
}
items = [
    {'sales_qty': 1, 'unit': '10\'S', 'item_name': 'MGMIX', 'comp': 'MED', 'batch_no': 'LGP12/028', 'expiry': '04/26', 'amount': 210.0},
    {'sales_qty': 2, 'unit': '10\'S', 'item_name': 'PROTONIX DSR', 'comp': 'ALK', 'batch_no': 'AC26040089', 'expiry': '08/27', 'amount': 340.0},
    {'sales_qty': 1, 'unit': '10\'S', 'item_name': 'BONULTRA', 'comp': 'ZUV', 'batch_no': 'BN8819', 'expiry': '12/26', 'amount': 190.0},
    {'sales_qty': 1, 'unit': '10\'S', 'item_name': 'ARTHRASPAZ 4MG', 'comp': 'INT', 'batch_no': 'AS401', 'expiry': '03/27', 'amount': 150.0},
]

store = memo_a6.get_store_identity()

scale = 300.0 / 25.4
w_px = int(round(memo_a6.PAGE_WIDTH_MM * scale))
h_px = int(round(memo_a6.PAGE_HEIGHT_MM * scale))

pix = QPixmap(w_px, h_px)
pix.fill(QColor('#ffffff'))
p = QPainter(pix)
p.setRenderHint(QPainter.Antialiasing, True)
p.setRenderHint(QPainter.TextAntialiasing, True)

def rx(mm): return (mm + memo_a6.OFFSET_X_MM) * scale
def ry(mm): return (mm + memo_a6.OFFSET_Y_MM) * scale
def rw(mm): return mm * scale
def rh(mm): return mm * scale

x0 = rx(memo_a6.MARGIN_LEFT_MM)
x1 = rx(memo_a6.MARGIN_LEFT_MM + memo_a6.CONTENT_WIDTH_MM)
w_content = rw(memo_a6.CONTENT_WIDTH_MM)

pen_rule = QPen(QColor("#000000"), max(2.5, rw(0.35)), Qt.SolidLine, Qt.SquareCap)
p.setPen(pen_rule)

# 1. Shop Name: 13.5 pt
memo_a6._draw_bold_text(p, x0, ry(5.0), w_content, rh(5.0), store["name"], 13.5, "center")

# 2. Shop Address: 9.0 pt
memo_a6._draw_bold_text(p, x0, ry(10.2), w_content, rh(3.8), store["address"], 9.0, "center")

# 3. Meta Rows: 9.5 pt
left_w = rw(memo_a6.CONTENT_WIDTH_MM * 0.58)
right_w = rw(memo_a6.CONTENT_WIDTH_MM * 0.42)
right_x = x0 + left_w

name_str = f"Name : {head['customer_name']}, {head['address']}"
memo_str = f"Cash Memo : {head['voucher_no']}"
doc_str = f"Doctor : {head['doctor_name']}"
dt_str = "Date : 24/10/2026"

memo_a6._draw_cut_to_fit_bold(p, x0, ry(14.3), left_w, rh(4.0), name_str, 9.5, "left")
memo_a6._draw_cut_to_fit_bold(p, right_x, ry(14.3), right_w, rh(4.0), memo_str, 9.5, "right")

memo_a6._draw_cut_to_fit_bold(p, x0, ry(18.5), left_w, rh(4.0), doc_str, 9.5, "left")
memo_a6._draw_cut_to_fit_bold(p, right_x, ry(18.5), right_w, rh(4.0), dt_str, 9.5, "right")

# Rule 1
p.setPen(pen_rule)
p.drawLine(QPointF(x0, ry(24.5)), QPointF(x1, ry(24.5)))

# Headings: 9.5 pt (shrink-to-fit min 8.0)
col_x_mm = memo_a6.MARGIN_LEFT_MM
for key, title, width_mm, align in memo_a6.COLUMN_DEFS:
    cx = rx(col_x_mm)
    cw = rw(width_mm)
    pad = rw(0.6) if align == "left" else 0.0
    r_pad = rw(0.6) if align == "right" else 0.0
    memo_a6._draw_shrink_to_fit_bold(
        p, cx + pad, ry(24.9), cw - pad - r_pad, rh(3.8), title, max_pt=9.5, min_pt=8.0, align=align
    )
    col_x_mm += width_mm

# Rule 2
p.drawLine(QPointF(x0, ry(29.0)), QPointF(x1, ry(29.0)))

# Items: 9.5 pt
for r_idx, itm in enumerate(items):
    curr_y_mm = memo_a6.ITEM_START_Y_MM + r_idx * memo_a6.ROW_HEIGHT_MM
    col_x_mm = memo_a6.MARGIN_LEFT_MM
    row_map = {
        "qty": str(int(itm["sales_qty"])),
        "unit": itm["unit"],
        "description": itm["item_name"],
        "comp": itm["comp"],
        "batch": itm["batch_no"],
        "expiry": itm["expiry"],
        "amount": f"{itm['amount']:.2f}",
    }
    for key, title, width_mm, align in memo_a6.COLUMN_DEFS:
        val = row_map.get(key, "")
        cx = rx(col_x_mm)
        cw = rw(width_mm)
        pad = rw(0.6) if align == "left" else 0.0
        r_pad = rw(0.6) if align == "right" else 0.0
        if key == "batch":
            memo_a6._draw_shrink_to_fit_bold(p, cx + pad, ry(curr_y_mm), cw - pad - r_pad, rh(memo_a6.ROW_HEIGHT_MM), val, max_pt=9.5, min_pt=6.5, align=align)
        elif key == "description":
            memo_a6._draw_cut_to_fit_bold(p, cx + pad, ry(curr_y_mm), cw - pad - r_pad, rh(memo_a6.ROW_HEIGHT_MM), val, pt_size=9.5, align=align)
        else:
            memo_a6._draw_shrink_to_fit_bold(p, cx + pad, ry(curr_y_mm), cw - pad - r_pad, rh(memo_a6.ROW_HEIGHT_MM), val, max_pt=9.5, min_pt=7.5, align=align)
        col_x_mm += width_mm

# Rule 3
p.drawLine(QPointF(x0, ry(memo_a6.ITEM_END_Y_MM)), QPointF(x1, ry(memo_a6.ITEM_END_Y_MM)))

# Footer
jur_line = f"E & O E. Subject to {store['jurisdiction']} Jurisdiction"
lic_line1 = store['licence'][:34]
lic_line2 = store['licence'][34:].strip(",")
foot_left_w = rw(memo_a6.CONTENT_WIDTH_MM * 0.65)
foot_right_w = rw(memo_a6.CONTENT_WIDTH_MM * 0.35)
foot_right_x = x0 + rw(memo_a6.CONTENT_WIDTH_MM * 0.65)

memo_a6._draw_shrink_to_fit_bold(p, x0, ry(75.5), foot_left_w, rh(4.2), jur_line, max_pt=9.5, min_pt=8.0, align="left")
memo_a6._draw_bold_text(p, x0, ry(80.0), foot_left_w, rh(4.0), lic_line1, 9.0, "left")
if lic_line2:
    memo_a6._draw_bold_text(p, x0, ry(84.5), foot_left_w, rh(4.0), lic_line2, 9.0, "left")
if store.get("gstin"):
    memo_a6._draw_bold_text(p, x0, ry(89.0), foot_left_w, rh(4.0), f"GSTIN: {store['gstin']}", 9.0, "left")

net_str = f"Net Amt : {int(round(head['net_amount']))}"
memo_a6._draw_bold_text(p, foot_right_x, ry(75.0), foot_right_w, rh(5.5), net_str, 12.0, "right")
memo_a6._draw_bold_text(p, foot_right_x, ry(83.5), foot_right_w, rh(4.2), store["name"], 9.5, "right")
memo_a6._draw_bold_text(p, foot_right_x, ry(92.5), foot_right_w, rh(4.2), "Pharmacist/Sign", 9.5, "right")

p.end()

pix.save("scratch/test_larger_fonts.png")
print("Saved scratch/test_larger_fonts.png")

