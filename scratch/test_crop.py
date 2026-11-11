import os, sys
sys.path.insert(0, '.')
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtWidgets import QApplication
from database.connection import init_database
from screens.purchase_invoice import _InvoiceDialog

app = QApplication.instance() or QApplication(sys.argv)
init_database()

# Test dialog layout
dlg = _InvoiceDialog()
dlg.resize(1200, 700)
dlg.show()
app.processEvents()

from PIL import Image
im = Image.open('scratch/rendered_fixed_header_dlg.png')
w, h = im.size
crop_hdr = im.crop((0, 0, w, 200))
crop_hdr.save('scratch/fixed_header_crop.png')
print('fixed_header_crop.png saved!')
