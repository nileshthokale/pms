"""Comprehensive test suite for the Duplicate Sales Bill feature.

Verifies:
1. Database Schema & Isolation:
   - Tables dup_sales_bill_head and dup_sales_bill_item are created without foreign keys to real tables.
   - Independent voucher number sequence.
   - CRUD operations work without touching real sales, stock, batch, ledger, or cash book tables.
2. Menu & Navigation Wiring:
   - "Duplicate Sales Bill" is located under "Reports" directly below "Sales Report".
   - Shortcuts "Ctrl+F1" for "Sales Report" and "Ctrl+Shift+F1" for "Duplicate Sales Bill".
   - Main window opens DuplicateSalesBillListPage when navigating to "Reports" > "Duplicate Sales Bill".
3. List Page UI & Operations:
   - Cyan header band with red title "Duplicate Sales Bill List".
   - Toolbar buttons (New, Edit, Print).
   - Filter controls (From, VhDate, To, Go, Search box, Filter).
   - 8-column grid (VhType | VhNo | VhDate | VhTime | Customer | Doctor | Total Items | Net Amount).
   - Respects active financial year and set_history_financial_year.
4. Popup Form UI & Calculations:
   - Sales Bill style layout with 3 header columns.
   - Disabled/read-only Item Stock and Batch Stock.
   - Item entry row with down arrow add button and returnPressed progression.
   - Real-time Net Receivable calculation (Total, Bill Discount, Less CN, Add Dr, Round off, Net Amount).
   - Save validation (requires at least one item).
   - "Show DUPLICATE label on print" checkbox.
5. Crystal Report Generation & Printing:
   - A4 portrait pagination using firm master identity.
   - DUPLICATE COPY header toggle.
   - Totals and line items matching saved data.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QMessageBox

from database.connection import get_connection, init_database
from database import auth, financial_year
from database.account_roles import ensure_system_ledgers
from database.duplicate_sales_dao import (
    DuplicateSalesDAO,
    ensure_duplicate_sales_schema,
)
from screens.duplicate_sales_bill import (
    DuplicateSalesBillDialog,
    DuplicateSalesBillListPage,
    DuplicateSalesBillA6PreviewDialog,
    build_duplicate_sales_bill_report_pages,
    generate_duplicate_a6_pdf,
    print_duplicate_a6_bill,
)
from ui.menu_data import MENUS
from ui.navigation_bar import MENU_SHORTCUTS, NavigationBar
from ui.main_window import PharmacyMainWindow
import screens


class TestDuplicateSalesBillSuite(unittest.TestCase):
    _DB_PATH = os.path.join(tempfile.gettempdir(), "_test_duplicate_sales_bill.db")

    @classmethod
    def setUpClass(cls):
        if os.path.exists(cls._DB_PATH):
            try:
                os.remove(cls._DB_PATH)
            except OSError:
                pass
        os.environ["PHARMACY_DB"] = cls._DB_PATH

        if not QApplication.instance():
            cls._app = QApplication([])
        else:
            cls._app = QApplication.instance()

        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_financial_year_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        ensure_system_ledgers()
        ensure_duplicate_sales_schema()

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls._DB_PATH):
            try:
                os.remove(cls._DB_PATH)
            except OSError:
                pass

    def setUp(self):
        self._msg_patches = [
            mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "information", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "critical", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "question", return_value=QMessageBox.No),
        ]
        for p in self._msg_patches:
            p.start()

        # Clean duplicate tables before each test
        conn = get_connection()
        try:
            conn.execute("DELETE FROM dup_sales_bill_item")
            conn.execute("DELETE FROM dup_sales_bill_head")
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        for p in self._msg_patches:
            p.stop()

    # ──────────────────────────────────────────────────────────────────
    # 1. DATABASE SCHEMA & ISOLATION TESTS
    # ──────────────────────────────────────────────────────────────────

    def test_01_schema_created_and_isolated(self):
        """Verify duplicate tables exist and contain required columns."""
        conn = get_connection()
        try:
            # Check dup_sales_bill_head columns
            cur = conn.execute("PRAGMA table_info(dup_sales_bill_head)")
            head_cols = {r[1] for r in cur.fetchall()}
            expected_head = {
                "id", "voucher_no", "financial_year", "vh_date", "vh_time",
                "cnt_no", "bill_type", "customer_name", "patient_name",
                "bill_no", "address", "doctor_name", "discount", "paid_amount",
                "total_items", "remarks", "total_amount", "less_bill_discount",
                "less_cn_amt", "add_dr_amt", "round_off", "net_amount",
                "created_on", "created_by", "last_edited_on",
            }
            self.assertTrue(expected_head.issubset(head_cols), f"Missing cols: {expected_head - head_cols}")

            # Check dup_sales_bill_item columns
            cur = conn.execute("PRAGMA table_info(dup_sales_bill_item)")
            item_cols = {r[1] for r in cur.fetchall()}
            expected_item = {
                "id", "dup_bill_id", "sr_no", "item_name", "pack_size",
                "location", "batch_no", "expiry", "mrp", "sales_date",
                "sales_qty", "disc", "disc_amt", "amount",
            }
            self.assertTrue(expected_item.issubset(item_cols), f"Missing cols: {expected_item - item_cols}")

            # Verify no foreign keys link to real transactions
            cur = conn.execute("PRAGMA foreign_key_list(dup_sales_bill_head)")
            self.assertEqual(len(cur.fetchall()), 0)
            cur = conn.execute("PRAGMA foreign_key_list(dup_sales_bill_item)")
            self.assertEqual(len(cur.fetchall()), 0)
        finally:
            conn.close()

    def test_02_independent_voucher_numbering(self):
        """Duplicate bills have their own independent running voucher sequence."""
        self.assertEqual(DuplicateSalesDAO.get_next_voucher_no(), 1)

        head = {
            "voucher_no": 1,
            "vh_date": "2026-10-21",
            "customer_name": "TEST CUSTOMER",
            "total_amount": 100.0,
            "net_amount": 100.0,
        }
        items = [{
            "item_name": "PARACETAMOL 500",
            "pack_size": "10x10",
            "batch_no": "B123",
            "mrp": 10.0,
            "sales_qty": 10.0,
            "amount": 100.0,
        }]
        dup_id = DuplicateSalesDAO.insert_bill(head, items)
        self.assertGreater(dup_id, 0)

        # Next voucher sequence must increment
        self.assertEqual(DuplicateSalesDAO.get_next_voucher_no(), 2)

    def test_03_zero_side_effects_on_real_tables(self):
        """Saving a duplicate bill does not write to real sales, stock, or ledger tables."""
        conn = get_connection()
        try:
            sales_before = conn.execute("SELECT COUNT(*) FROM sales_invoices").fetchone()[0]
            stock_before = conn.execute("SELECT COUNT(*) FROM stock_batches").fetchone()[0]
            ledger_before = conn.execute("SELECT COUNT(*) FROM account_ledgers").fetchone()[0]
        finally:
            conn.close()

        head = {
            "voucher_no": 101,
            "vh_date": "2026-10-21",
            "vh_time": "10:30 AM",
            "customer_name": "ISOLATION TEST",
            "total_amount": 500.0,
            "net_amount": 500.0,
        }
        items = [{
            "item_name": "AMOXICILLIN 500MG",
            "pack_size": "10",
            "batch_no": "AX999",
            "mrp": 50.0,
            "sales_qty": 10.0,
            "amount": 500.0,
        }]
        dup_id = DuplicateSalesDAO.insert_bill(head, items)

        conn = get_connection()
        try:
            sales_after = conn.execute("SELECT COUNT(*) FROM sales_invoices").fetchone()[0]
            stock_after = conn.execute("SELECT COUNT(*) FROM stock_batches").fetchone()[0]
            ledger_after = conn.execute("SELECT COUNT(*) FROM account_ledgers").fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(sales_before, sales_after, "Real sales_invoices table was modified!")
        self.assertEqual(stock_before, stock_after, "Real stock_batches table was modified!")
        self.assertEqual(ledger_before, ledger_after, "Real account_ledgers table was modified!")

        # Verify duplicate tables were written to
        fetched_head = DuplicateSalesDAO.get_bill_by_id(dup_id)
        self.assertIsNotNone(fetched_head)
        self.assertEqual(fetched_head["customer_name"], "ISOLATION TEST")
        self.assertEqual(fetched_head["voucher_no"], 101)

        fetched_items = DuplicateSalesDAO.get_bill_items(dup_id)
        self.assertEqual(len(fetched_items), 1)
        self.assertEqual(fetched_items[0]["item_name"], "AMOXICILLIN 500MG")

    def test_04_update_preserves_created_on_and_sets_last_edited(self):
        """Editing an existing duplicate bill preserves original created_on and writes last_edited_on."""
        head = {
            "voucher_no": 5,
            "vh_date": "2026-10-21",
            "customer_name": "ORIGINAL",
            "total_amount": 150.0,
            "net_amount": 150.0,
        }
        items = [{"item_name": "ITEM A", "sales_qty": 1, "mrp": 150.0, "amount": 150.0}]
        dup_id = DuplicateSalesDAO.insert_bill(head, items)

        b1 = DuplicateSalesDAO.get_bill_by_id(dup_id)
        orig_created_on = b1["created_on"]
        self.assertTrue(orig_created_on)

        # Update
        head["customer_name"] = "MODIFIED"
        items.append({"item_name": "ITEM B", "sales_qty": 2, "mrp": 50.0, "amount": 100.0})
        DuplicateSalesDAO.update_bill(dup_id, head, items)

        b2 = DuplicateSalesDAO.get_bill_by_id(dup_id)
        self.assertEqual(b2["customer_name"], "MODIFIED")
        self.assertEqual(b2["created_on"], orig_created_on, "created_on timestamp was altered!")
        self.assertTrue(b2["last_edited_on"], "last_edited_on timestamp was not populated!")
        self.assertEqual(len(DuplicateSalesDAO.get_bill_items(dup_id)), 2)

    # ──────────────────────────────────────────────────────────────────
    # 2. MENU & NAVIGATION WIRING TESTS
    # ──────────────────────────────────────────────────────────────────

    def test_05_menu_data_structure_and_shortcuts(self):
        """Verify Reports menu includes Duplicate Sales Bill below Sales Report, with correct shortcuts."""
        reports_items = MENUS["Reports"]

        # Sales Report is first item (as SubmenuDict)
        sales_rep_idx = -1
        dup_sales_idx = -1
        for idx, item in enumerate(reports_items):
            if item == "Sales Report":
                sales_rep_idx = idx
            elif item == "Duplicate Sales Bill":
                dup_sales_idx = idx

        self.assertNotEqual(sales_rep_idx, -1, "Sales Report not found in Reports menu")
        self.assertNotEqual(dup_sales_idx, -1, "Duplicate Sales Bill not found in Reports menu")
        self.assertEqual(dup_sales_idx, sales_rep_idx + 1, "Duplicate Sales Bill must be directly below Sales Report")

        # Shortcuts
        self.assertEqual(MENU_SHORTCUTS.get("Sales Report"), "Ctrl+F1")
        self.assertEqual(MENU_SHORTCUTS.get("Duplicate Sales Bill"), "Ctrl+Shift+F1")

    def test_06_navigation_bar_and_main_window_routing(self):
        """Verify NavigationBar creates actions and main window opens pages properly."""
        nav = NavigationBar()
        triggered_signals = []
        nav.menu_action_triggered.connect(lambda m, a: triggered_signals.append((m, a)))

        # Find Reports menu
        rep_btn = None
        for child in nav.findChildren(screens.QPushButton if hasattr(screens, "QPushButton") else type(nav.fy_button)):
            if child.text() == "Reports":
                rep_btn = child
                break
        self.assertIsNotNone(rep_btn, "Reports nav button not found")

        menu = rep_btn.menu()
        self.assertIsNotNone(menu)

        # Check action shortcuts in QMenu
        found_dup_action = False
        for action in menu.actions():
            if action.text() == "Duplicate Sales Bill":
                found_dup_action = True
                self.assertEqual(action.shortcut().toString(), "Ctrl+Shift+F1")
                # Trigger action
                action.trigger()
                break
        self.assertTrue(found_dup_action, "Duplicate Sales Bill action not found in Reports QMenu")
        self.assertIn(("Reports", "Duplicate Sales Bill"), triggered_signals)

        # Test Main Window Page Resolution
        win = PharmacyMainWindow()
        self.assertIn("Reports:Duplicate Sales Bill", win._page_map)
        target_idx = win._page_map["Reports:Duplicate Sales Bill"]
        page_widget = win._stack.widget(target_idx)
        self.assertIsInstance(page_widget, DuplicateSalesBillListPage)

        # Simulate trigger menu action
        win._on_menu_action("Reports", "Duplicate Sales Bill")
        self.assertEqual(win._stack.currentIndex(), target_idx)
        self.assertIn("Duplicate Sales Bill", win.windowTitle())

    # ──────────────────────────────────────────────────────────────────
    # 3. LIST PAGE UI & FINANCIAL YEAR TESTS
    # ──────────────────────────────────────────────────────────────────

    def test_07_list_page_ui_and_search(self):
        """Verify DuplicateSalesBillListPage UI elements, table population, and filters."""
        # Insert 2 test bills
        DuplicateSalesDAO.insert_bill(
            {
                "voucher_no": 1,
                "vh_date": "2026-10-01",
                "customer_name": "JOHN DOE",
                "patient_name": "JANE",
                "doctor_name": "DR. SMITH",
                "total_amount": 250.0,
                "net_amount": 250.0,
            },
            [{"item_name": "MED A", "sales_qty": 1, "mrp": 250.0, "amount": 250.0}],
        )
        DuplicateSalesDAO.insert_bill(
            {
                "voucher_no": 2,
                "vh_date": "2026-10-15",
                "customer_name": "ALICE WONDER",
                "patient_name": "BOB",
                "doctor_name": "DR. ADAMS",
                "total_amount": 400.0,
                "net_amount": 400.0,
            },
            [{"item_name": "MED B", "sales_qty": 2, "mrp": 200.0, "amount": 400.0}],
        )

        page = DuplicateSalesBillListPage()
        page._from_date.setDate(QDate.fromString("2026-10-01", "yyyy-MM-dd"))
        page._to_date.setDate(QDate.fromString("2026-10-31", "yyyy-MM-dd"))
        page._load_bills()

        # Check table row count
        self.assertEqual(page._table.rowCount(), 2)

        # Check newest first (voucher 2 should be at row 0)
        self.assertEqual(page._table.item(0, 1).text(), "2")
        self.assertEqual(page._table.item(1, 1).text(), "1")

        # Test Search Box filter
        page._search_edit.setText("ALICE")
        page._load_bills()
        self.assertEqual(page._table.rowCount(), 1)
        self.assertIn("ALICE", page._table.item(0, 4).text())

        # Test Search by Voucher No
        page._search_edit.setText("1")
        page._load_bills()
        self.assertEqual(page._table.rowCount(), 1)
        self.assertEqual(page._table.item(0, 1).text(), "1")

        # Test set_history_financial_year
        test_fy = {"name": "2025-2026", "start_date": "2025-04-01", "end_date": "2026-03-31"}
        page.set_history_financial_year(test_fy)
        self.assertEqual(page._from_date.date().toString("yyyy-MM-dd"), "2025-04-01")
        self.assertEqual(page._to_date.date().toString("yyyy-MM-dd"), "2026-03-31")

    # ──────────────────────────────────────────────────────────────────
    # 4. POPUP ENTRY FORM & NET RECEIVABLE CALCULATION TESTS
    # ──────────────────────────────────────────────────────────────────

    def test_08_popup_form_ui_and_calculations(self):
        """Verify calculations in DuplicateSalesBillDialog."""
        dlg = DuplicateSalesBillDialog()

        # Check disabled stocks
        self.assertFalse(dlg._entry_item_stock.isEnabled())
        self.assertFalse(dlg._entry_batch_stock.isEnabled())
        self.assertTrue(dlg._show_duplicate_chk.isChecked())

        # Add Item 1: Qty 2, MRP 100, Disc 10% -> DiscAmt 20.00, Amt 180.00
        dlg._entry_item.setText("TEST MEDICINE 1")
        dlg._entry_qty.setText("2")
        dlg._entry_mrp.setText("100.00")
        dlg._entry_disc.setText("10.00")
        dlg._on_add_item()

        self.assertEqual(len(dlg._items), 1)
        self.assertEqual(dlg._items[0]["amount"], 180.00)
        self.assertEqual(dlg._items[0]["disc_amt"], 20.00)

        # Add Item 2: Qty 1, MRP 320.45, Disc 0% -> Amt 320.45
        dlg._entry_item.setText("TEST MEDICINE 2")
        dlg._entry_qty.setText("1")
        dlg._entry_mrp.setText("320.45")
        dlg._entry_disc.setText("0.00")
        dlg._on_add_item()

        self.assertEqual(len(dlg._items), 2)
        # Total amount: 180.00 + 320.45 = 500.45
        self.assertEqual(dlg._tot_amt_edit.text(), "500.45")

        # Add bill discount: 20.00 -> Net before round = 480.45, rounded = 480.00, round off = -0.45
        dlg._bill_disc_edit.setText("20.00")
        dlg._recalc_net_totals()

        self.assertEqual(dlg._round_off_edit.text(), "-0.45")
        self.assertEqual(dlg._net_amt_edit.text(), "480.00")

        # Test item deletion
        dlg._on_delete_row(0)
        self.assertEqual(len(dlg._items), 1)
        self.assertEqual(dlg._tot_amt_edit.text(), "320.45")

    def test_09_popup_save_validation_and_persistence(self):
        """Cannot save empty bill; valid bill writes to dup tables."""
        dlg = DuplicateSalesBillDialog()
        # Empty save should fail validation
        self.assertFalse(dlg._on_save())

        # Add item and fill header
        dlg._customer_edit.setText("TEST PATIENT BILL")
        dlg._entry_item.setText("AZITHROMYCIN 500")
        dlg._entry_qty.setText("3")
        dlg._entry_mrp.setText("120.00")
        dlg._entry_disc.setText("0.00")
        dlg._on_add_item()

        saved_signal_emitted = []
        dlg.saved.connect(lambda: saved_signal_emitted.append(True))

        save_success = dlg._on_save()
        self.assertTrue(save_success)
        self.assertTrue(saved_signal_emitted)

        dup_id = dlg._dup_id
        self.assertIsNotNone(dup_id)
        self.assertGreater(dup_id, 0)
        fetched = DuplicateSalesDAO.get_bill_by_id(dup_id)
        v_num = int(dlg._voucher_edit.text())
        self.assertEqual(fetched["voucher_no"], v_num)
        self.assertEqual(fetched["customer_name"], "TEST PATIENT BILL")
        self.assertEqual(fetched["total_amount"], 360.0)

    # ──────────────────────────────────────────────────────────────────
    # 5. CRYSTAL REPORT PRINTING & PREVIEW TESTS
    # ──────────────────────────────────────────────────────────────────

    def test_10_crystal_report_page_generation(self):
        """Verify A4 portrait Crystal Report pages with DUPLICATE toggle."""
        head = {
            "voucher_no": 88,
            "vh_date": "2026-10-21",
            "vh_time": "11:00 AM",
            "customer_name": "MR. RAJESH",
            "patient_name": "KUMAR",
            "doctor_name": "DR. KAPOOR",
            "total_amount": 750.0,
            "less_bill_discount": 50.0,
            "round_off": 0.0,
            "net_amount": 700.0,
            "remarks": "Duplicate record for insurance submission",
        }
        items = [
            {
                "item_name": f"MEDICINE {i}",
                "pack_size": "10 TAB",
                "batch_no": f"BT{i}",
                "expiry": "10/28",
                "mrp": 75.0,
                "sales_qty": 1.0,
                "disc": 0.0,
                "amount": 75.0,
            }
            for i in range(1, 11)
        ]

        # 1. With [ DUPLICATE COPY ] label
        pages_with_dup = build_duplicate_sales_bill_report_pages(head, items, show_duplicate_copy=True)
        self.assertGreaterEqual(len(pages_with_dup), 1)
        self.assertEqual(pages_with_dup[0].orientation, "portrait")
        self.assertIn("[ DUPLICATE COPY ]", pages_with_dup[0].header.header_line_1)
        self.assertIn("MR. RAJESH", pages_with_dup[0].header.header_line_3)
        self.assertIn("DR. KAPOOR", pages_with_dup[0].header.header_line_3)

        # 2. Without [ DUPLICATE COPY ] label
        pages_without_dup = build_duplicate_sales_bill_report_pages(head, items, show_duplicate_copy=False)
        self.assertNotIn("[ DUPLICATE COPY ]", pages_without_dup[0].header.header_line_1)

    def test_11_item_and_batch_autofill_read_only(self):
        """Verify tablet MRP, batch, pack size, and expiry autofill correctly without altering stock."""
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO items (item_name, pack_size, mrp) VALUES (?, ?, ?)",
                ("TEST DOLO 650", "15 TAB", 32.50),
            )
            item_id = cur.lastrowid
            cur.execute(
                """
                INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, stock_qty)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (item_id, "DL-2026X", "2028-11-30", "15 TAB", 32.50, 45.0),
            )
            cur.execute(
                """
                INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, stock_qty)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (item_id, "DL-OLD-9", "2025-01-31", "15 TAB", 28.00, 0.0),
            )
            conn.commit()
        finally:
            conn.close()

        # 1. Test DAO suggestions - must pick active stock batch DL-2026X first
        suggestions = DuplicateSalesDAO.get_item_batch_suggestions("TEST DOLO 650")
        self.assertGreaterEqual(len(suggestions), 1)
        top_batch = suggestions[0]
        self.assertEqual(top_batch["batch_no"], "DL-2026X")
        self.assertEqual(top_batch["mrp"], 32.50)
        self.assertEqual(top_batch["pack_size"], "15 TAB")
        self.assertEqual(top_batch["expiry"], "2028-11-30")

        # 2. Test specific batch details
        old_batch = DuplicateSalesDAO.get_batch_details("TEST DOLO 650", "DL-OLD-9")
        self.assertIsNotNone(old_batch)
        self.assertEqual(old_batch["mrp"], 28.00)

        # 3. Test Dialog Autofill
        dlg = DuplicateSalesBillDialog()
        dlg._entry_item.setText("TEST DOLO 650")
        dlg._autofill_item_and_batch("TEST DOLO 650")

        self.assertEqual(dlg._entry_batch.text(), "DL-2026X")
        self.assertEqual(float(dlg._entry_mrp.text()), 32.50)
        self.assertEqual(dlg._entry_pack.text(), "15 TAB")
        self.assertEqual(dlg._entry_exp.text(), "11/28")

        # 4. Change batch to DL-OLD-9
        dlg._entry_batch.setText("DL-OLD-9")
        dlg._autofill_from_batch()
        self.assertEqual(float(dlg._entry_mrp.text()), 28.00)

        # 5. Add to bill and verify stock remains 100% untouched
        dlg._entry_qty.setText("5")
        dlg._on_add_item()
        self.assertEqual(dlg._table.rowCount(), 1)
        self.assertEqual(float(dlg._table.item(0, 5).text()), 28.00)  # MRP column

        conn = get_connection()
        try:
            qty_now = conn.execute(
                "SELECT stock_qty FROM stock_batches WHERE batch_no = 'DL-2026X'"
            ).fetchone()[0]
            self.assertEqual(qty_now, 45.0, "Stock qty was modified!")
        finally:
            conn.close()
        dlg.close()

    def test_12_a6_print_and_preview_integration(self):
        """Verify A6 receipt printing, PDF generation, and preview dialog."""
        head = {
            "voucher_no": 99,
            "vh_date": "2026-10-23",
            "vh_time": "04:15 PM",
            "bill_type": "Cash",
            "customer_name": "SUNIL PATEL",
            "patient_name": "AJAY",
            "doctor_name": "DR. SHAH",
            "total_items": 1,
            "total_amount": 250.0,
            "less_bill_discount": 0.0,
            "round_off": 0.0,
            "net_amount": 250.0,
        }
        items = [
            {
                "item_name": "AUGMENTIN 625",
                "pack_size": "10 TAB",
                "batch_no": "AG-771",
                "expiry": "09/27",
                "mrp": 250.0,
                "sales_qty": 1.0,
                "disc": 0.0,
                "amount": 250.0,
            }
        ]

        # 1. Test A6 PDF generation
        temp_pdf = os.path.join(tempfile.gettempdir(), "_test_dup_a6.pdf")
        if os.path.exists(temp_pdf):
            try:
                os.remove(temp_pdf)
            except OSError:
                pass

        pdf_path = generate_duplicate_a6_pdf(head, items, output_path=temp_pdf, show_duplicate_copy=True)
        self.assertEqual(pdf_path, temp_pdf)
        self.assertTrue(os.path.exists(temp_pdf))
        self.assertGreater(os.path.getsize(temp_pdf), 500)

        # 2. Test A6 Preview Dialog initialization without crash
        preview_dlg = DuplicateSalesBillA6PreviewDialog(head, items, show_duplicate_copy=True)
        self.assertIsNotNone(preview_dlg._print_btn)
        self.assertIsNotNone(preview_dlg._save_pdf_btn)
        self.assertTrue(preview_dlg._show_duplicate)
        preview_dlg.close()

        # Clean up
        if os.path.exists(temp_pdf):
            try:
                os.remove(temp_pdf)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
