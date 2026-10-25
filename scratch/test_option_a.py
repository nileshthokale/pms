from PySide6.QtWidgets import QApplication
import sys
app = QApplication.instance() or QApplication(sys.argv)
from PySide6.QtGui import QFont, QPixmap, QPainter, QColor, QPen, QImage
from PySide6.QtCore import QRectF, Qt
from PIL import Image
import numpy as np

import database.duplicate_a6_cash_memo as memo_a6

head = {
    'voucher_no': '2043',
    'sale_type': 'Cash',
    'sale_date': '2026-10-24',
    'customer_name': 'WALKIN',
    'doctor_name': 'DR. K.N. GHORPADE',
    'net_amount': 890.0
}
items = [
    {'sales_qty': 1, 'unit': 'TABLET', 'item_name': 'BIO D3 PLUS', 'comp': 'MCL', 'batch_no': 'KBC2402A', 'expiry': '31/12/2026', 'amount': 20.0},
    {'sales_qty': 2, 'unit': 'TABLET', 'item_name': 'PROTONIX DSR', 'comp': 'ALK', 'batch_no': 'AC26040089', 'expiry': '08/27', 'amount': 340.0},
    {'sales_qty': 1, 'unit': 'TABLET', 'item_name': 'BONULTRA', 'comp': 'ZUV', 'batch_no': 'BN8819', 'expiry': '12/26', 'amount': 190.0},
    {'sales_qty': 1, 'unit': 'TABLET', 'item_name': 'ARTHRASPAZ 4MG', 'comp': 'INT', 'batch_no': 'AS401', 'expiry': '03/27', 'amount': 150.0},
]
pages = memo_a6.paginate_duplicate_items(head, items, show_duplicate=False)
page = pages[0]

# Render option A: ExtraBold (800) + 1px overdraw + 0.35mm solid rule
def render_option_a(output_png):
    scale = 300.0 / 25.4
    w_px = int(round(memo_a6.PAGE_WIDTH_MM * scale))
    h_px = int(round(memo_a6.PAGE_HEIGHT_MM * scale))
    pix = QPixmap(w_px, h_px)
    pix.fill(QColor('#ffffff'))
    
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.TextAntialiasing, True)
    
    # Custom draw function with ExtraBold and subtle overdraw
    def draw_bold(painter, x, y, w, h, text, pt_size, align='left'):
        clean = str(text or '').strip()
        if not clean: return
        font = QFont('Arial', -1)
        font.setPointSizeF(pt_size)
        font.setWeight(QFont.Weight.ExtraBold)
        painter.setFont(font)
        painter.setPen(QColor('#000000'))
        
        qt_align = Qt.AlignVCenter
        if align == 'right': qt_align |= Qt.AlignRight
        elif align == 'center': qt_align |= Qt.AlignHCenter
        else: qt_align |= Qt.AlignLeft
        
        r = QRectF(x, y, w, h)
        painter.drawText(r, qt_align, clean)
        # 1-pixel horizontal overdraw for solid laser toner
        painter.drawText(r.translated(1.0, 0.0), qt_align, clean)
        painter.drawText(r.translated(0.0, 0.5), qt_align, clean)

    memo_a6._draw_bold_text = draw_bold
    memo_a6._draw_shrink_to_fit_bold = lambda p, x, y, w, h, t, max_pt=8.0, min_pt=6.0, align='left': draw_bold(p, x, y, w, h, t, max_pt, align)
    memo_a6._draw_cut_to_fit_bold = lambda p, x, y, w, h, t, pt_size=8.0, align='left': draw_bold(p, x, y, w, h, t, pt_size, align)
    
    memo_a6.draw_a6_cash_memo_page(p, page, scale=scale)
    p.end()
    pix.save(output_png)

render_option_a('scratch/option_a_extrabold_overdraw.png')
print('Option A rendered')

