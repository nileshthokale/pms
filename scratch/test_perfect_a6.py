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

dpi = 300.0
scale = dpi / 25.4
w_px = int(round(148.0 * scale))
h_px = int(round(105.0 * scale))

pix = QPixmap(w_px, h_px)
pix.fill(QColor('#ffffff'))
p = QPainter(pix)
p.setRenderHint(QPainter.Antialiasing, True)
p.setRenderHint(QPainter.TextAntialiasing, True)

MM_TO_PT = 72.0 / 25.4

def draw_bold(painter, x, y, w, h, text, pt_size, align='left', weight=900, overdraw=True):
    clean = str(text or '').strip()
    if not clean: return
    font = QFont('Arial', -1)
    px = max(1, int(round(pt_size * scale / MM_TO_PT)))
    font.setPixelSize(px)
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

def shrink_bold(painter, x, y, w, h, text, max_pt=8.5, min_pt=6.5, align='left', weight=900, overdraw=True):
    clean = str(text or '').strip()
    if not clean: return
    font = QFont('Arial', -1)
    font.setWeight(QFont.Weight(weight))
    pt = max_pt
    while pt > min_pt:
        px = max(1, int(round(pt * scale / MM_TO_PT)))
        font.setPixelSize(px)
        fm = QFontMetricsF(font)
        if fm.horizontalAdvance(clean) <= w:
            break
        pt -= 0.5
    if pt < min_pt: pt = min_pt
    draw_bold(painter, x, y, w, h, clean, pt, align, weight, overdraw)

def cut_bold(painter, x, y, w, h, text, pt_size=8.5, align='left', weight=900, overdraw=True):
    clean = str(text or '').strip()
    if not clean: return
    font = QFont('Arial', -1)
    px = max(1, int(round(pt_size * scale / MM_TO_PT)))
    font.setPixelSize(px)
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

# Set A6 profile fonts
memo_a6.DEFAULT_PAPER_SIZE = 'A6'
memo_a6.PAGE_WIDTH_MM = 148.0
memo_a6.PAGE_HEIGHT_MM = 105.0
memo_a6.CONTENT_WIDTH_MM = 140.0
memo_a6.CONTENT_HEIGHT_MM = 95.0
memo_a6.MARGIN_LEFT_MM = 4.0
memo_a6.MARGIN_RIGHT_MM = 4.0
memo_a6.MARGIN_TOP_MM = 5.0
memo_a6.MARGIN_BOTTOM_MM = 5.0

pages = memo_a6.paginate_duplicate_items(head, items, show_duplicate=True, paper_size='A6')
memo_a6.draw_a6_cash_memo_page(p, pages[0], scale=scale)
p.end()

pix.save('scratch/test_perfect_a6_300.png')
print('Rendered scratch/test_perfect_a6_300.png')

# Scale to 701x498
im_high = Image.open('scratch/test_perfect_a6_300.png')
im_user = Image.open(r'C:/Users/savan/.gemini/antigravity/brain/47acb2ce-bf28-4452-bd3e-7c17d1743d4f/.user_uploaded/media_1792915620627_5c37c577.png').convert('RGB')
im_scaled = im_high.resize(im_user.size, Image.Resampling.LANCZOS)
im_scaled.save('scratch/test_perfect_a6_scaled.png')

# Side by side:
combo = Image.new('RGB', (im_user.width * 2, im_user.height))
combo.paste(im_user, (0, 0))
combo.paste(im_scaled, (im_user.width, 0))
combo.save('scratch/compare_perfect_side_by_side.png')
print('Saved scratch/compare_perfect_side_by_side.png')

