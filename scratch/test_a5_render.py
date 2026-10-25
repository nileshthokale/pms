import sys, os
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from PySide6.QtGui import QFont, QPixmap, QPainter, QColor, QPen, QFontMetricsF
from PySide6.QtCore import QPointF, QRectF, Qt
from PIL import Image
import numpy as np

# A5 Landscape: 210 x 148 mm
PAGE_WIDTH_MM = 210.0
PAGE_HEIGHT_MM = 148.0

MARGIN_LEFT_MM = 12.0
MARGIN_RIGHT_MM = 12.0
MARGIN_TOP_MM = 10.0
MARGIN_BOTTOM_MM = 10.0

CONTENT_WIDTH_MM = PAGE_WIDTH_MM - MARGIN_LEFT_MM - MARGIN_RIGHT_MM # 186.0 mm
CONTENT_HEIGHT_MM = PAGE_HEIGHT_MM - MARGIN_TOP_MM - MARGIN_BOTTOM_MM # 128.0 mm

# Column definitions (Total = 186.0 mm)
# QTY, UNIT, COMP. left-aligned; AMT right-aligned;
COLUMN_DEFS = [
    ("qty", "QTY", 14.0, "left"),
    ("unit", "UNIT", 20.0, "left"),
    ("description", "DESCRIPTION", 50.0, "left"),
    ("comp", "COMP.", 16.0, "left"),
    ("batch", "BATCH", 32.0, "left"),
    ("expiry", "EXP. DT", 26.0, "left"),
    ("amount", "AMT", 28.0, "right"),
]

# Test bill matching Image 1 exactly:
# Name: MR RAMDAS BAIRGI, SHIVAJINAGAR RAHURI
# Doctor: DR. K.N. GHORPADE
# Cash Memo: 2047, Date: 23/10/2026
# Items:
# 15 TABLET UC-ROSE        QUA  JTF-2573  30/04/2027 567.27
# 15 TABLET DOLOXICAM      TRO  D125H129  31/03/2029 245.60
# 15 CAPSULE PROTONIX DSR  FOH  C-26056   30/06/2028 180.00
# Net Amt: 993
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

store = {
    "name": "SHREE SAMARTH MEDICAL AND GEN STORE",
    "address": "GHORPADE HOSPITAL, RAHURI",
    "jurisdiction": "AHMEDNAGAR",
    "licence": "20-MH-AHM-61069,21-MH-AHM-61070,20C-MH-AHM-610",
    "gstin": "",
}

scale = 300.0 / 25.4 # 300 DPI
w_px = int(round(PAGE_WIDTH_MM * scale))
h_px = int(round(PAGE_HEIGHT_MM * scale))

pix = QPixmap(w_px, h_px)
pix.fill(QColor("#ffffff"))
p = QPainter(pix)
p.setRenderHint(QPainter.Antialiasing, True)
p.setRenderHint(QPainter.TextAntialiasing, True)

def rx(mm): return mm * scale
def ry(mm): return mm * scale
def rw(mm): return mm * scale
def rh(mm): return mm * scale

def draw_bold(painter, x, y, w, h, text, pt_size, align="left", weight=900):
    clean = str(text or "").strip()
    if not clean: return
    font = QFont("Arial", -1)
    font.setPointSizeF(pt_size)
    font.setWeight(QFont.Weight(weight))
    painter.setFont(font)
    painter.setPen(QColor("#000000"))
    qt_align = Qt.AlignVCenter
    if align == "right": qt_align |= Qt.AlignRight
    elif align == "center": qt_align |= Qt.AlignHCenter
    else: qt_align |= Qt.AlignLeft
    r = QRectF(x, y, w, h)
    painter.drawText(r, qt_align, clean)
    # Toner overdraw
    painter.drawText(r.translated(1.0, 0.0), qt_align, clean)
    painter.drawText(r.translated(0.0, 0.5), qt_align, clean)

def shrink_bold(painter, x, y, w, h, text, max_pt=10.5, min_pt=7.5, align="left", weight=900):
    clean = str(text or "").strip()
    if not clean: return
    font = QFont("Arial", -1)
    font.setWeight(QFont.Weight(weight))
    pt = max_pt
    while pt > min_pt:
        font.setPointSizeF(pt)
        fm = QFontMetricsF(font)
        if fm.horizontalAdvance(clean) <= w:
            break
        pt -= 0.5
    if pt < min_pt: pt = min_pt
    draw_bold(painter, x, y, w, h, clean, pt, align, weight)

def cut_bold(painter, x, y, w, h, text, pt_size=10.5, align="left", weight=900):
    clean = str(text or "").strip()
    if not clean: return
    font = QFont("Arial", -1)
    font.setPointSizeF(pt_size)
    font.setWeight(QFont.Weight(weight))
    fm = QFontMetricsF(font)
    if fm.horizontalAdvance(clean) > w:
        cut_len = len(clean)
        while cut_len > 0 and fm.horizontalAdvance(clean[:cut_len]) > w:
            cut_len -= 1
        clean = clean[:cut_len]
    draw_bold(painter, x, y, w, h, clean, pt_size, align, weight)

x0 = rx(MARGIN_LEFT_MM)
x1 = rx(MARGIN_LEFT_MM + CONTENT_WIDTH_MM)
w_content = rw(CONTENT_WIDTH_MM)

pen_rule = QPen(QColor("#000000"), max(2.5, rw(0.35)), Qt.SolidLine, Qt.SquareCap)
p.setPen(pen_rule)

# 1. Header (Centered, Store name 15 pt bold, Subtitle 8.5 pt)
draw_bold(p, x0, ry(10.0), w_content, rh(6.0), store["name"], 15.0, "center")
draw_bold(p, x0, ry(16.5), w_content, rh(4.2), store["address"], 8.5, "center")

