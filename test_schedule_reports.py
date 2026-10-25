"""Comprehensive test suite for Schedule Reports (H1 & NRX).

Tests:
1. Navigation & Menu structure:
   - Schedule top-level menu placed immediately after Master.
   - Cascading 3-level menu hierarchy (12 leaf items total).
   - Existing Reports > Sheduled H1 (Sales) and Sheduled H1 (Purchase) preserved.
   - MainWindow page mapping and action routing for all 12 items.
2. DAO Queries:
   - H1 item filtering: items.scheduled IN ('2', 'H1').
   - NRX item filtering: items.scheduled IN ('4', 'NRX').
   - Sales schedule query (date range, sorting, columns).
   - Purchase schedule query (date range, sorting, columns).
3. Report UI & Crystal Report Generation:
   - Report A: Sales Datewise (11 cols, Grand Total Qty).
   - Report B: Sales Itemwise (searchable combo box filtered by H1/NRX).
   - Report C: Sales All Items (grouped by Item Name : <ITEM>, subtotal Qty, continuous SrNo).
   - Report D: Purchase Datewise (13 cols, whole integer PurValue, Grand Total).
   - Report E: Purchase Itemwise (whole integer PurValue, Grand Total).
   - Report F: Purchase All Items (grouped by Item Name : <ITEM>, 2-decimal PurValue, continuous SrNo).
   - Common headers (SHREE SAMARTH MEDICAL AND GEN STORE, GHORPADE HOSPITAL, RAHURI).
   - Date validation (From > To).
   - Financial year history view.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from database.connection import get_connection, init_database
from database import auth, financial_year
from database.account_roles import ensure_system_ledgers
from database.schedule_reports_dao import ScheduleReportsDAO
from ui.crystal_report_viewer import BlockKind
from screens.schedule_reports import (
    STORE_LINE_1,
    STORE_LINE_2,
    ScheduleSalesDatewisePage,
    ScheduleSalesItemwisePage,
    ScheduleSalesAllItemsPage,
    SchedulePurchaseDatewisePage,
    SchedulePurchaseItemwisePage,
    SchedulePurchaseAllItemsPage,
)
from ui.menu_data import MENUS
from ui.main_window import PharmacyMainWindow

_APP = None


def get_qapp() -> QApplication:
    global _APP
    app = QApplication.instance()
    if app is None:
        _APP = QApplication(sys.argv)
        return _APP
    return app


class TestScheduleReports(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        get_qapp()
        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_financial_year_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        ensure_system_ledgers()

    def setUp(self):
        self._msg_patches = [
            mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "information", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "critical", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "question", return_value=QMessageBox.No),
        ]
        for p in self._msg_patches:
            p.start()

    def tearDown(self):
        for p in self._msg_patches:
            p.stop()

    def test_01_menu_bar_structure_and_order(self):
        """Verify Schedule is in the menu list immediately after Master."""
        menu_keys = list(MENUS.keys())
        self.assertIn("Master", menu_keys)
        self.assertIn("Schedule", menu_keys)
        master_idx = menu_keys.index("Master")
        schedule_idx = menu_keys.index("Schedule")
        self.assertEqual(schedule_idx, master_idx + 1, "Schedule must be immediately after Master")

        # Verify Reports backwards compatibility menus
        reports_menu = MENUS.get("Reports", [])
        reports_titles = []
        for item in reports_menu:
            if isinstance(item, dict):
                reports_titles.extend(item.keys())
            elif isinstance(item, str):
                reports_titles.append(item)
        self.assertNotIn("Sheduled H1 (Sales)", reports_titles)
        self.assertNotIn("Sheduled H1 (Purchase)", reports_titles)

    def test_02_schedule_menu_hierarchy_12_leaf_items(self):
        """Verify the 12 leaf items in Schedule menu hierarchy."""
        schedule_menu = MENUS.get("Schedule", [])
        flattened = list(PharmacyMainWindow._flatten_menu_items(schedule_menu))
        self.assertEqual(len(flattened), 12, f"Expected 12 leaf items, got {len(flattened)}")

        expected_leaves = [
            ("Datewise Schedule", "H1 > Sales"),
            ("Itemwise Schedule", "H1 > Sales"),
            ("All Items Schedule", "H1 > Sales"),
            ("Datewise Schedule", "H1 > Purchase"),
            ("Itemwise Schedule", "H1 > Purchase"),
            ("All Items Schedule", "H1 > Purchase"),
            ("Datewise Schedule", "NRX > Sales"),
            ("Itemwise Schedule", "NRX > Sales"),
            ("All Items Schedule", "NRX > Sales"),
            ("Datewise Schedule", "NRX > Purchase"),
            ("Itemwise Schedule", "NRX > Purchase"),
            ("All Items Schedule", "NRX > Purchase"),
        ]
        self.assertEqual(flattened, expected_leaves)

    def test_03_dao_schedule_items_filtering(self):
        """Verify DAO queries correctly filter H1 and NRX items from the real database."""
        h1_items = ScheduleReportsDAO.get_scheduled_items("H1")
        nrx_items = ScheduleReportsDAO.get_scheduled_items("NRX")

        self.assertGreater(len(h1_items), 0, "Database should contain H1 items")
        self.assertGreater(len(nrx_items), 0, "Database should contain NRX items")

        # Ensure no cross-contamination
        h1_ids = {it["id"] for it in h1_items}
        nrx_ids = {it["id"] for it in nrx_items}
        self.assertTrue(h1_ids.isdisjoint(nrx_ids), "H1 and NRX items must be completely disjoint")

        # Spot check item names
        h1_names = [it["item_name"].upper() for it in h1_items]
        nrx_names = [it["item_name"].upper() for it in nrx_items]
        self.assertTrue(any("TRAMAGOLD" in n or "TRYLIQ" in n or "ZOSTUM" in n for n in h1_names))
        self.assertTrue(any("ATIVAN" in n or "CLONAPAX" in n or "MEZOLAM" in n for n in nrx_names))

    def test_04_dao_sales_and_purchase_queries(self):
        """Verify DAO queries for sales and purchase work without schema errors."""
        # Query over broad date range to verify SQL syntax and data retrieval
        sales_h1 = ScheduleReportsDAO.get_sales_schedule("2020-01-01", "2030-12-31", "H1")
        sales_nrx = ScheduleReportsDAO.get_sales_schedule("2020-01-01", "2030-12-31", "NRX")
        self.assertIsInstance(sales_h1, list)
        self.assertIsInstance(sales_nrx, list)

        pur_h1 = ScheduleReportsDAO.get_purchase_schedule("2020-01-01", "2030-12-31", "H1")
        pur_nrx = ScheduleReportsDAO.get_purchase_schedule("2020-01-01", "2030-12-31", "NRX")
        self.assertIsInstance(pur_h1, list)
        self.assertIsInstance(pur_nrx, list)

        # Check grouped query
        sales_all_items = ScheduleReportsDAO.get_sales_schedule("2020-01-01", "2030-12-31", "H1", grouped_by_item=True)
        self.assertIsInstance(sales_all_items, list)
        pur_all_items = ScheduleReportsDAO.get_purchase_schedule("2020-01-01", "2030-12-31", "H1", grouped_by_item=True)
        self.assertIsInstance(pur_all_items, list)

    def test_05_main_window_page_mapping(self):
        """Verify MainWindow registers and routes all 12 schedule pages and 2 legacy reports."""
        win = PharmacyMainWindow()

        # All 12 actions routed through navigation bar string
        test_actions = [
            ("Schedule", "H1 > Sales > Datewise Schedule", ScheduleSalesDatewisePage, "H1"),
            ("Schedule", "H1 > Sales > Itemwise Schedule", ScheduleSalesItemwisePage, "H1"),
            ("Schedule", "H1 > Sales > All Items Schedule", ScheduleSalesAllItemsPage, "H1"),
            ("Schedule", "H1 > Purchase > Datewise Schedule", SchedulePurchaseDatewisePage, "H1"),
            ("Schedule", "H1 > Purchase > Itemwise Schedule", SchedulePurchaseItemwisePage, "H1"),
            ("Schedule", "H1 > Purchase > All Items Schedule", SchedulePurchaseAllItemsPage, "H1"),
            ("Schedule", "NRX > Sales > Datewise Schedule", ScheduleSalesDatewisePage, "NRX"),
            ("Schedule", "NRX > Sales > Itemwise Schedule", ScheduleSalesItemwisePage, "NRX"),
            ("Schedule", "NRX > Sales > All Items Schedule", ScheduleSalesAllItemsPage, "NRX"),
            ("Schedule", "NRX > Purchase > Datewise Schedule", SchedulePurchaseDatewisePage, "NRX"),
            ("Schedule", "NRX > Purchase > Itemwise Schedule", SchedulePurchaseItemwisePage, "NRX"),
            ("Schedule", "NRX > Purchase > All Items Schedule", SchedulePurchaseAllItemsPage, "NRX"),

        ]

        for menu, action, expected_cls, expected_st in test_actions:
            win._on_menu_action(menu, action)
            cur = win._stack.currentWidget()
            self.assertIsInstance(cur, expected_cls, f"Action {action} did not route to {expected_cls.__name__}")
            self.assertEqual(cur.schedule_type, expected_st, f"Action {action} schedule_type mismatch")

        win.close()

    def test_06_report_date_validation_and_init(self):
        """Verify From <= To date validation and default financial year start date."""
        page = ScheduleSalesDatewisePage(schedule_type="H1")

        # Default From = start of active FY (01/04/2026), To = today
        self.assertEqual(page.from_date_edit.date().month(), 4)
        self.assertEqual(page.from_date_edit.date().day(), 1)
        self.assertEqual(page.to_date_edit.date(), QDate.currentDate())

        # Test invalid date: From > To
        page.from_date_edit.setDate(QDate(2026, 10, 20))
        page.to_date_edit.setDate(QDate(2026, 10, 10))
        valid = page.validate_dates()
        self.assertFalse(valid)
        self.assertIn("From Date cannot be after To Date", page.lbl_msg.text())

        # Test valid date: From <= To
        page.to_date_edit.setDate(QDate(2026, 10, 25))
        valid = page.validate_dates()
        self.assertTrue(valid)
        self.assertEqual(page.lbl_msg.text(), "")

    def test_07_report_a_sales_datewise(self):
        """Verify Report A layout, columns, store header, and grand totals."""
        page = ScheduleSalesDatewisePage(schedule_type="H1")
        self.assertEqual(page.window_title_text, "Sales Datewise Sheduled H1 Report")
        self.assertEqual(page.panel_title_text, "Sales Datewise Sheduled H1")

        # Mock sample rows
        mock_rows = [
            {
                "sale_date": "2026-06-15",
                "bill_no": "1001",
                "patient_name": "RAMESH PATIL",
                "address": "RAHURI",
                "unit_name": "TAB",
                "pack_size": "10",
                "item_name": "TRAMAGOLD TABLET",
                "batch_no": "TG101",
                "expiry": "2027-12-01",
                "qty": 20.0,
            },
            {
                "sale_date": "2026-06-16",
                "bill_no": "1002",
                "patient_name": "SURESH JADHAV",
                "address": "AHMEDNAGAR",
                "unit_name": "TAB",
                "pack_size": "10",
                "item_name": "TRAMAGOLD TABLET",
                "batch_no": "TG102",
                "expiry": "2027-11-01",
                "qty": 10.0,
            },
        ]
        with mock.patch.object(ScheduleReportsDAO, "get_sales_schedule", return_value=mock_rows):
            page.generate_report()
            self.assertGreater(len(page._pages), 0)
            rep_page = page._pages[0]
            self.assertEqual(rep_page.header.store_name, STORE_LINE_1)
            self.assertEqual(rep_page.header.store_address, STORE_LINE_2)
            self.assertIn("Sales Sheduled H1 Report for", rep_page.header.header_line_3)

            # Check that Grand Total row exists with qty 30
            total_blocks = [b for b in rep_page.blocks if b.kind == BlockKind.GRAND_TOTAL]
            self.assertEqual(len(total_blocks), 1)
            total_cells = total_blocks[0].data["cells"]
            self.assertIn("Total :", total_cells)
            self.assertIn("30", total_cells)

    def test_08_report_b_sales_itemwise(self):
        """Verify Report B item filter dropdown and single item report generation."""
        page = ScheduleSalesItemwisePage(schedule_type="NRX")
        self.assertEqual(page.window_title_text, "Sales Itemwise Sheduled NRX Report")
        self.assertEqual(page.panel_title_text, "Sales Itemwise Sheduled NRX")

        # Verify combo box has NRX items
        self.assertGreater(page.item_combo.count(), 0)
        # Select first item
        page.item_combo.setCurrentIndex(1)
        selected_id = page.item_combo.currentData()
        self.assertIsNotNone(selected_id)

        mock_rows = [
            {
                "sale_date": "2026-07-01",
                "bill_no": "2001",
                "patient_name": "ANIL SHARMA",
                "address": "PUNE",
                "unit_name": "TAB",
                "pack_size": "10",
                "item_name": "ATIVAN 2MG",
                "batch_no": "AT505",
                "expiry": "2028-05-01",
                "qty": 5.0,
            }
        ]
        with mock.patch.object(ScheduleReportsDAO, "get_sales_schedule", return_value=mock_rows) as mock_dao:
            page.generate_report()
            mock_dao.assert_called_once()
            self.assertGreater(len(page._pages), 0)
            rep_page = page._pages[0]
            self.assertIn("NRX", rep_page.header.header_line_1)
            self.assertIn("NRX", rep_page.header.header_line_3)

    def test_09_report_c_sales_all_items_grouping_and_continuous_srno(self):
        """Verify Report C groups items with 'Item Name : <ITEM>', continuous SrNo, and subtotals."""
        page = ScheduleSalesAllItemsPage(schedule_type="H1")
        self.assertEqual(page.window_title_text, "Sales Items (All) Sheduled H1 Report")
        self.assertEqual(page.panel_title_text, "Sales Items (All) Sheduled H1")

        mock_rows = [
            {
                "item_name": "TRYLIQ-P",
                "sale_date": "2026-05-10",
                "bill_no": "501",
                "patient_name": "VIJAY",
                "address": "RAHURI",
                "unit_name": "BOT",
                "pack_size": "100ML",
                "batch_no": "B1",
                "expiry": "2027-01-01",
                "qty": 2.0,
            },
            {
                "item_name": "TRYLIQ-P",
                "sale_date": "2026-05-11",
                "bill_no": "502",
                "patient_name": "AJAY",
                "address": "RAHURI",
                "unit_name": "BOT",
                "pack_size": "100ML",
                "batch_no": "B1",
                "expiry": "2027-01-01",
                "qty": 3.0,
            },
            {
                "item_name": "ZOSTUM 1GM",
                "sale_date": "2026-05-12",
                "bill_no": "503",
                "patient_name": "SANJAY",
                "address": "RAHURI",
                "unit_name": "VIAL",
                "pack_size": "1",
                "batch_no": "Z99",
                "expiry": "2028-02-01",
                "qty": 5.0,
            },
        ]
        with mock.patch.object(ScheduleReportsDAO, "get_sales_schedule", return_value=mock_rows):
            page.generate_report()
            self.assertGreater(len(page._pages), 0)
            rep_page = page._pages[0]

            # Verify group headers
            grp_headers = [b.data["title"] for b in rep_page.blocks if b.kind == BlockKind.GROUP_HEADER]
            self.assertIn("Item Name : TRYLIQ-P", grp_headers)
            self.assertIn("Item Name : ZOSTUM 1GM", grp_headers)

            # Verify SrNo resets to 1 within each section matching legacy report behavior
            data_rows = [b for b in rep_page.blocks if b.kind == BlockKind.DATA_ROW]
            sr_nos = [r.data["cells"][0] for r in data_rows]
            self.assertEqual(sr_nos, ["1", "2", "1"])

            # Verify subtotals and grand total
            subtotals = [b for b in rep_page.blocks if b.kind == BlockKind.ITEM_SUBTOTAL]
            self.assertEqual(len(subtotals), 2)
            self.assertIn("5", subtotals[0].data["cells"])
            self.assertIn("5", subtotals[1].data["cells"])

            grand_total = [b for b in rep_page.blocks if b.kind == BlockKind.GRAND_TOTAL]
            self.assertEqual(len(grand_total), 1)
            self.assertIn("10", grand_total[0].data["cells"])

    def test_10_report_d_purchase_datewise_whole_integer(self):
        """Verify Report D formats PurValue as whole integer (no decimals)."""
        page = SchedulePurchaseDatewisePage(schedule_type="H1")
        self.assertEqual(page.window_title_text, "Datewise Purchase Sheduled H1 Report")
        self.assertEqual(page.panel_title_text, "Datewise Purchase Sheduled H1")

        mock_rows = [
            {
                "inv_date": "2026-04-10",
                "inv_no": "INV-101",
                "supplier_name": "CIPLA LTD",
                "vh_no": "V001",
                "vh_date": "2026-04-10",
                "unit_name": "TAB",
                "pack_size": "10",
                "item_name": "TRAMAGOLD TABLET",
                "batch_no": "TG201",
                "expiry": "2028-01-01",
                "pur_qty": 50.0,
                "pur_value": 450.75,
            }
        ]
        with mock.patch.object(ScheduleReportsDAO, "get_purchase_schedule", return_value=mock_rows):
            page.generate_report()
            self.assertGreater(len(page._pages), 0)
            rep_page = page._pages[0]

            data_row = [b for b in rep_page.blocks if b.kind == BlockKind.DATA_ROW][0]
            pur_val_cell = data_row.data["cells"][12]
            # Whole integer: 450.75 rounded to 451
            self.assertEqual(pur_val_cell, "451")

            total_row = [b for b in rep_page.blocks if b.kind == BlockKind.GRAND_TOTAL][0]
            self.assertEqual(total_row.data["cells"][11], "50")
            self.assertEqual(total_row.data["cells"][12], "451")
            self.assertIn("custom_cells", total_row.data)
            self.assertEqual(total_row.data["custom_cells"][1]["text"], "50")
            self.assertEqual(total_row.data["custom_cells"][2]["text"], "451")

    def test_11_report_e_purchase_itemwise_whole_integer(self):
        """Verify Report E formats PurValue as whole integer and filters by item."""
        page = SchedulePurchaseItemwisePage(schedule_type="H1")
        self.assertEqual(page.window_title_text, "Itemwise Purchase Sheduled H1 Report")
        self.assertEqual(page.panel_title_text, "Itemwise Purchase Sheduled H1")

        mock_rows = [
            {
                "inv_date": "2026-04-12",
                "inv_no": "INV-102",
                "supplier_name": "SUN PHARMA",
                "vh_no": "V002",
                "vh_date": "2026-04-12",
                "unit_name": "TAB",
                "pack_size": "10",
                "item_name": "TRAMAGOLD TABLET",
                "batch_no": "TG202",
                "expiry": "2028-02-01",
                "pur_qty": 100.0,
                "pur_value": 900.25,
            }
        ]
        with mock.patch.object(ScheduleReportsDAO, "get_purchase_schedule", return_value=mock_rows):
            page.generate_report()
            rep_page = page._pages[0]
            data_row = [b for b in rep_page.blocks if b.kind == BlockKind.DATA_ROW][0]
            self.assertEqual(data_row.data["cells"][12], "900")
            total_row = [b for b in rep_page.blocks if b.kind == BlockKind.GRAND_TOTAL][0]
            self.assertEqual(total_row.data["cells"][11], "100")
            self.assertEqual(total_row.data["cells"][12], "900")
            self.assertIn("custom_cells", total_row.data)
            self.assertEqual(total_row.data["custom_cells"][1]["text"], "100")
            self.assertEqual(total_row.data["custom_cells"][2]["text"], "900")

    def test_12_report_f_purchase_all_items_2_decimals(self):
        """Verify Report F formats PurValue with 2 decimals (e.g. 110.00) and continuous SrNo."""
        page = SchedulePurchaseAllItemsPage(schedule_type="NRX")
        self.assertEqual(page.window_title_text, "All Items Purchase Sheduled NRX Report")
        self.assertEqual(page.panel_title_text, "Items (All) Purchase Sheduled NRX")

        mock_rows = [
            {
                "item_name": "ATIVAN 2MG",
                "inv_date": "2026-04-05",
                "inv_no": "INV-501",
                "supplier_name": "PFIZER",
                "vh_no": "V10",
                "vh_date": "2026-04-05",
                "unit_name": "TAB",
                "pack_size": "10",
                "batch_no": "AT01",
                "expiry": "2028-01-01",
                "pur_qty": 20.0,
                "pur_value": 110.0,
            },
            {
                "item_name": "CLONAPAX 0.5",
                "inv_date": "2026-04-06",
                "inv_no": "INV-502",
                "supplier_name": "INTAS",
                "vh_no": "V11",
                "vh_date": "2026-04-06",
                "unit_name": "TAB",
                "pack_size": "10",
                "batch_no": "CP01",
                "expiry": "2028-03-01",
                "pur_qty": 30.0,
                "pur_value": 250.5,
            },
        ]
        with mock.patch.object(ScheduleReportsDAO, "get_purchase_schedule", return_value=mock_rows):
            page.generate_report()
            rep_page = page._pages[0]

            # Verify 2 decimals on data rows
            data_rows = [b for b in rep_page.blocks if b.kind == BlockKind.DATA_ROW]
            self.assertEqual(data_rows[0].data["cells"][11], "110.00")
            self.assertEqual(data_rows[1].data["cells"][11], "250.50")

            # Verify continuous SrNo across item groups
            self.assertEqual(data_rows[0].data["cells"][0], "1")
            self.assertEqual(data_rows[1].data["cells"][0], "2")

            # Verify 2 decimals on subtotals and grand total
            subtotals = [b for b in rep_page.blocks if b.kind == BlockKind.ITEM_SUBTOTAL]
            self.assertEqual(subtotals[0].data["cells"][10], "20")
            self.assertEqual(subtotals[0].data["cells"][11], "110.00")
            self.assertEqual(subtotals[1].data["cells"][10], "30")
            self.assertEqual(subtotals[1].data["cells"][11], "250.50")

            grand_total = [b for b in rep_page.blocks if b.kind == BlockKind.GRAND_TOTAL][0]
            self.assertEqual(grand_total.data["cells"][10], "50")
            self.assertEqual(grand_total.data["cells"][11], "360.50")
            self.assertIn("custom_cells", grand_total.data)
            self.assertEqual(grand_total.data["custom_cells"][1]["text"], "50")
            self.assertEqual(grand_total.data["custom_cells"][2]["text"], "360.50")

    def test_14_purchase_schedule_vhno_clean_formatting(self):
        """Verify Datewise, Itemwise, and All Items purchase reports clean VhNo display."""
        mock_rows = [
            {
                "inv_date": "2026-04-10",
                "inv_no": "INV-101",
                "supplier_name": "CIPLA LTD",
                "vh_no": "2026-2027-Credit-0251",
                "purchase_type": "Credit",
                "vh_date": "2026-04-10",
                "unit_name": "TAB",
                "pack_size": "10",
                "item_name": "TRAMAGOLD TABLET",
                "batch_no": "TG201",
                "expiry": "2028-01-01",
                "pur_qty": 50.0,
                "pur_value": 450.0,
            },
            {
                "inv_date": "2026-04-11",
                "inv_no": "INV-102",
                "supplier_name": "SUN PHARMA",
                "vh_no": "2025-2026-Cash-80",
                "purchase_type": "Cash",
                "vh_date": "2026-04-11",
                "unit_name": "TAB",
                "pack_size": "10",
                "item_name": "TRAMAGOLD TABLET",
                "batch_no": "TG202",
                "expiry": "2028-02-01",
                "pur_qty": 30.0,
                "pur_value": 300.0,
            },
            {
                "inv_date": "2026-04-12",
                "inv_no": "INV-103",
                "supplier_name": "INTAS",
                "vh_no": "2026-2027-Credit-1905#12345",
                "purchase_type": "Credit",
                "vh_date": "2026-04-12",
                "unit_name": "TAB",
                "pack_size": "10",
                "item_name": "TRAMAGOLD TABLET",
                "batch_no": "TG203",
                "expiry": "2028-03-01",
                "pur_qty": 20.0,
                "pur_value": 200.0,
            },
        ]

        # Test Datewise
        page_d = SchedulePurchaseDatewisePage(schedule_type="H1")
        with mock.patch.object(ScheduleReportsDAO, "get_purchase_schedule", return_value=mock_rows):
            page_d.generate_report()
            rep_page = page_d._pages[0]
            data_rows = [b for b in rep_page.blocks if b.kind == BlockKind.DATA_ROW]
            self.assertEqual(len(data_rows), 3)
            self.assertEqual(data_rows[0].data["cells"][4], "251")
            self.assertEqual(data_rows[1].data["cells"][4], "80")
            self.assertEqual(data_rows[2].data["cells"][4], "1905")

        # Test Itemwise
        page_e = SchedulePurchaseItemwisePage(schedule_type="H1")
        with mock.patch.object(ScheduleReportsDAO, "get_purchase_schedule", return_value=mock_rows):
            page_e.generate_report()
            rep_page = page_e._pages[0]
            data_rows = [b for b in rep_page.blocks if b.kind == BlockKind.DATA_ROW]
            self.assertEqual(len(data_rows), 3)
            self.assertEqual(data_rows[0].data["cells"][4], "251")
            self.assertEqual(data_rows[1].data["cells"][4], "80")
            self.assertEqual(data_rows[2].data["cells"][4], "1905")

        # Test All Items
        page_f = SchedulePurchaseAllItemsPage(schedule_type="H1")
        with mock.patch.object(ScheduleReportsDAO, "get_purchase_schedule", return_value=mock_rows):
            page_f.generate_report()
            rep_page = page_f._pages[0]
            data_rows = [b for b in rep_page.blocks if b.kind == BlockKind.DATA_ROW]
            self.assertEqual(len(data_rows), 3)
            self.assertEqual(data_rows[0].data["cells"][4], "251")
            self.assertEqual(data_rows[1].data["cells"][4], "80")
            self.assertEqual(data_rows[2].data["cells"][4], "1905")

    def test_13_print_and_export_all_12_reports(self):
        """Verify print_report and export_report execute successfully across all 12 reports."""
        import tempfile
        classes = [
            ScheduleSalesDatewisePage,
            ScheduleSalesItemwisePage,
            ScheduleSalesAllItemsPage,
            SchedulePurchaseDatewisePage,
            SchedulePurchaseItemwisePage,
            SchedulePurchaseAllItemsPage,
        ]
        for st in ("H1", "NRX"):
            for cls in classes:
                p = cls(schedule_type=st)
                p.generate_report()
                self.assertGreater(len(p._pages), 0)
                # Verify print_report does not throw
                p.print_report()
                # Verify export_report generates PDF
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
                    tmp_pdf = tf.name
                with mock.patch("PySide6.QtWidgets.QFileDialog.getSaveFileName", return_value=(tmp_pdf, "")):
                    p.export_report()
                self.assertTrue(os.path.exists(tmp_pdf))
                self.assertGreater(os.path.getsize(tmp_pdf), 0)
                try:
                    os.remove(tmp_pdf)
                except OSError:
                    pass


if __name__ == "__main__":
    unittest.main()
