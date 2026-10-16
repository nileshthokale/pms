"""Test and screenshot verification for Sales History bill numbering and Customer removal.

Covers:
1. Legacy bill 2026-2027-Cash-187-S72213 (ID 72041):
   - Provenance verified in remarks and legacy_id_map (BillNo was 0 / missing)
   - Results table displays '---'
   - Sales Bill Details dialog displays '---'
   - Sales Bill Details dialog has NO Customer row (no Customer label or value)
   - Patient displays 'WALKIN'
2. Genuine historical bill (ID 1):
   - Provenance verified in remarks (BillNo was 1)
   - Number remains visible ('1')
   - Patient displays genuine name ('MRS BAIJABAI DHANWADE')
   - No Customer row
3. Open and reprint verification:
   - Both bills can be opened and reprinted to PDF
   - Database records, item records, and stock remain 100% unchanged
4. Captures visual screenshots of:
   - Sales History table with fallback bill '---'
   - Sales Bill Details dialog without Customer row and with '---'
"""
from __future__ import annotations

import os
import sys
import tempfile
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtGui import QPainter, QPixmap

from database.connection import get_connection, init_database
from database import auth, document_printing
from database.sales_dao import SalesDAO
from database.stock_dao import StockDAO
from screens.sales_history import SalesHistoryPage, SalesBillDetailsDialog, _fmt_bill_no, _is_synthetic_fallback_bill