# 2. Meta Lines (10.5 pt)
left_w = rw(CONTENT_WIDTH_MM * 0.60)
right_w = rw(CONTENT_WIDTH_MM * 0.40)
right_x = x0 + left_w

name_str = f"Name : {head['customer_name']}" + (f", {head['address']}" if head.get('address') else "")
memo_str = f"Cash Memo : {head['voucher_no']}"
doc_str = f"Doctor : {head['doctor_name']}"
dt_str = f"Date : {head['sale_date']}"

cut_bold(p, x0, ry(22.0), left_w, rh(5.0), name_str, 10.5, "left")
cut_bold(p, right_x, ry(22.0), right_w, rh(5.0), memo_str, 10.5, "right")

cut_bold(p, x0, ry(28.0), left_w, rh(5.0), doc_str, 10.5, "left")
cut_bold(p, right_x, ry(28.0), right_w, rh(5.0), dt_str, 10.5, "right")

# Rule 1
p.drawLine(QPointF(x0, ry(36.0)), QPointF(x1, ry(36.0)))

# Column Headings (10.5 pt)
col_x_mm = MARGIN_LEFT_MM
for key, title, width_mm, align in COLUMN_DEFS:
    cx = rx(col_x_mm)
    cw = rw(width_mm)
    pad = rw(0.8) if align == "left" else 0.0
    r_pad = rw(0.8) if align == "right" else 0.0
    shrink_bold(p, cx + pad, ry(36.8), cw - pad - r_pad, rh(5.0), title, max_pt=10.5, min_pt=8.5, align=align)
    col_x_mm += width_mm

# Rule 2
p.drawLine(QPointF(x0, ry(42.5)), QPointF(x1, ry(42.5)))

# Item Rows (10.5 pt, 10 fixed rows x 5.0 mm = 50.0 mm)
item_start_y = 44.0
row_height = 5.0
padded_items = list(items) + [{}] * (10 - len(items))

for r_idx in range(10):
    curr_y = item_start_y + r_idx * row_height
    itm = padded_items[r_idx]
    if itm and itm.get("item_name"):
        row_map = {
            "qty": str(itm["sales_qty"]),
            "unit": itm["unit"],
            "description": itm["item_name"],
            "comp": itm["comp"],
            "batch": itm["batch_no"],
            "expiry": itm["expiry"],
            "amount": f"{itm['amount']:.2f}",
        }
        col_x_mm = MARGIN_LEFT_MM
        for key, title, width_mm, align in COLUMN_DEFS:
            val = row_map.get(key, "")
            cx = rx(col_x_mm)
            cw = rw(width_mm)
            pad = rw(0.8) if align == "left" else 0.0
            r_pad = rw(0.8) if align == "right" else 0.0
            if key == "batch":
                shrink_bold(p, cx + pad, ry(curr_y), cw - pad - r_pad, rh(row_height), val, max_pt=10.5, min_pt=7.5, align=align)
            elif key == "description":
                cut_bold(p, cx + pad, ry(curr_y), cw - pad - r_pad, rh(row_height), val, pt_size=10.5, align=align)
            else:
                shrink_bold(p, cx + pad, ry(curr_y), cw - pad - r_pad, rh(row_height), val, max_pt=10.5, min_pt=8.0, align=align)
            col_x_mm += width_mm

# Rule 3
item_end_y = item_start_y + 10 * row_height # 94.0 mm
p.drawLine(QPointF(x0, ry(item_end_y)), QPointF(x1, ry(item_end_y)))

# Net Amt on the right, below the table (12 pt bold)
net_str = f"Net Amt : {int(round(head['net_amount']))}"
draw_bold(p, right_x, ry(item_end_y + 2.0), right_w, rh(6.0), net_str, 12.0, "right")

# Footer (9.5 pt)
foot_left_w = rw(CONTENT_WIDTH_MM * 0.65)
foot_right_w = rw(CONTENT_WIDTH_MM * 0.35)
foot_right_x = x0 + foot_left_w

jur_line = f"E & O E. Subject to {store['jurisdiction']} Jurisdiction"
shrink_bold(p, x0, ry(105.0), foot_left_w, rh(4.5), jur_line, max_pt=9.5, min_pt=8.5, align="left")

lic_raw = store["licence"]
lic_line1 = lic_raw[:34]
lic_line2 = lic_raw[34:].strip(",")
draw_bold(p, x0, ry(110.0), foot_left_w, rh(4.5), lic_line1, 9.5, "left")
if lic_line2:
    draw_bold(p, x0, ry(115.0), foot_left_w, rh(4.5), lic_line2, 9.5, "left")

if store.get("gstin"):
    draw_bold(p, x0, ry(120.0), foot_left_w, rh(4.5), f"GSTIN: {store['gstin']}", 9.5, "left")
else:
    draw_bold(p, x0, ry(120.0), foot_left_w, rh(4.5), "GSTIN:", 9.5, "left")

# Right Footer
draw_bold(p, foot_right_x, ry(110.0), foot_right_w, rh(4.5), store["name"], 9.5, "right")
draw_bold(p, foot_right_x, ry(120.0), foot_right_w, rh(4.5), "Pharmacist/Sign", 9.5, "right")

# Proof tag
draw_bold(p, x0, ry(127.0), w_content, rh(3.0), "RPT v2", 6.0, "right", weight=500)

p.end()

pix.save("scratch/test_a5_bill_render.png")
print("Rendered scratch/test_a5_bill_render.png successfully! Size:", pix.width(), "x", pix.height())

