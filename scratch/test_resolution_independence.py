import sys, os
sys.path.insert(0, os.getcwd())
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from PySide6.QtGui import QFont, QFontMetricsF, QPixmap, QPainter, QColor, QPen
from PySide6.QtCore import QRectF, Qt, QPointF
from PIL import Image
import numpy as np

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

import database.duplicate_a6_cash_memo as memo_a6

# Test our scaling implementation:
MM_TO_PT = 72.0 / 25.4

def render_at_dpi(dpi):
    scale = dpi / 25.4
    w_px = int(round(148.0 * scale))
    h_px = int(round(105.0 * scale))
    pix = QPixmap(w_px, h_px)
    pix.fill(QColor('#ffffff'))
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.TextAntialiasing, True)
    
    # Custom draw using pixelSize:
    def draw_bold(painter, x, y, w, h, text, pt_size, align='left', weight=900, overdraw=True):
        clean = str(text or '').strip()
        if not clean: return
        font = QFont('Arial', -1)
        font.setPixelSize(max(1, int(round(pt_size * scale / MM_TO_PT))))
        font.setWeight(QFont.Weight(weight))
        painter.setFont(font)
        painter.setPen(QColor('#000000'))
        qt_align = Qt.AlignVCenter
        if align == 'right': qt_align |= Qt.AlignRight
        elif align == 'center': qt_align |= Qt.AlignHCenter
        else: qt_align |= Qt.AlignLeft
        r = QRectF(x, y, w, h)
        painter.drawText(r, qt_align, clean)
        if overdraw:
            ov = max(0.5, 0.08 * scale)
            painter.drawText(r.translated(ov, 0.0), qt_align, clean)
            painter.drawText(r.translated(0.0, ov * 0.5), qt_align, clean)

    def shrink_bold(painter, x, y, w, h, text, max_pt=9.5, min_pt=6.5, align='left', weight=900, overdraw=True):
        clean = str(text or '').strip()
        if not clean: return
        font = QFont('Arial', -1)
        font.setWeight(QFont.Weight(weight))
        pt = max_pt
        while pt > min_pt:
            font.setPixelSize(max(1, int(round(pt * scale / MM_TO_PT))))
            fm = QFontMetricsF(font)
            if fm.horizontalAdvance(clean) <= w:
                break
            pt -= 0.5
        if pt < min_pt: pt = min_pt
        draw_bold(painter, x, y, w, h, clean, pt, align, weight, overdraw)

    def cut_bold(painter, x, y, w, h, text, pt_size=9.5, align='left', weight=900, overdraw=True):
        clean = str(text or '').strip()
        if not clean: return
        font = QFont('Arial', -1)
        font.setPixelSize(max(1, int(round(pt_size * scale / MM_TO_PT))))
        font.setWeight(QFont.Weight(weight))
        fm = QFontMetricsF(font)
        if fm.horizontalAdvance(clean) > w:
            cut_len = len(clean)
            while cut_len > 0 and fm.horizontalAdvance(clean[:cut_len]) > w:
                cut_len -= 1
            clean = clean[:cut_len]
        draw_bold(painter, x, y, w, h, clean, pt_size, align, weight, overdraw)

    memo_a6._draw_bold_text = draw_bold
    memo_a6._draw_shrink_to_fit_bold = shrink_bold
    memo_a6._draw_cut_to_fit_bold = cut_bold

    pages = memo_a6.paginate_duplicate_items(head, items, show_duplicate=True, paper_size='A6')
    memo_a6.draw_a6_cash_memo_page(p, pages[0], scale=scale)
    p.end()
    return pix

pix_low = render_at_dpi(120.3)
pix_high = render_at_dpi(300.0)

pix_low.save('scratch/pix_120.png')
pix_high.save('scratch/pix_300.png')

# Scale high to low:
im_high = Image.open('scratch/pix_300.png')
im_low = Image.open('scratch/pix_120.png')
im_high_scaled = im_high.resize(im_low.size, Image.Resampling.LANCZOS)
im_high_scaled.save('scratch/pix_300_scaled_to_120.png')

diff = np.abs(np.array(im_high_scaled.convert('L'), dtype=int) - np.array(im_low.convert('L'), dtype=int))
print('Difference between 300 DPI scaled down and 120 DPI render:', diff.mean())

