"""Comprehensive Test Suite for the 6 Purchase Reports.

Verifies:
1. Reports > Purchase Report submenu items, ordering, separators, and window opening.
2. Common report window layout (toolbar, Main Report tab, canvas, status bar, filter panel).
3. Filter validation (From <= To, dropdown selection).
4. Store header ("SHREE SAMARTH MEDICAL AND GEN STORE", "GHORPADE HOSPITAL, RAHURI").
5. Report 1 - Companywise Itemwise Purchase (grouping by item, columns, totals, grand total).
6. Report 2 - Companywise Supplierwise Purchase (Supplier, Address, Amount, bold total, "Suppler" spelling).
7. Report 3 - Supplierwise Itemwise Purchase (Invoice) (grouping, company code, pagination, invoice only).
8. Report 4 - Supplierwise Itemwise Purchase (Challan) (ChallanNo, ChallanDate, challan only).
9. Report 5 - Itemwise Purchase (columns, totals, line 2 format).
10. Report 6 - Itemwise Batchwise Purchase (BatchNo and Rate on first row only, batch subtotal box, grand total).
11. Print and export functions (A4 portrait, header on each page, borders, bold totals).
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication, QPushButton

from database.connection import get_connection, init_database
from database import auth, financial_year
from database.purchase_reports_dao import PurchaseReportsDAO
from ui.menu_data import MENUS, REPORT_PURCHASE_SUBMENU
from ui.navigation_bar import NavigationBar
from ui.main_window import PharmacyMainWindow
from ui.crystal_report_viewer import (
    BlockKind,
    PAGE_WIDTH,
    PAGE_HEIGHT,
    ReportHeaderData,
    draw_report_page,
    fmt_amt,
    fmt_date_dash,
    fmt_date_slash,
    fmt_free,
    fmt_qty,
    get_default_store_identity,
    print_or_export_report_pages,
)
import screens


class TestPurchaseReportsSuite(unittest.TestCase):
    _DB_PATH = os.path.join(tempfile.gettempdir(), "_test_purchase_reports_suite.db")

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

        cls.app = QApplication.instance() or QApplication([])

        # Seed test data for companies, units, items, suppliers, purchase invoices
        conn = get_connection()
        try:
            # 1. Company
            cls.comp_id = conn.execute(
                "INSERT INTO companies (company_name, short_name) VALUES ('CIPLA LIMITED', 'CIP')"
            ).lastrowid
            cls.comp2_id = conn.execute(
                "INSERT INTO companies (company_name, short_name) VALUES ('ALKEM LABORATORIES', 'ALK')"
            ).lastrowid

            # 2. Units
            cls.unit_tab = conn.execute("INSERT INTO units (unit_name) VALUES ('TABLET')").lastrowid
            cls.unit_cap = conn.execute("INSERT INTO units (unit_name) VALUES ('CAPSULE')").lastrowid

            # 3. Items
            cls.item1_id = conn.execute(
                "INSERT INTO items (item_name, unit_id, company_id, pack_size) VALUES ('CIPLOX 500', ?, ?, '10')",
                (cls.unit_tab, cls.comp_id),
            ).lastrowid
            cls.item2_id = conn.execute(
                "INSERT INTO items (item_name, unit_id, company_id, pack_size) VALUES ('NERVMAX XT OD', ?, ?, '10')",
                (cls.unit_cap, cls.comp2_id),
            ).lastrowid

            # 4. Suppliers
            cls.supp1_id = conn.execute(
                "INSERT INTO suppliers (supplier_name, address, city) VALUES ('MAHAVIR DRUG AGENCY', 'STATION ROAD, RAHURI', 'RAHURI')"
            ).lastrowid
            cls.supp2_id = conn.execute(
                "INSERT INTO suppliers (supplier_name, address, city) VALUES ('ARIHANT PHARMA', 'MARKET YARD, AHMEDNAGAR', 'AHMEDNAGAR')"
            ).lastrowid

            # 5. Purchase Invoices (Invoice-type and Challan-type)
            # Invoice 1: Credit, from supp1, has item1
            cls.pi1_id = conn.execute(
                """
                INSERT INTO purchase_invoices (voucher_no, voucher_date, purchase_type, supplier_id, invoice_no, invoice_date, total_amount, net_amount)
                VALUES ('2026-2027-Credit-79', '2026-06-08', 'Credit', ?, 'INV-1001', '2026-06-08', 3634.20, 3634.20)
                """,
                (cls.supp1_id,),
            ).lastrowid
            conn.execute(
                """
                INSERT INTO purchase_invoice_items (purchase_invoice_id, item_id, pack_size, batch_no, expiry, rate, pay_qty, free_qty, amount)
                VALUES (?, ?, '10', 'HCL5695', '2027-11-30', 121.14, 30.0, 6.0, 3634.20)
                """,
                (cls.pi1_id, cls.item1_id),
            )

            # Invoice 2: Cash, from supp2, has item1 (different batch)
            cls.pi2_id = conn.execute(
                """
                INSERT INTO purchase_invoices (voucher_no, voucher_date, purchase_type, supplier_id, invoice_no, invoice_date, total_amount, net_amount)
                VALUES ('2026-2027-Cash-80', '2026-06-10', 'Cash', ?, 'INV-1002', '2026-06-10', 1211.40, 1211.40)
                """,
                (cls.supp2_id,),
            ).lastrowid
            conn.execute(
                """
                INSERT INTO purchase_invoice_items (purchase_invoice_id, item_id, pack_size, batch_no, expiry, rate, pay_qty, free_qty, amount)
                VALUES (?, ?, '10', 'HCL5696', '2027-12-31', 121.14, 10.0, 0.0, 1211.40)
                """,
                (cls.pi2_id, cls.item1_id),
            )

            # Invoice 3: Challan-type purchase, from supp1, has item2
            cls.pi3_id = conn.execute(
                """
                INSERT INTO purchase_invoices (voucher_no, voucher_date, purchase_type, supplier_id, invoice_no, invoice_date, total_amount, net_amount)
                VALUES ('2026-2027-Challan-1', '2026-07-01', 'Challan', ?, 'CH-501', '2026-07-01', 500.0, 500.0)
                """,
                (cls.supp1_id,),
            ).lastrowid
            conn.execute(
                """
                INSERT INTO purchase_invoice_items (purchase_invoice_id, item_id, pack_size, batch_no, expiry, rate, pay_qty, free_qty, amount)
                VALUES (?, ?, '10', 'NV01', '2028-05-31', 50.0, 10.0, 2.0, 500.0)
                """,
                (cls.pi3_id, cls.item2_id),
            )

            conn.commit()
        finally:
            conn.close()

        cls.win = PharmacyMainWindow()

    @classmethod
    def tearDownClass(cls):
        cls.win.close()
        if os.path.exists(cls._DB_PATH):
            try:
                os.remove(cls._DB_PATH)
            except OSError:
                pass

    # ── TASK 1: Menu Tests ─────────────────────────────────────────────

    def test_01_menu_purchase_report_submenu_structure(self):
        """Under Reports > Purchase Report, submenu contains exactly the 6 items with separators."""
        expected_items = [
            "Companywise Itemwise Purchase",
            "Companywise Supplierwise Purchase",
            "---",
            "Supplierwise Itemwise Purchase (Invoice)",
            "Supplierwise Itemwise Purchase (Challan)",
            "---",
            "Itemwise Purchase",
            "Itemwise Batchwise Purchase",
        ]
        self.assertEqual(REPORT_PURCHASE_SUBMENU, expected_items)

        reports_btn = next(
            btn for btn in self.win._nav.findChildren(QPushButton)
            if btn.objectName() == "NavButton" and btn.text() == "Reports"
        )
        reports_menu = reports_btn.menu()
        pr_action = next(a for a in reports_menu.actions() if a.text() == "Purchase Report")
        pr_submenu = pr_action.menu()
        self.assertIsNotNone(pr_submenu, "Purchase Report must have a right-arrow submenu")

        sub_actions = pr_submenu.actions()
        non_separator_texts = [a.text() for a in sub_actions if not a.isSeparator()]
        expected_non_separators = [item for item in expected_items if item != "---"]
        self.assertEqual(non_separator_texts, expected_non_separators)

        # Check separators
        self.assertTrue(sub_actions[2].isSeparator())
        self.assertTrue(sub_actions[5].isSeparator())

    def test_02_menu_items_navigate_to_correct_pages(self):
        """Clicking each submenu item opens its own report window inside the app."""
        checks = [
            ("Companywise Itemwise Purchase", screens.CompanywiseItemwisePurchasePage, "Companywise Itemwise Purchase Report"),
            ("Companywise Supplierwise Purchase", screens.CompanywiseSupplierwisePurchasePage, "Companywise Supplierwise Purchase Report"),
            ("Supplierwise Itemwise Purchase (Invoice)", screens.SupplierwiseItemwiseInvoicePurchasePage, "Supplierwise Itemwise Purchase (Invoice) Report"),
            ("Supplierwise Itemwise Purchase (Challan)", screens.SupplierwiseItemwiseChallanPurchasePage, "Supplierwise Itemwise Purchase (Challan) Report"),
            ("Itemwise Purchase", screens.ItemwisePurchasePage, "Itemwise Purchase Report"),
            ("Itemwise Batchwise Purchase", screens.ItemwiseBatchwisePurchasePage, "Itemwise Batchwise Purchase Report"),
        ]

        for action_text, expected_class, expected_title in checks:
            self.win._on_menu_action("Reports", action_text)
            curr = self.win._stack.currentWidget()
            self.assertIsInstance(curr, expected_class)
            self.assertEqual(curr.lbl_title.text(), expected_title)
            self.assertEqual(self.win._nav.status_label.text(), f"Reports / {action_text}")

    def test_03_close_button_returns_to_counter_sale(self):
        """Clicking the close 'X' button on the blue title bar returns to Counter Sale."""
        self.win._on_menu_action("Reports", "Companywise Itemwise Purchase")
        page = self.win._stack.currentWidget()
        self.assertIsInstance(page, screens.CompanywiseItemwisePurchasePage)
        page.btn_close.click()
        self.assertIsInstance(self.win._stack.currentWidget(), screens.CounterSalePage)

    # ── TASK 2: Common Layout & Validation Tests ───────────────────────

    def test_04_common_window_layout_components(self):
        """All 6 report windows have toolbar, Main Report tab, status bar, and filter panel."""
        page = screens.CompanywiseItemwisePurchasePage()

        # Blue title bar
        self.assertEqual(page.title_bar.height(), 32)
        self.assertEqual(page.btn_close.text(), "✕")

        # Viewer toolbar controls
        self.assertIsNotNone(page.viewer.btn_export)
        self.assertIsNotNone(page.viewer.btn_print)
        self.assertIsNotNone(page.viewer.btn_copy)
        self.assertIsNotNone(page.viewer.btn_first)
        self.assertIsNotNone(page.viewer.btn_prev)
        self.assertIsNotNone(page.viewer.page_box)
        self.assertIsNotNone(page.viewer.btn_next)
        self.assertIsNotNone(page.viewer.btn_last)
        self.assertIsNotNone(page.viewer.btn_find)
        self.assertIsNotNone(page.viewer.zoom_combo)

        # Status bar
        self.assertIn("Current Page No.", page.viewer.lbl_stat_curr.text())
        self.assertIn("Total Page No.", page.viewer.lbl_stat_total.text())
        self.assertIn("Zoom Factor: 100%", page.viewer.lbl_stat_zoom.text())

        # Filter panel
        self.assertEqual(page.from_date_edit.displayFormat(), "dd/MM/yyyy")
        self.assertEqual(page.to_date_edit.displayFormat(), "dd/MM/yyyy")
        self.assertIsNotNone(page.dropdown)
        self.assertIsNotNone(page.btn_show_report)
        self.assertIsNotNone(page.btn_panel_print)

        # Print button disabled until a report is shown
        self.assertFalse(page.btn_panel_print.isEnabled())
        self.assertFalse(page.viewer.btn_print.isEnabled())

    def test_05_filter_validation(self):
        """Validate: From <= To and dropdown must be selected; otherwise show small message."""
        page = screens.CompanywiseItemwisePurchasePage()

        # Test From > To
        page.from_date_edit.setDate(QDate(2026, 12, 31))
        page.to_date_edit.setDate(QDate(2026, 1, 1))
        page.dropdown.setCurrentIndex(1)
        page._on_show_report_clicked()
        self.assertEqual(len(page._pages), 0)
        self.assertFalse(page.btn_panel_print.isEnabled())
        self.assertFalse(page.lbl_msg.isHidden())
        self.assertIn("From Date", page.lbl_msg.text())

        # Test dropdown unselected
        page.from_date_edit.setDate(QDate(2026, 4, 1))
        page.to_date_edit.setDate(QDate(2026, 9, 18))
        page.dropdown.setCurrentIndex(0)  # "-- Select Company --"
        page._on_show_report_clicked()
        self.assertEqual(len(page._pages), 0)
        self.assertFalse(page.btn_panel_print.isEnabled())
        self.assertFalse(page.lbl_msg.isHidden())
        self.assertIn("Company", page.lbl_msg.text())

        # Test valid submission clears message
        page.dropdown.setCurrentIndex(1)
        page._on_show_report_clicked()
        self.assertTrue(page.lbl_msg.isHidden())
        self.assertEqual(page.lbl_msg.text(), "")

    def test_06_store_header_identity_not_hardcoded(self):
        """Header reads store name and address from store_profile()."""
        name, address = get_default_store_identity()
        self.assertEqual(name, "SHREE SAMARTH MEDICAL AND GEN STORE")
        self.assertIn("GHORPADE HOSPITAL", address)

    # ── REPORT 1 Tests ─────────────────────────────────────────────────

    def test_07_report_1_companywise_itemwise_purchase(self):
        """REPORT 1 - Companywise Itemwise Purchase structure, grouping, and totals."""
        page = screens.CompanywiseItemwisePurchasePage()
        page.from_date_edit.setDate(QDate(2026, 4, 1))
        page.to_date_edit.setDate(QDate(2026, 9, 18))

        idx = page.dropdown.findData(self.comp_id)
        self.assertGreater(idx, 0)
        page.dropdown.setCurrentIndex(idx)

        page._on_show_report_clicked()
        self.assertGreater(len(page._pages), 0)
        self.assertTrue(page.btn_panel_print.isEnabled())

        p1 = page._pages[0]
        self.assertIn("Companywise Itemwise Purchase for 01-04-2026 To 18-09-2026", p1.header.header_line_1)
        self.assertEqual(p1.header.header_line_2, "Company : CIPLA LIMITED")

        # Check blocks
        kinds = [b.kind for b in p1.blocks]
        self.assertIn(BlockKind.GROUP_HEADER, kinds)
        self.assertIn(BlockKind.TABLE_HEADER, kinds)
        self.assertIn(BlockKind.DATA_ROW, kinds)
        self.assertIn(BlockKind.ITEM_SUBTOTAL, kinds)
        self.assertIn(BlockKind.GRAND_TOTAL, kinds)

        # Check item header: "<ITEM NAME>   <FORM>"
        grp = next(b for b in p1.blocks if b.kind == BlockKind.GROUP_HEADER)
        self.assertEqual(grp.data["text"], "CIPLOX 500   TABLET")

        # Check data row format: VhType | VhNo | VhDate | BatchNo | PackSize | ExpiryDate | Rate | Pay Qty | Free | Amount
        row_b = next(b for b in p1.blocks if b.kind == BlockKind.DATA_ROW)
        cells = row_b.data["cells"]
        self.assertEqual(cells[0], "Credit")
        self.assertEqual(cells[1], "79")
        self.assertEqual(cells[2], "08/06/2026")
        self.assertEqual(cells[3], "HCL5695")
        self.assertEqual(cells[4], "10")
        self.assertEqual(cells[5], "30-11-2027")
        self.assertEqual(cells[6], "121.14")
        self.assertEqual(cells[7], "30")
        self.assertEqual(cells[8], "6")
        self.assertEqual(cells[9], "3634.20")

        # Grand total
        gt = next(b for b in p1.blocks if b.kind == BlockKind.GRAND_TOTAL)
        self.assertEqual(gt.data["pay_str"], "40")
        self.assertEqual(gt.data["free_str"], "6")
        self.assertEqual(gt.data["amt_str"], "4845.60")

    # ── REPORT 2 Tests ─────────────────────────────────────────────────

    def test_08_report_2_companywise_supplierwise_purchase(self):
        """REPORT 2 - Companywise Supplierwise Purchase structure, exact spelling 'Suppler'."""
        page = screens.CompanywiseSupplierwisePurchasePage()
        page.from_date_edit.setDate(QDate(2026, 4, 1))
        page.to_date_edit.setDate(QDate(2026, 9, 18))

        idx = page.dropdown.findData(self.comp_id)
        page.dropdown.setCurrentIndex(idx)
        page._on_show_report_clicked()

        self.assertGreater(len(page._pages), 0)
        p1 = page._pages[0]
        self.assertEqual(p1.header.header_line_1, "Companywise Suppler Purchase for 01-04-2026 To 18-09-2026")
        self.assertEqual(p1.header.header_line_2, "Company Name: CIPLA LIMITED")

        # Check table columns: Sr No | Supplier | Address | Amount
        hdr = next(b for b in p1.blocks if b.kind == BlockKind.TABLE_HEADER)
        self.assertEqual(hdr.data["columns"], ["Sr No", "Supplier", "Address", "Amount"])

        # Check rows
        data_rows = [b for b in p1.blocks if b.kind == BlockKind.DATA_ROW]
        self.assertEqual(len(data_rows), 2)  # MAHAVIR and ARIHANT

        # Check Total row
        gt = next(b for b in p1.blocks if b.kind == BlockKind.GRAND_TOTAL)
        self.assertEqual(gt.data["label"], "Total :")
        self.assertEqual(gt.data["amt_str"], "4845.60")

    # ── REPORT 3 Tests ─────────────────────────────────────────────────

    def test_09_report_3_supplierwise_itemwise_invoice_purchase(self):
        """REPORT 3 - Supplierwise Itemwise Purchase (Invoice) includes only invoices."""
        page = screens.SupplierwiseItemwiseInvoicePurchasePage()
        page.from_date_edit.setDate(QDate(2026, 4, 1))
        page.to_date_edit.setDate(QDate(2026, 9, 18))

        idx = page.dropdown.findData(self.supp1_id)
        page.dropdown.setCurrentIndex(idx)
        page._on_show_report_clicked()

        self.assertGreater(len(page._pages), 0)
        p1 = page._pages[0]
        self.assertIn("Supplierwise Itemwise Purchase for 01-04-2026 To 18-09-2026", p1.header.header_line_1)
        self.assertEqual(p1.header.header_line_2, "Supplier: MAHAVIR DRUG AGENCY")

        # Check group title: "<ITEM NAME> (<COMPANY SHORT CODE>)"
        grp = next(b for b in p1.blocks if b.kind == BlockKind.GROUP_HEADER)
        self.assertEqual(grp.data["text"], "CIPLOX 500 (CIP)")

        # Columns: VhType | InvoiceNo | InvoiceDate | BatchNo | PackSize | ExpiryDate | Rate | Pay Qty | Free | Amount
        hdr = next(b for b in p1.blocks if b.kind == BlockKind.TABLE_HEADER)
        self.assertEqual(hdr.data["columns"][1], "InvoiceNo")
        self.assertEqual(hdr.data["columns"][2], "InvoiceDate")

        # Challan item (NERVMAX) should NOT be present in Invoice report
        texts = [b.data.get("text", "") for b in p1.blocks if b.kind == BlockKind.GROUP_HEADER]
        self.assertNotIn("NERVMAX XT OD (ALK)", texts)

    # ── REPORT 4 Tests ─────────────────────────────────────────────────

    def test_10_report_4_supplierwise_itemwise_challan_purchase(self):
        """REPORT 4 - Supplierwise Itemwise Purchase (Challan) includes only challans."""
        page = screens.SupplierwiseItemwiseChallanPurchasePage()
        page.from_date_edit.setDate(QDate(2026, 4, 1))
        page.to_date_edit.setDate(QDate(2026, 9, 18))

        idx = page.dropdown.findData(self.supp1_id)
        page.dropdown.setCurrentIndex(idx)
        page._on_show_report_clicked()

        self.assertGreater(len(page._pages), 0)
        p1 = page._pages[0]
        self.assertIn("Supplierwise Itemwise Purchase (Challan) for 01-04-2026 To 18-09-2026", p1.header.header_line_1)

        # Columns: VhType | ChallanNo | ChallanDate | ...
        hdr = next(b for b in p1.blocks if b.kind == BlockKind.TABLE_HEADER)
        self.assertEqual(hdr.data["columns"][1], "ChallanNo")
        self.assertEqual(hdr.data["columns"][2], "ChallanDate")

        # Only challan item (NERVMAX) should be present
        grp = next(b for b in p1.blocks if b.kind == BlockKind.GROUP_HEADER)
        self.assertEqual(grp.data["text"], "NERVMAX XT OD (ALK)")

        # Row check
        row_b = next(b for b in p1.blocks if b.kind == BlockKind.DATA_ROW)
        self.assertEqual(row_b.data["cells"][1], "501")  # Challan No (CH-501)
        self.assertEqual(row_b.data["cells"][7], "10")   # Pay Qty
        self.assertEqual(row_b.data["cells"][8], "2")    # Free

    # ── REPORT 5 Tests ─────────────────────────────────────────────────

    def test_11_report_5_itemwise_purchase(self):
        """REPORT 5 - Itemwise Purchase structure and line 2 format."""
        page = screens.ItemwisePurchasePage()
        page.from_date_edit.setDate(QDate(2026, 4, 1))
        page.to_date_edit.setDate(QDate(2026, 9, 18))

        idx = page.dropdown.findData(self.item1_id)
        page.dropdown.setCurrentIndex(idx)
        page._on_show_report_clicked()

        self.assertGreater(len(page._pages), 0)
        p1 = page._pages[0]
        self.assertEqual(p1.header.header_line_1, "Itemwise Purchase for 01-04-2026 To 18-09-2026")
        self.assertEqual(p1.header.header_line_2, "CIPLOX 500 - TABLET (CIP)")

        # Columns: InvoiceNo | VhType | VhNo | VhDate | Supplier | BatchNo | Rate | Pay Qty | Free | Amount
        hdr = next(b for b in p1.blocks if b.kind == BlockKind.TABLE_HEADER)
        self.assertEqual(
            hdr.data["columns"],
            ["InvoiceNo", "VhType", "VhNo", "VhDate", "Supplier", "BatchNo", "Rate", "Pay Qty", "Free", "Amount"],
        )

        # 2 purchase rows
        data_rows = [b for b in p1.blocks if b.kind == BlockKind.DATA_ROW]
        self.assertEqual(len(data_rows), 2)

        # Bordered bold Total row
        tot = next(b for b in p1.blocks if b.kind == BlockKind.GRAND_TOTAL)
        self.assertEqual(tot.data["label"], "Total :")
        self.assertEqual(tot.data["pay_str"], "40")
        self.assertEqual(tot.data["free_str"], "6")
        self.assertEqual(tot.data["amt_str"], "4845.60")

    # ── REPORT 6 Tests ─────────────────────────────────────────────────

    def test_12_report_6_itemwise_batchwise_purchase(self):
        """REPORT 6 - BatchNo and Rate printed only on first row of batch, batch subtotal box."""
        # Add another purchase of the SAME batch to test multi-row batch behavior
        conn = get_connection()
        try:
            pi_extra = conn.execute(
                """
                INSERT INTO purchase_invoices (voucher_no, voucher_date, purchase_type, supplier_id, invoice_no, invoice_date, total_amount, net_amount)
                VALUES ('2026-2027-Credit-81', '2026-06-12', 'Credit', ?, 'INV-1003', '2026-06-12', 1211.40, 1211.40)
                """,
                (self.supp1_id,),
            ).lastrowid
            conn.execute(
                """
                INSERT INTO purchase_invoice_items (purchase_invoice_id, item_id, pack_size, batch_no, expiry, rate, pay_qty, free_qty, amount)
                VALUES (?, ?, '10', 'HCL5695', '2027-11-30', 121.14, 10.0, 0.0, 1211.40)
                """,
                (pi_extra, self.item1_id),
            )
            conn.commit()
        finally:
            conn.close()

        page = screens.ItemwiseBatchwisePurchasePage()
        page.from_date_edit.setDate(QDate(2026, 4, 1))
        page.to_date_edit.setDate(QDate(2026, 9, 18))

        idx = page.dropdown.findData(self.item1_id)
        page.dropdown.setCurrentIndex(idx)
        page._on_show_report_clicked()

        self.assertGreater(len(page._pages), 0)
        p1 = page._pages[0]

        # For batch HCL5695 with 2 rows:
        # First row has BatchNo and Rate; second row has blank BatchNo and Rate
        rows_5695 = [
            b for b in p1.blocks
            if b.kind == BlockKind.DATA_ROW and (b.data["cells"][5] == "HCL5695" or b.data["cells"][0] == "1003")
        ]
        self.assertEqual(len(rows_5695), 2)
        # Row 1: has BatchNo and Rate
        self.assertEqual(rows_5695[0].data["cells"][5], "HCL5695")
        self.assertEqual(rows_5695[0].data["cells"][6], "121.14")
        # Row 2: blank BatchNo and Rate
        self.assertEqual(rows_5695[1].data["cells"][5], "")
        self.assertEqual(rows_5695[1].data["cells"][6], "")

        # Subtotal box for HCL5695
        sub_5695 = next(
            b for b in p1.blocks
            if b.kind == BlockKind.BATCH_SUBTOTAL and b.data.get("batch_no") == "HCL5695"
        )
        self.assertEqual(sub_5695.data["pay_str"], "40")
        self.assertEqual(sub_5695.data["free_str"], "6")
        self.assertEqual(sub_5695.data["amt_str"], "4845.60")

        # Grand Total
        gt = next(b for b in p1.blocks if b.kind == BlockKind.GRAND_TOTAL)
        self.assertEqual(gt.data["label"], "Grand Total :")
        self.assertEqual(gt.data["pay_str"], "50")
        self.assertEqual(gt.data["free_str"], "6")
        self.assertEqual(gt.data["amt_str"], "6057.00")

    # ── Print & Export Tests ───────────────────────────────────────────

    def test_13_print_and_export_to_pdf(self):
        """Print / Export produces a valid PDF file matching the A4 portrait layout."""
        page = screens.CompanywiseItemwisePurchasePage()
        page.from_date_edit.setDate(QDate(2026, 4, 1))
        page.to_date_edit.setDate(QDate(2026, 9, 18))
        idx = page.dropdown.findData(self.comp_id)
        page.dropdown.setCurrentIndex(idx)
        page._on_show_report_clicked()

        temp_pdf = os.path.join(tempfile.gettempdir(), "_test_export_purchase_report.pdf")
        if os.path.exists(temp_pdf):
            try:
                os.remove(temp_pdf)
            except OSError:
                pass

        ok = print_or_export_report_pages(page._pages, output_pdf_path=temp_pdf)
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(temp_pdf))
        self.assertGreater(os.path.getsize(temp_pdf), 1000)

        # Clean up
        if os.path.exists(temp_pdf):
            try:
                os.remove(temp_pdf)
            except OSError:
                pass

    def test_14_viewer_toolbar_interactions(self):
        """Viewer toolbar zoom, copy, find, page navigation work correctly."""
        page = screens.CompanywiseItemwisePurchasePage()
        page.from_date_edit.setDate(QDate(2026, 4, 1))
        page.to_date_edit.setDate(QDate(2026, 9, 18))
        idx = page.dropdown.findData(self.comp_id)
        page.dropdown.setCurrentIndex(idx)
        page._on_show_report_clicked()

        viewer = page.viewer
        self.assertEqual(len(viewer._pages), 1)

        # Zoom
        viewer.zoom_combo.setCurrentText("150%")
        self.assertAlmostEqual(viewer._zoom_factor, 1.5)
        self.assertIn("150%", viewer.lbl_stat_zoom.text())

        # Page navigation
        viewer.first_page()
        self.assertEqual(viewer.page_box.text(), "1")

        # Copy puts text onto clipboard
        viewer._on_copy()
        cb_text = QApplication.clipboard().text()
        self.assertIn("SHREE SAMARTH MEDICAL AND GEN STORE", cb_text)
        self.assertIn("CIPLOX 500", cb_text)

    def test_15_set_history_financial_year_none_resets(self):
        """Passing None to set_history_financial_year resets dates to active FY."""
        page = screens.CompanywiseItemwisePurchasePage()
        # Set to specific non-default dates
        page.set_history_financial_year({
            "name": "2018-2019",
            "start_date": "2018-04-01",
            "end_date": "2019-03-31",
        })
        self.assertEqual(page.from_date_edit.date().year(), 2018)
        self.assertEqual(page.to_date_edit.date().year(), 2019)

        # Reset with None
        page.set_history_financial_year(None)
        self.assertEqual(page.from_date_edit.date().year(), 2026)

    def test_16_searchable_dropdown_partial_match(self):
        """Typing partial text into searchable dropdown resolves the matching item ID."""
        page = screens.CompanywiseItemwisePurchasePage()
        page.dropdown.setEditText("cipla")
        self.assertEqual(page.get_selected_id(), self.comp_id)

    def test_17_paginate_blocks_orphan_header_prevention(self):
        """Group headers are not orphaned at the bottom of a page without rows."""
        from screens.purchase_reports import MAX_PAGE_BODY_HEIGHT, paginate_blocks
        from ui.crystal_report_viewer import ReportBlock, ReportHeaderData
        hdr = ReportHeaderData("Store", "Addr", "Line1", "Line2")
        tb_hdr = ReportBlock(kind=BlockKind.TABLE_HEADER, height=24.0)

        # Fill page 1 up to MAX_PAGE_BODY_HEIGHT - 30px (e.g. 950px)
        blocks = [ReportBlock(kind=BlockKind.DATA_ROW, height=950.0)]
        # Add a group header (height 22.0) which would fit in 980-950=30px,
        # but cannot fit the group header + table header + at least 1 row (66px)
        blocks.append(ReportBlock(kind=BlockKind.GROUP_HEADER, height=22.0))
        blocks.append(tb_hdr)
        blocks.append(ReportBlock(kind=BlockKind.DATA_ROW, height=20.0))

        pages = paginate_blocks(hdr, blocks, tb_hdr)
        self.assertEqual(len(pages), 2)
        # Page 1 should NOT contain the GROUP_HEADER
        p1_kinds = [b.kind for b in pages[0].blocks]
        self.assertNotIn(BlockKind.GROUP_HEADER, p1_kinds)
        # Page 2 MUST start with the GROUP_HEADER
        p2_kinds = [b.kind for b in pages[1].blocks]
        self.assertEqual(p2_kinds[0], BlockKind.GROUP_HEADER)

    def test_18_dropdown_selection_after_edit(self):
        """Editing combo text after selecting an item correctly resolves the typed item, not the old item."""
        page = screens.CompanywiseItemwisePurchasePage()
        # First select company 1
        idx1 = page.dropdown.findData(self.comp_id)
        page.dropdown.setCurrentIndex(idx1)
        self.assertEqual(page.get_selected_id(), self.comp_id)

        # Now edit text to company 2 without changing index manually
        page.dropdown.setEditText("alkem")
        self.assertEqual(page.get_selected_id(), self.comp2_id)

    def test_19_print_button_click_offscreen_does_not_hang(self):
        """Calling print_report() or clicking print button executes without hanging in headless mode."""
        page = screens.CompanywiseItemwisePurchasePage()
        page.from_date_edit.setDate(QDate(2026, 4, 1))
        page.to_date_edit.setDate(QDate(2026, 9, 18))
        idx = page.dropdown.findData(self.comp_id)
        page.dropdown.setCurrentIndex(idx)
        page._on_show_report_clicked()
        self.assertTrue(page.btn_panel_print.isEnabled())

        # Click panel print button — must complete quickly without hang
        page.btn_panel_print.click()

        # Call viewer toolbar print directly — must complete quickly without hang
        page.print_report()

    def test_20_validation_clears_previous_report(self):
        """When validation fails on Show Report, any previous report is cleared and print is disabled."""
        page = screens.CompanywiseItemwisePurchasePage()
        page.from_date_edit.setDate(QDate(2026, 4, 1))
        page.to_date_edit.setDate(QDate(2026, 9, 18))
        idx = page.dropdown.findData(self.comp_id)
        page.dropdown.setCurrentIndex(idx)
        page._on_show_report_clicked()
        self.assertEqual(len(page._pages), 1)
        self.assertTrue(page.btn_panel_print.isEnabled())

        # Now set invalid date: From > To
        page.from_date_edit.setDate(QDate(2026, 12, 31))
        page.to_date_edit.setDate(QDate(2026, 1, 1))
        page._on_show_report_clicked()

        self.assertEqual(len(page._pages), 0)
        self.assertFalse(page.btn_panel_print.isEnabled())
        self.assertIsNone(page.viewer.canvas._page)

    def test_21_canonical_entity_name_in_header_even_when_partial_typed(self):
        """When user types partial text into dropdown, Header Line 2 shows full canonical name."""
        page = screens.CompanywiseItemwisePurchasePage()
        page.from_date_edit.setDate(QDate(2026, 4, 1))
        page.to_date_edit.setDate(QDate(2026, 9, 18))
        page.dropdown.setEditText("cipla")
        page._on_show_report_clicked()

        self.assertEqual(len(page._pages), 1)
        self.assertEqual(page._pages[0].header.header_line_2, "Company : CIPLA LIMITED")

    def test_22_date_format_helpers_all_variants(self):
        """Date format helpers convert YYYY-MM-DD, DD-MM-YYYY, YYYY/MM/DD, DD/MM/YYYY properly."""
        self.assertEqual(fmt_date_slash("2026-06-08"), "08/06/2026")
        self.assertEqual(fmt_date_slash("08-06-2026"), "08/06/2026")
        self.assertEqual(fmt_date_slash("2026/06/08"), "08/06/2026")
        self.assertEqual(fmt_date_slash("08/06/2026"), "08/06/2026")
        self.assertEqual(fmt_date_slash(""), "")

        self.assertEqual(fmt_date_dash("2026-06-08"), "08-06-2026")
        self.assertEqual(fmt_date_dash("08-06-2026"), "08-06-2026")
        self.assertEqual(fmt_date_dash("2026/06/08"), "08-06-2026")
        self.assertEqual(fmt_date_dash("08/06/2026"), "08-06-2026")
        self.assertEqual(fmt_date_dash("12/27"), "12/27")

    def test_23_batchwise_case_insensitive_grouping(self):
        """Batches with casing differences group into a single batch in Report 6."""
        conn = get_connection()
        try:
            pi_lower = conn.execute(
                """
                INSERT INTO purchase_invoices (voucher_no, voucher_date, purchase_type, supplier_id, invoice_no, invoice_date, total_amount, net_amount)
                VALUES ('2026-2027-Credit-99', '2026-06-15', 'Credit', ?, 'INV-1099', '2026-06-15', 1211.40, 1211.40)
                """,
                (self.supp1_id,),
            ).lastrowid
            conn.execute(
                """
                INSERT INTO purchase_invoice_items (purchase_invoice_id, item_id, pack_size, batch_no, expiry, rate, pay_qty, free_qty, amount)
                VALUES (?, ?, '10', 'hcl5695', '2027-11-30', 121.14, 5.0, 1.0, 605.70)
                """,
                (pi_lower, self.item1_id),
            )
            conn.commit()
        finally:
            conn.close()

        page = screens.ItemwiseBatchwisePurchasePage()
        page.from_date_edit.setDate(QDate(2026, 4, 1))
        page.to_date_edit.setDate(QDate(2026, 9, 18))
        idx = page.dropdown.findData(self.item1_id)
        page.dropdown.setCurrentIndex(idx)
        page._on_show_report_clicked()

        p1 = page._pages[0]
        # HCL5695 and hcl5695 must produce exactly ONE subtotal block
        sub_blocks = [
            b for b in p1.blocks
            if b.kind == BlockKind.BATCH_SUBTOTAL and b.data.get("batch_no").upper() == "HCL5695"
        ]
        self.assertEqual(len(sub_blocks), 1)


if __name__ == "__main__":
    unittest.main()
