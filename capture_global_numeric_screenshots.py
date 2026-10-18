"""Capture visual screenshots for Global Numeric Bill & Voucher Number display."""

import os
import pathlib
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])
app.setStyle("Fusion")

from database import auth
from database.connection import get_connection, init_database
from screens.counter_sale import CounterSalePage
from screens.purchase_invoice import PurchaseInvoicePage, _InvoiceDialog
from screens.sales_history import SalesHistoryPage, SalesBillDetailsDialog
from ui import theme

init_database()
auth.ensure_auth_schema()
if auth.user_count() == 0:
    auth.create_first_admin("admin", "admin-pass-1")
auth.session.user = {"id": 1, "username": "admin", "role": auth.ROLE_ADMIN, "is_active": 1}

ARTIFACT_DIR = pathlib.Path(r"C:\Users\Nilesh\.gemini\antigravity\brain\e3b761b3-55c7-40fb-98cd-6e0b36ed2722")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


def capture(widget, filename):
    widget.show()
    app.processEvents()
    pixmap = widget.grab()
    out_path = ARTIFACT_DIR / filename
    pixmap.save(str(out_path), "PNG")
    print(f"Captured: {out_path}")
    return out_path


def capture_suite(mode_suffix=""):
    conn = get_connection()
    try:
        # 1. Purchase History Page
        p_page = PurchaseInvoicePage()
        p_page.resize(1280, 720)
        p_page._refresh_history()
        capture(p_page, f"purchase_history_numeric{mode_suffix}.png")
        p_page.close()

        # 2. Purchase Invoice Dialog (New)
        p_dlg = _InvoiceDialog()
        p_dlg.resize(1100, 650)
        capture(p_dlg, f"new_purchase_invoice_numeric{mode_suffix}.png")
        p_dlg.close()

        # 3. Sales History Page (showing both empty patient blank bills and named patient numeric bills)
        s_page = SalesHistoryPage()
        s_page.resize(1280, 720)
        s_page._date_check.setChecked(True)
        s_page._from_date.setDate(QDate(2015, 4, 1))
        s_page._to_date.setDate(QDate(2015, 4, 1))
        s_page._perform_search()
        capture(s_page, f"sales_history_empty_patient{mode_suffix}.png")
        s_page.close()

        # 4. Sales Bill Details Dialog for Bill with Empty Patient (ID 4 -> blank Bill / CNo)
        s_dlg_empty = SalesBillDetailsDialog(4)
        s_dlg_empty.resize(850, 500)
        capture(s_dlg_empty, f"sales_bill_details_empty_patient{mode_suffix}.png")
        s_dlg_empty.close()

        # 5. Sales Bill Details Dialog for Bill with Patient (ID 1 -> numeric '1')
        s_dlg_pat = SalesBillDetailsDialog(1)
        s_dlg_pat.resize(850, 500)
        capture(s_dlg_pat, f"sales_bill_details_with_patient{mode_suffix}.png")
        s_dlg_pat.close()

        # 6. Counter Sale Panel (showing Bill History table with mixed empty/present patient rows on 2015-04-01)
        cs_panel = CounterSalePage()
        cs_panel.resize(1280, 720)
        cs_panel._hist_date.setDate(QDate(2015, 4, 1))
        cs_panel._refresh_history()
        capture(cs_panel, f"counter_sale_bill_history_empty_patient{mode_suffix}.png")
        cs_panel.close()

    finally:
        conn.close()


def main():
    # Dark / Night Mode
    theme.theme_manager.set_mode("dark")
    app.processEvents()
    capture_suite("")

    # Light / Day Mode
    theme.theme_manager.set_mode("light")
    app.processEvents()
    capture_suite("_day")

    print("All numeric screenshots (Night and Day) captured successfully!")


if __name__ == "__main__":
    main()
