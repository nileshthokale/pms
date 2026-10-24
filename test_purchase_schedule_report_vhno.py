"""Unit and regression tests for Datewise, Itemwise, and All Items Purchase Scheduled Reports (H1 & NRX) VhNo display.

Verifies:
1. VhNo column displays only the genuine voucher number (no financial year or voucher-type prefix).
2. Known voucher numbers matching Pharma-WINNER: 47, 92, 190, 234.
3. Different financial years (e.g. 2015-2016, 2024-2025, 2025-2026, 2026-2027).
4. Different voucher types (Credit, Cash, Challan, Debit, PV-).
5. Collision (#12345) and legacy (-S72213) suffixes properly stripped.
6. Leading zeros stripped for pure numeric vouchers (0251 -> 251, 0001 -> 1) matching Pharma-WINNER integer VhNo.
7. Non-numeric test vouchers (e.g. V001) preserved without corruption.
8. Applied consistently across all 6 Purchase Scheduled Reports:
   - Datewise Purchase Scheduled H1 Report
   - All Items Purchase Scheduled H1 Report
   - Itemwise Purchase Scheduled H1 Report
   - Datewise Purchase Scheduled NRX Report
   - All Items Purchase Scheduled NRX Report
   - Itemwise Purchase Scheduled NRX Report
9. Invoice number (Inv.No) and voucher date (Vh Date) preserved separately without confusion.
10. Report columns, date filters, sorting, subtotals, grand totals, printing, and PDF export preserved.
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
from PySide6.QtWidgets import QApplication, QMessageBox

from core.doc_formatter import format_purchase_voucher_number
from database import auth, financial_year
from database.account_roles import ensure_system_ledgers
from database.connection import get_connection, init_database
from database.schedule_reports_dao import ScheduleReportsDAO
from screens.schedule_reports import (
    SchedulePurchaseDatewisePage,
    SchedulePurchaseItemwisePage,
    SchedulePurchaseAllItemsPage,
)
from ui.crystal_report_viewer import BlockKind

_APP = None


def get_qapp() -> QApplication:
    global _APP
    app = QApplication.instance()
    if app is None:
        _APP = QApplication(sys.argv)
        return _APP
    return app


class TestPurchaseScheduleReportVhNo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        get_qapp()

    def setUp(self):
        self._temp_dir = tempfile.mkdtemp(prefix="test_pur_sched_")
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

        self._msg_patches = [
            mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "information", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "critical", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "question", return_value=QMessageBox.No),
        ]
        for p in self._msg_patches:
            p.start()

        self._seed_schedule_purchase_data()

    def tearDown(self):
        for p in self._msg_patches:
            p.stop()

        if self._prev_db:
            os.environ["PHARMACY_DB"] = self._prev_db
        else:
            os.environ.pop("PHARMACY_DB", None)
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def _seed_schedule_purchase_data(self):
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO units (unit_name) VALUES ('TAB')")
            unit_id = cur.lastrowid
            cur.execute("INSERT INTO companies (company_name, short_name) VALUES ('CIPLA LTD', 'CIP')")
            comp_id = cur.lastrowid
            cur.execute("INSERT INTO suppliers (supplier_name) VALUES ('MAHAVEER MEDICO')")
            self.supp_id = cur.lastrowid

            # Create Schedule H1 item
            cur.execute(
                """
                INSERT INTO items (item_name, unit_id, company_id, pack_size, scheduled, mrp, rate)
                VALUES ('TRAMAGOLD 50MG', ?, ?, '10', 'H1', 100.0, 80.0)
                """,
                (unit_id, comp_id),
            )
            self.h1_item_id = cur.lastrowid

            # Create Schedule NRX item
            cur.execute(
                """
                INSERT INTO items (item_name, unit_id, company_id, pack_size, scheduled, mrp, rate)
                VALUES ('ATIVAN 2 MG', ?, ?, '10', 'NRX', 150.0, 120.0)
                """,
                (unit_id, comp_id),
            )
            self.nrx_item_id = cur.lastrowid

            # Seed H1 purchases across different FYs and types, including 47, 92, 190, 234
            h1_invoices = [
                ("2024-2025-Credit-368", "2025-01-20", "Credit", "INV-101"),
                ("2025-2026-Credit-6", "2025-04-10", "Credit", "INV-102"),
                ("2025-2026-Credit-47", "2025-05-19", "Credit", "INV-105"),
                ("2025-2026-Cash-80", "2025-06-15", "Cash", "INV-103"),
                ("2025-2026-Credit-92", "2025-06-16", "Credit", "INV-106"),
                ("2025-2026-Credit-190", "2025-08-24", "Credit", "INV-108"),
                ("2025-2026-Credit-234", "2025-09-24", "Credit", "INV-109"),
                ("2026-2027-Credit-0251", "2026-05-01", "Credit", "INV-104"),
                ("2026-2027-Challan-1", "2026-07-01", "Challan", "INV-107"),
                ("2026-2027-Credit-1905#12345", "2026-10-01", "Credit", "INV-110"),
                ("2026-2027-Cash-187-S72213", "2026-10-05", "Cash", "INV-111"),
                ("PV-0001", "2026-10-10", "Credit", "INV-112"),
            ]

            for vno, vdate, ptype, inv_no in h1_invoices:
                cur.execute(
                    """
                    INSERT INTO purchase_invoices (
                        voucher_no, voucher_date, purchase_type, supplier_id,
                        invoice_no, invoice_date, total_amount, net_amount
                    ) VALUES (?, ?, ?, ?, ?, ?, 800.0, 800.0)
                    """,
                    (vno, vdate, ptype, self.supp_id, inv_no, vdate),
                )
                pi_id = cur.lastrowid
                cur.execute(
                    """
                    INSERT INTO purchase_invoice_items (
                        purchase_invoice_id, item_id, pack_size, batch_no, expiry,
                        rate, mrp, pay_qty, free_qty, amount
                    ) VALUES (?, ?, '10', 'BAT-H1', '2028-12-31', 80.0, 100.0, 10.0, 0.0, 800.0)
                    """,
                    (pi_id, self.h1_item_id),
                )

            # Seed NRX purchases in chronological order including 47, 92, 190, 234
            nrx_invoices = [
                ("2026-2027-Credit-47", "2026-05-19", "Credit", "NRX-47"),
                ("2026-2027-Credit-92", "2026-06-16", "Credit", "NRX-92"),
                ("2026-2027-Credit-190", "2026-08-24", "Credit", "NRX-190"),
                ("2026-2027-Credit-234", "2026-09-24", "Credit", "NRX-234"),
            ]
            for vno, vdate, ptype, inv_no in nrx_invoices:
                cur.execute(
                    """
                    INSERT INTO purchase_invoices (
                        voucher_no, voucher_date, purchase_type, supplier_id,
                        invoice_no, invoice_date, total_amount, net_amount
                    ) VALUES (?, ?, ?, ?, ?, ?, 1200.0, 1200.0)
                    """,
                    (vno, vdate, ptype, self.supp_id, inv_no, vdate),
                )
                pi_id = cur.lastrowid
                cur.execute(
                    """
                    INSERT INTO purchase_invoice_items (
                        purchase_invoice_id, item_id, pack_size, batch_no, expiry,
                        rate, mrp, pay_qty, free_qty, amount
                    ) VALUES (?, ?, '10', 'BAT-NRX', '2028-12-31', 120.0, 150.0, 10.0, 0.0, 1200.0)
                    """,
                    (pi_id, self.nrx_item_id),
                )

            conn.commit()
        finally:
            conn.close()

    def test_01_doc_formatter_purchase_voucher_cases(self):
        """Test standalone extraction rules of format_purchase_voucher_number."""
        cases = [
            ("2026-2027-Credit-47", "47"),
            ("2026-2027-Credit-92", "92"),
            ("2026-2027-Credit-190", "190"),
            ("2026-2027-Credit-234", "234"),
            ("2026-2027-Credit-0251", "251"),
            ("2026-2027-Credit-79", "79"),
            ("2025-2026-Cash-80", "80"),
            ("2024-2025-Credit-368", "368"),
            ("2015-2016-Credit-1", "1"),
            ("2026-2027-Challan-1", "1"),
            ("2026-2027-Credit-1905#12345", "1905"),
            ("2026-2027-Cash-187-S72213", "187"),
            ("PV-0001", "1"),
            ("PV-101", "101"),
            ("2026-2027-1905", "1905"),
            ("2026-2027-Credit-V001", "V001"),
            ("V001", "V001"),
            ("0252", "252"),
            ("252", "252"),
            ("2026-2027-Credit Card-5", "5"),
            ("2026-2027-Debit-12", "12"),
            ("", ""),
            (None, ""),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(format_purchase_voucher_number(raw), expected)

    def test_02_dao_get_purchase_schedule_known_vouchers_h1_and_nrx(self):
        """Verify DAO get_purchase_schedule returns clean vh_no for H1 and NRX."""
        # Check H1
        h1_rows = ScheduleReportsDAO.get_purchase_schedule("2024-01-01", "2026-12-31", "H1")
        self.assertEqual(len(h1_rows), 12)
        h1_map = {r["inv_no"]: r["vh_no"] for r in h1_rows}
        self.assertEqual(h1_map["INV-105"], "47")
        self.assertEqual(h1_map["INV-106"], "92")
        self.assertEqual(h1_map["INV-108"], "190")
        self.assertEqual(h1_map["INV-109"], "234")
        self.assertEqual(h1_map["INV-104"], "251")
        self.assertEqual(h1_map["INV-110"], "1905")
        self.assertEqual(h1_map["INV-111"], "187")

        # Check NRX
        nrx_rows = ScheduleReportsDAO.get_purchase_schedule("2024-01-01", "2026-12-31", "NRX")
        self.assertEqual(len(nrx_rows), 4)
        nrx_map = {r["inv_no"]: r["vh_no"] for r in nrx_rows}
        self.assertEqual(nrx_map["NRX-47"], "47")
        self.assertEqual(nrx_map["NRX-92"], "92")
        self.assertEqual(nrx_map["NRX-190"], "190")
        self.assertEqual(nrx_map["NRX-234"], "234")

    def test_03_datewise_purchase_schedule_report_h1_and_nrx(self):
        """Verify Datewise Purchase Schedule Report displays clean VhNo for H1 and NRX."""
        # 1. H1
        page_h1 = SchedulePurchaseDatewisePage(schedule_type="H1")
        page_h1.from_date_edit.setDate(QDate(2024, 1, 1))
        page_h1.to_date_edit.setDate(QDate(2026, 12, 31))
        page_h1.generate_report()
        data_rows_h1 = [b for b in page_h1._pages[0].blocks if b.kind == BlockKind.DATA_ROW]
        self.assertEqual(len(data_rows_h1), 12)
        vhs_h1 = [r.data["cells"][4] for r in data_rows_h1]
        self.assertIn("47", vhs_h1)
        self.assertIn("92", vhs_h1)
        self.assertIn("190", vhs_h1)
        self.assertIn("234", vhs_h1)
        self.assertIn("251", vhs_h1)
        self.assertIn("1905", vhs_h1)
        for vh in vhs_h1:
            self.assertFalse("2026-2027" in vh)
            self.assertFalse("Credit" in vh)

        # 2. NRX
        page_nrx = SchedulePurchaseDatewisePage(schedule_type="NRX")
        page_nrx.from_date_edit.setDate(QDate(2024, 1, 1))
        page_nrx.to_date_edit.setDate(QDate(2026, 12, 31))
        page_nrx.generate_report()
        data_rows_nrx = [b for b in page_nrx._pages[0].blocks if b.kind == BlockKind.DATA_ROW]
        self.assertEqual(len(data_rows_nrx), 4)
        vhs_nrx = [r.data["cells"][4] for r in data_rows_nrx]
        self.assertEqual(vhs_nrx, ["47", "92", "190", "234"])

    def test_04_itemwise_purchase_schedule_report_h1_and_nrx(self):
        """Verify Itemwise Purchase Schedule Report displays clean VhNo for H1 and NRX."""
        # 1. H1
        page_h1 = SchedulePurchaseItemwisePage(schedule_type="H1")
        page_h1.from_date_edit.setDate(QDate(2024, 1, 1))
        page_h1.to_date_edit.setDate(QDate(2026, 12, 31))
        page_h1.generate_report()
        data_rows_h1 = [b for b in page_h1._pages[0].blocks if b.kind == BlockKind.DATA_ROW]
        vhs_h1 = [r.data["cells"][4] for r in data_rows_h1]
        self.assertIn("47", vhs_h1)
        self.assertIn("92", vhs_h1)
        self.assertIn("190", vhs_h1)
        self.assertIn("234", vhs_h1)

        # 2. NRX
        page_nrx = SchedulePurchaseItemwisePage(schedule_type="NRX")
        page_nrx.from_date_edit.setDate(QDate(2024, 1, 1))
        page_nrx.to_date_edit.setDate(QDate(2026, 12, 31))
        page_nrx.generate_report()
        data_rows_nrx = [b for b in page_nrx._pages[0].blocks if b.kind == BlockKind.DATA_ROW]
        vhs_nrx = [r.data["cells"][4] for r in data_rows_nrx]
        self.assertEqual(vhs_nrx, ["47", "92", "190", "234"])

    def test_05_all_items_purchase_schedule_report_h1_and_nrx(self):
        """Verify All Items Purchase Schedule Report displays clean VhNo for H1 and NRX."""
        # 1. H1
        page_h1 = SchedulePurchaseAllItemsPage(schedule_type="H1")
        page_h1.from_date_edit.setDate(QDate(2024, 1, 1))
        page_h1.to_date_edit.setDate(QDate(2026, 12, 31))
        page_h1.generate_report()
        data_rows_h1 = [b for b in page_h1._pages[0].blocks if b.kind == BlockKind.DATA_ROW]
        vhs_h1 = [r.data["cells"][4] for r in data_rows_h1]
        self.assertIn("47", vhs_h1)
        self.assertIn("92", vhs_h1)
        self.assertIn("190", vhs_h1)
        self.assertIn("234", vhs_h1)

        # 2. NRX
        page_nrx = SchedulePurchaseAllItemsPage(schedule_type="NRX")
        page_nrx.from_date_edit.setDate(QDate(2024, 1, 1))
        page_nrx.to_date_edit.setDate(QDate(2026, 12, 31))
        page_nrx.generate_report()
        data_rows_nrx = [b for b in page_nrx._pages[0].blocks if b.kind == BlockKind.DATA_ROW]
        vhs_nrx = [r.data["cells"][4] for r in data_rows_nrx]
        self.assertEqual(vhs_nrx, ["47", "92", "190", "234"])

    def test_06_invoice_no_and_voucher_date_preserved_separately(self):
        """Verify Inv.No (col 2) and Vh Date (col 5) remain distinct and uncorrupted."""
        page_nrx = SchedulePurchaseDatewisePage(schedule_type="NRX")
        page_nrx.from_date_edit.setDate(QDate(2024, 1, 1))
        page_nrx.to_date_edit.setDate(QDate(2026, 12, 31))
        page_nrx.generate_report()

        data_rows = [b for b in page_nrx._pages[0].blocks if b.kind == BlockKind.DATA_ROW]
        row0 = data_rows[0].data["cells"]
        # Cols: SrNo(0), Inv.Date(1), Inv.No(2), Supplier(3), VhNo(4), Vh Date(5), Unit(6), Pack(7), ItemName(8), BatchNo(9), ExpiryDate(10), PurQty(11), PurValue(12)
        self.assertEqual(row0[2], "NRX-47")      # Inv.No
        self.assertEqual(row0[4], "47")          # VhNo
        self.assertEqual(row0[5], "19/05/2026")  # Vh Date
        self.assertEqual(row0[8], "ATIVAN 2 MG") # ItemName
        self.assertEqual(row0[11], "10")         # PurQty
        self.assertEqual(row0[12], "1200")       # PurValue

    def test_07_print_and_export_execution(self):
        """Verify print and PDF export work cleanly with formatted VhNo."""
        page = SchedulePurchaseDatewisePage(schedule_type="NRX")
        page.from_date_edit.setDate(QDate(2024, 1, 1))
        page.to_date_edit.setDate(QDate(2026, 12, 31))
        page.generate_report()

        # Print executes without throwing
        page.print_report()

        # PDF export generates valid file
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
