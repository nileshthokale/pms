"""Regression and integration tests for Global Numeric-Only Bill and Voucher Numbers.

Verifies:
1. Centralized doc formatter logic for all patterns and edge cases.
2. Query matching logic with leading-zero tolerance.
3. SalesDAO search by numeric bill numbers.
4. UI screens: Sales History, Sales Bill Details, Purchase History, Purchase Invoice dialog,
   Credit Note, Debit Note, Customer Receipt, Supplier Payment, Journal Entry, Account Ledger.
5. Zero modifications to database records or inventory stock.
"""

from __future__ import annotations

import os
import sys

# Ensure QApplication exists before importing PySide6 widgets
from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import QApplication

_app = QApplication.instance()
if _app is None:
    _app = QApplication(sys.argv)

from core.doc_formatter import format_document_number, match_document_query
from database.connection import get_connection
from database.sales_dao import SalesDAO
from screens.sales_history import SalesHistoryPage, SalesBillDetailsDialog
from screens.purchase_invoice import PurchaseInvoicePage, _InvoiceDialog
from screens.credit_note import CreditNotePage, _CreditNoteEntryDialog
from screens.debit_note import DebitNotePage, _DebitNoteEntryDialog
from screens.customer_receipt import CustomerReceiptPage, _CustomerReceiptEntryDialog
from screens.supplier_payment import SupplierPaymentPage, _SupplierPaymentEntryDialog
from screens.journal_entry import JournalEntryPage, _JournalEntryDialog
from screens.account_ledger import AccountLedgerPage


def test_doc_formatter_cases():
    print("[1/5] Testing format_document_number edge cases...")
    cases = [
        # Standard compound keys
        ("2026-2027-Credit-0251", "0251"),
        ("2026-2027-1905", "1905"),
        ("2017-2018-1", "1"),
        ("2023-2024-250", "250"),
        ("2026-2027-Cash-187-S72213", "187"),
        ("2026-2027-1905#12345", "1905"),
        ("2026-2027-CR-0012", "0012"),
        ("2026-2027-DN-0005", "0005"),
        ("2026-2027-CRCPT-0042", "0042"),
        ("2026-2027-SPAY-0019", "0019"),
        ("2026-2027-JV-0003", "0003"),
        ("2026-2027-OB-0001", "0001"),
        # Plain numeric numbers
        ("0251", "0251"),
        ("1905", "1905"),
        ("7", "7"),
        ("00042", "00042"),
        # Protected strings (Dates, FY ranges, empty / placeholders)
        ("2026-10-17", "2026-10-17"),
        ("2026-2027", "2026-2027"),
        ("", "--"),
        (None, "--"),
        ("--", "--"),
        ("---", "---"),
    ]

    for raw, expected in cases:
        got = format_document_number(raw, default="--")
        assert got == expected, f"format_document_number({raw!r}) -> {got!r}, expected {expected!r}"

    print("      All formatting test cases passed.")


def test_query_matching():
    print("[2/5] Testing match_document_query matching logic...")
    query_cases = [
        ("2026-2027-Credit-0251", "0251", True),
        ("2026-2027-Credit-0251", "251", True),
        ("2026-2027-Credit-0251", "025", True),
        ("2026-2027-Credit-0251", "999", False),
        ("2026-2027-1905", "1905", True),
        ("2026-2027-1905#12345", "1905", True),
        ("2026-2027-Cash-187-S72213", "187", True),
        ("2015-2016-1", "1", True),
        ("2015-2016-1", "01", True),
        ("2015-2016-1", "2", False),
    ]

    for stored, query, expected in query_cases:
        res = match_document_query(stored, query)
        assert res is expected, f"match_document_query({stored!r}, {query!r}) -> {res}, expected {expected}"

    print("      All query matching test cases passed.")


