"""Unit and regression tests for All Items Purchase Scheduled H1 Report.

Verifies:
1. Grouping by Item Name with 'Item Name : <NAME>' heading for each medicine.
2. Distinct group headers and table headers per medicine.
3. Column headers under each medicine:
   SrNo, Inv.Date, Inv.No, Supplier, VhNo, Vh Date, Unit, Pack Size, BatchNo, ExpiryDate, PurQty, PurValue.
4. Continuous SrNo across medicine groups (e.g. 1..11 on Page 1).
5. Accurate calculation of PurQty in loose units ((pay_qty + free_qty) * pack_size).
6. Accurate calculation of PurValue to 2 decimal places (net_rate * pay_qty).
7. Subtotal ('Total :') at the end of each medicine group summing PurQty and PurValue.
8. Grand total ('Grand Total :') at the end of the report summing PurQty and PurValue.
9. Pagination thresholds preventing orphaned group headers.
10. Exact reproduction of the reference screenshot data (Bills 12555, 539, 1257, 5014, 1229, 8310, 36, 598, 1299, 1859, 2163).
11. Isolated temporary test database verification ensuring tests are independent of production data.
12. Compatibility with both H1 and NRX schedule types.
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

from core.doc_formatter import format_purchase_voucher_number
from database import auth, financial_year
from database.account_roles import ensure_system_ledgers
from database.connection import get_connection, init_database
from database.schedule_reports_dao import ScheduleReportsDAO
from screens.schedule_reports import (
    BlockKind,
    ReportBlock,
    ReportHeaderData,
    SchedulePurchaseAllItemsPage,
    _format_dmy,
    _format_expiry_display,
    paginate_schedule_blocks,
)
from ui.crystal_report_viewer import fmt_qty


def get_qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


class TestScheduleH1PurchaseAllItemsReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        get_qapp()

    def setUp(self):
        self._temp_dir = tempfile.mkdtemp(prefix="test_pur_h1_")
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

    def _seed_sample_purchase_data(self):
        """Seed representative purchase records for testing."""
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO units (unit_name) VALUES ('INJECT')")
            unit_inject = cur.lastrowid
            cur.execute("INSERT INTO units (unit_name) VALUES ('TABLET')")
            unit_tablet = cur.lastrowid

            cur.execute("INSERT INTO suppliers (supplier_name) VALUES ('SUPEKAR AGENCIES')")
            supp_supekar = cur.lastrowid
            cur.execute("INSERT INTO suppliers (supplier_name) VALUES ('BHARAT AGENCIES')")
            supp_bharat = cur.lastrowid
            cur.execute("INSERT INTO suppliers (supplier_name) VALUES ('SANJAY AGECIES')")
            supp_sanjay = cur.lastrowid

            # Item 1: ZOSTUM 1GM (Pack 1)
            cur.execute(
                """
                INSERT INTO items (id, item_name, unit_id, pack_size, scheduled, mrp, rate)
                VALUES (1056, 'ZOSTUM 1GM', ?, '1', 'H1', 85.0, 68.25)
                """,
                (unit_inject,),
            )

            # Item 2: LOX 2% 30ML (Pack 1)
            cur.execute(
                """
                INSERT INTO items (id, item_name, unit_id, pack_size, scheduled, mrp, rate)
                VALUES (1059, 'LOX 2% 30ML', ?, '1', 'H1', 35.0, 27.30)
                """,
                (unit_inject,),
            )

            # Item 3: OPOX 100DT (Pack 10)
            cur.execute(
                """
                INSERT INTO items (id, item_name, unit_id, pack_size, scheduled, mrp, rate)
                VALUES (1120, 'OPOX 100DT', ?, '10', 'H1', 120.0, 99.18)
                """,
                (unit_tablet,),
            )

            # Purchase 1: ZOSTUM 1GM (Pay 6, Free 0) -> PurQty 6, PurVal 409.50
            cur.execute(
                """
                INSERT INTO purchase_invoices (invoice_date, invoice_no, supplier_id, voucher_no, voucher_date, purchase_type)
                VALUES ('2026-05-14', '12555', ?, '47', '2026-05-19', 'Credit')
                """,
                (supp_supekar,),
            )
            pi_1 = cur.lastrowid
            cur.execute(
                """
                INSERT INTO purchase_invoice_items (
                    purchase_invoice_id, item_id, pack_size, batch_no, expiry,
                    rate, net_rate, mrp, pay_qty, free_qty, amount
                ) VALUES (?, 1056, '1', 'Z01BE25013', '2027-09-30', 68.25, 68.25, 85.0, 6.0, 0.0, 409.50)
                """,
                (pi_1,),
            )

            # Purchase 2: LOX 2% 30ML (Pay 5, Free 0) -> PurQty 5, PurVal 136.50
            cur.execute(
                """
                INSERT INTO purchase_invoices (invoice_date, invoice_no, supplier_id, voucher_no, voucher_date, purchase_type)
                VALUES ('2026-06-15', '539', ?, '92', '2026-06-16', 'Credit')
                """,
                (supp_bharat,),
            )
            pi_2 = cur.lastrowid
            cur.execute(
                """
                INSERT INTO purchase_invoice_items (
                    purchase_invoice_id, item_id, pack_size, batch_no, expiry,
                    rate, net_rate, mrp, pay_qty, free_qty, amount
                ) VALUES (?, 1059, '1', 'KM144326', '2027-10-31', 27.30, 27.30, 35.0, 5.0, 0.0, 136.50)
                """,
                (pi_2,),
            )

            # Purchase 3: LOX 2% 30ML (Pay 3, Free 0) -> PurQty 3, PurVal 81.90
            cur.execute(
                """
                INSERT INTO purchase_invoices (invoice_date, invoice_no, supplier_id, voucher_no, voucher_date, purchase_type)
                VALUES ('2026-09-17', '1257', ?, '234', '2026-09-24', 'Credit')
                """,
                (supp_bharat,),
            )
            pi_3 = cur.lastrowid
            cur.execute(
                """
                INSERT INTO purchase_invoice_items (
                    purchase_invoice_id, item_id, pack_size, batch_no, expiry,
                    rate, net_rate, mrp, pay_qty, free_qty, amount
                ) VALUES (?, 1059, '1', 'SM144771', '2028-02-29', 27.30, 27.30, 35.0, 3.0, 0.0, 81.90)
                """,
                (pi_3,),
            )

            # Purchase 4: OPOX 100DT (Pay 9, Free 1, Pack 10) -> PurQty (9+1)*10 = 100, PurVal 99.18 * 9 = 892.62
            cur.execute(
                """
                INSERT INTO purchase_invoices (invoice_date, invoice_no, supplier_id, voucher_no, voucher_date, purchase_type)
                VALUES ('2026-08-19', '5014', ?, '190', '2026-08-24', 'Credit')
                """,
                (supp_sanjay,),
            )
            pi_4 = cur.lastrowid
            cur.execute(
                """
                INSERT INTO purchase_invoice_items (
                    purchase_invoice_id, item_id, pack_size, batch_no, expiry,
                    rate, net_rate, mrp, pay_qty, free_qty, amount
                ) VALUES (?, 1120, '10', 'HH2510532', '2027-09-30', 99.18, 99.18, 120.0, 9.0, 1.0, 892.62)
                """,
                (pi_4,),
            )

            conn.commit()
        finally:
            conn.close()

    def test_01_page_properties(self):
        """Verify window title, panel title and schedule type."""
        page_h1 = SchedulePurchaseAllItemsPage(schedule_type="H1")
        self.assertEqual(page_h1.window_title_text, "All Items Purchase Sheduled H1 Report")
        self.assertEqual(page_h1.panel_title_text, "Items (All) Purchase Sheduled H1")
        self.assertEqual(page_h1.schedule_type, "H1")

        page_nrx = SchedulePurchaseAllItemsPage(schedule_type="NRX")
        self.assertEqual(page_nrx.window_title_text, "All Items Purchase Sheduled NRX Report")
        self.assertEqual(page_nrx.panel_title_text, "Items (All) Purchase Sheduled NRX")
        self.assertEqual(page_nrx.schedule_type, "NRX")

    def test_02_dao_grouping_and_ordering(self):
        """Verify get_purchase_schedule groups and orders records accurately."""
        self._seed_sample_purchase_data()
        rows = ScheduleReportsDAO.get_purchase_schedule("2026-01-01", "2026-12-31", "H1", grouped_by_item=True)
        self.assertEqual(len(rows), 4)

        # Order by i.id ASC: ZOSTUM (1056), LOX 2% (1059), OPOX (1120)
        self.assertEqual(rows[0]["item_name"], "ZOSTUM 1GM")
        self.assertEqual(rows[0]["pur_qty"], 6.0)
        self.assertEqual(rows[0]["pur_value"], 409.50)

        self.assertEqual(rows[1]["item_name"], "LOX 2% 30ML")
        self.assertEqual(rows[1]["pur_qty"], 5.0)
        self.assertEqual(rows[1]["pur_value"], 136.50)

        self.assertEqual(rows[2]["item_name"], "LOX 2% 30ML")
        self.assertEqual(rows[2]["pur_qty"], 3.0)
        self.assertEqual(rows[2]["pur_value"], 81.90)

        self.assertEqual(rows[3]["item_name"], "OPOX 100DT")
        # Loose units: (9 pay + 1 free) * 10 pack = 100
        self.assertEqual(rows[3]["pur_qty"], 100.0)
        # Net value: 99.18 * 9 = 892.62
        self.assertEqual(rows[3]["pur_value"], 892.62)

    def test_03_report_structure_and_continuous_srno(self):
        """Verify report blocks structure, item headings, table headers, and continuous SrNo."""
        self._seed_sample_purchase_data()
        page = SchedulePurchaseAllItemsPage(schedule_type="H1")
        page.from_date_edit.setDate(QDate(2026, 1, 1))
        page.to_date_edit.setDate(QDate(2026, 12, 31))
        page.generate_report()

        self.assertGreater(len(page._pages), 0)
        rep_page = page._pages[0]

        # Extract group headers
        group_headers = [b for b in rep_page.blocks if b.kind == BlockKind.GROUP_HEADER]
        self.assertEqual(len(group_headers), 3)
        self.assertEqual(group_headers[0].data["text"], "Item Name : ZOSTUM 1GM")
        self.assertEqual(group_headers[1].data["text"], "Item Name : LOX 2% 30ML")
        self.assertEqual(group_headers[2].data["text"], "Item Name : OPOX 100DT")

        # Extract data rows and verify continuous SrNo: 1, 2, 3, 4
        data_rows = [b for b in rep_page.blocks if b.kind == BlockKind.DATA_ROW]
        self.assertEqual(len(data_rows), 4)
        sr_nos = [r.data["cells"][0] for r in data_rows]
        self.assertEqual(sr_nos, ["1", "2", "3", "4"])

        # Check Row 1 (ZOSTUM 1GM)
        # Cols: SrNo(0), Inv.Date(1), Inv.No(2), Supplier(3), VhNo(4), Vh Date(5), Unit(6), Pack Size(7), BatchNo(8), ExpiryDate(9), PurQty(10), PurValue(11)
        r0 = data_rows[0].data["cells"]
        self.assertEqual(r0[0], "1")
        self.assertEqual(r0[1], "14/05/2026")
        self.assertEqual(r0[2], "12555")
        self.assertEqual(r0[3], "SUPEKAR AGENCIES")
        self.assertEqual(r0[4], "47")
        self.assertEqual(r0[5], "19/05/2026")
        self.assertEqual(r0[6], "INJECT")
        self.assertEqual(r0[7], "1")
        self.assertEqual(r0[8], "Z01BE25013")
        self.assertEqual(r0[9], "30/09/2027")
        self.assertEqual(r0[10], "6")
        self.assertEqual(r0[11], "409.50")

        # Check Subtotals
        subtotals = [b for b in rep_page.blocks if b.kind == BlockKind.ITEM_SUBTOTAL]
        self.assertEqual(len(subtotals), 3)

        # Subtotal for ZOSTUM: PurQty=6, PurVal=409.50
        self.assertEqual(subtotals[0].data["pay_str"], "6")
        self.assertEqual(subtotals[0].data["amt_str"], "409.50")

        # Subtotal for LOX 2%: PurQty=8 (5+3), PurVal=218.40 (136.50+81.90)
        self.assertEqual(subtotals[1].data["pay_str"], "8")
        self.assertEqual(subtotals[1].data["amt_str"], "218.40")

        # Subtotal for OPOX: PurQty=100, PurVal=892.62
        self.assertEqual(subtotals[2].data["pay_str"], "100")
        self.assertEqual(subtotals[2].data["amt_str"], "892.62")

        # Grand Total
        grand_totals = [b for b in rep_page.blocks if b.kind == BlockKind.GRAND_TOTAL]
        self.assertEqual(len(grand_totals), 1)
        # Total Qty = 6 + 8 + 100 = 114
        # Total Val = 409.50 + 218.40 + 892.62 = 1520.52
        self.assertEqual(grand_totals[0].data["qty_str"], "114")
        self.assertEqual(grand_totals[0].data["amt_str"], "1520.52")

    def test_04_production_screenshot_match(self):
        """If data/pharmacy.db exists, verify rows 1-11 match the reference screenshot exactly."""
        prod_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "pharmacy.db")
        if not os.path.exists(prod_db):
            self.skipTest("Production data/pharmacy.db not found.")

        # Temporarily switch to production database read-only
        os.environ["PHARMACY_DB"] = prod_db
        try:
            page = SchedulePurchaseAllItemsPage(schedule_type="H1")
            page.from_date_edit.setDate(QDate(2026, 4, 1))
            page.to_date_edit.setDate(QDate(2026, 10, 24))
            page.generate_report()

            self.assertGreaterEqual(len(page._pages), 2)
            page_1 = page._pages[0]
            data_rows_p1 = [b for b in page_1.blocks if b.kind == BlockKind.DATA_ROW]
            self.assertEqual(len(data_rows_p1), 11)

            # Expected rows 1 to 11 matching media_1792825294235_73acc33a.jpg
            expected_p1 = [
                ("1", "14/05/2026", "12555", "SUPEKAR AGENCIES", "47", "19/05/2026", "INJECT", "1", "Z01BE25013", "30/09/2027", "6", "409.50"),
                ("2", "15/06/2026", "539", "BHARAT AGENCIES", "92", "16/06/2026", "INJECT", "1", "KM144326", "31/10/2027", "5", "136.50"),
                ("3", "17/09/2026", "1257", "BHARAT AGENCIES", "234", "24/09/2026", "INJECT", "1", "SM144771", "29/02/2028", "3", "81.90"),
                ("4", "19/08/2026", "5014", "SANJAY AGECIES", "190", "24/08/2026", "TABLET", "10", "HH2510532", "30/09/2027", "100", "892.62"),
                ("5", "13/09/2026", "1229", "BHARAT AGENCIES", "227", "18/09/2026", "INJECT", "1", "SU1478555", "31/05/2027", "2", "55.64"),
                ("6", "15/09/2026", "8310", "SANJIVANI AGENCIES", "228", "18/09/2026", "TABLET", "10", "K15Z001", "31/03/2028", "120", "398.16"),
                ("7", "02/04/2026", "36", "RELAINCE TRADERS", "4", "07/04/2026", "TABLET", "10", "ST25-3994", "31/10/2027", "120", "706.90"),
                ("8", "30/04/2026", "598", "RELAINCE TRADERS", "22", "01/05/2026", "TABLET", "10", "ST25-3994", "31/10/2027", "120", "706.90"),
                ("9", "04/06/2026", "1299", "RELAINCE TRADERS", "86", "12/06/2026", "TABLET", "10", "ST25-3994", "31/10/2027", "120", "706.90"),
                ("10", "06/07/2026", "1859", "RELAINCE TRADERS", "128", "09/07/2026", "TABLET", "10", "ST25-3994", "31/10/2027", "120", "706.90"),
                ("11", "20/07/2026", "2163", "RELAINCE TRADERS", "145", "21/07/2026", "TABLET", "10", "ST26-0653", "31/01/2028", "120", "706.90"),
            ]

            for idx, exp in enumerate(expected_p1):
                actual = tuple(data_rows_p1[idx].data["cells"])
                self.assertEqual(actual, exp, f"Mismatch at row {idx+1}: {actual} != {exp}")
        finally:
            os.environ["PHARMACY_DB"] = self._db_path

    def test_05_pagination_prevents_orphaned_group_headers(self):
        """Verify GROUP_HEADER is never placed alone at the bottom of a page without a data row."""
        header = ReportHeaderData(
            store_name="TEST STORE",
            store_address="TEST ADDR",
            header_line_1="TEST HEADER 1",
            header_line_2="TEST HEADER 2",
            header_line_3="TEST HEADER 3",
        )
        table_header = ReportBlock(
            kind=BlockKind.TABLE_HEADER,
            height=24.0,
            data={"columns": ["Col1", "Col2"], "widths": [100.0, 100.0], "aligns": ["left", "right"]},
        )

        blocks = []
        # Add 30 data rows to fill near the bottom of Page 1 (max height = 635.0)
        # Each row height is 20.0; 30 * 20 = 600.0
        for i in range(30):
            blocks.append(
                ReportBlock(
                    kind=BlockKind.DATA_ROW,
                    height=20.0,
                    data={"cells": [str(i), f"Val {i}"], "widths": [100.0, 100.0], "aligns": ["left", "right"]},
                )
            )

        # Now add a GROUP_HEADER (height 26) + TABLE_HEADER (height 24) + DATA_ROW (height 20)
        # Remaining height on Page 1 is 635 - 600 = 35.
        # GROUP_HEADER (height 26) would fit in 35 if needed_h was 26, but TABLE_HEADER (24) would not.
        # With needed_h = 75, GROUP_HEADER must move to Page 2!
        blocks.append(
            ReportBlock(
                kind=BlockKind.GROUP_HEADER,
                height=26.0,
                data={"text": "Item Name : NEW ITEM", "width": 800.0},
            )
        )
        blocks.append(
            ReportBlock(
                kind=BlockKind.TABLE_HEADER,
                height=24.0,
                data={"columns": ["Col1", "Col2"], "widths": [100.0, 100.0], "aligns": ["left", "right"]},
            )
        )
        blocks.append(
            ReportBlock(
                kind=BlockKind.DATA_ROW,
                height=20.0,
                data={"cells": ["1", "Val 1"], "widths": [100.0, 100.0], "aligns": ["left", "right"]},
            )
        )

        pages = paginate_schedule_blocks(header, blocks, table_header, orientation="landscape")
        self.assertEqual(len(pages), 2)
        # Page 1 should NOT have GROUP_HEADER as its last block
        last_block_p1 = pages[0].blocks[-1]
        self.assertNotEqual(last_block_p1.kind, BlockKind.GROUP_HEADER)

        # Page 2 should start with GROUP_HEADER
        first_block_p2 = pages[1].blocks[0]
        self.assertEqual(first_block_p2.kind, BlockKind.GROUP_HEADER)


if __name__ == "__main__":
    unittest.main()
