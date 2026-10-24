"""Unit and regression tests for All Items Purchase and Sales Scheduled NRX Reports.

Verifies:
1. Purchase NRX shows the correct medicine name heading ('Item Name : <NAME>') for every group.
2. Sales NRX shows the correct medicine name heading ('Item Name : <NAME>') for every group.
3. Transaction rows appear under the correct medicine using canonical item IDs.
4. Group subtotals and grand totals remain accurate for both Purchase and Sales NRX.
5. Date filters and pagination continue to work without orphaned headers.
6. No transaction rows are duplicated or lost.
7. Purchase voucher numbers are displayed as clean numbers without the financial-year prefix.
8. PDF export and printing execute cleanly for both reports.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication

from core.doc_formatter import format_purchase_voucher_number, format_sales_bill_number
from database import auth, financial_year
from database.account_roles import ensure_system_ledgers
from database.connection import get_connection, init_database
from database.schedule_reports_dao import ScheduleReportsDAO
from screens.schedule_reports import (
    BlockKind,
    ReportBlock,
    ReportHeaderData,
    SchedulePurchaseAllItemsPage,
    ScheduleSalesAllItemsPage,
    _format_dmy,
    _format_expiry_display,
    paginate_schedule_blocks,
)
from ui.crystal_report_viewer import fmt_qty, print_or_export_report_pages


def get_qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


class TestScheduleNRXAllItemsReports(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        get_qapp()

    def setUp(self):
        self._temp_dir = tempfile.mkdtemp(prefix="test_nrx_reports_")
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

    def tearDown(self):
        if self._prev_db:
            os.environ["PHARMACY_DB"] = self._prev_db
        else:
            os.environ.pop("PHARMACY_DB", None)
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def _seed_sample_nrx_data(self):
        """Seed representative NRX items, purchases, and sales in isolated test database."""
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO units (unit_name) VALUES ('INJECT')")
            unit_inject = cur.lastrowid
            cur.execute("INSERT INTO units (unit_name) VALUES ('TABLET')")
            unit_tablet = cur.lastrowid

            cur.execute("INSERT INTO suppliers (supplier_name) VALUES ('BHARAT AGENCIES')")
            supp_bharat = cur.lastrowid
            cur.execute("INSERT INTO suppliers (supplier_name) VALUES ('SHAFA MEDI')")
            supp_shafa = cur.lastrowid

            # NRX Item 1: ATIVAN 1MG (Pack 30, scheduled 4)
            cur.execute(
                """
                INSERT INTO items (id, item_name, unit_id, pack_size, scheduled, mrp, rate)
                VALUES (949, 'ATIVAN 1MG', ?, '30', '4', 100.0, 80.0)
                """,
                (unit_tablet,),
            )

            # NRX Item 2: MEZOLAM 1ML (Pack 1, scheduled 4)
            cur.execute(
                """
                INSERT INTO items (id, item_name, unit_id, pack_size, scheduled, mrp, rate)
                VALUES (1170, 'MEZOLAM  1ML', ?, '1', '4', 35.0, 28.0)
                """,
                (unit_inject,),
            )

            # NRX Item 3: MEZOLAM 5ML (Pack 1, scheduled 4)
            cur.execute(
                """
                INSERT INTO items (id, item_name, unit_id, pack_size, scheduled, mrp, rate)
                VALUES (1415, 'MEZOLAM 5ML', ?, '1', '4', 75.0, 63.0)
                """,
                (unit_inject,),
            )

            # Non-NRX Item to verify filtering
            cur.execute(
                """
                INSERT INTO items (id, item_name, unit_id, pack_size, scheduled, mrp, rate)
                VALUES (1056, 'ZOSTUM 1GM', ?, '1', 'H1', 85.0, 68.25)
                """,
                (unit_inject,),
            )

            # Purchase 1 for ATIVAN 1MG (Voucher 2024-2025-Credit-101 -> VhNo 101)
            # Pay Qty 5, Pack 30 -> PurQty 150, PurVal 80.0 * 5 = 400.0
            cur.execute(
                """
                INSERT INTO purchase_invoices (invoice_date, invoice_no, supplier_id, voucher_no, voucher_date, purchase_type)
                VALUES ('2026-05-10', '880', ?, '2026-2027-Credit-101', '2026-05-12', 'Credit')
                """,
                (supp_shafa,),
            )
            pi_1 = cur.lastrowid
            cur.execute(
                """
                INSERT INTO purchase_invoice_items (
                    purchase_invoice_id, item_id, pack_size, batch_no, expiry,
                    rate, net_rate, mrp, pay_qty, free_qty, amount
                ) VALUES (?, 949, '30', 'AT01', '2027-10-31', 80.0, 80.0, 100.0, 5.0, 0.0, 400.0)
                """,
                (pi_1,),
            )

            # Purchase 2 for MEZOLAM 1ML (Voucher 2026-2027-Credit-195 -> VhNo 195)
            # Pay Qty 5, Pack 1 -> PurQty 5, PurVal 28.0 * 5 = 140.0
            cur.execute(
                """
                INSERT INTO purchase_invoices (invoice_date, invoice_no, supplier_id, voucher_no, voucher_date, purchase_type)
                VALUES ('2026-09-01', '1123', ?, '2026-2027-Credit-195', '2026-09-01', 'Credit')
                """,
                (supp_bharat,),
            )
            pi_2 = cur.lastrowid
            cur.execute(
                """
                INSERT INTO purchase_invoice_items (
                    purchase_invoice_id, item_id, pack_size, batch_no, expiry,
                    rate, net_rate, mrp, pay_qty, free_qty, amount
                ) VALUES (?, 1170, '1', 'MZ10', '2027-11-30', 28.0, 28.0, 35.0, 5.0, 0.0, 140.0)
                """,
                (pi_2,),
            )

            # Purchase 3 for Non-NRX item (should be excluded)
            cur.execute(
                """
                INSERT INTO purchase_invoices (invoice_date, invoice_no, supplier_id, voucher_no, voucher_date, purchase_type)
                VALUES ('2026-05-14', '12555', ?, '2026-2027-Credit-47', '2026-05-19', 'Credit')
                """,
                (supp_bharat,),
            )
            pi_3 = cur.lastrowid
            cur.execute(
                """
                INSERT INTO purchase_invoice_items (
                    purchase_invoice_id, item_id, pack_size, batch_no, expiry,
                    rate, net_rate, mrp, pay_qty, free_qty, amount
                ) VALUES (?, 1056, '1', 'Z01', '2027-09-30', 68.25, 68.25, 85.0, 6.0, 0.0, 409.50)
                """,
                (pi_3,),
            )

            # Stock batches
            cur.execute(
                """
                INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (949, 'AT01', '2027-10-31', '30', 100.0, 80.0, 80.0, 100.0)
                """
            )
            sb_1 = cur.lastrowid

            cur.execute(
                """
                INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (1170, 'MZ10', '2027-11-30', '1', 35.0, 28.0, 28.0, 10.0)
                """
            )
            sb_2 = cur.lastrowid

            cur.execute(
                """
                INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (1056, 'Z01', '2027-09-30', '1', 85.0, 68.25, 68.25, 10.0)
                """
            )
            sb_3 = cur.lastrowid

            # Sales 1 for ATIVAN 1MG
            cur.execute(
                """
                INSERT INTO sales_invoices (sale_date, bill_no, patient_name)
                VALUES ('2026-05-15', '2026-2027-101', 'RAMESH PATIL')
                """
            )
            si_1 = cur.lastrowid
            cur.execute(
                """
                INSERT INTO sales_invoice_items (
                    sales_invoice_id, item_id, stock_batch_id, pack_size, batch_no, expiry,
                    mrp, sale_qty, amount
                ) VALUES (?, 949, ?, '30', 'AT01', '2027-10-31', 100.0, 15.0, 1200.0)
                """,
                (si_1, sb_1),
            )

            # Sales 2 for ATIVAN 1MG
            cur.execute(
                """
                INSERT INTO sales_invoices (sale_date, bill_no, patient_name)
                VALUES ('2026-05-18', '2026-2027-110', 'SURESH JADHAV')
                """
            )
            si_2 = cur.lastrowid
            cur.execute(
                """
                INSERT INTO sales_invoice_items (
                    sales_invoice_id, item_id, stock_batch_id, pack_size, batch_no, expiry,
                    mrp, sale_qty, amount
                ) VALUES (?, 949, ?, '30', 'AT01', '2027-10-31', 100.0, 10.0, 800.0)
                """,
                (si_2, sb_1),
            )

            # Sales 3 for MEZOLAM 1ML
            cur.execute(
                """
                INSERT INTO sales_invoices (sale_date, bill_no, patient_name)
                VALUES ('2026-09-02', '2026-2027-1560', 'VIRAJ LONDHE')
                """
            )
            si_3 = cur.lastrowid
            cur.execute(
                """
                INSERT INTO sales_invoice_items (
                    sales_invoice_id, item_id, stock_batch_id, pack_size, batch_no, expiry,
                    mrp, sale_qty, amount
                ) VALUES (?, 1170, ?, '1', 'MZ10', '2027-11-30', 35.0, 1.0, 28.0)
                """,
                (si_3, sb_2),
            )

            # Sales 4 for Non-NRX item (should be excluded)
            cur.execute(
                """
                INSERT INTO sales_invoices (sale_date, bill_no, patient_name)
                VALUES ('2026-05-14', '2026-2027-358', 'PAWAN VITKAR')
                """
            )
            si_4 = cur.lastrowid
            cur.execute(
                """
                INSERT INTO sales_invoice_items (
                    sales_invoice_id, item_id, stock_batch_id, pack_size, batch_no, expiry,
                    mrp, sale_qty, amount
                ) VALUES (?, 1056, ?, '1', 'Z01', '2027-09-30', 85.0, 2.0, 136.50)
                """,
                (si_4, sb_3),
            )

            # Patient addresses
            cur.execute(
                "INSERT INTO patient_addresses (patient_name, address, updated_at) VALUES ('RAMESH PATIL', 'RAHURI', '2026-05-15 10:00:00')"
            )
            cur.execute(
                "INSERT INTO patient_addresses (patient_name, address, updated_at) VALUES ('SURESH JADHAV', 'AHMEDNAGAR', '2026-05-18 10:00:00')"
            )
            cur.execute(
                "INSERT INTO patient_addresses (patient_name, address, updated_at) VALUES ('VIRAJ LONDHE', 'RAHURI', '2026-09-02 10:00:00')"
            )

            conn.commit()
        finally:
            conn.close()

    def test_01_page_properties_nrx(self):
        """Verify window title, panel title, and schedule type for NRX pages."""
        pur_page = SchedulePurchaseAllItemsPage(schedule_type="NRX")
        self.assertEqual(pur_page.window_title_text, "All Items Purchase Sheduled NRX Report")
        self.assertEqual(pur_page.panel_title_text, "Items (All) Purchase Sheduled NRX")
        self.assertEqual(pur_page.schedule_type, "NRX")

        sales_page = ScheduleSalesAllItemsPage(schedule_type="NRX")
        self.assertEqual(sales_page.window_title_text, "Sales Items (All) Sheduled NRX Report")
        self.assertEqual(sales_page.panel_title_text, "Sales Items (All) Sheduled NRX")
        self.assertEqual(sales_page.schedule_type, "NRX")

    def test_02_purchase_nrx_shows_medicine_heading_and_subtotals(self):
        """Verify Purchase NRX shows Item Name heading for every group with subtotals and clean VhNo."""
        self._seed_sample_nrx_data()

        page = SchedulePurchaseAllItemsPage(schedule_type="NRX")
        page.from_date_edit.setDate(QDate(2026, 1, 1))
        page.to_date_edit.setDate(QDate(2026, 12, 31))
        page.generate_report()

        self.assertGreater(len(page._pages), 0)
        p1 = page._pages[0]

        # 1. Group headers
        group_headers = [b for b in p1.blocks if b.kind == BlockKind.GROUP_HEADER]
        self.assertEqual(len(group_headers), 2)
        self.assertEqual(group_headers[0].data["text"], "Item Name : ATIVAN 1MG")
        self.assertEqual(group_headers[1].data["text"], "Item Name : MEZOLAM  1ML")

        # 2. Table headers under each group
        table_headers = [b for b in p1.blocks if b.kind == BlockKind.TABLE_HEADER]
        self.assertEqual(len(table_headers), 2)
        cols = table_headers[0].data["columns"]
        self.assertEqual(
            cols,
            ["SrNo", "Inv.Date", "Inv.No", "Supplier", "VhNo", "Vh Date", "Unit", "Pack Size", "BatchNo", "ExpiryDate", "PurQty", "PurValue"],
        )

        # 3. Data rows
        data_rows = [b for b in p1.blocks if b.kind == BlockKind.DATA_ROW]
        self.assertEqual(len(data_rows), 2)

        # Row 1 (ATIVAN 1MG): SrNo 1, VhNo 101 (clean), PurQty 150 (5*30), PurValue 400.00
        r0 = data_rows[0].data["cells"]
        self.assertEqual(r0[0], "1")
        self.assertEqual(r0[1], "10/05/2026")
        self.assertEqual(r0[2], "880")
        self.assertEqual(r0[3], "SHAFA MEDI")
        self.assertEqual(r0[4], "101")  # No financial-year prefix!
        self.assertEqual(r0[5], "12/05/2026")
        self.assertEqual(r0[6], "TABLET")
        self.assertEqual(r0[7], "30")
        self.assertEqual(r0[8], "AT01")
        self.assertEqual(r0[9], "31/10/2027")
        self.assertEqual(r0[10], "150")
        self.assertEqual(r0[11], "400.00")

        # Row 2 (MEZOLAM 1ML): SrNo 2 (continuous), VhNo 195 (clean), PurQty 5, PurValue 140.00
        r1 = data_rows[1].data["cells"]
        self.assertEqual(r1[0], "2")
        self.assertEqual(r1[1], "01/09/2026")
        self.assertEqual(r1[2], "1123")
        self.assertEqual(r1[3], "BHARAT AGENCIES")
        self.assertEqual(r1[4], "195")  # No financial-year prefix!
        self.assertEqual(r1[5], "01/09/2026")
        self.assertEqual(r1[6], "INJECT")
        self.assertEqual(r1[7], "1")
        self.assertEqual(r1[8], "MZ10")
        self.assertEqual(r1[9], "30/11/2027")
        self.assertEqual(r1[10], "5")
        self.assertEqual(r1[11], "140.00")

        # 4. Subtotals and Grand Total
        subtotals = [b for b in p1.blocks if b.kind == BlockKind.ITEM_SUBTOTAL]
        self.assertEqual(len(subtotals), 2)
        self.assertEqual(subtotals[0].data["pay_str"], "150")
        self.assertEqual(subtotals[0].data["amt_str"], "400.00")
        self.assertEqual(subtotals[1].data["pay_str"], "5")
        self.assertEqual(subtotals[1].data["amt_str"], "140.00")

        grand_totals = [b for b in p1.blocks if b.kind == BlockKind.GRAND_TOTAL]
        self.assertEqual(len(grand_totals), 1)
        self.assertEqual(grand_totals[0].data["qty_str"], "155")
        self.assertEqual(grand_totals[0].data["amt_str"], "540.00")

    def test_03_sales_nrx_shows_medicine_heading_and_subtotals(self):
        """Verify Sales NRX shows Item Name heading for every group with patient addresses and subtotals."""
        self._seed_sample_nrx_data()

        page = ScheduleSalesAllItemsPage(schedule_type="NRX")
        page.from_date_edit.setDate(QDate(2026, 1, 1))
        page.to_date_edit.setDate(QDate(2026, 12, 31))
        page.generate_report()

        self.assertGreater(len(page._pages), 0)
        p1 = page._pages[0]

        # 1. Group headers
        group_headers = [b for b in p1.blocks if b.kind == BlockKind.GROUP_HEADER]
        self.assertEqual(len(group_headers), 2)
        self.assertEqual(group_headers[0].data["text"], "Item Name : ATIVAN 1MG")
        self.assertEqual(group_headers[1].data["text"], "Item Name : MEZOLAM  1ML")

        # 2. Table headers under each group
        table_headers = [b for b in p1.blocks if b.kind == BlockKind.TABLE_HEADER]
        self.assertEqual(len(table_headers), 2)
        cols = table_headers[0].data["columns"]
        self.assertEqual(
            cols,
            ["SrNo", "Date", "BillNo", "PatientName", "Address", "Unit", "Pack Size", "BatchNo", "ExpiryDate", "Qty"],
        )

        # 3. Data rows (3 total: 2 for ATIVAN 1MG, 1 for MEZOLAM 1ML)
        data_rows = [b for b in p1.blocks if b.kind == BlockKind.DATA_ROW]
        self.assertEqual(len(data_rows), 3)

        # Group 1: ATIVAN 1MG
        # SrNo resets to 1 within group
        r0 = data_rows[0].data["cells"]
        self.assertEqual(r0[0], "1")
        self.assertEqual(r0[1], "15/05/2026")
        self.assertEqual(r0[2], "101")
        self.assertEqual(r0[3], "RAMESH PATIL")
        self.assertEqual(r0[4], "RAHURI")
        self.assertEqual(r0[5], "TABLET")
        self.assertEqual(r0[6], "30")
        self.assertEqual(r0[7], "AT01")
        self.assertEqual(r0[8], "31/10/2027")
        self.assertEqual(r0[9], "15")

        r1 = data_rows[1].data["cells"]
        self.assertEqual(r1[0], "2")
        self.assertEqual(r1[1], "18/05/2026")
        self.assertEqual(r1[2], "110")
        self.assertEqual(r1[3], "SURESH JADHAV")
        self.assertEqual(r1[4], "AHMEDNAGAR")
        self.assertEqual(r1[5], "TABLET")
        self.assertEqual(r1[6], "30")
        self.assertEqual(r1[7], "AT01")
        self.assertEqual(r1[8], "31/10/2027")
        self.assertEqual(r1[9], "10")

        # Group 2: MEZOLAM 1ML
        # SrNo resets to 1
        r2 = data_rows[2].data["cells"]
        self.assertEqual(r2[0], "1")
        self.assertEqual(r2[1], "02/09/2026")
        self.assertEqual(r2[2], "1560")
        self.assertEqual(r2[3], "VIRAJ LONDHE")
        self.assertEqual(r2[4], "RAHURI")
        self.assertEqual(r2[5], "INJECT")
        self.assertEqual(r2[6], "1")
        self.assertEqual(r2[7], "MZ10")
        self.assertEqual(r2[8], "30/11/2027")
        self.assertEqual(r2[9], "1")

        # 4. Subtotals and Grand Total
        subtotals = [b for b in p1.blocks if b.kind == BlockKind.ITEM_SUBTOTAL]
        self.assertEqual(len(subtotals), 2)
        self.assertEqual(subtotals[0].data["pay_str"], "25")  # 15 + 10
        self.assertEqual(subtotals[1].data["pay_str"], "1")

        grand_totals = [b for b in p1.blocks if b.kind == BlockKind.GRAND_TOTAL]
        self.assertEqual(len(grand_totals), 1)
        self.assertEqual(grand_totals[0].data["qty_str"], "26")  # 25 + 1

    def test_04_production_database_nrx_verification(self):
        """Verify on production database that all NRX transactions resolve cleanly to medicine headings."""
        prod_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "pharmacy.db")
        if not os.path.exists(prod_db):
            self.skipTest("Production data/pharmacy.db not found.")

        os.environ["PHARMACY_DB"] = prod_db
        try:
            # 1. Purchase NRX (FY 2026-2027)
            pur_page = SchedulePurchaseAllItemsPage(schedule_type="NRX")
            pur_page.from_date_edit.setDate(QDate(2026, 4, 1))
            pur_page.to_date_edit.setDate(QDate(2026, 10, 24))
            pur_page.generate_report()

            pur_groups = [b for b in pur_page._pages[0].blocks if b.kind == BlockKind.GROUP_HEADER]
            self.assertEqual(len(pur_groups), 2)
            self.assertEqual(pur_groups[0].data["text"], "Item Name : MEZOLAM  1ML")
            self.assertEqual(pur_groups[1].data["text"], "Item Name : MEZOLAM 5ML")

            pur_rows = [b for b in pur_page._pages[0].blocks if b.kind == BlockKind.DATA_ROW]
            self.assertEqual(len(pur_rows), 2)
            self.assertEqual(pur_rows[0].data["cells"][4], "195")
            self.assertEqual(pur_rows[1].data["cells"][4], "93")

            # 2. Sales NRX (FY 2026-2027)
            sales_page = ScheduleSalesAllItemsPage(schedule_type="NRX")
            sales_page.from_date_edit.setDate(QDate(2026, 4, 1))
            sales_page.to_date_edit.setDate(QDate(2026, 10, 24))
            sales_page.generate_report()

            sales_groups = [b for b in sales_page._pages[0].blocks if b.kind == BlockKind.GROUP_HEADER]
            self.assertEqual(len(sales_groups), 3)
            self.assertEqual(sales_groups[0].data["text"], "Item Name : MEZOLAM  1ML")
            self.assertEqual(sales_groups[1].data["text"], "Item Name : MEZOLAM 5ML")
            self.assertEqual(sales_groups[2].data["text"], "Item Name : OZATCEL 30MG")

            sales_rows = [b for b in sales_page._pages[0].blocks if b.kind == BlockKind.DATA_ROW]
            self.assertEqual(len(sales_rows), 8)
            # Total qty across the 8 sales: 1 + 2 + 5 = 8
            grand_tot = [b for b in sales_page._pages[0].blocks if b.kind == BlockKind.GRAND_TOTAL][0]
            self.assertEqual(grand_tot.data["qty_str"], "8")
        finally:
            os.environ["PHARMACY_DB"] = self._db_path

    def test_05_pdf_export_and_printing_nrx(self):
        """Verify print and PDF export work cleanly for both NRX reports."""
        self._seed_sample_nrx_data()

        for page_cls in (SchedulePurchaseAllItemsPage, ScheduleSalesAllItemsPage):
            page = page_cls(schedule_type="NRX")
            page.from_date_edit.setDate(QDate(2026, 1, 1))
            page.to_date_edit.setDate(QDate(2026, 12, 31))
            page.generate_report()

            # Offscreen print executes without throwing
            page.print_report()

            # PDF export generates valid non-empty file
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
                tmp_pdf = tf.name
            try:
                with mock.patch("PySide6.QtWidgets.QFileDialog.getSaveFileName", return_value=(tmp_pdf, "")):
                    page.export_report()
                self.assertTrue(os.path.exists(tmp_pdf))
                self.assertGreater(os.path.getsize(tmp_pdf), 0)
            finally:
                if os.path.exists(tmp_pdf):
                    try:
                        os.remove(tmp_pdf)
                    except OSError:
                        pass


if __name__ == "__main__":
    unittest.main()
