"""Verification for Sales History bill number formatting and remarks removal.

Specifically tests:
1. Bill number formatting in dialog and table (FY prefix stripped)
2. Remarks section removed from dialog
"""
from __future__ import annotations

import os
import sys
import tempfile
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

DB_PATH = tempfile.mktemp(prefix="verify_billno_", suffix=".db")

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtTest import QTest

def main() -> int:
    os.environ["PHARMACY_DB"] = DB_PATH
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

    from database.connection import init_database, get_connection
    from database import auth, financial_year
    from database.account_roles import ensure_system_ledgers
    from database.customer_dao import CustomerDAO
    from database.doctor_dao import DoctorDAO
    from database.item_dao import ItemDAO
    from database.purchase_dao import PurchaseDAO
    from database.sales_dao import SalesDAO
    from database.supplier_dao import SupplierDAO
    from database.unit_dao import UnitDAO

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_database()
    auth.ensure_auth_schema()
    financial_year.ensure_financial_year_schema()
    financial_year.ensure_default_financial_year()
    if auth.user_count() == 0:
        auth.create_first_admin("admin", "admin-pass-1")
    auth.session.login("admin", "admin-pass-1")
    ensure_system_ledgers()

    # Seed test data
    unit_id = UnitDAO.insert("Strip")
    supplier_id = SupplierDAO.insert("MainSupplier")
    customer_a = CustomerDAO.insert("Customer Alpha")
    doctor_a = DoctorDAO.insert("Dr. Smith")
    item = ItemDAO.insert(item_name="Test Item", unit_id=unit_id,
                          company_id=None, pack_size="10x10")

    PurchaseDAO.insert_invoice(
        voucher_no="PV-0001", voucher_date="2026-05-01", voucher_time="10:00",
        purchase_type="Cash", supplier_id=supplier_id,
        invoice_no="PINV-001", invoice_date="2026-05-01",
        invoice_net_amount=5000.0, bill_discount=0, due_date="",
        total_amount=5000.0, gst_amount=0, debit_note_amount=0,
        other_amount=0, paid_amount=5000.0, round_off=0,
        net_amount=5000.0, remarks="Test remarks for verification",
        items=[{"item_id": item, "pack_size": "10x10", "pay_qty": 100.0,
                "free_qty": 0, "batch_no": "BATCH-TEST-01", "expiry": "12/28",
                "rate": 50.0, "mrp": 100.0, "discount": 0, "gst_percent": 0,
                "gst_amount": 0, "amount": 5000.0, "purchase_rate": 50.0,
                "net_rate": 50.0, "pp": 50.0}],
    )

    # Manually insert bills with FY-prefixed bill numbers and non-prefixed ones
    conn = get_connection()
    try:
        # FY-prefixed bill
        conn.execute("""
            INSERT INTO sales_invoices 
            (bill_no, sale_date, sale_time, sale_type, customer_id, 
             patient_name, doctor_id, total_amount, discount, paid_amount,
             round_off, net_amount, remarks)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, ("2026-2027-1905", "2026-06-15", "10:00", "Cash", customer_a, 
              "Alice Patient", doctor_a, 70.0, 0.0, 70.0, 0.0, 70.0, "FY formatted bill remarks"))
        fy_bill_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        
        # Non-FY prefixed bill
        conn.execute("""
            INSERT INTO sales_invoices 
            (bill_no, sale_date, sale_time, sale_type, customer_id, 
             patient_name, doctor_id, total_amount, discount, paid_amount,
             round_off, net_amount, remarks)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, ("CS-0002", "2026-08-20", "14:00", "Cash", customer_a, 
              "Bob Patient", doctor_a, 70.0, 0.0, 70.0, 0.0, 70.0, "Non-FY bill remarks"))
        cs_bill_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        
        conn.commit()
    finally:
        conn.close()

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    from ui import theme
    theme.apply_to_app()

    from screens.sales_history import SalesHistoryPage, _fmt_bill_no, SalesBillDetailsDialog

    # Test 1: _fmt_bill_no function strips FY prefix correctly
    print("Testing _fmt_bill_no function...")
    assert _fmt_bill_no("2026-2027-1905") == "1905", "Should strip 2026-2027- prefix"
    assert _fmt_bill_no("2025-2026-0123") == "0123", "Should strip 2025-2026- prefix"
    assert _fmt_bill_no("CS-0001") == "CS-0001", "Should not modify non-FY format"
    assert _fmt_bill_no("1905") == "1905", "Should not modify bare number"
    assert _fmt_bill_no("--") == "--", "Should handle placeholder"
    assert _fmt_bill_no(None) == None, "Should handle None"
    print("  _fmt_bill_no function: OK")
    
    # Test 2: Bill number formatting in dialog
    print("Testing bill number formatting in dialog...")
    dlg = SalesBillDetailsDialog(fy_bill_id)
    dlg.show()
    QTest.qWait(100)
    
    meta_group = dlg._meta_group
    grid = meta_group.layout()
    bill_item = grid.itemAtPosition(0, 1)
    if bill_item and bill_item.widget():
        bill_value = bill_item.widget().text()
        assert bill_value == "1905", f"Expected '1905', got '{bill_value}'"
        print(f"  Dialog bill number displayed as: '{bill_value}' (correctly stripped FY prefix)")
    
    # Test 3: Non-FY bill preserved in dialog
    dlg2 = SalesBillDetailsDialog(cs_bill_id)
    dlg2.show()
    QTest.qWait(100)
    grid2 = dlg2._meta_group.layout()
    bill_item2 = grid2.itemAtPosition(0, 1)
    if bill_item2 and bill_item2.widget():
        bill_value2 = bill_item2.widget().text()
        assert bill_value2 == "CS-0002", f"Expected 'CS-0002', got '{bill_value2}'"
        print(f"  Dialog bill number for non-FY format: '{bill_value2}' (preserved)")
    dlg2.close()
    dlg.close()
    
    # Test 4: Remarks removed from dialog
    print("Testing remarks removal from dialog...")
    remarks_found = False
    for child in dlg.findChildren(QLabel):
        if child.text() == "Remarks:":
            remarks_found = True
            break
    
    assert not remarks_found, "Remarks label still present in dialog"
    print("  Remarks label correctly removed")
    
    # Verify stored remarks preserved
    stored_bill = SalesDAO.get_by_id(fy_bill_id)
    assert stored_bill["remarks"] == "FY formatted bill remarks", \
        "Remarks should still be in DB"
    print("  Stored remarks preserved in database")
    
    # Test 5: Bill numbers in history table
    print("Testing bill number formatting in history table...")
    page = SalesHistoryPage()
    page.show()
    QTest.qWait(200)
    
    # Find both bills in table and verify formatting
    found_fy = False
    found_cs = False
    for row in range(page._table.rowCount()):
        item = page._table.item(row, 0)
        if item:
            displayed = item.text()
            if displayed == "1905":
                found_fy = True
            elif displayed == "CS-0002":
                found_cs = True
    
    assert found_fy, "FY-formatted bill with stripped number not found in table"
    assert found_cs, "Non-FY bill not found in table"
    print(f"  Table bill numbers correct: FY-stripped='1905', Non-FY='CS-0002'")
    page.close()
    
    # Test 6: Verify database records unchanged
    print("Verifying database records unchanged...")
    fy_bill_final = SalesDAO.get_by_id(fy_bill_id)
    assert fy_bill_final["bill_no"] == "2026-2027-1905", "Bill number modified in DB!"
    assert fy_bill_final["remarks"] == "FY formatted bill remarks", "Remarks modified in DB!"
    cs_bill_final = SalesDAO.get_by_id(cs_bill_id)
    assert cs_bill_final["bill_no"] == "CS-0002", "Bill number modified in DB!"
    print("  All database records verified unchanged")
    
    # Cleanup
    for suffix in ("", "-wal", "-shm"):
        p = pathlib.Path(f"{DB_PATH}{suffix}")
        if p.exists():
            p.unlink()
    
    print("\nAll verification checks passed!")
    return 0

if __name__ == "__main__":
    sys.exit(main())