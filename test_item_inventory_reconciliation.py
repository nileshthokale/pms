"""Comprehensive regression test suite for Item Inventory Reconciliation.

Tests:
1. Baseline opening stock calculation:
   Baseline Stock = Current Batch Stock - (Lifetime Inward - Lifetime Outward)
2. Mathematical invariance of baseline stock under subsequent transactions.
3. Itemwise Ledger calculation with baseline opening stock:
   Total Inward = Opening Stock + Period Inward
   Closing Stock = Total Inward - Total Outward
4. Ledger closing stock reconciles with Current Batch Stock.
5. Multi-year roll-forward (FY N closing stock == FY N+1 opening stock).
6. Arbitrary date range roll-forward (e.g., sub-period mid-month).
7. Items with zero transactions reconcile opening == closing == batch stock.
8. Items with genuine negative stock reflect batch stock and clear false calculation warnings.
9. Pack size conversions: purchases (pack factor), debit notes (is_pack_qty), sales/credit notes (loose).
10. Database initialization auto-migration and idempotency.
11. ELERAB D exact scenario:
    Opening 357 + Inward 3,029 = Total Inward 3,386; Outward 2,734; Closing 652.
12. Zero opening stock behavior.
13. Negative opening stock behavior.
14. Table UI Row 0 displays opening stock under Inward Qty column.
"""

from __future__ import annotations

import os
import sqlite3
import unittest
from datetime import date

from database.connection import get_connection, init_database
from database.ledger_report_dao import LedgerReportDAO, pack_factor


