import sys, os
sys.path.insert(0, os.getcwd())
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from PySide6.QtGui import QFont, QPixmap, QPainter, QColor, QPen
from PySide6.QtCore import QPointF, QRectF, Qt
from PIL import Image
import numpy as np

import database.duplicate_a6_cash_memo as memo_a6

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

def bold_text(painter, x, y, w, h, text, pt_size, align='left', weight=900, overdraw_px=1.0):
    clean = str(text or '').strip()
    if not clean: return
    font = QFont('Arial', -1)
    font.setPointSizeF(pt_size)
    font.setWeight(QFont.Weight(weight))
    painter.setFont(font)
    painter.setPen(QColor('#000000'))
    
    qt_align = Qt.AlignVCenter
    if align == 'right': qt_align |= Qt.AlignRight
    elif align == 'center': qt_align |= Qt.AlignHCenter
    else: qt_align |= Qt.AlignLeft
    
    r = QRectF(x, y, w, h)
    painter.drawText(r, qt_align, clean)
    if overdraw_px > 0:
        painter.drawText(r.translated(overdraw_px, 0.0), qt_align, clean)
        painter.drawText(r.translated(0.0, overdraw_px * 0.5), qt_align, clean)

def shrink_bold(painter, x, y, w, h, text, max_pt=8.5, min_pt=6.0, align='left', weight=900, overdraw_px=1.0):
    clean = str(text or '').strip()
    if not clean: return
    font = QFont('Arial', -1)
    font.setWeight(QFont.Weight(weight))
    pt = max_pt
    while pt > min_pt:
        font.setPointSizeF(pt)
        from PySide6.QtGui import QFontMetricsF
        fm = QFontMetricsF(font)
        if fm.horizontalAdvance(clean) <= w:
            break
        pt -= 0.5
    if pt < min_pt: pt = min_pt
    bold_text(painter, x, y, w, h, clean, pt, align, weight, overdraw_px)

def cut_bold(painter, x, y, w, h, text, pt_size=8.5, align='left', weight=900, overdraw_px=1.0):
    clean = str(text or '').strip()
    if not clean: return
    font = QFont('Arial', -1)
    font.setPointSizeF(pt_size)
    font.setWeight(QFont.Weight(weight))
    from PySide6.QtGui import QFontMetricsF
    fm = QFontMetricsF(font)
    if fm.horizontalAdvance(clean) > w:
        cut_len = len(clean)
        while cut_len > 0 and fm.horizontalAdvance(clean[:cut_len]) > w:
            cut_len -= 1
        clean = clean[:cut_len]
    bold_text(painter, x, y, w, h, clean, pt_size, align, weight, overdraw_px)

memo_a6._draw_bold_text = bold_text
memo_a6._draw_shrink_to_fit_bold = shrink_bold
memo_a6._draw_cut_to_fit_bold = cut_bold

pages = memo_a6.paginate_duplicate_items(head, items, show_duplicate=False)
memo_a6.draw_a6_cash_memo_page(p, pages[0], scale=scale)

# Overdraw 3 horizontal rules with crisp solid 0.35 mm width
pen_rule = QPen(QColor("#000000"), max(2.5, 0.35 * scale), Qt.SolidLine, Qt.SquareCap)
p.setPen(pen_rule)
x0 = (memo_a6.MARGIN_LEFT_MM + memo_a6.OFFSET_X_MM) * scale
x1 = (memo_a6.MARGIN_LEFT_MM + memo_a6.CONTENT_WIDTH_MM + memo_a6.OFFSET_X_MM) * scale
p.drawLine(QPointF(x0, (24.5 + memo_a6.OFFSET_Y_MM) * scale), QPointF(x1, (24.5 + memo_a6.OFFSET_Y_MM) * scale))
p.drawLine(QPointF(x0, (29.0 + memo_a6.OFFSET_Y_MM) * scale), QPointF(x1, (29.0 + memo_a6.OFFSET_Y_MM) * scale))
p.drawLine(QPointF(x0, (memo_a6.ITEM_END_Y_MM + memo_a6.OFFSET_Y_MM) * scale), QPointF(x1, (memo_a6.ITEM_END_Y_MM + memo_a6.OFFSET_Y_MM) * scale))

p.end()

pix.save('scratch/full_bill_super_bold_with_rules.png')
print('Rendered scratch/full_bill_super_bold_with_rules.png')

