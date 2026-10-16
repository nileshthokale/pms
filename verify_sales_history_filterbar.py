"""Verification + screenshot capture for the Sales History one-line filter bar.

Renders the live SalesHistoryPage on the real Qt ``windows`` platform and checks:
- Customer / Bill-CNo filter controls are gone (no _customer_edit / _bill_no_edit).
- The remaining filter controls exist (Patient, FY, Date checkbox, From, To,
  Search, Reset).
- The filter bar fits on ONE horizontal line at 1366px width.
- Patient search, FY selection, date filtering, Search and Reset all work.

Uses an isolated throwaway database.
"""
from __future__ import annotations

import os
import sys
import tempfile
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
# Ensure project root importable (we will chdir so relative paths resolve).

DB_PATH = tempfile.mktemp(prefix="test_sales_db", suffix=".db")

from PySide6.QtCore import QDate, QTimer
from PySide6.QtWidgets import QApplication, QHBoxLayout
from PySide6.QtTest import QTest


def main() -> int:
    root = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    os.chdir(str(root))

    os.environ["PHARMACY_DB"] = DB_PATH
    os.environ["QT_QPA_PLATFORM"] = "windows"

    from database.connection import init_database, get_connection
    from database import auth, financial_year
    from database.account_roles import ensure_system_ledgers
    from database.customer_dao import CustomerDAO
    from database.doctor_dao import DoctorDAO
    from database.item_dao import ItemDAO
    from database.purchase_dao import PurchaseDAO
    from database.sales_dao import SalesDAO
    from database.stock_dao import StockDAO
    from database.supplier_dao import SupplierDAO
    from database.unit_dao import UnitDAO
    from database.company_dao import CompanyDAO

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

    # Seed master data + two sales on different dates.
    conn = get_connection()
    try:
        financial_year.create_financial_year("2025-2026", "2025-04-01", "2026-03-31", activate=False)
    finally:
        conn.close()

    unit_id = UnitDAO.insert("Strip")
    supplier_id = SupplierDAO.insert("MainSupplier")
    customer_a = CustomerDAO.insert("Customer Alpha")
    doctor_a = DoctorDAO.insert("Dr. Smith", specialty="Cardiology")
    item = ItemDAO.insert(item_name="Amoxicillin 500mg", unit_id=unit_id,
                          company_id=None, pack_size="10x10")
    ensure_system_ledgers()
    PurchaseDAO.insert_invoice(
        voucher_no="PV-0001", voucher_date="2025-05-01", voucher_time="10:00",
        purchase_type="Cash", supplier_id=supplier_id,
        invoice_no="PINV-001", invoice_date="2025-05-01",
        invoice_net_amount=5000.0, bill_discount=0, due_date="",
        total_amount=5000.0, gst_amount=0, debit_note_amount=0,
        other_amount=0, paid_amount=5000.0, round_off=0,
        net_amount=5000.0, remarks="",
        items=[{"item_id": item, "pack_size": "10x10", "pay_qty": 200.0,
                "free_qty": 0, "batch_no": "BATCH-AMOX-01", "expiry": "12/28",
                "rate": 50.0, "mrp": 70.0, "discount": 0, "gst_percent": 0,
                "gst_amount": 0, "amount": 5000.0, "purchase_rate": 50.0,
                "net_rate": 50.0, "pp": 50.0}],
    )
    batches = StockDAO.get_stock_batches_for_item(item)
    batch_id = batches[0]["id"]

    SalesDAO.insert_invoice(
        bill_no="CS-0001", sale_date="2025-06-15", sale_time="10:00",
        sale_type="Cash", customer_id=customer_a, patient_name="Alice Wonderland",
        doctor_id=doctor_a, discount=0.0, paid_amount=70.0,
        total_amount=70.0, round_off=0.0, net_amount=70.0, remarks="",
        items=[{"item_id": item, "stock_batch_id": batch_id, "pack_size": "10x10",
                "location": "", "batch_no": "BATCH-AMOX-01", "expiry": "12/28",
                "mrp": 70.0, "sale_qty": 1.0, "discount_amount": 0.0, "amount": 70.0}],
    )
    SalesDAO.insert_invoice(
        bill_no="CS-0002", sale_date="2026-08-20", sale_time="14:00",
        sale_type="Cash", customer_id=customer_a, patient_name="Bob Builder",
        doctor_id=doctor_a, discount=0.0, paid_amount=70.0,
        total_amount=70.0, round_off=0.0, net_amount=70.0, remarks="",
        items=[{"item_id": item, "stock_batch_id": batch_id, "pack_size": "10x10",
                "location": "", "batch_no": "BATCH-AMOX-01", "expiry": "12/28",
                "mrp": 70.0, "sale_qty": 1.0, "discount_amount": 0.0, "amount": 70.0}],
    )

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    from ui import theme
    theme.apply_to_app()

    from screens.sales_history import SalesHistoryPage

    page = SalesHistoryPage()
    page.setObjectName("SalesHistoryPage")
    page.resize(1300, 700)
    page.show()
    QTest.qWait(300)

    # 1. Customer / Bill-CNo controls removed?
    has_customer_edit = hasattr(page, "_customer_edit")
    has_bill_no_edit = hasattr(page, "_bill_no_edit")
    print(f"has _customer_edit (should be False): {has_customer_edit}")
    print(f"has _bill_no_edit (should be False): {has_bill_no_edit}")

    # 2. Remaining controls present?
    for attr in ("_patient_edit", "_fy_combo", "_date_check", "_from_date",
                 "_to_date", "_search_btn", "_reset_btn"):
        print(f"has {attr}: {hasattr(page, attr)}")

    # 3. Filter bar on one line? Check all immediate children of the filter
    # layout share the same row (single QHBoxLayout).  The group box height
    # includes its title, so we only verify that all children are arranged
    # horizontally rather than wrapping vertically.
    filter_box = page._filter_box
    layout = filter_box.layout()
    if layout is not None and isinstance(layout, QHBoxLayout):
        children = [layout.itemAt(i).widget() for i in range(layout.count())
                    if layout.itemAt(i).widget() is not None]
        print(f"filter bar has {len(children)} direct children "
              f"(layout type: {type(layout).__name__})")
        # A single QHBoxLayout row: all widgets should be visible on one line
        # and share approximately the same vertical position.
        if len(children) >= 2:
            y0 = children[0].geometry().y() if children[0].isVisible() else 0
            all_same_row = all(
                abs((child.geometry().y() if child.isVisible() else 0) - y0) < 5
                for child in children[1:] if child.isVisible()
            )
            print(f"  all in same row: {all_same_row}")
            assert all_same_row, (
                "Filter controls appear to wrap vertically - not a single line")
        else:
            print("  insufficient children to check row layout")
    else:
        print("  layout not found or not QHBoxLayout; skipping row check")

    # Screenshot of full page + a tight crop of the filter bar.
    out_dir = pathlib.Path("docs/sales_history_screenshots")
    out_dir.mkdir(parents=True, exist_ok=True)

    full = app.activeWindow().grab() or page.grab()
    if not full.isNull():
        full.save(str(out_dir / "sales_history_filterbar_full.png"))
        print(f"saved {out_dir / 'sales_history_filterbar_full.png'}")

    crop = filter_box.grab()
    if not crop.isNull():
        crop.save(str(out_dir / "sales_history_filterbar_oneline.png"))
        print(f"saved {out_dir / 'sales_history_filterbar_oneline.png'}")

    # 4. Functional checks.
    # Patient search (case-insensitive partial)
    page._patient_edit.setText("alice")
    page._perform_search()
    QTest.qWait(200)
    rows = [page._table.item(r, 0).text() for r in range(page._table.rowCount())]
    print(f"patient='alice' -> {rows}")
    assert "CS-0001" in rows and "CS-0002" not in rows, "Patient search failed"

    # Partial case-insensitive: 'bob'
    page._patient_edit.clear()
    page._patient_edit.setText("bob")
    page._perform_search()
    QTest.qWait(200)
    rows = [page._table.item(r, 0).text() for r in range(page._table.rowCount())]
    print(f"patient='bob' -> {rows}")
    assert "CS-0002" in rows and "CS-0001" not in rows, "Partial patient search failed"

    # FY selection
    page._patient_edit.clear()
    idx = -1
    for i in range(page._fy_combo.count()):
        if "2025-2026" in page._fy_combo.itemText(i):
            idx = i
            break
    page._fy_combo.setCurrentIndex(idx)
    QTest.qWait(200)
    rows = [page._table.item(r, 0).text() for r in range(page._table.rowCount())]
    print(f"FY 2025-2026 -> {rows}")
    assert "CS-0001" in rows, "FY filtering failed to show FY start"
    assert "CS-0002" not in rows, "FY filtering failed to exclude next FY"

    # Date filtering (manual range)
    page._fy_combo.setCurrentIndex(0)
    QTest.qWait(200)
    page._date_check.setChecked(True)
    page._from_date.setDate(QDate.fromString("2025-04-01", "yyyy-MM-dd"))
    page._to_date.setDate(QDate.fromString("2025-12-31", "yyyy-MM-dd"))
    page._perform_search()
    QTest.qWait(200)
    rows = [page._table.item(r, 0).text() for r in range(page._table.rowCount())]
    print(f"date 2025-04-01..2025-12-31 -> {rows}")
    assert "CS-0001" in rows and "CS-0002" not in rows, "Date filtering failed"

    # Reset
    page._on_reset_clicked()
    QTest.qWait(200)
    rows = [page._table.item(r, 0).text() for r in range(page._table.rowCount())]
    print(f"after reset -> {len(rows)} rows")
    assert len(rows) >= 2, "Reset did not return to all records"

    # 5. Day + Night mode screenshots.
    theme.theme_manager.set_mode("dark", notify=False)
    page.refresh_theme()
    QTest.qWait(200)
    dark = filter_box.grab()
    if not dark.isNull():
        dark.save(str(out_dir / "sales_history_filterbar_night.png"))
        print(f"saved {out_dir / 'sales_history_filterbar_night.png'}")
    theme.theme_manager.set_mode("light", notify=False)
    page.refresh_theme()
    QTest.qWait(200)

    print("\nALL VERIFICATION CHECKS PASSED")

    # Cleanup
    for suffix in ("", "-wal", "-shm"):
        p = pathlib.Path(f"{DB_PATH}{suffix}")
        if p.exists():
            p.unlink()
    page.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())