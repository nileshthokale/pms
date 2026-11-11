import sys, os
sys.path.insert(0, os.getcwd())
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from PySide6.QtGui import QPixmap
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

# Render at dpi = 120.3 (or 150)
for dpi_test in [120.0, 120.3, 150.0]:
    pages = memo_a6.paginate_duplicate_items(head, items, show_duplicate=True, paper_size='A6')
    pix = memo_a6.render_a6_cash_memo_pixmap(pages[0], dpi=dpi_test)
    pix.save(f'scratch/render_a6_{dpi_test}.png')
    print(f'Rendered at dpi={dpi_test}: {pix.width()} x {pix.height()}')

# Load user image:
im_user = Image.open(r'C:/Users/savan/.gemini/antigravity/brain/47acb2ce-bf28-4452-bd3e-7c17d1743d4f/.user_uploaded/media_1792915620627_5c37c577.png')
print('User image size:', im_user.size)

