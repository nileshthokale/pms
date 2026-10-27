import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"c:\Users\savan\OneDrive\Desktop\pms-main")

from PySide6.QtWidgets import QApplication
from database.connection import init_database
from database.purchase_dao import PurchaseDAO
from screens.purchase_invoice import _InvoiceDialog

app = QApplication.instance() or QApplication(sys.argv)
init_database()

# Open dialog in new mode
dlg_new = _InvoiceDialog()
dlg_new.show()
app.processEvents()
dlg_new.grab().save("scratch/rendered_new_invoice.png")
dlg_new.close()

# Open dialog in edit mode with first historical invoice if exists
invs = PurchaseDAO.get_all()
if invs:
    target_inv = PurchaseDAO.get_by_id(invs[0]["id"])
    dlg_edit = _InvoiceDialog(invoice=target_inv)
    dlg_edit.show()
    app.processEvents()
    dlg_edit.grab().save("scratch/rendered_edit_invoice.png")
    dlg_edit.close()

print("Rendered screenshots saved!")
