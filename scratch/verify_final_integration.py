import sys, os
sys.path.insert(0, os.getcwd())
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from PySide6.QtGui import QPixmap
from PIL import Image

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

pages = memo_a6.paginate_duplicate_items(head, items, show_duplicate=True)
print("Page count:", len(pages), "paper_size:", pages[0].get("paper_size"))

# Render 300 DPI pixmap (used by print)
pix300 = memo_a6.render_a6_cash_memo_pixmap(pages[0], dpi=300.0)
pix300.save("scratch/final_verified_a6_print_300dpi.png")
print("Saved 300 DPI pixmap:", pix300.width(), "x", pix300.height())

# Render 150 DPI pixmap (used by screen preview)
pix150 = memo_a6.render_a6_cash_memo_pixmap(pages[0], dpi=150.0)
pix150.save("scratch/final_verified_a6_preview_150dpi.png")
print("Saved 150 DPI preview:", pix150.width(), "x", pix150.height())

# Scale 300 DPI down to user image size (701 x 498) to verify
im_user = Image.open(r"C:/Users/savan/.gemini/antigravity/brain/47acb2ce-bf28-4452-bd3e-7c17d1743d4f/.user_uploaded/media_1792915620627_5c37c577.png").convert("RGB")
im_print = Image.open("scratch/final_verified_a6_print_300dpi.png")
im_scaled = im_print.resize(im_user.size, Image.Resampling.LANCZOS)
im_scaled.save("scratch/final_verified_a6_print_scaled.png")

# Save side-by-side comparison for visual confirmation
combo = Image.new("RGB", (im_user.width * 2, im_user.height))
combo.paste(im_user, (0, 0))
combo.paste(im_scaled, (im_user.width, 0))
combo.save("scratch/final_comparison_user_vs_print.png")
print("Saved scratch/final_comparison_user_vs_print.png successfully!")

