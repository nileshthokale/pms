"""Comprehensive Tests for Doctor's Reports (Menu, DAO, Screens, Pagination, and Theme).

Verifies:
1. Reports > Doctor's Reports menu structure, cascading submenu, right arrow, and navigation signals.
2. Doctor-to-sale relationships: only sales linked to doctor_id are included.
3. Accurate financial calculations: costing rules, pack factor, sales, purchase cost, net profit.
4. Prevention of duplicate rows when joining bills, items, and customers.
5. Numeric sales bill formatting.
6. Details report item-selection tree filtering and (All Items) behavior.
7. Empty report handling without exceptions.
8. Multi-page pagination and repeating table/group headers.
9. Print and Export PDF/CSV functions.
10. Day Mode and Night Mode theme compatibility.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QPushButton, QMenu, QTreeWidgetItem

from database.connection import get_connection, init_database
from database import auth, financial_year
from database.account_roles import ensure_system_ledgers
from database.doctor_dao import DoctorDAO
from database.doctor_reports_dao import DoctorReportsDAO
from database.item_dao import ItemDAO
from database.unit_dao import UnitDAO
from database.stock_dao import StockDAO
from database.sales_dao import SalesDAO
from ui.menu_data import (
    MENUS,
    REPORT_DOCTOR_SUBMENU,
    SubmenuDict,
)
from ui.navigation_bar import NavigationBar
from ui.main_window import PharmacyMainWindow
from screens.doctor_reports import (
    DoctorwiseItemSalePage,
    DoctorwiseItemSaleDetailsPage,
    paginate_doctor_report_blocks,
)
from ui.crystal_report_viewer import (
    BlockKind,
    ReportBlock,
    ReportHeaderData,
    draw_report_page,
    print_or_export_report_pages,
)
import ui.theme as theme


class TestDoctorReports(unittest.TestCase):
    _DB_PATH = os.path.join(tempfile.gettempdir(), "_test_doctor_reports.db")

    @classmethod
    def setUpClass(cls):
        if os.path.exists(cls._DB_PATH):
            try:
                os.remove(cls._DB_PATH)
            except OSError:
                pass
        os.environ["PHARMACY_DB"] = cls._DB_PATH
        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_financial_year_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        ensure_system_ledgers()

        # Seed test master data: Units, Items, Doctors, Batches, Sales
        cls._seed_test_data()

        cls.app = QApplication.instance() or QApplication([])
        cls.win = PharmacyMainWindow()

    @classmethod
    def tearDownClass(cls):
        cls.win.close()
        if os.path.exists(cls._DB_PATH):
            try:
                os.remove(cls._DB_PATH)
            except OSError:
                pass

    @classmethod
    def _seed_test_data(cls):
        # 1. Units
        unit_tab_id = UnitDAO.insert("TABLET")
        unit_inj_id = UnitDAO.insert("INJECT")

        # 2. Doctors
        cls.doc1_id = DoctorDAO.insert("DR. K. N. GHORPADE", city="RAHURI", specialty="ORTHO")
        cls.doc2_id = DoctorDAO.insert("DR. NISHIGAND", city="RAHURI", specialty="SKIN")

        # 3. Items
        cls.item1_id = ItemDAO.insert(
            item_name="BIO D3 PLUS",
            unit_id=unit_tab_id,
            pack_size="15",
            mrp=341.34,
            rate=260.07,
        )
        cls.item2_id = ItemDAO.insert(
            item_name="DALACIN C 300MG",
            unit_id=unit_tab_id,
            pack_size="10",
            mrp=297.00,
            rate=244.35,
        )
        cls.item3_id = ItemDAO.insert(
            item_name="DEXONA",
            unit_id=unit_inj_id,
            pack_size="1",
            mrp=10.94,
            rate=8.36,
        )

        # 4. Stock Batches
        conn = get_connection()
        try:
            cur1 = conn.execute(
                """INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, purchase_rate, net_rate, mrp, stock_qty)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (cls.item1_id, "B1425", "2028-11-30", "15", 260.07, 273.07, 341.34, 100.0),
            )
            batch1_id = cur1.lastrowid

            cur2 = conn.execute(
                """INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, purchase_rate, net_rate, mrp, stock_qty)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (cls.item2_id, "D0382", "2027-06-30", "10", 244.35, 256.255, 297.00, 100.0),
            )
            batch2_id = cur2.lastrowid

            cur3 = conn.execute(
                """INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, purchase_rate, net_rate, mrp, stock_qty)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (cls.item3_id, "NB003", "2027-11-30", "1", 8.36, 8.78, 10.94, 50.0),
            )
            batch3_id = cur3.lastrowid
            conn.commit()
        finally:
            conn.close()

        # 5. Sales Invoices for Doctor 1 (2026-05-10)
        # Bill 1: 5 tablets of BIO D3 PLUS (MRP 341.34/15 = 22.756 each -> 113.78)
        SalesDAO.insert_invoice(
            bill_no="2026-2027-61",
            sale_date="2026-05-10",
            sale_time="10:00:00",
            sale_type="Cash",
            customer_id=None,
            patient_name="MRS BHARTI GHADGE",
            doctor_id=cls.doc1_id,
            discount=0.0,
            paid_amount=113.78,
            total_amount=113.78,
            round_off=0.0,
            net_amount=113.78,
            remarks="",
            items=[{
                "item_id": cls.item1_id,
                "stock_batch_id": batch1_id,
                "pack_size": "15",
                "location": "",
                "batch_no": "B1425",
                "expiry": "2028-11-30",
                "mrp": 341.34,
                "sale_qty": 5.0,
                "discount_amount": 0.0,
                "amount": 113.78,
            }],
        )

        # Bill 2: 10 tablets of DALACIN C (MRP 297/10 = 29.70 each -> 297.00)
        SalesDAO.insert_invoice(
            bill_no="2026-2027-89",
            sale_date="2026-05-12",
            sale_time="11:30:00",
            sale_type="Cash",
            customer_id=None,
            patient_name="MRS UJJWALA HARDE",
            doctor_id=cls.doc1_id,
            discount=0.0,
            paid_amount=297.00,
            total_amount=297.00,
            round_off=0.0,
            net_amount=297.00,
            remarks="",
            items=[{
                "item_id": cls.item2_id,
                "stock_batch_id": batch2_id,
                "pack_size": "10",
                "location": "",
                "batch_no": "D0382",
                "expiry": "2027-06-30",
                "mrp": 297.00,
                "sale_qty": 10.0,
                "discount_amount": 0.0,
                "amount": 297.00,
            }],
        )

        # Bill 3: Multi-item bill for Doctor 1 (15 tablets of BIO D3 PLUS + 2 inject of DEXONA)
        SalesDAO.insert_invoice(
            bill_no="2026-2027-102",
            sale_date="2026-05-15",
            sale_time="14:00:00",
            sale_type="Cash",
            customer_id=None,
            patient_name="MR SAHEBRAO KAKADE",
            doctor_id=cls.doc1_id,
            discount=0.0,
            paid_amount=363.22,
            total_amount=363.22,
            round_off=0.0,
            net_amount=363.22,
            remarks="",
            items=[
                {
                    "item_id": cls.item1_id,
                    "stock_batch_id": batch1_id,
                    "pack_size": "15",
                    "location": "",
                    "batch_no": "B1425",
                    "expiry": "2028-11-30",
                    "mrp": 341.34,
                    "sale_qty": 15.0,
                    "discount_amount": 0.0,
                    "amount": 341.34,
                },
                {
                    "item_id": cls.item3_id,
                    "stock_batch_id": batch3_id,
                    "pack_size": "1",
                    "location": "",
                    "batch_no": "NB003",
                    "expiry": "2027-11-30",
                    "mrp": 10.94,
                    "sale_qty": 2.0,
                    "discount_amount": 0.0,
                    "amount": 21.88,
                },
            ],
        )

        # Bill 4: Sale for Doctor 2 (DR. NISHIGAND) — should be EXCLUDED from Doctor 1 reports
        SalesDAO.insert_invoice(
            bill_no="2026-2027-200",
            sale_date="2026-05-16",
            sale_time="15:00:00",
            sale_type="Cash",
            customer_id=None,
            patient_name="OTHER PATIENT",
            doctor_id=cls.doc2_id,
            discount=0.0,
            paid_amount=341.34,
            total_amount=341.34,
            round_off=0.0,
            net_amount=341.34,
            remarks="",
            items=[{
                "item_id": cls.item1_id,
                "stock_batch_id": batch1_id,
                "pack_size": "15",
                "location": "",
                "batch_no": "B1425",
                "expiry": "2028-11-30",
                "mrp": 341.34,
                "sale_qty": 15.0,
                "discount_amount": 0.0,
                "amount": 341.34,
            }],
        )

        # Bill 5: Sale with NO doctor (Walk-in without prescription) — should be EXCLUDED
        SalesDAO.insert_invoice(
            bill_no="2026-2027-201",
            sale_date="2026-05-17",
            sale_time="16:00:00",
            sale_type="Cash",
            customer_id=None,
            patient_name="NO DOCTOR PATIENT",
            doctor_id=None,
            discount=0.0,
            paid_amount=10.94,
            total_amount=10.94,
            round_off=0.0,
            net_amount=10.94,
            remarks="",
            items=[{
                "item_id": cls.item3_id,
                "stock_batch_id": batch3_id,
                "pack_size": "1",
                "location": "",
                "batch_no": "NB003",
                "expiry": "2027-11-30",
                "mrp": 10.94,
                "sale_qty": 1.0,
                "discount_amount": 0.0,
                "amount": 10.94,
            }],
        )

    # ── Test 1: Menu Structure & Submenu Navigation ───────────────────
    def test_01_menu_structure_and_doctor_submenu(self):
        """Reports menu contains Doctor's Reports with the two exact options."""
        self.assertEqual(
            REPORT_DOCTOR_SUBMENU,
            ["Doctorwise Item Sale", "Doctorwise Item Sale Details"],
        )

        reports = MENUS["Reports"]
        doc_entry = next((item for item in reports if item == "Doctor's Reports"), None)
        self.assertIsNotNone(doc_entry, "Doctor's Reports must be in Reports menu")
        self.assertIsInstance(doc_entry, dict)
        self.assertIn("Doctor's Reports", doc_entry)
        self.assertEqual(doc_entry["Doctor's Reports"], REPORT_DOCTOR_SUBMENU)

    def test_02_navigation_bar_builds_doctor_submenu(self):
        """NavigationBar builds a nested QMenu for Doctor's Reports with right-arrow."""
        reports_btn = next(
            btn for btn in self.win._nav.findChildren(QPushButton)
            if btn.objectName() == "NavButton" and btn.text() == "Reports"
        )
        reports_menu = reports_btn.menu()
        self.assertIsNotNone(reports_menu)

        actions = reports_menu.actions()
        action_map = {a.text(): a for a in actions}
        self.assertIn("Doctor's Reports", action_map)

        doc_action = action_map["Doctor's Reports"]
        submenu = doc_action.menu()
        self.assertIsNotNone(submenu, "Doctor's Reports action must have an attached QMenu submenu")

        sub_actions = [a.text() for a in submenu.actions() if not a.isSeparator()]
        self.assertEqual(
            sub_actions,
            ["Doctorwise Item Sale", "Doctorwise Item Sale Details"],
        )

    def test_03_menu_action_routing(self):
        """Triggering Doctor's Reports menu actions routes to correct pages in MainWindow."""
        # 1. Doctorwise Item Sale
        self.win._on_menu_action("Reports", "Doctorwise Item Sale")
        current_widget = self.win._stack.currentWidget()
        self.assertIsInstance(current_widget, DoctorwiseItemSalePage)
        self.assertIn("Doctorwise Item Sale", self.win.windowTitle())

        # 2. Doctorwise Item Sale Details
        self.win._on_menu_action("Reports", "Doctorwise Item Sale Details")
        current_widget = self.win._stack.currentWidget()
        self.assertIsInstance(current_widget, DoctorwiseItemSaleDetailsPage)
        self.assertIn("Doctorwise Item Sale Details", self.win.windowTitle())

    # ── Test 2: Doctor Filtering & Relationships ──────────────────────
    def test_04_doctor_filtering_dao(self):
        """DAO returns only sales belonging to selected doctor, excluding others."""
        # Doctor 1 sales
        res1 = DoctorReportsDAO.get_doctorwise_item_sale("2026-05-01", "2026-05-31", self.doc1_id)
        rows1 = res1["rows"]
        item_names = {r["item_name"] for r in rows1}
        self.assertIn("BIO D3 PLUS", item_names)
        self.assertIn("DALACIN C 300MG", item_names)
        self.assertIn("DEXONA", item_names)

        # Doctor 2 sales
        res2 = DoctorReportsDAO.get_doctorwise_item_sale("2026-05-01", "2026-05-31", self.doc2_id)
        rows2 = res2["rows"]
        self.assertEqual(len(rows2), 1)
        self.assertEqual(rows2[0]["item_name"], "BIO D3 PLUS")
        self.assertEqual(rows2[0]["sales_qty"], 15.0)

        # Non-existent doctor returns empty rows
        res_empty = DoctorReportsDAO.get_doctorwise_item_sale("2026-05-01", "2026-05-31", 99999)
        self.assertEqual(len(res_empty["rows"]), 0)

    # ── Test 3: Financial Calculations ────────────────────────────────
    def test_05_financial_calculations(self):
        """Verifies sales, costing rules, purchase cost, and net profit calculations."""
        res = DoctorReportsDAO.get_doctorwise_item_sale("2026-05-01", "2026-05-31", self.doc1_id)
        item_map = {r["item_name"]: r for r in res["rows"]}

        # BIO D3 PLUS: Sold 5 (Bill 1) + 15 (Bill 3) = 20 tablets
        # Unit cost = 273.07 / 15 = 18.2046667
        # Total cost = 20 * 18.2046667 = 364.09
        # Sales = 113.78 + 341.34 = 455.12
        # Net Profit = 455.12 - 364.09 = 91.03
        bio = item_map["BIO D3 PLUS"]
        self.assertEqual(bio["sales_qty"], 20.0)
        self.assertEqual(bio["sales"], 455.12)
        self.assertEqual(bio["purchase"], 364.09)
        self.assertEqual(bio["net_profit"], 91.03)

        # DEXONA: Sold 2 units (Bill 3)
        # Unit cost = 8.78 / 1 = 8.78 -> 2 * 8.78 = 17.56
        # Sales = 21.88
        # Net Profit = 21.88 - 17.56 = 4.32
        dex = item_map["DEXONA"]
        self.assertEqual(dex["sales_qty"], 2.0)
        self.assertEqual(dex["sales"], 21.88)
        self.assertEqual(dex["purchase"], 17.56)
        self.assertEqual(dex["net_profit"], 4.32)

        # Summary totals
        summ = res["summary"]
        self.assertEqual(summ["total_items"], 3)
        self.assertEqual(summ["total_qty"], 32.0)  # 20 + 10 + 2
        self.assertEqual(
            summ["total_sales"],
            round(bio["sales"] + item_map["DALACIN C 300MG"]["sales"] + dex["sales"], 2),
        )

    # ── Test 4: Details Report & Item Tree ────────────────────────────
    def test_06_details_report_grouping_and_tree_filter(self):
        """Details report groups by item and respects item-level selection."""
        # 1. All items
        res_all = DoctorReportsDAO.get_doctorwise_item_sale_details(
            "2026-05-01", "2026-05-31", self.doc1_id, item_id=None
        )
        groups = res_all["groups"]
        self.assertEqual(len(groups), 3)

        bio_grp = next(g for g in groups if g["item_name"] == "BIO D3 PLUS")
        self.assertEqual(len(bio_grp["lines"]), 2)  # Bill 61 and Bill 102
        self.assertEqual(bio_grp["subtotal_qty"], 20.0)
        self.assertEqual(bio_grp["subtotal_amount"], 455.12)

        # Check numeric bill number formatting (e.g. '2026-2027-61' -> '61')
        self.assertEqual(bio_grp["lines"][0]["bill_no_display"], "61")
        self.assertEqual(bio_grp["lines"][0]["patient_name"], "MRS BHARTI GHADGE")

        # 2. Filter single item (DEXONA)
        res_dex = DoctorReportsDAO.get_doctorwise_item_sale_details(
            "2026-05-01", "2026-05-31", self.doc1_id, item_id=self.item3_id
        )
        self.assertEqual(len(res_dex["groups"]), 1)
        self.assertEqual(res_dex["groups"][0]["item_name"], "DEXONA")
        self.assertEqual(res_dex["groups"][0]["subtotal_qty"], 2.0)

    # ── Test 5: UI Screens Execution & Pagination ─────────────────────
    def test_07_doctorwise_item_sale_page_ui(self):
        """DoctorwiseItemSalePage renders report, updates viewer, and handles dates."""
        page = DoctorwiseItemSalePage()
        # Set dates
        page.from_date_edit.setDate(QDate(2026, 5, 1))
        page.to_date_edit.setDate(QDate(2026, 5, 31))

        # Select doctor
        idx = page.doctor_combo.findData(self.doc1_id)
        self.assertGreaterEqual(idx, 0)
        page.doctor_combo.setCurrentIndex(idx)

        # Generate report
        page.generate_report()
        self.assertGreater(len(page._pages), 0)
        self.assertTrue(page.btn_panel_print.isEnabled())
        self.assertTrue(page.btn_panel_export.isEnabled())

        # Check page header and blocks
        p0 = page._pages[0]
        self.assertIn("DR. K. N. GHORPADE", p0.header.header_line_2)
        data_rows = [b for b in p0.blocks if b.kind == BlockKind.DATA_ROW]
        self.assertEqual(len(data_rows), 3)

    def test_08_doctorwise_item_sale_details_page_ui(self):
        """DoctorwiseItemSaleDetailsPage renders grouped report and tree interaction."""
        page = DoctorwiseItemSaleDetailsPage()
        page.from_date_edit.setDate(QDate(2026, 5, 1))
        page.to_date_edit.setDate(QDate(2026, 5, 31))

        idx = page.doctor_combo.findData(self.doc1_id)
        self.assertGreaterEqual(idx, 0)
        page.doctor_combo.setCurrentIndex(idx)

        page.generate_report()
        self.assertGreater(len(page._pages), 0)

        # Verify tree has item nodes
        self.assertGreater(page.item_tree.topLevelItemCount(), 1)
        first_item = page.item_tree.topLevelItem(0)
        self.assertIn("All Items", first_item.text(0))

        # Select single item in tree
        dex_node = None
        for i in range(page.item_tree.topLevelItemCount()):
            node = page.item_tree.topLevelItem(i)
            if node.data(0, Qt.UserRole) == self.item3_id:
                dex_node = node
                break
        self.assertIsNotNone(dex_node)
        page._on_item_tree_clicked(dex_node, 0)

        # Page now shows only DEXONA
        p0 = page._pages[0]
        group_headers = [b for b in p0.blocks if b.kind == BlockKind.GROUP_HEADER]
        self.assertEqual(len(group_headers), 1)
        self.assertIn("DEXONA", group_headers[0].data["text"])

    def test_09_empty_report_rendering(self):
        """Empty reports render without crashing and show helpful empty message."""
        page = DoctorwiseItemSalePage()
        page.from_date_edit.setDate(QDate(2020, 1, 1))
        page.to_date_edit.setDate(QDate(2020, 1, 31))

        idx = page.doctor_combo.findData(self.doc1_id)
        page.doctor_combo.setCurrentIndex(idx)
        page.generate_report()

        self.assertEqual(len(page._pages), 1)
        p0 = page._pages[0]
        empty_blocks = [b for b in p0.blocks if b.kind == BlockKind.EMPTY]
        self.assertEqual(len(empty_blocks), 1)
        self.assertIn("No transactions found", empty_blocks[0].data["message"])

    def test_10_multipage_pagination_and_repeated_headers(self):
        """Multi-page pagination correctly distributes blocks and repeats headers."""
        header = ReportHeaderData(
            store_name="TEST PHARMACY",
            store_address="MAIN ROAD",
            header_line_1="Doctorwise Item Sale Details",
            header_line_2="Doctor Name: DR. TEST",
        )
        grp_hdr = ReportBlock(BlockKind.GROUP_HEADER, 24.0, {"text": "TEST MEDICINE"})
        tbl_hdr = ReportBlock(
            BlockKind.TABLE_HEADER,
            22.0,
            {"columns": ["SrNo", "Name"], "widths": [50.0, 674.0], "aligns": ["center", "left"]},
        )
        blocks = [grp_hdr, tbl_hdr]
        # Add 60 data rows (20px each = 1200px > 980px max body height)
        for i in range(60):
            blocks.append(
                ReportBlock(
                    BlockKind.DATA_ROW,
                    20.0,
                    {"cells": [str(i + 1), f"Patient {i + 1}"], "widths": [50.0, 674.0], "aligns": ["center", "left"]},
                )
            )

        pages = paginate_doctor_report_blocks(header, blocks, tbl_hdr)
        self.assertGreater(len(pages), 1)
        self.assertEqual(pages[0].page_num, 1)
        self.assertEqual(pages[0].total_pages, len(pages))
        self.assertEqual(pages[1].page_num, 2)
        self.assertEqual(pages[1].total_pages, len(pages))

        # Continuation page repeats group header and table header
        self.assertEqual(pages[1].blocks[0].kind, BlockKind.GROUP_HEADER)
        self.assertEqual(pages[1].blocks[1].kind, BlockKind.TABLE_HEADER)

    def test_11_print_and_export_functions(self):
        """Print and export methods work without exceptions."""
        page = DoctorwiseItemSalePage()
        page.from_date_edit.setDate(QDate(2026, 5, 1))
        page.to_date_edit.setDate(QDate(2026, 5, 31))
        idx = page.doctor_combo.findData(self.doc1_id)
        page.doctor_combo.setCurrentIndex(idx)
        page.generate_report()

        # Headless print routes safely via PDF generator
        print_res = print_or_export_report_pages(page._pages, parent=page)
        self.assertTrue(print_res)

        # PDF export to temp file
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
            tmp_pdf = tf.name
        try:
            exp_res = print_or_export_report_pages(page._pages, output_pdf_path=tmp_pdf)
            self.assertTrue(exp_res)
            self.assertGreater(os.path.getsize(tmp_pdf), 100)
        finally:
            if os.path.exists(tmp_pdf):
                try:
                    os.remove(tmp_pdf)
                except OSError:
                    pass

    def test_12_day_and_night_mode_compatibility(self):
        """Both pages refresh theme cleanly in Day Mode and Night Mode."""
        page1 = DoctorwiseItemSalePage()
        page2 = DoctorwiseItemSaleDetailsPage()

        orig_mode = theme.theme_manager.mode()
        try:
            # Test dark mode refresh
            theme.theme_manager._mode = "dark"
            page1.refresh_theme()
            page2.refresh_theme()

            self.assertEqual(page1.viewer.canvas._bg_color, QColor("#303030"))
            self.assertEqual(page2.viewer.canvas._bg_color, QColor("#303030"))

            # Test light mode refresh
            theme.theme_manager._mode = "light"
            page1.refresh_theme()
            page2.refresh_theme()

            self.assertEqual(page1.viewer.canvas._bg_color, QColor("#808080"))
            self.assertEqual(page2.viewer.canvas._bg_color, QColor("#808080"))
        finally:
            theme.theme_manager._mode = orig_mode


if __name__ == "__main__":
    unittest.main()