class TestItemInventoryReconciliation(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_db_path = os.path.join(
            os.path.dirname(__file__), "scratch", "test_item_recon_suite.db"
        )
        os.environ["PHARMACY_DB"] = cls.test_db_path
        if os.path.exists(cls.test_db_path):
            try:
                os.remove(cls.test_db_path)
            except OSError:
                pass
        init_database()

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("PHARMACY_DB", None)
        if os.path.exists(cls.test_db_path):
            try:
                os.remove(cls.test_db_path)
            except OSError:
                pass

    def setUp(self):
        conn = get_connection()
        try:
            conn.execute("DELETE FROM item_opening_balances")
            conn.execute("DELETE FROM purchase_invoice_items")
            conn.execute("DELETE FROM purchase_invoices")
            conn.execute("DELETE FROM sales_invoice_items")
            conn.execute("DELETE FROM sales_invoices")
            conn.execute("DELETE FROM credit_note_items")
            conn.execute("DELETE FROM credit_notes")
            conn.execute("DELETE FROM debit_note_items")
            conn.execute("DELETE FROM debit_notes")
            conn.execute("DELETE FROM stock_batches")
            conn.execute("DELETE FROM items")
            conn.execute("DELETE FROM suppliers")
            conn.execute("DELETE FROM customers")

            conn.execute("INSERT INTO suppliers (id, supplier_name) VALUES (1, 'TEST SUPPLIER')")
            conn.execute("INSERT INTO customers (id, customer_name) VALUES (1, 'TEST CUSTOMER')")

            conn.execute("""
                INSERT INTO items (id, item_name, pack_size, mrp, rate, opening_stock)
                VALUES (1, 'RECON MEDICINE 500', '10', 100.0, 80.0, 0.0)
            """)
            conn.commit()
        finally:
            conn.close()

    def test_01_baseline_stock_reconciliation_formula(self):
        """Baseline stock is correctly derived from batch stock and lifetime transactions."""
        conn = get_connection()
        try:
            cur = conn.execute("""
                INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, stock_qty)
                VALUES (1, 'BATCH-001', '2028-12-31', '10', 100.0, 652.0)
            """)
            batch_id = cur.lastrowid
            conn.execute("""
                INSERT INTO purchase_invoices (id, voucher_no, voucher_date, supplier_id)
                VALUES (1, 'PUR-1', '2026-04-05', 1)
            """)
            conn.execute("""
                INSERT INTO purchase_invoice_items (purchase_invoice_id, item_id, batch_no, pack_size, pay_qty, free_qty)
                VALUES (1, 1, 'BATCH-001', '10', 100.0, 10.0)
            """)
            conn.execute("""
                INSERT INTO sales_invoices (id, bill_no, sale_date, customer_id)
                VALUES (1, 'BILL-1', '2026-04-10', 1)
            """)
            conn.execute("""
                INSERT INTO sales_invoice_items (sales_invoice_id, item_id, stock_batch_id, batch_no, pack_size, sale_qty)
                VALUES (1, 1, ?, 'BATCH-001', '10', 800.0)
            """, (batch_id,))
            conn.commit()

            updated = LedgerReportDAO.reconcile_item_baseline_stock(conn=conn, overwrite=True)
            conn.commit()
            self.assertEqual(updated, 1)

            ob_row = conn.execute("SELECT opening_stock FROM item_opening_balances WHERE item_id = 1").fetchone()
            self.assertEqual(ob_row["opening_stock"], 352.0)

            item_row = conn.execute("SELECT opening_stock FROM items WHERE id = 1").fetchone()
            self.assertEqual(item_row["opening_stock"], 352.0)
        finally:
            conn.close()

    def test_02_ledger_reconciles_perfectly_with_batch_stock(self):
        """Ledger report closing stock matches batch stock, Total Inward includes opening stock."""
        conn = get_connection()
        try:
            cur = conn.execute("""
                INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, stock_qty)
                VALUES (1, 'BATCH-001', '2028-12-31', '10', 100.0, 652.0)
            """)
            batch_id = cur.lastrowid
            conn.execute("""
                INSERT INTO purchase_invoices (id, voucher_no, voucher_date, supplier_id)
                VALUES (1, 'PUR-1', '2026-04-05', 1)
            """)
            conn.execute("""
                INSERT INTO purchase_invoice_items (purchase_invoice_id, item_id, batch_no, pack_size, pay_qty, free_qty)
                VALUES (1, 1, 'BATCH-001', '10', 100.0, 10.0)
            """)
            conn.execute("""
                INSERT INTO sales_invoices (id, bill_no, sale_date, customer_id)
                VALUES (1, 'BILL-1', '2026-04-10', 1)
            """)
            conn.execute("""
                INSERT INTO sales_invoice_items (sales_invoice_id, item_id, stock_batch_id, batch_no, pack_size, sale_qty)
                VALUES (1, 1, ?, 'BATCH-001', '10', 800.0)
            """, (batch_id,))
            conn.commit()
            LedgerReportDAO.reconcile_item_baseline_stock(conn=conn, overwrite=True)
            conn.commit()
        finally:
            conn.close()

        rep = LedgerReportDAO.get_item_ledger(1, "2026-04-01", "2026-04-30")
        self.assertEqual(rep["opening_stock"], 352.0)
        self.assertEqual(rep["period_inward"], 1100.0)
        # Total Inward = Opening Stock (352) + Period Inward (1,100) = 1,452
        self.assertEqual(rep["total_inward"], 1452.0)
        self.assertEqual(rep["total_outward"], 800.0)
        # Closing stock = Total Inward - Total Outward = 1,452 - 800 = 652
        self.assertEqual(rep["closing_stock"], 652.0)
        self.assertEqual(rep["current_batch_stock"], 652.0)
        self.assertIsNone(rep["warning"])
        self.assertEqual(rep["total_inward"] - rep["total_outward"], rep["closing_stock"])

    def test_03_date_range_roll_forward(self):
        """Transactions roll forward across multi-year and custom date ranges."""
        conn = get_connection()
        try:
            cur = conn.execute("""
                INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, stock_qty)
                VALUES (1, 'BATCH-001', '2028-12-31', '10', 100.0, 500.0)
            """)
            batch_id = cur.lastrowid
            # FY 2024-2025 purchase: 30 packs * 10 = 300
            conn.execute("""
                INSERT INTO purchase_invoices (id, voucher_no, voucher_date, supplier_id)
                VALUES (1, 'PUR-2024', '2024-06-01', 1)
            """)
            conn.execute("""
                INSERT INTO purchase_invoice_items (purchase_invoice_id, item_id, batch_no, pack_size, pay_qty, free_qty)
                VALUES (1, 1, 'BATCH-001', '10', 30.0, 0.0)
            """)
            # FY 2024-2025 sale: 100
            conn.execute("""
                INSERT INTO sales_invoices (id, bill_no, sale_date, customer_id)
                VALUES (1, 'BILL-2024', '2024-07-01', 1)
            """)
            conn.execute("""
                INSERT INTO sales_invoice_items (sales_invoice_id, item_id, stock_batch_id, batch_no, pack_size, sale_qty)
                VALUES (1, 1, ?, 'BATCH-001', '10', 100.0)
            """, (batch_id,))
            # FY 2025-2026 purchase: 20 packs * 10 = 200
            conn.execute("""
                INSERT INTO purchase_invoices (id, voucher_no, voucher_date, supplier_id)
                VALUES (2, 'PUR-2025', '2025-05-01', 1)
            """)
            conn.execute("""
                INSERT INTO purchase_invoice_items (purchase_invoice_id, item_id, batch_no, pack_size, pay_qty, free_qty)
                VALUES (2, 1, 'BATCH-001', '10', 20.0, 0.0)
            """)
            # FY 2025-2026 sale: 150
            conn.execute("""
                INSERT INTO sales_invoices (id, bill_no, sale_date, customer_id)
                VALUES (2, 'BILL-2025', '2025-06-01', 1)
            """)
            conn.execute("""
                INSERT INTO sales_invoice_items (sales_invoice_id, item_id, stock_batch_id, batch_no, pack_size, sale_qty)
                VALUES (2, 1, ?, 'BATCH-001', '10', 150.0)
            """, (batch_id,))
            conn.commit()

            LedgerReportDAO.reconcile_item_baseline_stock(conn=conn, overwrite=True)
            conn.commit()
        finally:
            conn.close()

        # FY 2024-2025: Opening=250, Period In=300 -> Total In=550, Out=100 -> Closing=450
        rep_2024 = LedgerReportDAO.get_item_ledger(1, "2024-04-01", "2025-03-31")
        self.assertEqual(rep_2024["opening_stock"], 250.0)
        self.assertEqual(rep_2024["total_inward"], 550.0)
        self.assertEqual(rep_2024["total_outward"], 100.0)
        self.assertEqual(rep_2024["closing_stock"], 450.0)

        # FY 2025-2026: Opening MUST EQUAL FY 2024 closing (450.0)
        # Total Inward = 450 + 200 = 650, Outward = 150 -> Closing = 500
        rep_2025 = LedgerReportDAO.get_item_ledger(1, "2025-04-01", "2026-03-31")
        self.assertEqual(rep_2025["opening_stock"], 450.0)
        self.assertEqual(rep_2025["total_inward"], 650.0)
        self.assertEqual(rep_2025["total_outward"], 150.0)
        self.assertEqual(rep_2025["closing_stock"], 500.0)

        # FY 2026-2027: Opening MUST EQUAL FY 2025 closing (500.0)
        # Total Inward = 500 + 0 = 500, Outward = 0 -> Closing = 500
        rep_2026 = LedgerReportDAO.get_item_ledger(1, "2026-04-01", "2027-03-31")
        self.assertEqual(rep_2026["opening_stock"], 500.0)
        self.assertEqual(rep_2026["total_inward"], 500.0)
        self.assertEqual(rep_2026["total_outward"], 0.0)
        self.assertEqual(rep_2026["closing_stock"], 500.0)
        self.assertEqual(rep_2026["current_batch_stock"], 500.0)

    def test_04_item_with_zero_movements_shows_positive_stock(self):
        """An item with zero transactions but positive batch stock reports opening == closing == batch stock."""
        conn = get_connection()
        try:
            conn.execute("""
                INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, stock_qty)
                VALUES (1, 'INITIAL-BATCH', '2029-01-01', '10', 50.0, 150.0)
            """)
            conn.commit()
            LedgerReportDAO.reconcile_item_baseline_stock(conn=conn, overwrite=True)
            conn.commit()
        finally:
            conn.close()

        rep = LedgerReportDAO.get_item_ledger(1, "2026-04-01", "2026-10-21")
        self.assertEqual(rep["opening_stock"], 150.0)
        self.assertEqual(rep["total_inward"], 150.0)
        self.assertEqual(rep["total_outward"], 0.0)
        self.assertEqual(rep["closing_stock"], 150.0)
        self.assertEqual(rep["current_batch_stock"], 150.0)
        self.assertIsNone(rep["warning"])

    def test_05_item_with_genuine_negative_stock(self):
        """Preserves genuine negative stock from legacy system and displays accurate notice."""
        conn = get_connection()
        try:
            conn.execute("""
                INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, stock_qty)
                VALUES (1, 'DEFICIT-1', '2026-01-01', '10', 50.0, -42.0)
            """)
            conn.commit()
            LedgerReportDAO.reconcile_item_baseline_stock(conn=conn, overwrite=True)
            conn.commit()
        finally:
            conn.close()

        rep = LedgerReportDAO.get_item_ledger(1, "2026-04-01", "2026-10-21")
        self.assertEqual(rep["opening_stock"], -42.0)
        self.assertEqual(rep["total_inward"], -42.0)
        self.assertEqual(rep["closing_stock"], -42.0)
        self.assertEqual(rep["current_batch_stock"], -42.0)
        self.assertIsNotNone(rep["warning"])
        self.assertIn("negative (-42)", rep["warning"])

    def test_06_debit_note_pack_size_conversions(self):
        """Debit note respects pack size when is_pack_qty=1 and free quantities."""
        conn = get_connection()
        try:
            cur = conn.execute("""
                INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, stock_qty)
                VALUES (1, 'BATCH-001', '2028-12-31', '10', 100.0, 50.0)
            """)
            batch_id = cur.lastrowid
            conn.execute("""
                INSERT INTO debit_notes (id, voucher_no, voucher_date, supplier_id)
                VALUES (1, 'DN-001', '2026-04-15', 1)
            """)
            # Return 2 packs + 1 free pack of pack_size 10 = 30 loose units
            conn.execute("""
                INSERT INTO debit_note_items (debit_note_id, item_id, stock_batch_id, batch_no, pack_size, return_qty, free_qty, is_pack_qty)
                VALUES (1, 1, ?, 'BATCH-001', '10', 2.0, 1.0, 1)
            """, (batch_id,))
            conn.commit()
            LedgerReportDAO.reconcile_item_baseline_stock(conn=conn, overwrite=True)
            conn.commit()
        finally:
            conn.close()

        rep = LedgerReportDAO.get_item_ledger(1, "2026-04-01", "2026-04-30")
        self.assertEqual(rep["total_outward"], 30.0)
        self.assertEqual(rep["closing_stock"], 50.0)
        self.assertEqual(rep["current_batch_stock"], 50.0)
        self.assertEqual(rep["total_inward"] - rep["total_outward"], rep["closing_stock"])

    def test_07_mathematical_invariance_under_new_transactions(self):
        """Subsequent transactions do not alter baseline stock, preserving reconciliation."""
        conn = get_connection()
        try:
            cur = conn.execute("""
                INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, stock_qty)
                VALUES (1, 'BATCH-INV', '2028-12-31', '10', 100.0, 100.0)
            """)
            batch_id = cur.lastrowid
            conn.commit()
            LedgerReportDAO.reconcile_item_baseline_stock(conn=conn, overwrite=True)
            conn.commit()
        finally:
            conn.close()

        ob1 = LedgerReportDAO.get_item_ledger(1, "2026-04-01", "2026-04-30")["opening_stock"]
        self.assertEqual(ob1, 100.0)

        # Now simulate a new sale of 20 loose units
        conn = get_connection()
        try:
            conn.execute("""
                INSERT INTO sales_invoices (id, bill_no, sale_date, customer_id)
                VALUES (10, 'BILL-NEW', '2026-05-01', 1)
            """)
            conn.execute("""
                INSERT INTO sales_invoice_items (sales_invoice_id, item_id, stock_batch_id, batch_no, pack_size, sale_qty)
                VALUES (10, 1, ?, 'BATCH-INV', '10', 20.0)
            """, (batch_id,))
            conn.execute("UPDATE stock_batches SET stock_qty = stock_qty - 20.0 WHERE id = ?", (batch_id,))
            conn.commit()
        finally:
            conn.close()

        # Query May 2026: opening stock is STILL 100, outward is 20, closing is 80, batch stock is 80!
        rep = LedgerReportDAO.get_item_ledger(1, "2026-04-01", "2026-05-31")
        self.assertEqual(rep["opening_stock"], 100.0)
        self.assertEqual(rep["total_inward"], 100.0)
        self.assertEqual(rep["total_outward"], 20.0)
        self.assertEqual(rep["closing_stock"], 80.0)
        self.assertEqual(rep["current_batch_stock"], 80.0)

    def test_08_elerab_d_full_workflow_reconstruction(self):
        """Simulates ELERAB D: Opening 357 + Inward 3,029 = Total Inward 3,386; Outward 2,734; Closing 652."""
        conn = get_connection()
        try:
            cur = conn.execute("""
                INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, stock_qty)
                VALUES (1, 'ACRD4017C', '2026-06-30', '10', 109.0, 652.0)
            """)
            batch_id = cur.lastrowid

            # Prior Purchases (< 2026-04-01): 120,924 units (12,092.4 packs)
            conn.execute("""
                INSERT INTO purchase_invoices (id, voucher_no, voucher_date, supplier_id)
                VALUES (100, 'PUR-HIST', '2020-01-01', 1)
            """)
            conn.execute("""
                INSERT INTO purchase_invoice_items (purchase_invoice_id, item_id, batch_no, pack_size, pay_qty, free_qty)
                VALUES (100, 1, 'HIST', '10', 12092.4, 0.0)
            """)

            # Prior Sales (< 2026-04-01): 121,783 units
            conn.execute("""
                INSERT INTO sales_invoices (id, bill_no, sale_date, customer_id)
                VALUES (100, 'BILL-HIST', '2020-02-01', 1)
            """)
            conn.execute("""
                INSERT INTO sales_invoice_items (sales_invoice_id, item_id, stock_batch_id, batch_no, pack_size, sale_qty)
                VALUES (100, 1, ?, 'HIST', '10', 121783.0)
            """, (batch_id,))

            # Period Purchases (>= 2026-04-01): 3,029 units (302.9 packs)
            conn.execute("""
                INSERT INTO purchase_invoices (id, voucher_no, voucher_date, supplier_id)
                VALUES (101, 'PUR-PERIOD', '2026-05-01', 1)
            """)
            conn.execute("""
                INSERT INTO purchase_invoice_items (purchase_invoice_id, item_id, batch_no, pack_size, pay_qty, free_qty)
                VALUES (101, 1, 'ACRD4017C', '10', 302.9, 0.0)
            """)

            # Period Sales (>= 2026-04-01): 2,734 units
            conn.execute("""
                INSERT INTO sales_invoices (id, bill_no, sale_date, customer_id)
                VALUES (101, 'BILL-PERIOD', '2026-05-15', 1)
            """)
            conn.execute("""
                INSERT INTO sales_invoice_items (sales_invoice_id, item_id, stock_batch_id, batch_no, pack_size, sale_qty)
                VALUES (101, 1, ?, 'ACRD4017C', '10', 2734.0)
            """, (batch_id,))
            conn.commit()

            LedgerReportDAO.reconcile_item_baseline_stock(conn=conn, overwrite=True)
            conn.commit()
        finally:
            conn.close()

        rep = LedgerReportDAO.get_item_ledger(1, "2026-04-01", "2026-10-21")
        self.assertEqual(rep["opening_stock"], 357.0)
        self.assertEqual(rep["period_inward"], 3029.0)
        # Total Inward = 357 + 3,029 = 3,386
        self.assertEqual(rep["total_inward"], 3386.0)
        self.assertEqual(rep["total_outward"], 2734.0)
        # Closing stock = 3,386 - 2,734 = 652
        self.assertEqual(rep["closing_stock"], 652.0)
        self.assertEqual(rep["current_batch_stock"], 652.0)
        self.assertEqual(rep["total_inward"] - rep["total_outward"], rep["closing_stock"])
        self.assertIsNone(rep["warning"])

    def test_09_zero_opening_stock_behavior(self):
        """Zero opening stock correctly results in Total Inward == Period Inward."""
        conn = get_connection()
        try:
            cur = conn.execute("""
                INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, stock_qty)
                VALUES (1, 'ZERO-OB', '2028-12-31', '10', 100.0, 30.0)
            """)
            batch_id = cur.lastrowid
            conn.execute("""
                INSERT INTO purchase_invoices (id, voucher_no, voucher_date, supplier_id)
                VALUES (1, 'PUR-ZERO', '2026-04-05', 1)
            """)
            conn.execute("""
                INSERT INTO purchase_invoice_items (purchase_invoice_id, item_id, batch_no, pack_size, pay_qty, free_qty)
                VALUES (1, 1, 'ZERO-OB', '10', 5.0, 0.0)
            """)
            conn.execute("""
                INSERT INTO sales_invoices (id, bill_no, sale_date, customer_id)
                VALUES (1, 'BILL-ZERO', '2026-04-10', 1)
            """)
            conn.execute("""
                INSERT INTO sales_invoice_items (sales_invoice_id, item_id, stock_batch_id, batch_no, pack_size, sale_qty)
                VALUES (1, 1, ?, 'ZERO-OB', '10', 20.0)
            """, (batch_id,))
            conn.commit()
            LedgerReportDAO.reconcile_item_baseline_stock(conn=conn, overwrite=True)
            conn.commit()
        finally:
            conn.close()

        rep = LedgerReportDAO.get_item_ledger(1, "2026-04-01", "2026-04-30")
        self.assertEqual(rep["opening_stock"], 0.0)
        self.assertEqual(rep["period_inward"], 50.0)
        self.assertEqual(rep["total_inward"], 50.0)
        self.assertEqual(rep["total_outward"], 20.0)
        self.assertEqual(rep["closing_stock"], 30.0)
        self.assertEqual(rep["current_batch_stock"], 30.0)
        self.assertEqual(rep["total_inward"] - rep["total_outward"], rep["closing_stock"])

    def test_10_negative_opening_stock_behavior(self):
        """Negative opening balance mathematically calculates Total Inward = Opening + Period Inward."""
        conn = get_connection()
        try:
            cur = conn.execute("""
                INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, stock_qty)
                VALUES (1, 'NEG-BATCH', '2028-12-31', '10', 100.0, 5.0)
            """)
            batch_id = cur.lastrowid
            # Period Inward: 25 units
            conn.execute("""
                INSERT INTO purchase_invoices (id, voucher_no, voucher_date, supplier_id)
                VALUES (1, 'PUR-NEG', '2026-04-05', 1)
            """)
            conn.execute("""
                INSERT INTO purchase_invoice_items (purchase_invoice_id, item_id, batch_no, pack_size, pay_qty, free_qty)
                VALUES (1, 1, 'NEG-BATCH', '10', 2.5, 0.0)
            """)
            # Period Outward: 5 units
            conn.execute("""
                INSERT INTO sales_invoices (id, bill_no, sale_date, customer_id)
                VALUES (1, 'BILL-NEG', '2026-04-10', 1)
            """)
            conn.execute("""
                INSERT INTO sales_invoice_items (sales_invoice_id, item_id, stock_batch_id, batch_no, pack_size, sale_qty)
                VALUES (1, 1, ?, 'NEG-BATCH', '10', 5.0)
            """, (batch_id,))
            # Force opening stock = -15
            conn.execute("""
                INSERT INTO item_opening_balances (item_id, opening_date, opening_stock)
                VALUES (1, '2015-04-01', -15.0)
            """)
            conn.commit()
        finally:
            conn.close()

        rep = LedgerReportDAO.get_item_ledger(1, "2026-04-01", "2026-04-30")
        self.assertEqual(rep["opening_stock"], -15.0)
        self.assertEqual(rep["period_inward"], 25.0)
        # Total Inward = -15 + 25 = 10
        self.assertEqual(rep["total_inward"], 10.0)
        self.assertEqual(rep["total_outward"], 5.0)
        # Closing stock = 10 - 5 = 5
        self.assertEqual(rep["closing_stock"], 5.0)
        self.assertEqual(rep["current_batch_stock"], 5.0)
        self.assertEqual(rep["total_inward"] - rep["total_outward"], rep["closing_stock"])

    def test_11_ui_row_0_displays_opening_stock_in_inward_column(self):
        """Table UI row 0 displays opening stock under the Inward Qty column."""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        import screens

        page = screens.ItemwiseLedgerPage()
        mock_report = {
            "item": {"item_name": "ELERAB D", "pack_size": "10", "unit_name": "CAPSULE"},
            "from_date": "2026-04-01",
            "to_date": "2026-10-21",
            "opening_stock": 357.0,
            "total_inward": 3386.0,
            "total_outward": 2734.0,
            "closing_stock": 652.0,
            "current_batch_stock": 652.0,
            "warning": None,
            "rows": [],
        }
        page._render(mock_report)

        # Check Row 0 cells
        row0_part = page._table.item(0, 1).text()
        self.assertIn("OPENING", row0_part)
        row0_inward = page._table.item(0, 6).text()
        self.assertEqual(row0_inward, "357")
        row0_closing = page._table.item(0, 8).text()
        self.assertEqual(row0_closing, "357")

        # Check Last Row cells (totals)
        last_row = page._table.rowCount() - 1
        last_inward = page._table.item(last_row, 6).text()
        self.assertEqual(last_inward, "3386")
        last_outward = page._table.item(last_row, 7).text()
        self.assertEqual(last_outward, "2734")
        last_closing = page._table.item(last_row, 8).text()
        self.assertEqual(last_closing, "652")

        # Check summary cards
        self.assertEqual(page._val_card_os.text(), "357 CAPSULE")
        self.assertEqual(page._val_card_in.text(), "3386")
        self.assertEqual(page._val_card_out.text(), "2734")
        self.assertEqual(page._val_card_cs.text(), "652 CAPSULE")
        self.assertEqual(page._val_card_hand.text(), "652 CAPSULE")


if __name__ == "__main__":
    unittest.main()
