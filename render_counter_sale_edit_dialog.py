"""Capture crisp screenshots of Counter Sale Edit Dialog in Night and Day modes with native fonts."""

import os
import pathlib
import sys
import tempfile

from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)
app.setStyle("Fusion")

from database import auth, financial_year
from database.connection import init_database
from database.customer_dao import CustomerDAO
from database.doctor_dao import DoctorDAO
from database.item_dao import ItemDAO
from database.company_dao import CompanyDAO
from database.unit_dao import UnitDAO
from database.drug_dao import DrugDAO
from database.supplier_dao import SupplierDAO
from database.purchase_dao import PurchaseDAO
from database.stock_dao import StockDAO
from database.sales_dao import SalesDAO
from database.hold_bill_dao import ensure_hold_tables
from database.account_roles import ensure_system_ledgers
from screens.counter_sale import CounterSalePage
from ui import theme

ARTIFACT_DIR = pathlib.Path(r"C:\Users\Nilesh\.gemini\antigravity\brain\e3b761b3-55c7-40fb-98cd-6e0b36ed2722")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


def setup_sample_data():
    db_path = os.path.join(tempfile.gettempdir(), "pharmacy_render_edit_test.db")
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass
    os.environ["PHARMACY_DB"] = db_path

    init_database()
    ensure_hold_tables()
    ensure_system_ledgers()
    auth.ensure_auth_schema()
    financial_year.ensure_default_financial_year()
    if auth.user_count() == 0:
        auth.create_first_admin("admin", "admin-pass-1")
    auth.session.login("admin", "admin-pass-1")

    company_id = CompanyDAO.insert("Sun Pharma", "SP")
    unit_id = UnitDAO.insert("Strip")
    drug_id = DrugDAO.insert("Amoxicillin")
    supplier_id = SupplierDAO.insert("National Distributors")
    customer_id = CustomerDAO.insert("Ramesh Kumar", contact_no="9876543210", address="123 Market Road, City")
    doctor_id = DoctorDAO.insert("Dr. A. K. Verma", "Cardiologist")

    item1_id = ItemDAO.insert(
        item_name="Augmentin 625 Duo Tablet",
        unit_id=unit_id,
        company_id=company_id,
        pack_size="10",
        mrp=205.50,
    )
    item2_id = ItemDAO.insert(
        item_name="Pan 40 Tablet",
        unit_id=unit_id,
        company_id=company_id,
        pack_size="15",
        mrp=155.00,
    )

    PurchaseDAO.insert_invoice(
        voucher_no="PV-DEMO-001",
        voucher_date="2026-06-01",
        voucher_time="10:00",
        purchase_type="Cash",
        supplier_id=supplier_id,
        invoice_no="INV-DEMO-001",
        invoice_date="2026-06-01",
        invoice_net_amount=5000.0,
        bill_discount=0,
        due_date="",
        total_amount=5000.0,
        gst_amount=0,
        debit_note_amount=0,
        other_amount=0,
        paid_amount=5000.0,
        round_off=0,
        net_amount=5000.0,
        remarks="",
        items=[
            {
                "item_id": item1_id,
                "pack_size": "10",
                "pay_qty": 100,
                "free_qty": 0,
                "batch_no": "AUG26A",
                "expiry": "05/28",
                "rate": 160.0,
                "mrp": 205.50,
                "discount": 0,
                "gst_percent": 0,
                "gst_amount": 0,
                "amount": 16000.0,
                "purchase_rate": 160.0,
                "net_rate": 160.0,
                "pp": 160.0,
            },
            {
                "item_id": item2_id,
                "pack_size": "15",
                "pay_qty": 100,
                "free_qty": 0,
                "batch_no": "PAN26B",
                "expiry": "09/28",
                "rate": 120.0,
                "mrp": 155.00,
                "discount": 0,
                "gst_percent": 0,
                "gst_amount": 0,
                "amount": 12000.0,
                "purchase_rate": 120.0,
                "net_rate": 120.0,
                "pp": 120.0,
            }
        ],
    )

    batches1 = StockDAO.get_stock_batches_for_item(item1_id)
    batches2 = StockDAO.get_stock_batches_for_item(item2_id)

    # Insert a sample invoice to edit
    inv_id = SalesDAO.insert_invoice(
        bill_no="2026-2027-1842",
        sale_date="2026-06-15",
        sale_time="11:45",
        sale_type="Cash",
        customer_id=customer_id,
        patient_name="Smt. Savita Sharma",
        doctor_id=doctor_id,
        discount=15.50,
        paid_amount=350.00,
        total_amount=365.50,
        round_off=0.00,
        net_amount=350.00,
        remarks="Prescription refill for 15 days",
        items=[
            {
                "item_id": item1_id,
                "stock_batch_id": batches1[0]["id"],
                "batch_no": batches1[0]["batch_no"],
                "pack_size": "10",
                "location": "Rack A-2",
                "expiry": batches1[0]["expiry"],
                "mrp": batches1[0]["mrp"],
                "sale_qty": 10.0,
                "discount_amount": 5.50,
                "amount": 200.00,
            },
            {
                "item_id": item2_id,
                "stock_batch_id": batches2[0]["id"],
                "batch_no": batches2[0]["batch_no"],
                "pack_size": "15",
                "location": "Rack B-1",
                "expiry": batches2[0]["expiry"],
                "mrp": batches2[0]["mrp"],
                "sale_qty": 15.0,
                "discount_amount": 10.00,
                "amount": 145.00,
            }
        ],
    )

    return inv_id, customer_id, item1_id, batches1[0]["id"]


