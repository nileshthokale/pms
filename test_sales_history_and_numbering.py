"""Regression tests for Sales History and Bill Numbering.

Covers the complete acceptance criteria:
1. Open and close an unsaved draft; next saved bill can use the next available sequential CNo.
2. Creating multiple drafts does not reserve permanent invoice numbers.
3. Saving multiple bills produces unique, sequential numbers according to existing numbering rules.
4. Sales → Sales History actually navigates to the dedicated history screen.
5. Daily Sales shows only the chosen day's transactions.
6. Patient/customer name search finds historical bills across financial years.
7. Date and optional FY filtering use correct inclusive boundaries.
8. Opening and reprinting an old bill makes no database or stock changes.
9. Historical invoice numbers and line-item values remain unchanged.
10. The screen works in Day and Night Mode.

Runs offscreen: QT_QPA_PLATFORM=offscreen.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication, QMessageBox

from database.connection import get_connection, init_database
from database import auth, financial_year
from database.company_dao import CompanyDAO
from database.customer_dao import CustomerDAO
from database.doctor_dao import DoctorDAO
from database.item_dao import ItemDAO
from database.purchase_dao import PurchaseDAO
from database.sales_dao import SalesDAO
from database.stock_dao import StockDAO
from database.supplier_dao import SupplierDAO
from database.unit_dao import UnitDAO
from database.account_roles import ensure_system_ledgers
from database.document_printing import generate_counter_sale_bill

from screens.counter_sale import CounterSalePage, _BillItemRow, HISTORY_FILTER_DATE
from screens.sales_history import SalesHistoryPage, SalesBillDetailsDialog
from ui.main_window import PharmacyMainWindow
from ui import theme as theme_mod


class SalesHistoryAndNumberingTests(unittest.TestCase):
    _DB_PATH = os.path.join(tempfile.gettempdir(), "_test_sales_hist_num.db")

    @classmethod
    def setUpClass(cls):
        if os.path.exists(cls._DB_PATH):
            os.remove(cls._DB_PATH)
        os.environ["PHARMACY_DB"] = cls._DB_PATH
        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_financial_year_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        ensure_system_ledgers()
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        # Clean transactional tables
        conn = get_connection()
        try:
            for tbl in (
                "ledger_transactions", "sales_invoice_items", "sales_invoices",
                "purchase_invoice_items", "purchase_invoices", "stock_batches",
                "hold_bill_items", "hold_bills", "items", "customers",
                "doctors", "suppliers", "drugs", "units", "companies", "financial_years"
            ):
                try:
                    conn.execute(f"DELETE FROM {tbl}")
                except Exception:
                    pass
            conn.commit()
        finally:
            conn.close()

        # Master setup
        financial_year.ensure_default_financial_year()
        # Create an older financial year: 2025-2026
        financial_year.create_financial_year("2025-2026", "2025-04-01", "2026-03-31", activate=False)

        self.company_id = CompanyDAO.insert("TestPharma", "TP")
        self.unit_id = UnitDAO.insert("Strip")
        self.supplier_id = SupplierDAO.insert("MainSupplier")
        self.customer_a = CustomerDAO.insert("Customer Alpha")
        self.customer_b = CustomerDAO.insert("Customer Beta")
        self.doctor_a = DoctorDAO.insert("Dr. Smith", specialty="Cardiology")
        self.doctor_b = DoctorDAO.insert("Dr. Adams", specialty="General")

        self.item_id = ItemDAO.insert(
            item_name="Amoxicillin 500mg",
            unit_id=self.unit_id,
            company_id=self.company_id,
            pack_size="10x10",
        )
        ensure_system_ledgers()

        # Seed initial stock
        PurchaseDAO.insert_invoice(
            voucher_no="PV-0001", voucher_date="2025-05-01", voucher_time="10:00",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="PINV-001", invoice_date="2025-05-01",
            invoice_net_amount=5000.0, bill_discount=0, due_date="",
            total_amount=5000.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=5000.0, round_off=0,
            net_amount=5000.0, remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": 200.0, "free_qty": 0, "batch_no": "BATCH-AMOX-01",
                "expiry": "12/28", "rate": 50.0, "mrp": 70.0,
                "discount": 0, "gst_percent": 0, "gst_amount": 0,
                "amount": 5000.0, "purchase_rate": 50.0,
                "net_rate": 50.0, "pp": 50.0
            }],
        )
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        self.assertTrue(batches)
        self.batch_id = batches[0]["id"]

        # Prevent blocking dialogs
        self._patches = [
            mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "information", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "critical", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def _pump(self, n=3):
        for _ in range(n):
            self._app.processEvents()

    # ------------------------------------------------------------------
    # Criterion 1: Open and close unsaved draft; next saved bill can use
    # next available sequential CNo (no gaps left).
    # ------------------------------------------------------------------
    def test_01_closing_unsaved_draft_leaves_no_gap(self):
        page = CounterSalePage()
        page.show()
        self._pump()
        self.addCleanup(lambda: (page.hide(), page.deleteLater()))

        # Initially next sequential bill is CS-0001
        initial_next = SalesDAO.generate_next_bill_no()
        self.assertEqual(initial_next, "CS-0001")

        # Open a new draft (+ Add Bill)
        page._on_add_bill()
        self._pump()
        self.assertEqual(len(page._open_bills), 2)

        # Close the active unsaved draft without saving
        page._cancel_active_open_bill()
        self._pump()
        self.assertEqual(len(page._open_bills), 1)

        # Ensure no invoice was inserted in DB
        self.assertEqual(len(SalesDAO.get_all()), 0)

        # Now fill panel and commit sale
        panel = page._sale_panel
        panel.customer_combo.setCurrentIndex(panel.customer_combo.findData(self.customer_a))
        panel.patient_name_edit.setText("Test Patient 1")
        panel._item_rows.clear()
        panel._item_rows.append(_BillItemRow(
            item_id=self.item_id, item_name="Amoxicillin 500mg",
            stock_batch_id=self.batch_id, pack_size="10x10", location="",
            batch_no="BATCH-AMOX-01", expiry="12/28", mrp=70.0,
            sale_qty=2.0, discount_amount=0.0, amount=140.0
        ))
        panel._refresh_table()
        panel._recalc_totals()
        panel.paid_edit.setText("140.00")
        panel._recalc_totals()

        panel._commit_sale()
        self._pump()

        # The saved bill took CS-0001 without any gap!
        saved_bills = SalesDAO.get_all()
        self.assertEqual(len(saved_bills), 1)
        self.assertEqual(saved_bills[0]["bill_no"], "CS-0001")

    # ------------------------------------------------------------------
    # Criterion 2: Creating multiple drafts does not reserve permanent
    # invoice numbers.
    # ------------------------------------------------------------------
    def test_02_multiple_drafts_do_not_reserve_permanent_numbers(self):
        page = CounterSalePage()
        page.show()
        self._pump()
        self.addCleanup(lambda: (page.hide(), page.deleteLater()))

        # Add 3 drafts
        page._on_add_bill()
        page._on_add_bill()
        page._on_add_bill()
        self._pump()
        self.assertEqual(len(page._open_bills), 4)

        # Database must still have 0 invoices
        conn = get_connection()
        try:
            cnt = conn.execute("SELECT COUNT(*) FROM sales_invoices").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(cnt, 0)

        # Next permanent number in DB is still CS-0001
        self.assertEqual(SalesDAO.generate_next_bill_no(), "CS-0001")

    # ------------------------------------------------------------------
    # Criterion 3: Saving multiple bills produces unique, sequential
    # numbers according to existing numbering rules.
    # ------------------------------------------------------------------
    def test_03_saving_multiple_bills_sequential_and_unique(self):
        page = CounterSalePage()
        page.show()
        self._pump()
        self.addCleanup(lambda: (page.hide(), page.deleteLater()))

        panel = page._sale_panel

        for i in range(1, 4):
            panel.customer_combo.setCurrentIndex(panel.customer_combo.findData(self.customer_a))
            panel.patient_name_edit.setText(f"Patient {i}")
            panel._item_rows.clear()
            panel._item_rows.append(_BillItemRow(
                item_id=self.item_id, item_name="Amoxicillin 500mg",
                stock_batch_id=self.batch_id, pack_size="10x10", location="",
                batch_no="BATCH-AMOX-01", expiry="12/28", mrp=70.0,
                sale_qty=1.0, discount_amount=0.0, amount=70.0
            ))
            panel._refresh_table()
            panel._recalc_totals()
            panel.paid_edit.setText("70.00")
            panel._recalc_totals()

            panel._commit_sale()
            self._pump()

        saved = sorted([r["bill_no"] for r in SalesDAO.get_all()])
        self.assertEqual(len(saved), 3)
        self.assertEqual(saved, ["CS-0001", "CS-0002", "CS-0003"])

    # ------------------------------------------------------------------
    # Criterion 4: Sales → Sales History navigates to the dedicated
    # history screen.
    # ------------------------------------------------------------------
    def test_04_sales_history_navigation_opens_dedicated_page(self):
        main_win = PharmacyMainWindow()
        main_win.resize(1200, 800)
        main_win.show()
        self._pump()
        self.addCleanup(lambda: (main_win.hide(), main_win.deleteLater()))

        # Trigger Sales -> Sales History menu action
        main_win._on_menu_action("Sales", "Sales History")
        self._pump()

        current_widget = main_win._stack.currentWidget()
        self.assertEqual(
            current_widget.__class__.__name__,
            "SalesHistoryPage",
            "Sales -> Sales History must navigate to dedicated SalesHistoryPage"
        )

    # ------------------------------------------------------------------
    # Criterion 5: Daily Sales shows only the chosen day's transactions.
    # ------------------------------------------------------------------
    def test_05_daily_sales_shows_only_chosen_day(self):
        # Insert sales on two different dates
        SalesDAO.insert_invoice(
            bill_no="CS-D01", sale_date="2026-10-10", sale_time="10:00",
            sale_type="Cash", customer_id=self.customer_a, patient_name="Pat Oct10",
            doctor_id=self.doctor_a, discount=0.0, paid_amount=70.0,
            total_amount=70.0, round_off=0.0, net_amount=70.0, remarks="",
            items=[{"item_id": self.item_id, "stock_batch_id": self.batch_id,
                    "pack_size": "10x10", "location": "", "batch_no": "BATCH-AMOX-01",
                    "expiry": "12/28", "mrp": 70.0, "sale_qty": 1.0,
                    "discount_amount": 0.0, "amount": 70.0}],
        )
        SalesDAO.insert_invoice(
            bill_no="CS-D02", sale_date="2026-10-12", sale_time="11:00",
            sale_type="Cash", customer_id=self.customer_a, patient_name="Pat Oct12",
            doctor_id=self.doctor_a, discount=0.0, paid_amount=70.0,
            total_amount=70.0, round_off=0.0, net_amount=70.0, remarks="",
            items=[{"item_id": self.item_id, "stock_batch_id": self.batch_id,
                    "pack_size": "10x10", "location": "", "batch_no": "BATCH-AMOX-01",
                    "expiry": "12/28", "mrp": 70.0, "sale_qty": 1.0,
                    "discount_amount": 0.0, "amount": 70.0}],
        )

        page = CounterSalePage()
        page.show()
        self._pump()
        self.addCleanup(lambda: (page.hide(), page.deleteLater()))

        # Filter to 2026-10-10
        page._hist_date.setDate(QDate.fromString("2026-10-10", "yyyy-MM-dd"))
        self._pump()

        # History table must contain only CS-D01, not CS-D02
        bill_nos = [page._hist_table.item(r, 0).text() for r in range(page._hist_table.rowCount())]
        self.assertIn("CS-D01", bill_nos)
        self.assertNotIn("CS-D02", bill_nos)

# ------------------------------------------------------------------
    # Criterion 6: Patient name search finds historical bills across
    # financial years (customer-name filter removed from the UI).
    # ------------------------------------------------------------------
    def test_06_search_patient_across_financial_years(self):
        # Bill 1 in FY 2025-2026 (date: 2025-06-15)
        SalesDAO.insert_invoice(
            bill_no="CS-2025-01", sale_date="2025-06-15", sale_time="10:00",
            sale_type="Cash", customer_id=self.customer_a, patient_name="Alice Wonderland",
            doctor_id=self.doctor_a, discount=0.0, paid_amount=70.0,
            total_amount=70.0, round_off=0.0, net_amount=70.0, remarks="",
            items=[{"item_id": self.item_id, "stock_batch_id": self.batch_id,
                    "pack_size": "10x10", "location": "", "batch_no": "BATCH-AMOX-01",
                    "expiry": "12/28", "mrp": 70.0, "sale_qty": 1.0,
                    "discount_amount": 0.0, "amount": 70.0}],
        )
        # Bill 2 in FY 2026-2027 (date: 2026-08-20)
        SalesDAO.insert_invoice(
            bill_no="CS-2026-01", sale_date="2026-08-20", sale_time="14:00",
            sale_type="Cash", customer_id=self.customer_b, patient_name="Bob Builder",
            doctor_id=self.doctor_b, discount=0.0, paid_amount=70.0,
            total_amount=70.0, round_off=0.0, net_amount=70.0, remarks="",
            items=[{"item_id": self.item_id, "stock_batch_id": self.batch_id,
                    "pack_size": "10x10", "location": "", "batch_no": "BATCH-AMOX-01",
                    "expiry": "12/28", "mrp": 70.0, "sale_qty": 1.0,
                    "discount_amount": 0.0, "amount": 70.0}],
        )

        hist_page = SalesHistoryPage()
        hist_page.show()
        self._pump()
        self.addCleanup(lambda: (hist_page.hide(), hist_page.deleteLater()))

        # Search by patient name "Alice" across all years (case-insensitive)
        hist_page._patient_edit.setText("alice")
        hist_page._perform_search()
        self._pump()

        self.assertEqual(hist_page._table.rowCount(), 1)
        self.assertEqual(hist_page._table.item(0, 0).text(), "CS-2025-01")
        self.assertEqual(hist_page._table.item(0, 3).text(), "Alice Wonderland")

        # Patient search must be partial: "bob" matches "Bob Builder"
        hist_page._patient_edit.clear()
        hist_page._patient_edit.setText("bob")
        hist_page._perform_search()
        self._pump()

        self.assertEqual(hist_page._table.rowCount(), 1)
        self.assertEqual(hist_page._table.item(0, 0).text(), "CS-2026-01")
        self.assertEqual(hist_page._table.item(0, 3).text(), "Bob Builder")

        # Clearing patient search returns every bill across all years
        hist_page._patient_edit.clear()
        hist_page._perform_search()
        self._pump()

        self.assertEqual(hist_page._table.rowCount(), 2)

    # ------------------------------------------------------------------
    # Criterion 7: Date and optional FY filtering use correct inclusive boundaries.
    # ------------------------------------------------------------------
    def test_07_financial_year_inclusive_boundaries(self):
        # 2025-04-01 (exact FY start)
        SalesDAO.insert_invoice(
            bill_no="CS-FY-START", sale_date="2025-04-01", sale_time="09:00",
            sale_type="Cash", customer_id=self.customer_a, patient_name="Start Patient",
            doctor_id=self.doctor_a, discount=0.0, paid_amount=70.0,
            total_amount=70.0, round_off=0.0, net_amount=70.0, remarks="",
            items=[{"item_id": self.item_id, "stock_batch_id": self.batch_id,
                    "pack_size": "10x10", "location": "", "batch_no": "BATCH-AMOX-01",
                    "expiry": "12/28", "mrp": 70.0, "sale_qty": 1.0,
                    "discount_amount": 0.0, "amount": 70.0}],
        )
        # 2026-03-31 (exact FY end)
        SalesDAO.insert_invoice(
            bill_no="CS-FY-END", sale_date="2026-03-31", sale_time="17:00",
            sale_type="Cash", customer_id=self.customer_a, patient_name="End Patient",
            doctor_id=self.doctor_a, discount=0.0, paid_amount=70.0,
            total_amount=70.0, round_off=0.0, net_amount=70.0, remarks="",
            items=[{"item_id": self.item_id, "stock_batch_id": self.batch_id,
                    "pack_size": "10x10", "location": "", "batch_no": "BATCH-AMOX-01",
                    "expiry": "12/28", "mrp": 70.0, "sale_qty": 1.0,
                    "discount_amount": 0.0, "amount": 70.0}],
        )
        # 2026-04-01 (next FY)
        SalesDAO.insert_invoice(
            bill_no="CS-NEXT-FY", sale_date="2026-04-01", sale_time="09:00",
            sale_type="Cash", customer_id=self.customer_a, patient_name="Next FY Patient",
            doctor_id=self.doctor_a, discount=0.0, paid_amount=70.0,
            total_amount=70.0, round_off=0.0, net_amount=70.0, remarks="",
            items=[{"item_id": self.item_id, "stock_batch_id": self.batch_id,
                    "pack_size": "10x10", "location": "", "batch_no": "BATCH-AMOX-01",
                    "expiry": "12/28", "mrp": 70.0, "sale_qty": 1.0,
                    "discount_amount": 0.0, "amount": 70.0}],
        )

        hist_page = SalesHistoryPage()
        hist_page.show()
        self._pump()
        self.addCleanup(lambda: (hist_page.hide(), hist_page.deleteLater()))

        # Select FY 2025-2026 in dropdown
        idx = -1
        for i in range(hist_page._fy_combo.count()):
            if "2025-2026" in hist_page._fy_combo.itemText(i):
                idx = i
                break
        self.assertGreater(idx, 0)
        hist_page._fy_combo.setCurrentIndex(idx)
        self._pump()

        # Both 1 April 2025 and 31 March 2026 must be included; 1 April 2026 excluded
        found_bills = [hist_page._table.item(r, 0).text() for r in range(hist_page._table.rowCount())]
        self.assertIn("CS-FY-START", found_bills)
        self.assertIn("CS-FY-END", found_bills)
        self.assertNotIn("CS-NEXT-FY", found_bills)

    # ------------------------------------------------------------------
    # Criterion 8 & 9: Opening and reprinting old bill makes NO database
    # or stock changes; historical values remain unchanged.
    # ------------------------------------------------------------------
    def test_08_reprinting_old_bill_does_not_modify_stock_or_db(self):
        inv_id = SalesDAO.insert_invoice(
            bill_no="CS-HIST-01", sale_date="2025-05-15", sale_time="10:30",
            sale_type="Cash", customer_id=self.customer_a, patient_name="Historical Patient",
            doctor_id=self.doctor_a, discount=10.0, paid_amount=130.0,
            total_amount=140.0, round_off=0.0, net_amount=130.0, remarks="Original remarks",
            items=[{"item_id": self.item_id, "stock_batch_id": self.batch_id,
                    "pack_size": "10x10", "location": "SHELF-A", "batch_no": "BATCH-AMOX-01",
                    "expiry": "12/28", "mrp": 70.0, "sale_qty": 2.0,
                    "discount_amount": 0.0, "amount": 140.0}],
        )

        # Record stock and invoice state before
        stock_before = StockDAO.get_stock_batches_for_item(self.item_id)[0]["stock_qty"]
        inv_before = SalesDAO.get_by_id(inv_id)
        items_before = SalesDAO.get_invoice_items(inv_id)

        # Open details dialog
        dlg = SalesBillDetailsDialog(inv_id)
        dlg.show()
        self._pump()
        self.addCleanup(lambda: (dlg.hide(), dlg.deleteLater()))

        # Historical values displayed accurately
        self.assertEqual(dlg._table.rowCount(), 1)
        self.assertEqual(dlg._table.item(0, 1).text(), "Amoxicillin 500mg")
        self.assertEqual(dlg._table.item(0, 4).text(), "BATCH-AMOX-01")
        self.assertEqual(dlg._table.item(0, 6).text(), "2")
        self.assertEqual(dlg._table.item(0, 9).text(), "140.00")

        # Generate reprint PDF
        temp_pdf = os.path.join(tempfile.gettempdir(), "_test_reprint.pdf")
        if os.path.exists(temp_pdf):
            os.remove(temp_pdf)
        output_path = generate_counter_sale_bill(inv_id, temp_pdf)
        self.assertTrue(os.path.exists(output_path))
        self.assertGreater(os.path.getsize(output_path), 0)

        # Verify: Stock was NOT touched
        stock_after = StockDAO.get_stock_batches_for_item(self.item_id)[0]["stock_qty"]
        self.assertEqual(stock_before, stock_after)

        # Verify: Invoice data in DB was NOT touched
        inv_after = SalesDAO.get_by_id(inv_id)
        items_after = SalesDAO.get_invoice_items(inv_id)
        self.assertEqual(inv_before, inv_after)
        self.assertEqual(items_before, items_after)

    # ------------------------------------------------------------------
    # Criterion 10: Screens work in Day and Night mode.
    # ------------------------------------------------------------------
    def test_10_day_and_night_mode_compatibility(self):
        hist_page = SalesHistoryPage()
        hist_page.show()
        self._pump()
        self.addCleanup(lambda: (hist_page.hide(), hist_page.deleteLater()))

        counter_page = CounterSalePage()
        counter_page.show()
        self._pump()
        self.addCleanup(lambda: (counter_page.hide(), counter_page.deleteLater()))

        # Toggle through dark and light themes repeatedly
        for mode in ("dark", "light", "dark", "light"):
            theme_mod.theme_manager.set_mode(mode)
            hist_page.refresh_theme()
            counter_page.refresh_theme()
            self._pump()

        # Both remain valid and responsive
        self.assertTrue(hist_page.isVisible())
        self.assertTrue(counter_page.isVisible())


if __name__ == "__main__":
    unittest.main()
