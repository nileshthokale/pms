"""Capture visual verification screenshots for the Purchase Invoice dialog in Day and Night modes."""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QTimer, QRect
from PySide6.QtGui import QPixmap

from ui.theme import theme_manager
from database import financial_year
from database.purchase_dao import PurchaseDAO
from database.supplier_dao import SupplierDAO
from database.item_dao import ItemDAO
import screens.purchase_invoice as pi_mod

ARTIFACTS_DIR = Path(r"C:\Users\Nilesh\.gemini\antigravity\brain\e3b761b3-55c7-40fb-98cd-6e0b36ed2722")
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


def capture_all():
    app = QApplication.instance() or QApplication(sys.argv)
    financial_year.ensure_default_financial_year()

    # 1. Day Mode - New Purchase Invoice
    theme_manager.set_mode("light")
    dlg_day = pi_mod._InvoiceDialog()
    # Select first supplier and first item for realistic appearance
    if dlg_day.supplier_combo.count() > 0:
        dlg_day.supplier_combo.setCurrentIndex(0)
    dlg_day.invoice_no_edit.setText("INV-2026-9081")
    if dlg_day._entry_bar.item_combo.count() > 0:
        dlg_day._entry_bar.item_combo.setCurrentIndex(0)
    dlg_day.resize(1200, 720)
    dlg_day.show()
    app.processEvents()

    pix_day = dlg_day.grab()
    day_path = ARTIFACTS_DIR / "new_purchase_invoice_dialog_day.png"
    pix_day.save(str(day_path), "PNG")
    print(f"Saved: {day_path}")

    # Zoom crop of header and entry bar
    crop_rect = QRect(0, 0, dlg_day.width(), 260)
    zoom_day = pix_day.copy(crop_rect)
    zoom_day_path = ARTIFACTS_DIR / "header_entry_bar_zoom_day.png"
    zoom_day.save(str(zoom_day_path), "PNG")
    print(f"Saved: {zoom_day_path}")
    dlg_day.close()

    # 2. Night Mode - New Purchase Invoice
    theme_manager.set_mode("dark")
    dlg_night = pi_mod._InvoiceDialog()
    dlg_night.refresh_theme()
    if dlg_night.supplier_combo.count() > 0:
        dlg_night.supplier_combo.setCurrentIndex(0)
    dlg_night.invoice_no_edit.setText("INV-2026-9081")
    if dlg_night._entry_bar.item_combo.count() > 0:
        dlg_night._entry_bar.item_combo.setCurrentIndex(0)
    dlg_night.resize(1200, 720)
    dlg_night.show()
    app.processEvents()

    pix_night = dlg_night.grab()
    night_path = ARTIFACTS_DIR / "new_purchase_invoice_dialog_night.png"
    pix_night.save(str(night_path), "PNG")
    print(f"Saved: {night_path}")

    zoom_night = pix_night.copy(crop_rect)
    zoom_night_path = ARTIFACTS_DIR / "header_entry_bar_zoom_night.png"
    zoom_night.save(str(zoom_night_path), "PNG")
    print(f"Saved: {zoom_night_path}")
    dlg_night.close()

    # 3. Day Mode - Edit Purchase Invoice
    theme_manager.set_mode("light")
    # Fetch an existing invoice or mock one with full voucher
    invoices = PurchaseDAO.get_all()
    if invoices:
        inv_data = invoices[0]
    else:
        inv_data = {
            "id": 1,
            "voucher_no": "2026-2027-Credit-0251",
            "voucher_date": "2026-05-15",
            "voucher_time": "14:30",
            "purchase_type": "Credit",
            "supplier_id": 1,
            "invoice_no": "MED-SUPP-4402",
            "invoice_date": "2026-05-15",
            "invoice_net_amount": 12500.0,
            "bill_discount": 100.0,
            "due_date": "2026-06-14",
            "debit_note_amount": 0.0,
            "other_amount": 0.0,
            "paid_amount": 0.0,
            "round_off": 0.0,
        }
    dlg_edit = pi_mod._InvoiceDialog(invoice=inv_data)
    dlg_edit.resize(1200, 720)
    dlg_edit.show()
    app.processEvents()

    pix_edit = dlg_edit.grab()
    edit_path = ARTIFACTS_DIR / "edit_purchase_invoice_dialog_day.png"
    pix_edit.save(str(edit_path), "PNG")
    print(f"Saved: {edit_path}")
    dlg_edit.close()


if __name__ == "__main__":
    capture_all()