def main():
    inv_id, customer_id, item1_id, batch1_id = setup_sample_data()

    # 1. NIGHT MODE
    theme.theme_manager.set_mode("dark")
    app.processEvents()

    page = CounterSalePage()
    page.resize(1366, 768)
    page.show()
    page._hist_date.setDate(QDate(2026, 6, 15))
    page._refresh_history()

    # Add an active draft item on the main screen to verify isolation
    page._sale_panel.customer_combo.setCurrentIndex(
        page._sale_panel.customer_combo.findData(customer_id)
    )
    page._sale_panel._entry_bar.item_combo.setCurrentIndex(
        page._sale_panel._entry_bar.item_combo.findData(item1_id)
    )
    page._sale_panel._entry_bar.batch_combo.setCurrentIndex(
        page._sale_panel._entry_bar.batch_combo.findData(batch1_id)
    )
    page._sale_panel._entry_bar.qty_edit.setText("2")
    page._sale_panel._on_add_item()
    app.processEvents()

    # Select the saved invoice row in history
    for r in range(page._hist_table.rowCount()):
        if page._hist_table.item(r, 0).data(Qt.UserRole) == inv_id:
            page._hist_table.selectRow(r)
            break

    dlg = page._on_edit()
    dlg.resize(1180, 680)
    dlg.show()
    app.processEvents()

    dlg_night = dlg.grab()
    dlg_night.save(str(ARTIFACT_DIR / "counter_sale_edit_dialog_night.png"), "PNG")
    print("Saved counter_sale_edit_dialog_night.png")

    page_night = page.grab()
    page_night.save(str(ARTIFACT_DIR / "counter_sale_edit_page_with_dialog_night.png"), "PNG")
    print("Saved counter_sale_edit_page_with_dialog_night.png")

    # 2. DAY / LIGHT MODE
    theme.theme_manager.set_mode("light")
    page.refresh_theme()
    dlg.refresh_theme()
    app.processEvents()

    dlg_day = dlg.grab()
    dlg_day.save(str(ARTIFACT_DIR / "counter_sale_edit_dialog_day.png"), "PNG")
    print("Saved counter_sale_edit_dialog_day.png")

    page_day = page.grab()
    page_day.save(str(ARTIFACT_DIR / "counter_sale_edit_page_with_dialog_day.png"), "PNG")
    print("Saved counter_sale_edit_page_with_dialog_day.png")

    dlg.reject()
    page.close()
    print("Render complete!")


if __name__ == "__main__":
    main()
