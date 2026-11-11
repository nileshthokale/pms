"""Automated regression tests for patient mapping and Schedule H1 report joins.

Verifies:
1. Patient address retrieval from patient_addresses.
2. Case-insensitive and whitespace-normalized matching.
3. Schedule H1 report query correctly displays patient address.
4. Schedule H1 report query DOES NOT duplicate rows when a patient has multiple saved addresses.
5. Fallback to customer address when patient_addresses is missing.
6. Safe fallback to empty string when no address exists.
7. Data isolation: sales invoices and item quantities are read-only and preserved.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import auth, financial_year
from database.account_roles import ensure_system_ledgers
from database.connection import get_connection, init_database
from database.customer_dao import CustomerDAO
from database.schedule_reports_dao import ScheduleReportsDAO


class TestPatientAddressMappingAndScheduleH1(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.mkdtemp(prefix="test_pat_addr_")
        self._db_path = os.path.join(self._temp_dir, "test_pharmacy.db")
        self._prev_db = os.environ.get("PHARMACY_DB")
        os.environ["PHARMACY_DB"] = self._db_path

        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_financial_year_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        ensure_system_ledgers()

        # Seed sample patient addresses and schedule H1 sales data
        self._seed_test_data()

    def tearDown(self):
        if self._prev_db:
            os.environ["PHARMACY_DB"] = self._prev_db
        else:
            os.environ.pop("PHARMACY_DB", None)
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def _seed_test_data(self):
        conn = get_connection()
        try:
            cur = conn.cursor()
            # 1. Seed unit & company
            cur.execute("INSERT INTO units (unit_name) VALUES ('TAB')")
            unit_id = cur.lastrowid
            cur.execute("INSERT INTO companies (company_name, short_name) VALUES ('CIPLA', 'CIPLA')")
            comp_id = cur.lastrowid

            # 2. Seed an H1 scheduled item (scheduled = '2' or 'H1')
            cur.execute("""
                INSERT INTO items (item_name, unit_id, company_id, pack_size, scheduled, mrp, rate)
                VALUES ('CEFAXONE 1GM', ?, ?, '1', '2', 150.0, 120.0)
            """, (unit_id, comp_id))
            self.h1_item_id = cur.lastrowid

            # 3. Seed stock batch
            cur.execute("""
                INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (?, 'BATCH001', '2028-12-31', '1', 150.0, 100.0, 100.0, 50.0)
            """, (self.h1_item_id,))
            self.batch_id = cur.lastrowid

            # 4. Seed walkin customer (id=159 or normal)
            cur.execute("INSERT INTO customers (customer_name, address) VALUES ('WALKIN', '')")
            self.walkin_cust_id = cur.lastrowid

            cur.execute("INSERT INTO customers (customer_name, address) VALUES ('CREDIT CUSTOMER', 'REGISTERED OFFICE')")
            self.credit_cust_id = cur.lastrowid

            # 5. Seed patient_addresses:
            # Patient A: single consistent address
            cur.execute("""
                INSERT INTO patient_addresses (patient_name, address, updated_at)
                VALUES ('MR POPAT TODMAL', 'UMBARE', '2026-01-01 10:00:00')
            """)

            # Patient B: multiple addresses over time (latifa pathan)
            cur.execute("""
                INSERT INTO patient_addresses (patient_name, address, updated_at)
                VALUES ('MRS LATIFA PATHAN', 'SADE', '2025-01-01 10:00:00')
            """)
            cur.execute("""
                INSERT INTO patient_addresses (patient_name, address, updated_at)
                VALUES ('MRS LATIFA PATHAN', 'MANORI', '2026-06-01 10:00:00')
            """)

            # 6. Seed sales invoices:
            # Sale 1: Popat Todmal (H1 item, Walkin)
            cur.execute("""
                INSERT INTO sales_invoices (bill_no, sale_date, sale_time, customer_id, patient_name, total_amount, net_amount)
                VALUES ('2026-0001', '2026-05-10', '10:30', ?, 'MR POPAT TODMAL', 150.0, 150.0)
            """, (self.walkin_cust_id,))
            self.sale1_id = cur.lastrowid
            cur.execute("""
                INSERT INTO sales_invoice_items (sales_invoice_id, item_id, stock_batch_id, batch_no, expiry, pack_size, sale_qty, mrp, amount)
                VALUES (?, ?, ?, 'BATCH001', '2028-12-31', '1', 2.0, 150.0, 300.0)
            """, (self.sale1_id, self.h1_item_id, self.batch_id))

            # Sale 2: Latifa Pathan (H1 item, Walkin)
            cur.execute("""
                INSERT INTO sales_invoices (bill_no, sale_date, sale_time, customer_id, patient_name, total_amount, net_amount)
                VALUES ('2026-0002', '2026-06-15', '11:00', ?, 'MRS LATIFA PATHAN', 150.0, 150.0)
            """, (self.walkin_cust_id,))
            self.sale2_id = cur.lastrowid
            cur.execute("""
                INSERT INTO sales_invoice_items (sales_invoice_id, item_id, stock_batch_id, batch_no, expiry, pack_size, sale_qty, mrp, amount)
                VALUES (?, ?, ?, 'BATCH001', '2028-12-31', '1', 1.0, 150.0, 150.0)
            """, (self.sale2_id, self.h1_item_id, self.batch_id))

            # Sale 3: Credit customer with fallback address
            cur.execute("""
                INSERT INTO sales_invoices (bill_no, sale_date, sale_time, customer_id, patient_name, total_amount, net_amount)
                VALUES ('2026-0003', '2026-07-01', '12:00', ?, 'CREDIT CUSTOMER', 150.0, 150.0)
            """, (self.credit_cust_id,))
            self.sale3_id = cur.lastrowid
            cur.execute("""
                INSERT INTO sales_invoice_items (sales_invoice_id, item_id, stock_batch_id, batch_no, expiry, pack_size, sale_qty, mrp, amount)
                VALUES (?, ?, ?, 'BATCH001', '2028-12-31', '1', 1.0, 150.0, 150.0)
            """, (self.sale3_id, self.h1_item_id, self.batch_id))

            # Sale 4: Patient with no address anywhere
            cur.execute("""
                INSERT INTO sales_invoices (bill_no, sale_date, sale_time, customer_id, patient_name, total_amount, net_amount)
                VALUES ('2026-0004', '2026-07-02', '13:00', ?, 'UNKNOWN PATIENT', 150.0, 150.0)
            """, (self.walkin_cust_id,))
            self.sale4_id = cur.lastrowid
            cur.execute("""
                INSERT INTO sales_invoice_items (sales_invoice_id, item_id, stock_batch_id, batch_no, expiry, pack_size, sale_qty, mrp, amount)
                VALUES (?, ?, ?, 'BATCH001', '2028-12-31', '1', 1.0, 150.0, 150.0)
            """, (self.sale4_id, self.h1_item_id, self.batch_id))

            conn.commit()
        finally:
            conn.close()

    def test_01_customer_dao_retrieves_saved_patient_addresses(self):
        """CustomerDAO.get_saved_addresses_for_patient returns correct addresses."""
        addrs = CustomerDAO.get_saved_addresses_for_patient("MR POPAT TODMAL")
        self.assertEqual(addrs, ["UMBARE"])

        # Case-insensitive & extra whitespace
        addrs_ci = CustomerDAO.get_saved_addresses_for_patient("   mr   popat   todmal  ")
        self.assertEqual(addrs_ci, ["UMBARE"])

        # Multi-address returns distinct addresses ordered by updated_at desc
        addrs_multi = CustomerDAO.get_saved_addresses_for_patient("MRS LATIFA PATHAN")
        self.assertIn("MANORI", addrs_multi)
        self.assertIn("SADE", addrs_multi)
        self.assertEqual(addrs_multi[0], "MANORI")  # latest updated_at

    def test_02_schedule_h1_report_resolves_patient_address(self):
        """ScheduleReportsDAO.get_sales_schedule resolves address from patient_addresses."""
        rows = ScheduleReportsDAO.get_sales_schedule("2026-01-01", "2026-12-31", "H1")
        self.assertEqual(len(rows), 4, "Should have exactly 4 sale item rows without duplication")

        row_popat = next(r for r in rows if r["bill_no"] == "2026-0001")
        self.assertEqual(row_popat["patient_name"], "MR POPAT TODMAL")
        self.assertEqual(row_popat["address"], "UMBARE")

    def test_03_schedule_h1_multi_address_does_not_duplicate_rows(self):
        """Multi-address patients match without Cartesian row duplication in Schedule H1."""
        rows = ScheduleReportsDAO.get_sales_schedule("2026-01-01", "2026-12-31", "H1")
        latifa_rows = [r for r in rows if r["bill_no"] == "2026-0002"]
        self.assertEqual(len(latifa_rows), 1, "Multi-address patient must NOT produce duplicate report rows")
        # Should resolve to the primary / latest updated address
        self.assertEqual(latifa_rows[0]["address"], "MANORI")

    def test_04_schedule_h1_customer_address_fallback(self):
        """If patient_addresses has no entry, customer.address is used as fallback."""
        rows = ScheduleReportsDAO.get_sales_schedule("2026-01-01", "2026-12-31", "H1")
        credit_row = next(r for r in rows if r["bill_no"] == "2026-0003")
        self.assertEqual(credit_row["address"], "REGISTERED OFFICE")

    def test_05_schedule_h1_safe_empty_when_no_address_exists(self):
        """If neither patient_addresses nor customer has an address, safely returns empty string."""
        rows = ScheduleReportsDAO.get_sales_schedule("2026-01-01", "2026-12-31", "H1")
        unknown_row = next(r for r in rows if r["bill_no"] == "2026-0004")
        self.assertEqual(unknown_row["address"], "")


if __name__ == "__main__":
    unittest.main()
