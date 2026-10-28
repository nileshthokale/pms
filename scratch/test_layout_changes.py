import os, sys
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtWidgets import QApplication
from database.connection import init_database

app = QApplication.instance() or QApplication(sys.argv)
init_database()

from screens.purchase_invoice import _InvoiceDialog

# Let's subclass or monkey-patch to test the new layout
def test_layout(w_size=1200):
    dlg = _InvoiceDialog()
    # Apply adjustments
    dlg.btn_supplier_edit.setFixedSize(46, 26)
    dlg.btn_supplier_edit.setStyleSheet(
        "QPushButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #dbe7f5); border: 1px solid #7eaadb; border-radius: 2px; color: #0a3663; font-size: 11px; font-weight: bold; padding: 1px 4px; } QPushButton:hover { background: #cde2f8; }"
    )
    dlg.supplier_combo.setMinimumWidth(210)
    dlg.supplier_combo.setMaximumWidth(300)
    dlg.bill_disc_type_combo.setFixedSize(65, 26)
    dlg.due_date.setFixedWidth(135)
    dlg.invoice_date.setFixedWidth(135)

    dlg.resize(w_size, 700)
    dlg.show()
    app.processEvents()

    # Find locations
    pos_btn = dlg.btn_supplier_edit.mapTo(dlg, dlg.btn_supplier_edit.rect().topLeft())
    pos_combo = dlg.supplier_combo.mapTo(dlg, dlg.supplier_combo.rect().topLeft())
    pos_bal = dlg.sup_bal_suffix.mapTo(dlg, dlg.sup_bal_suffix.rect().topRight())
    pos_disc = dlg.bill_disc_type_combo.mapTo(dlg, dlg.bill_disc_type_combo.rect().topLeft())
    pos_due = dlg.due_date.mapTo(dlg, dlg.due_date.rect().topLeft())

    print(f"=== Width {w_size} ===")
    print("Supplier combo right:", pos_combo.x() + dlg.supplier_combo.width())
    print("Edit btn x:", pos_btn.x(), "w:", dlg.btn_supplier_edit.width())
    print("Balance suffix right:", pos_bal.x())
    print("Discount combo x:", pos_disc.x())
    print("Gap between Balance and Discount:", pos_disc.x() - pos_bal.x())
    print("Due date x:", pos_due.x(), "w:", dlg.due_date.width(), "right:", pos_due.x() + dlg.due_date.width())
    dlg.close()

test_layout(1200)
test_layout(1000)