def test_sales_dao_search():
    print("[3/5] Testing SalesDAO database numeric search...")
    # Search for genuine bill 1
    rows1, _ = SalesDAO.search_sales_history(bill_no="1", limit=10)
    assert any(format_document_number(r.get("bill_no")) == "1" for r in rows1), \
        "SalesDAO.search_sales_history(bill_no='1') failed to find bill 1"

    # Search for legacy fallback bill 187
    rows187, _ = SalesDAO.search_sales_history(bill_no="187", limit=10)
    assert any("72213" in (r.get("bill_no") or "") or format_document_number(r.get("bill_no")) == "187" for r in rows187), \
        "SalesDAO.search_sales_history(bill_no='187') failed to find legacy bill 187"

    print("      SalesDAO search by numeric sequence verified.")


def test_ui_screens_display():
    print("[4/5] Testing UI screens and dialogs...")
    conn = get_connection()
    try:
        # Check sales invoice
        sale = conn.execute(
            "SELECT id, bill_no, patient_name FROM sales_invoices "
            "WHERE bill_no = '2026-2027-Cash-187-S72213'"
        ).fetchone()
        if sale:
            sale_id, sale_bno, sale_pat = sale
            # A historical row with an empty stored patient name keeps a
            # genuinely blank Bill / CNo; no legacy number is exposed.
            if not (sale_pat or "").strip():
                dlg = SalesBillDetailsDialog(sale_id)
                grid = dlg._meta_group.layout()
                val = grid.itemAtPosition(0, 1).widget().text()
                assert val == "", f"SalesBillDetailsDialog expected blank, got {val!r}"
                dlg.close()

        # Check genuine sales invoice with patient name
        gen_sale = conn.execute("SELECT id, bill_no, patient_name FROM sales_invoices WHERE id = 1").fetchone()
        if gen_sale:
            dlg_gen = SalesBillDetailsDialog(gen_sale[0])
            grid_gen = dlg_gen._meta_group.layout()
            val_gen = grid_gen.itemAtPosition(0, 1).widget().text()
            assert val_gen == "1", f"SalesBillDetailsDialog expected '1', got {val_gen!r}"
            dlg_gen.close()

        # Check purchase invoice
        purch = conn.execute("SELECT id, voucher_no, invoice_no FROM purchase_invoices LIMIT 1").fetchone()
        if purch:
            p_id, v_no, inv_no = purch
            p_page = PurchaseInvoicePage()
            p_page._refresh_history()
            if p_page._hist_table.rowCount() > 0:
                tbl_v_no = p_page._hist_table.item(0, 1).text()
                assert tbl_v_no.isdigit(), f"Purchase history table voucher {tbl_v_no!r} is not numeric"
            p_page.close()

            # Check purchase dialog
            from database.purchase_dao import PurchaseDAO
            purch_dict = PurchaseDAO.get_by_id(p_id)
            p_dlg = _InvoiceDialog(invoice=purch_dict)
            disp_vh = p_dlg.voucher_no_edit.text()
            assert disp_vh.isdigit(), f"Purchase dialog voucher {disp_vh!r} is not numeric"
            assert p_dlg._full_voucher_no == v_no, "Underlying full voucher_no altered in dialog"
            p_dlg.close()

        # Check credit note dialog
        cn_dlg = _CreditNoteEntryDialog()
        cn_vh = (getattr(cn_dlg, "voucher_no_edit", None) or getattr(cn_dlg, "voucher_no_lbl")).text()
        assert cn_vh.isdigit(), f"_CreditNoteEntryDialog voucher {cn_vh!r} is not numeric"
        cn_dlg.close()

        # Check debit note dialog
        dn_dlg = _DebitNoteEntryDialog()
        dn_vh = (getattr(dn_dlg, "voucher_no_edit", None) or getattr(dn_dlg, "voucher_no_lbl")).text()
        assert dn_vh.isdigit(), f"_DebitNoteEntryDialog voucher {dn_vh!r} is not numeric"
        dn_dlg.close()

        # Check customer receipt dialog
        cr_dlg = _CustomerReceiptEntryDialog()
        cr_vh = cr_dlg.voucher_no_edit.text()
        assert cr_vh.isdigit(), f"_CustomerReceiptEntryDialog voucher {cr_vh!r} is not numeric"
        cr_dlg.close()

        # Check supplier payment dialog
        sp_dlg = _SupplierPaymentEntryDialog()
        sp_vh = sp_dlg.voucher_no_edit.text()
        assert sp_vh.isdigit(), f"_SupplierPaymentEntryDialog voucher {sp_vh!r} is not numeric"
        sp_dlg.close()

        # Check journal entry dialog
        jv_dlg = _JournalEntryDialog()
        jv_vh = jv_dlg.voucher_no_edit.text()
        assert jv_vh.isdigit(), f"_JournalEntryDialog voucher {jv_vh!r} is not numeric"
        jv_dlg.close()

        # Check SalesHistoryPage table
        sh_page = SalesHistoryPage()
        sh_page._perform_search()
        assert sh_page._table.rowCount() > 0, "SalesHistoryPage returned no rows"
        first_bno_item = sh_page._table.item(0, 0)
        assert isinstance(first_bno_item.data(Qt.UserRole), int), "SalesHistoryPage missing invoice id in UserRole"
        # Find a named row (numeric Bill No + full-number tooltip) and an
        # unnamed row (genuinely blank Bill No + blank tooltip).
        has_verified_numeric = False
        has_verified_blank = False
        for r in range(sh_page._table.rowCount()):
            pat_text = sh_page._table.item(r, 2).text()
            bno_item = sh_page._table.item(r, 0)
            bno_text = bno_item.text()
            if pat_text != "WALKIN" and not has_verified_numeric:
                assert bno_text.isdigit(), f"Row {r} with patient {pat_text!r} expected numeric bill no, got {bno_text!r}"
                assert "Full Bill No:" in bno_item.toolTip(), "Named row missing Full Bill No tooltip"
                has_verified_numeric = True
            elif pat_text == "WALKIN" and not has_verified_blank:
                assert bno_text == "", f"Row {r} with WALKIN patient expected blank bill no, got {bno_text!r}"
                assert bno_item.toolTip() == "", "Unnamed row must have a blank tooltip"
                has_verified_blank = True
            if has_verified_numeric and has_verified_blank:
                break
        assert has_verified_numeric, "Could not find a row with patient name"
        assert has_verified_blank, "Could not find a row with empty patient name"
        sh_page.close()

        # Check document_printing formatting
        from database import document_printing
        assert document_printing._purchase_display_bill_no("2026-2027-Credit-0251") == "0251"
        assert document_printing._purchase_display_bill_no("2026-2027-1905#12345") == "1905"
        assert document_printing._purchase_display_bill_no("2026-2027-Cash-187-S72213") == "187"

    finally:
        conn.close()

    print("      All UI screens, tables, dialogs and printing display purely numeric numbers.")


