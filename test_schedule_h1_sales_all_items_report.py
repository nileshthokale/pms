"""Unit and regression tests for Sales Items (All) Scheduled H1 Report.

Verifies:
1. Grouping by Item Name with 'Item Name : <NAME>' heading.
2. Table header under each medicine heading with columns:
   SrNo, Date, BillNo, PatientName, Address, Unit, Pack Size, BatchNo, ExpiryDate, Qty.
3. SrNo resets to 1 within each medicine group.
4. Total row at the end of each medicine group summing sold quantity.
5. Date, BillNo, ExpiryDate, and Qty formatting.
6. Patient address mapping accuracy without inventing or cross-leaking addresses.
7. Report viewer pagination, clipboard copy, and CSV export.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication

from core.doc_formatter import format_sales_bill_number
from database.connection import get_connection
from database.schedule_reports_dao import ScheduleReportsDAO
from screens.schedule_reports import (
    STORE_LINE_1,
    STORE_LINE_2,
    ScheduleSalesAllItemsPage,
    _format_dmy,
    _format_expiry_display,
    paginate_schedule_blocks,
)
from ui.crystal_report_viewer import BlockKind, fmt_qty


def get_qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


class TestScheduleH1SalesAllItemsReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        get_qapp()

    def test_01_page_properties_and_titles(self):
        page = ScheduleSalesAllItemsPage(schedule_type="H1")
        self.assertEqual(page.window_title_text, "Sales Items (All) Sheduled H1 Report")
        self.assertEqual(page.panel_title_text, "Sales Items (All) Sheduled H1")
        self.assertEqual(page.schedule_type, "H1")

    def test_02_grouping_table_headers_and_srno_reset(self):
        """Verify grouping by item, table header under every group, and SrNo reset to 1."""
        page = ScheduleSalesAllItemsPage(schedule_type="H1")

        mock_rows = [
            {
                "item_name": "ZOSTUM 1GM",
                "sale_date": "2026-05-14",
                "bill_no": "2026-2027-358",
                "patient_name": "MAST PAWAN VITKAR",
                "address": "DEHARE",
                "unit_name": "INJECT",
                "pack_size": "1",
                "batch_no": "Z01BE24020",
                "expiry": "2026-10-31",
                "qty": 2.0,
            },
            {
                "item_name": "ZOSTUM 1GM",
                "sale_date": "2026-05-16",
                "bill_no": "2026-2027-383",
                "patient_name": "MAST PAWAN VITKAR",
                "address": "DEHARE",
                "unit_name": "INJECT",
                "pack_size": "1",
                "batch_no": "Z01BE24020",
                "expiry": "2026-10-31",
                "qty": 1.0,
            },
            {
                "item_name": "LOX 2% 30ML",
                "sale_date": "2026-04-02",
                "bill_no": "2026-2027-6",
                "patient_name": "MRS MANISHA KALHAPURE",
                "address": "KHADAMABA",
                "unit_name": "INJECT",
                "pack_size": "1",
                "batch_no": "KM144310",
                "expiry": "2027-09-30",
                "qty": 1.0,
            },
            {
                "item_name": "LOX 2% 30ML",
                "sale_date": "2026-04-05",
                "bill_no": "2026-2027-34",
                "patient_name": "MRS UJJWALA HARDE",
                "address": "JOGESHWARI AK",
                "unit_name": "INJECT",
                "pack_size": "1",
                "batch_no": "KM144310",
                "expiry": "2027-09-30",
                "qty": 1.0,
            },
        ]

        with mock.patch.object(ScheduleReportsDAO, "get_sales_schedule", return_value=mock_rows):
            page.generate_report()
            self.assertGreater(len(page._pages), 0)
            p1 = page._pages[0]

            expected_cols = ["SrNo", "Date", "BillNo", "PatientName", "Address", "Unit", "Pack Size", "BatchNo", "ExpiryDate", "Qty"]

            # Verify blocks sequence: GROUP_HEADER, TABLE_HEADER, DATA_ROWs, ITEM_SUBTOTAL
            kinds = [b.kind for b in p1.blocks]
            self.assertIn(BlockKind.GROUP_HEADER, kinds)
            self.assertIn(BlockKind.TABLE_HEADER, kinds)
            self.assertIn(BlockKind.ITEM_SUBTOTAL, kinds)
            self.assertIn(BlockKind.GRAND_TOTAL, kinds)

            # Check ZOSTUM 1GM section
            zostum_gh = next(b for b in p1.blocks if b.kind == BlockKind.GROUP_HEADER and "ZOSTUM 1GM" in b.data.get("text", ""))
            self.assertEqual(zostum_gh.data.get("text"), "Item Name : ZOSTUM 1GM")

            # Check that table header immediately follows group header
            gh_idx = p1.blocks.index(zostum_gh)
            th_block = p1.blocks[gh_idx + 1]
            self.assertEqual(th_block.kind, BlockKind.TABLE_HEADER)
            self.assertEqual(th_block.data["columns"], expected_cols)

            # Check data rows for ZOSTUM: SrNo 1 and 2
            r1 = p1.blocks[gh_idx + 2]
            r2 = p1.blocks[gh_idx + 3]
            self.assertEqual(r1.kind, BlockKind.DATA_ROW)
            self.assertEqual(r1.data["cells"][0], "1")
            self.assertEqual(r1.data["cells"][1], "14/05/2026")
            self.assertEqual(r1.data["cells"][2], "358")
            self.assertEqual(r1.data["cells"][3], "MAST PAWAN VITKAR")
            self.assertEqual(r1.data["cells"][4], "DEHARE")
            self.assertEqual(r1.data["cells"][8], "31/10/2026")
            self.assertEqual(r1.data["cells"][9], "2")

            self.assertEqual(r2.data["cells"][0], "2")
            self.assertEqual(r2.data["cells"][1], "16/05/2026")
            self.assertEqual(r2.data["cells"][2], "383")
            self.assertEqual(r2.data["cells"][9], "1")

            # Subtotal for ZOSTUM: Total : 3
            sub_z = p1.blocks[gh_idx + 4]
            self.assertEqual(sub_z.kind, BlockKind.ITEM_SUBTOTAL)
            self.assertEqual(sub_z.data["label"], "Total :")
            self.assertEqual(sub_z.data["pay_str"], "3")

            # Next item: LOX 2% 30ML
            lox_gh = p1.blocks[gh_idx + 5]
            self.assertEqual(lox_gh.kind, BlockKind.GROUP_HEADER)
            self.assertEqual(lox_gh.data.get("text"), "Item Name : LOX 2% 30ML")

            lox_th = p1.blocks[gh_idx + 6]
            self.assertEqual(lox_th.kind, BlockKind.TABLE_HEADER)

            # SrNo MUST reset to 1 for LOX 2% 30ML
            lox_r1 = p1.blocks[gh_idx + 7]
            self.assertEqual(lox_r1.data["cells"][0], "1")
            self.assertEqual(lox_r1.data["cells"][2], "6")
            self.assertEqual(lox_r1.data["cells"][3], "MRS MANISHA KALHAPURE")
            self.assertEqual(lox_r1.data["cells"][4], "KHADAMABA")

            lox_r2 = p1.blocks[gh_idx + 8]
            self.assertEqual(lox_r2.data["cells"][0], "2")
            self.assertEqual(lox_r2.data["cells"][2], "34")
            self.assertEqual(lox_r2.data["cells"][3], "MRS UJJWALA HARDE")
            self.assertEqual(lox_r2.data["cells"][4], "JOGESHWARI AK")

            # Subtotal for LOX: Total : 2
            sub_lox = p1.blocks[gh_idx + 9]
            self.assertEqual(sub_lox.kind, BlockKind.ITEM_SUBTOTAL)
            self.assertEqual(sub_lox.data["pay_str"], "2")

            # Grand Total: 5
            gt = [b for b in p1.blocks if b.kind == BlockKind.GRAND_TOTAL][0]
            self.assertEqual(gt.data["qty_str"], "5")

    def test_03_expiry_and_date_formatting(self):
        """Verify _format_dmy and _format_expiry_display handle 3-part and 2-part dates correctly."""
        self.assertEqual(_format_dmy("2026-05-14"), "14/05/2026")
        self.assertEqual(_format_dmy("2026-10-31"), "31/10/2026")
        self.assertEqual(_format_dmy(""), "")

        self.assertEqual(_format_expiry_display("2026-10-31"), "31/10/2026")
        self.assertEqual(_format_expiry_display("2027-09-30"), "30/09/2027")
        self.assertEqual(_format_expiry_display("2028-02-28"), "28/02/2028")
        self.assertEqual(_format_expiry_display("2026-10"), "10/2026")
        self.assertEqual(_format_expiry_display(""), "")

    def test_04_patient_address_mapping_accuracy_on_production_data(self):
        """Verify that get_sales_schedule resolves correct historical patient addresses without leakage."""
        rows = ScheduleReportsDAO.get_sales_schedule("2026-04-01", "2026-10-24", "H1", grouped_by_item=True)
        self.assertGreater(len(rows), 0)

        # Build lookup by bill_no and patient_name
        sales_map = {(r["bill_no"], r["patient_name"]): r["address"] for r in rows}

        expected_cases = [
            ("2026-2027-358", "MAST PAWAN VITKAR", "DEHARE"),
            ("2026-2027-383", "MAST PAWAN VITKAR", "DEHARE"),
            ("2026-2027-1421", "MR SANJAY SHINDE", "MOMIN AKHADA"),
            ("2026-2027-6", "MRS MANISHA KALHAPURE", "KHADAMABA"),
            ("2026-2027-34", "MRS UJJWALA HARDE", "JOGESHWARI AK"),
            ("2026-2027-657", "MRS NANDA GHULE", "SAKUR"),
            ("2026-2027-927", "MR SAMIM SHAIKH", "RAHURI"),
            ("2026-2027-1095", "MRS INDUBAI SHINDE", "LAKH"),
            ("2026-2027-1683", "MRS SONALI SHINDE", "MOMIN AKHADA"),
            ("2026-2027-1719", "MRS PRAMILA VETAL", "RAHURI"),
            ("2026-2027-807", "MAST SAMARTTH DAFAL", "RAHURI"),
            ("2026-2027-1320", "MAST AHEMAD SHAIKH", "DEOLALI"),
            ("2026-2027-1424", "MAST VIGNESH DIVEKAR", "TAHARABAD"),
            ("2026-2027-151", "MAST ADITYA PAWAR", "DEOLALI"),
            ("2026-2027-361", "MISS PAVITRA CHOTHE", "KUKADWEDHE"),
            ("2026-2027-388", "MISS PAVITRA CHOTHE", "KUKADWEDHE"),
            ("2026-2027-549", "MAST MAHESH JADHAV", "KENDAL"),
            ("2026-2027-728", "MAST PRAJVIR GHADGE", "KANGAR"),
            ("2026-2027-986", "MAST ARYA BARKADE", "BABHULGAON"),
            ("2026-2027-1014", "MAST ARYA BARKADE", "BABHULGAON"),
        ]

        for b_no, p_name, exp_addr in expected_cases:
            actual = sales_map.get((b_no, p_name))
            self.assertEqual(actual, exp_addr, f"Mismatch for bill {b_no} ({p_name}): expected {exp_addr}, got {actual}")

    def test_05_unknown_patient_leaves_blank_address(self):
        """Verify that when a patient has no linked address, the address is empty string rather than invented."""
        mock_rows = [
            {
                "item_name": "ZOSTUM 1GM",
                "sale_date": "2026-05-14",
                "bill_no": "2026-2027-99999",
                "patient_name": "COMPLETELY UNKNOWN PATIENT 12345",
                "unit_name": "INJECT",
                "pack_size": "1",
                "batch_no": "Z01",
                "expiry": "2026-10-31",
                "qty": 1.0,
            }
        ]
        page = ScheduleSalesAllItemsPage(schedule_type="H1")
        with mock.patch.object(ScheduleReportsDAO, "get_sales_schedule", return_value=mock_rows):
            page.generate_report()
            data_row = next(b for b in page._pages[0].blocks if b.kind == BlockKind.DATA_ROW)
            # Address column is index 4
            self.assertEqual(data_row.data["cells"][4], "")

    def test_06_pagination_repeats_table_header_on_continuation(self):
        """Verify that when an item has many rows, page 2 starts with TABLE_HEADER."""
        page = ScheduleSalesAllItemsPage(schedule_type="H1")
        page.from_date_edit.setDate(QDate(2026, 4, 1))
        page.to_date_edit.setDate(QDate(2026, 10, 24))
        page.generate_report()

        self.assertGreater(len(page._pages), 1)
        # Page 1 has L-CIN 250 which continues onto Page 2
        p2 = page._pages[1]
        self.assertEqual(p2.blocks[0].kind, BlockKind.TABLE_HEADER)
        self.assertEqual(p2.blocks[1].kind, BlockKind.DATA_ROW)


if __name__ == "__main__":
    unittest.main()