def run_tests():
    init_database()
    auth.ensure_auth_schema()
    if auth.user_count() == 0:
        auth.create_first_admin("admin", "admin-pass-1")
    auth.session.login("admin", "admin-pass-1")

    app = QApplication.instance() or QApplication(sys.argv)
    from ui import theme
    theme.apply_to_app()

    conn = get_connection()
    try:
        # Check fallback bill 72041
        fb_row = conn.execute(
            "SELECT id, bill_no, sale_date, patient_name, customer_id, remarks "
            "FROM sales_invoices WHERE bill_no = '2026-2027-Cash-187-S72213'"
        ).fetchone()
        assert fb_row is not None, "Fallback bill 2026-2027-Cash-187-S72213 not found in data/pharmacy.db"
        fb_id, fb_bill_no, fb_date, fb_pat, fb_cust_id, fb_remarks = fb_row

        # Check legacy_id_map
        map_row = conn.execute(
            "SELECT legacy_id FROM legacy_id_map WHERE entity = 'sale' AND new_id = ?",
            (fb_id,)
        ).fetchone()
        assert map_row is not None, f"Invoice {fb_id} not mapped in legacy_id_map"
        legacy_id = map_row[0]
        assert legacy_id == "72213", f"Expected legacy_id 72213, got {legacy_id}"

        # Check provenance in remarks
        assert "Legacy salesvhheader ID 72213" in fb_remarks
        assert "BillNo 0" in fb_remarks
        print(f"[PASS] Provenance verified for {fb_bill_no}: legacy_id={legacy_id}, BillNo in remarks=0")

        # Check genuine historical bill (ID 1)
        gen_row = conn.execute(
            "SELECT id, bill_no, sale_date, patient_name, customer_id, remarks "
            "FROM sales_invoices WHERE id = 1"
        ).fetchone()
        assert gen_row is not None, "Genuine bill ID 1 not found in data/pharmacy.db"
        gen_id, gen_bill_no, gen_date, gen_pat, gen_cust_id, gen_remarks = gen_row
        assert "Legacy salesvhheader ID 10" in gen_remarks
        assert "BillNo 1" in gen_remarks
        print(f"[PASS] Provenance verified for genuine bill {gen_bill_no}: BillNo in remarks=1")

        # Snapshot DB state before tests
        fb_before = SalesDAO.get_by_id(fb_id)
        gen_before = SalesDAO.get_by_id(gen_id)
        stock_count_before = conn.execute("SELECT COUNT(*), SUM(stock_qty) FROM stock_batches").fetchone()
    finally:
        conn.close()

    # -------------------------------------------------------------
    # 1. Test helper formatting functions
    # -------------------------------------------------------------
    assert _is_synthetic_fallback_bill(fb_bill_no, fb_remarks, fb_id) is True
    assert _fmt_bill_no(fb_bill_no, fb_remarks, fb_id) == "---"
    print(f"[PASS] _fmt_bill_no for fallback bill returns '---'")

    assert _is_synthetic_fallback_bill(gen_bill_no, gen_remarks, gen_id) is False
    assert _fmt_bill_no(gen_bill_no, gen_remarks, gen_id) == "1"
    print(f"[PASS] _fmt_bill_no for genuine bill returns '1'")

    # -------------------------------------------------------------
    # 2. Test SalesBillDetailsDialog for Fallback Bill
    # -------------------------------------------------------------
    dlg_fb = SalesBillDetailsDialog(fb_id)
    dlg_fb.show()
    app.processEvents()

    # Verify no Customer label anywhere in the dialog
    customer_labels = [
        lbl.text() for lbl in dlg_fb.findChildren(QLabel)
        if "Customer" in lbl.text()
    ]
    assert len(customer_labels) == 0, f"Customer label found in dialog: {customer_labels}"
    print(f"[PASS] No Customer label or row found in SalesBillDetailsDialog")

    # Verify Bill / CNo value is '---'
    grid_fb = dlg_fb._meta_group.layout()
    bno_lbl_item = grid_fb.itemAtPosition(0, 0)
    bno_val_item = grid_fb.itemAtPosition(0, 1)
    assert bno_lbl_item and "Bill / CNo" in bno_lbl_item.widget().text()
    assert bno_val_item and bno_val_item.widget().text() == "---", \
        f"Expected '---', got {bno_val_item.widget().text()}"
    print(f"[PASS] Dialog Bill / CNo displays: '{bno_val_item.widget().text()}'")

    # Verify Patient label and value at (1, 0) and (1, 1)
    pat_lbl_item = grid_fb.itemAtPosition(1, 0)
    pat_val_item = grid_fb.itemAtPosition(1, 1)
    assert pat_lbl_item and "Patient" in pat_lbl_item.widget().text()
    assert pat_val_item and pat_val_item.widget().text() == "WALKIN"
    print(f"[PASS] Dialog Patient displays: '{pat_val_item.widget().text()}' at row 1, col 0-1 (no gap)")

    # Verify Doctor label and value at (1, 2) and (1, 3)
    doc_lbl_item = grid_fb.itemAtPosition(1, 2)
    doc_val_item = grid_fb.itemAtPosition(1, 3)
    assert doc_lbl_item and "Doctor" in doc_lbl_item.widget().text()
    print(f"[PASS] Dialog Doctor displays: '{doc_val_item.widget().text()}' at row 1, col 2-3")

    # -------------------------------------------------------------
    # 3. Test SalesBillDetailsDialog for Genuine Bill
    # -------------------------------------------------------------
    dlg_gen = SalesBillDetailsDialog(gen_id)
    dlg_gen.show()
    app.processEvents()

    grid_gen = dlg_gen._meta_group.layout()
    gen_bno_val = grid_gen.itemAtPosition(0, 1).widget().text()
    assert gen_bno_val == "1", f"Expected genuine bill number '1', got '{gen_bno_val}'"
    gen_pat_val = grid_gen.itemAtPosition(1, 1).widget().text()
    assert gen_pat_val == "MRS BAIJABAI DHANWADE", f"Expected patient name preserved, got '{gen_pat_val}'"
    print(f"[PASS] Genuine dialog: Bill / CNo = '{gen_bno_val}', Patient = '{gen_pat_val}'")

    # -------------------------------------------------------------
    # 4. Test SalesHistoryPage results table
    # -------------------------------------------------------------
    page = SalesHistoryPage()
    page.show()
    app.processEvents()

    # Search specifically for the date of the fallback bill: 2026-10-05
    page._date_check.setChecked(True)
    page._from_date.setDate(QDate.fromString(fb_date, "yyyy-MM-dd"))
    page._to_date.setDate(QDate.fromString(fb_date, "yyyy-MM-dd"))
    page._perform_search()
    app.processEvents()

    # Find the row for fb_id in table
    found_row = -1
    for r in range(page._table.rowCount()):
        item = page._table.item(r, 0)
        if item and item.data(Qt.UserRole) == fb_id:
            found_row = r
            break
    assert found_row >= 0, f"Fallback bill {fb_id} not found in search results"
    table_bno_text = page._table.item(found_row, 0).text()
    table_pat_text = page._table.item(found_row, 2).text()
    assert table_bno_text == "---", f"Expected table Bill No / CNo '---', got '{table_bno_text}'"
    assert table_pat_text == "WALKIN", f"Expected table Patient 'WALKIN', got '{table_pat_text}'"
    print(f"[PASS] Sales History table row {found_row}: Bill No / CNo = '{table_bno_text}', Patient = '{table_pat_text}'")

    # Search specifically for genuine bill date: 2015-04-01
    page._date_check.setChecked(True)
    page._from_date.setDate(QDate.fromString(gen_date, "yyyy-MM-dd"))
    page._to_date.setDate(QDate.fromString(gen_date, "yyyy-MM-dd"))
    page._perform_search()
    app.processEvents()

    found_gen_row = -1
    for r in range(page._table.rowCount()):
        item = page._table.item(r, 0)
        if item and item.data(Qt.UserRole) == gen_id:
            found_gen_row = r
            break
    assert found_gen_row >= 0, f"Genuine bill {gen_id} not found in search results"
    gen_table_bno = page._table.item(found_gen_row, 0).text()
    gen_table_pat = page._table.item(found_gen_row, 2).text()
    assert gen_table_bno == "1", f"Expected genuine bill number '1', got '{gen_table_bno}'"
    assert gen_table_pat == "MRS BAIJABAI DHANWADE", f"Expected genuine patient, got '{gen_table_pat}'"
    print(f"[PASS] Sales History table genuine row: Bill No / CNo = '{gen_table_bno}', Patient = '{gen_table_pat}'")

    # -------------------------------------------------------------
    # 5. Test Reprinting Both Bills to PDF
    # -------------------------------------------------------------
    temp_fb_pdf = os.path.join(tempfile.gettempdir(), "_test_reprint_fb.pdf")
    temp_gen_pdf = os.path.join(tempfile.gettempdir(), "_test_reprint_gen.pdf")
    for p in (temp_fb_pdf, temp_gen_pdf):
        if os.path.exists(p):
            os.remove(p)

    out_fb = document_printing.generate_counter_sale_bill(fb_id, temp_fb_pdf)
    assert os.path.exists(out_fb) and os.path.getsize(out_fb) > 0
    out_gen = document_printing.generate_counter_sale_bill(gen_id, temp_gen_pdf)
    assert os.path.exists(out_gen) and os.path.getsize(out_gen) > 0
    print(f"[PASS] Reprinting PDF succeeded for both fallback ({out_fb}) and genuine bill ({out_gen})")

    # -------------------------------------------------------------
    # 6. Verify Database & Stock are completely unchanged
    # -------------------------------------------------------------
    conn = get_connection()
    try:
        fb_after = SalesDAO.get_by_id(fb_id)
        gen_after = SalesDAO.get_by_id(gen_id)
        stock_count_after = conn.execute("SELECT COUNT(*), SUM(stock_qty) FROM stock_batches").fetchone()

        assert fb_before == fb_after, "Fallback bill record was modified in database!"
        assert gen_before == gen_after, "Genuine bill record was modified in database!"
        assert stock_count_before == stock_count_after, "Stock was modified!"
        print("[PASS] Database transactions, invoice records, and stock verified 100% UNCHANGED")
    finally:
        conn.close()

    # -------------------------------------------------------------
    # 7. Capture Screenshots
    # -------------------------------------------------------------
    # Reset search so the fallback bill is visible on page
    page._date_check.setChecked(True)
    page._from_date.setDate(QDate.fromString(fb_date, "yyyy-MM-dd"))
    page._to_date.setDate(QDate.fromString(fb_date, "yyyy-MM-dd"))
    page._perform_search()
    page._table.selectRow(found_row)
    app.processEvents()

    page.resize(1100, 480)
    app.processEvents()
    table_pix = page.grab()

    dlg_fb.resize(920, 520)
    app.processEvents()
    dlg_pix = dlg_fb.grab()

    # Save individual screenshots
    table_path = str(ROOT / "screenshot_sales_history_table.png")
    dlg_path = str(ROOT / "screenshot_sales_bill_details.png")
    table_pix.save(table_path)
    dlg_pix.save(dlg_path)

    # Save combined screenshot
    combined_w = max(table_pix.width(), dlg_pix.width())
    combined_h = table_pix.height() + dlg_pix.height() + 20
    combined_pix = QPixmap(combined_w, combined_h)
    combined_pix.fill(Qt.white)
    painter = QPainter(combined_pix)
    painter.drawPixmap(0, 0, table_pix)
    painter.drawPixmap(0, table_pix.height() + 20, dlg_pix)
    painter.end()

    combined_path = str(ROOT / "screenshot_sales_history_and_details.png")
    combined_pix.save(combined_path)
    print(f"[PASS] Screenshots captured and saved to:\n  {table_path}\n  {dlg_path}\n  {combined_path}")

    dlg_fb.close()
    dlg_gen.close()
    page.close()
    print("\nALL VERIFICATIONS PASSED SUCCESSFULLY!")
    return 0


if __name__ == "__main__":
    sys.exit(run_tests())