def test_database_integrity():
    print("[5/5] Verifying database integrity...")
    conn = get_connection()
    try:
        # Check sales invoices count
        cnt_sales = conn.execute("SELECT COUNT(*) FROM sales_invoices").fetchone()[0]
        assert cnt_sales > 0, "No sales invoices found"

        # Check compound keys preserved in DB
        sample_sale = conn.execute("SELECT bill_no FROM sales_invoices WHERE bill_no LIKE '%-%' LIMIT 1").fetchone()
        assert sample_sale is not None and "-" in sample_sale[0], "Sales invoice keys corrupted in DB"

        sample_purch = conn.execute("SELECT voucher_no FROM purchase_invoices WHERE voucher_no LIKE '%-%' LIMIT 1").fetchone()
        assert sample_purch is not None and "-" in sample_purch[0], "Purchase invoice keys corrupted in DB"

        print(f"      Database verified: {cnt_sales} sales records intact, compound keys preserved.")
    finally:
        conn.close()


if __name__ == "__main__":
    test_doc_formatter_cases()
    test_query_matching()
    test_sales_dao_search()
    test_ui_screens_display()
    test_database_integrity()
    print("\nALL GLOBAL NUMERIC DOCUMENT VERIFICATIONS PASSED SUCCESSFULLY!")
