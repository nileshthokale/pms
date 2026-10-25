import sys, os
sys.path.insert(0, os.getcwd())
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from PySide6.QtGui import QFont, QFontMetricsF, QPixmap, QPainter, QColor, QPen
from PySide6.QtCore import QRectF, Qt, QPointF
from PIL import Image
import numpy as np

import database.duplicate_a6_cash_memo as memo_a6

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

# Set paper profile to A6
memo_a6.DEFAULT_PAPER_SIZE = 'A6'

dpi = 300.0
scale = dpi / 25.4 # ~11.811 px / mm
w_px = int(round(148.0 * scale))
h_px = int(round(105.0 * scale))

pix = QPixmap(w_px, h_px)
pix.fill(QColor('#ffffff'))
p = QPainter(pix)
p.setRenderHint(QPainter.Antialiasing, True)
p.setRenderHint(QPainter.TextAntialiasing, True)

# Custom drawing functions with DPI-aware font sizing:
MM_TO_PT = 72.0 / 25.4

def bold_text_dpi(painter, x, y, w, h, text, pt_size, align='left', weight=900, overdraw_px=1.0):
    clean = str(text or '').strip()
    if not clean: return
    font = QFont('Arial', -1)
    # Target pixel size on this painter at current scale:
    # 1 pt = 25.4 / 72 mm = (scale / MM_TO_PT) pixels!
    px_size = int(round(pt_size * scale / MM_TO_PT))
    font.setPixelSize(px_size)
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

def shrink_bold_dpi(painter, x, y, w, h, text, max_pt=9.5, min_pt=6.5, align='left', weight=900, overdraw_px=1.0):
    clean = str(text or '').strip()
    if not clean: return
    font = QFont('Arial', -1)
    font.setWeight(QFont.Weight(weight))
    pt = max_pt
    while pt > min_pt:
        px = int(round(pt * scale / MM_TO_PT))
        font.setPixelSize(px)
        fm = QFontMetricsF(font)
        if fm.horizontalAdvance(clean) <= w:
            break
        pt -= 0.5
    if pt < min_pt: pt = min_pt
    bold_text_dpi(painter, x, y, w, h, clean, pt, align, weight, overdraw_px)

def cut_bold_dpi(painter, x, y, w, h, text, pt_size=9.5, align='left', weight=900, overdraw_px=1.0):
    clean = str(text or '').strip()
    if not clean: return
    font = QFont('Arial', -1)
    px = int(round(pt_size * scale / MM_TO_PT))
    font.setPixelSize(px)
    font.setWeight(QFont.Weight(weight))
    fm = QFontMetricsF(font)
    if fm.horizontalAdvance(clean) > w:
        cut_len = len(clean)
        while cut_len > 0 and fm.horizontalAdvance(clean[:cut_len]) > w:
            cut_len -= 1
        clean = clean[:cut_len]
    bold_text_dpi(painter, x, y, w, h, clean, pt_size, align, weight, overdraw_px)

memo_a6._draw_bold_text = bold_text_dpi
memo_a6._draw_shrink_to_fit_bold = shrink_bold_dpi
memo_a6._draw_cut_to_fit_bold = cut_bold_dpi

pages = memo_a6.paginate_duplicate_items(head, items, show_duplicate=True, paper_size='A6')
memo_a6.draw_a6_cash_memo_page(p, pages[0], scale=scale)
p.end()

pix.save('scratch/test_dpi_aware_300.png')
print('Rendered scratch/test_dpi_aware_300.png successfully!')

# Now scale it down to user image size (701 x 498) and compare!
im_rendered = Image.open('scratch/test_dpi_aware_300.png')
im_user = Image.open(r'C:/Users/savan/.gemini/antigravity/brain/47acb2ce-bf28-4452-bd3e-7c17d1743d4f/.user_uploaded/media_1792915620627_5c37c577.png').convert('RGB')

im_scaled = im_rendered.resize(im_user.size, Image.Resampling.LANCZOS)
im_scaled.save('scratch/test_dpi_aware_scaled_to_user.png')

# Create side-by-side comparison:
combo = Image.new('RGB', (im_user.width * 2, im_user.height))
combo.paste(im_user, (0, 0))
combo.paste(im_scaled, (im_user.width, 0))
combo.save('scratch/user_vs_dpi_aware_scaled.png')
print('Saved scratch/user_vs_dpi_aware_scaled.png!')

