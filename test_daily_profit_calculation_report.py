"""Comprehensive tests for the new Daily Profit Calculation report.

Verifies:
1. Reports menu contains both separate options:
   - 'Profit Calculation' (existing report, unchanged)
   - 'Daily Profit Calculation' (new report with actual purchase cost calculation)
2. Each option opens its own distinct page.
3. Actual purchase cost per tablet calculation:
   - Paid Qty = 100, Free Qty = 20, Rate = 10, Discount = 10%
   - Total Received = 120
   - Gross = 1000, Discount = 100, Net Purchase Cost = 900
   - Cost Per Tablet = 900 / 120 = 7.50
   - Sold Qty = 10, Selling Rate = 12
   - Profit Per Tablet = 4.50
   - Net Sales = 120, Purchase Cost = 75, Profit = 45
4. Report table columns:
   1. Sr. No.
   2. Medicine Name
   3. Company Name
   4. Batch Number
   5. Total Quantity Sold
   6. Actual Selling Rate
   7. Purchase Rate
   8. Free Quantity
   9. Purchase Discount
   10. Actual Net Purchase Cost Per Tablet
   11. Total Net Sales
   12. Total Purchase Cost of Sold Quantity
   13. Total Profit
5. Totals row at bottom for net sales, purchase cost, profit, sold qty.
6. Filters: From Date, To Date, Medicine filter, Company filter.
7. Actions: Search, Clear, Refresh, Print, Export CSV.
8. Printable A4 landscape report page generation.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch, DEFAULT

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

import database.connection as db_conn
from database import auth, financial_year
from database.account_roles import ensure_system_ledgers
from database.company_dao import CompanyDAO
from database.customer_dao import CustomerDAO
from database.item_dao import ItemDAO
from database.purchase_dao import PurchaseDAO
from database.sales_dao import SalesDAO
from database.supplier_dao import SupplierDAO
from database.unit_dao import UnitDAO
from database.sales_reports_dao import SalesReportsDAO

from ui.menu_data import MENUS, REPORT_SALES_SUBMENU
from ui.navigation_bar import NavigationBar, MENU_SHORTCUTS
from ui.main_window import PharmacyMainWindow
import screens
from screens.sales_reports import DailyProfitCalculationPage as ExistingProfitCalcPage
from screens.daily_profit_calculation import (
    DailyProfitCalculationReportPage,
    DailyProfitCostReportWidget,
    DailyProfitCostCalculationDialog,
)


class TestDailyProfitCalculationReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls._temp_path = cls._temp_file.name
        cls._temp_file.close()

        cls._db_patch = patch.object(db_conn, "get_db_path", return_value=cls._temp_path)
        cls._db_patch.start()
        os.environ["PHARMACY_DB"] = cls._temp_path

        db_conn.init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        ensure_system_ledgers()

        # Seed sample data for testing exact calculation:
        cls.cid1 = CompanyDAO.insert("Alpha Pharma", "ALP")
        cls.cid2 = CompanyDAO.insert("Beta Labs", "BET")
        cls.uid = UnitDAO.insert("Tablet")
        cls.item1 = ItemDAO.insert(item_name="PARACETAMOL", unit_id=cls.uid, company_id=cls.cid1, pack_size="1")
        cls.item2 = ItemDAO.insert(item_name="AMOXICILLIN", unit_id=cls.uid, company_id=cls.cid2, pack_size="1")
        cls.supp_id = SupplierDAO.insert("Med Distributors", "9876543210")
        cls.cust_id = CustomerDAO.insert("Walkin Patient", "Local City")

        # Purchase 1 (matches user example exactly):
        # PARACETAMOL: Paid 100, Free 20, Rate 10, Discount 10%
        # Gross = 1000, Disc = 100, Net = 900, Qty = 120 -> Cost/Tab = 7.50
        PurchaseDAO.insert_invoice(
            voucher_no="PUR-001",
            voucher_date="2026-10-10",
            voucher_time="09:00:00",
            purchase_type="Credit",
            supplier_id=cls.supp_id,
            invoice_no="INV-001",
            invoice_date="2026-10-10",
            invoice_net_amount=900.0,
            bill_discount=0.0,
            due_date="2026-11-10",
            total_amount=900.0,
            gst_amount=0.0,
            debit_note_amount=0.0,
            other_amount=0.0,
            paid_amount=0.0,
            round_off=0.0,
            net_amount=900.0,
            remarks="",
            items=[{
                "item_id": cls.item1,
                "batch_no": "PARA-B1",
                "expiry": "2028-12-31",
                "pack_size": "1",
                "pay_qty": 100.0,
                "free_qty": 20.0,
                "rate": 10.0,
                "mrp": 15.0,
                "discount": 10.0,
                "gst_percent": 0.0,
                "gst_amount": 0.0,
                "amount": 900.0,
                "purchase_rate": 10.0,
                "net_rate": 7.5,
                "pp": 25.0,
            }],
        )

        # Purchase 2:
        # AMOXICILLIN: Paid 50, Free 0, Rate 20, Discount 5%
        # Gross = 1000, Disc = 50, Net = 950, Qty = 50 -> Cost/Tab = 19.00
        PurchaseDAO.insert_invoice(
            voucher_no="PUR-002",
            voucher_date="2026-10-10",
            voucher_time="09:30:00",
            purchase_type="Credit",
            supplier_id=cls.supp_id,
            invoice_no="INV-002",
            invoice_date="2026-10-10",
            invoice_net_amount=950.0,
            bill_discount=0.0,
            due_date="2026-11-10",
            total_amount=950.0,
            gst_amount=0.0,
            debit_note_amount=0.0,
            other_amount=0.0,
            paid_amount=0.0,
            round_off=0.0,
            net_amount=950.0,
            remarks="",
            items=[{
                "item_id": cls.item2,
                "batch_no": "AMOX-B1",
                "expiry": "2027-10-31",
                "pack_size": "1",
                "pay_qty": 50.0,
                "free_qty": 0.0,
                "rate": 20.0,
                "mrp": 25.0,
                "discount": 5.0,
                "gst_percent": 0.0,
                "gst_amount": 0.0,
                "amount": 950.0,
                "purchase_rate": 20.0,
                "net_rate": 19.0,
                "pp": 25.0,
            }],
        )

        # Get batch IDs
        conn = db_conn.get_connection()
        cls.sb_para = conn.execute("SELECT id FROM stock_batches WHERE item_id = ? AND batch_no = ?", (cls.item1, "PARA-B1")).fetchone()[0]
        cls.sb_amox = conn.execute("SELECT id FROM stock_batches WHERE item_id = ? AND batch_no = ?", (cls.item2, "AMOX-B1")).fetchone()[0]
        conn.close()

        # Sale 1 (matches user example exactly):
        # PARACETAMOL: 10 sold, Rate 12 -> Net Sales = 120
        SalesDAO.insert_invoice(
            bill_no="BILL-001",
            sale_date="2026-10-12",
            sale_time="10:00:00",
            sale_type="Cash",
            customer_id=cls.cust_id,
            patient_name="Patient One",
            doctor_id=None,
            discount=0.0,
            paid_amount=120.0,
            total_amount=120.0,
            round_off=0.0,
            net_amount=120.0,
            remarks="",
            items=[{
                "item_id": cls.item1,
                "stock_batch_id": cls.sb_para,
                "batch_no": "PARA-B1",
                "expiry": "2028-12-31",
                "pack_size": "1",
                "mrp": 15.0,
                "sale_qty": 10.0,
                "discount_amount": 0.0,
                "amount": 120.0,
            }],
        )

        # Sale 2:
        # AMOXICILLIN: 5 sold, Rate 24 -> Net Sales = 120
        # Cost = 5 * 19.00 = 95.00, Profit = 120 - 95 = 25.00
        SalesDAO.insert_invoice(
            bill_no="BILL-002",
            sale_date="2026-10-12",
            sale_time="10:30:00",
            sale_type="Cash",
            customer_id=cls.cust_id,
            patient_name="Patient Two",
            doctor_id=None,
            discount=0.0,
            paid_amount=120.0,
            total_amount=120.0,
            round_off=0.0,
            net_amount=120.0,
            remarks="",
            items=[{
                "item_id": cls.item2,
                "stock_batch_id": cls.sb_amox,
                "batch_no": "AMOX-B1",
                "expiry": "2027-10-31",
                "pack_size": "1",
                "mrp": 25.0,
                "sale_qty": 5.0,
                "discount_amount": 0.0,
                "amount": 120.0,
            }],
        )

        cls.app = QApplication.instance() or QApplication([])

        cls.messages = patch.multiple(
            QMessageBox, warning=DEFAULT, information=DEFAULT,
            critical=DEFAULT, question=DEFAULT,
        )
        cls.messages.start()

        cls.win = PharmacyMainWindow()
        cls.win.resize(1366, 768)
        cls.win.show()
        cls.app.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.messages.stop()
        cls.win.hide()
        cls.win.deleteLater()
        cls.app.processEvents()
        cls._db_patch.stop()
        os.environ.pop("PHARMACY_DB", None)
        if os.path.exists(cls._temp_path):
            try:
                os.remove(cls._temp_path)
            except OSError:
                pass

    def test_01_menu_contains_both_reports(self):
        """Verifies Reports menu submenu has both 'Profit Calculation' and 'Daily Profit Calculation'."""
        self.assertIn("Profit Calculation", REPORT_SALES_SUBMENU)
        self.assertIn("Daily Profit Calculation", REPORT_SALES_SUBMENU)

        # Check navigation bar actions under Reports -> Sales Report
        reports_btn = next(
            btn for btn in self.win._nav.findChildren(QPushButton)
            if btn.objectName() == "NavButton" and btn.text() == "Reports"
        )
        reports_menu = reports_btn.menu()
        sales_sub = next(a for a in reports_menu.actions() if a.text() == "Sales Report").menu()
        action_names = [a.text() for a in sales_sub.actions() if not a.isSeparator()]

        self.assertIn("Profit Calculation", action_names)
        self.assertIn("Daily Profit Calculation", action_names)

    def test_02_separate_pages_for_each_report(self):
        """Clicking each report opens its separate, distinct page."""
        # 1. Profit Calculation opens existing page
        self.win._on_menu_action("Reports", "Profit Calculation")
        self.app.processEvents()
        curr_profit = self.win._stack.currentWidget()
        self.assertIsInstance(curr_profit, ExistingProfitCalcPage)

        # 2. Daily Profit Calculation opens new page
        self.win._on_menu_action("Reports", "Daily Profit Calculation")
        self.app.processEvents()
        curr_daily = self.win._stack.currentWidget()
        self.assertIsInstance(curr_daily, DailyProfitCalculationReportPage)
        self.assertIsNot(curr_profit, curr_daily)
        self.assertIn("Daily Profit Calculation", self.win.windowTitle())

    def test_03_actual_purchase_cost_and_profit_calculation_math(self):
        """Verify calculations match the user's exact specification and sample:
        PARACETAMOL:
        - Paid Qty = 100, Free Qty = 20, Rate = 10, Discount = 10%
        - Total Received = 120, Gross = 1000, Discount = 100, Net Cost = 900
        - Actual Purchase Cost Per Tablet = 900 / 120 = 7.50
        - Sold Qty = 10, Selling Rate = 12
        - Profit Per Tablet = 12 - 7.50 = 4.50
        - Total Net Sales = 120, Total Purchase Cost = 75, Total Profit = 45
        """
        res = SalesReportsDAO.get_daily_profit_cost_calculation("2026-10-10", "2026-10-15")
        rows = res["rows"]
        para = next((r for r in rows if r["item_name"] == "PARACETAMOL"), None)
        self.assertIsNotNone(para)

        self.assertEqual(para["company_name"], "Alpha Pharma")
        self.assertEqual(para["batch_no"], "PARA-B1")
        self.assertEqual(para["total_sold_qty"], 10.0)
        self.assertEqual(para["actual_selling_rate"], 12.0)
        self.assertEqual(para["purchase_rate"], 10.0)
        self.assertEqual(para["free_qty"], 20.0)
        self.assertEqual(para["purchase_discount"], 10.0)
        self.assertEqual(para["actual_cost_per_tablet"], 7.50)
        self.assertEqual(para["total_net_sales"], 120.0)
        self.assertEqual(para["total_purchase_cost"], 75.0)
        self.assertEqual(para["total_profit"], 45.0)

        # Also verify AMOXICILLIN:
        # Rate = 20, Disc = 5% -> Cost/Tab = 19.00
        # Sold = 5, Selling Rate = 24 -> Sales = 120, Cost = 95, Profit = 25
        amox = next((r for r in rows if r["item_name"] == "AMOXICILLIN"), None)
        self.assertIsNotNone(amox)
        self.assertEqual(amox["actual_cost_per_tablet"], 19.00)
        self.assertEqual(amox["total_sold_qty"], 5.0)
        self.assertEqual(amox["total_net_sales"], 120.0)
        self.assertEqual(amox["total_purchase_cost"], 95.0)
        self.assertEqual(amox["total_profit"], 25.0)

        # Summary check
        summary = res["summary"]
        self.assertEqual(summary["total_records"], 2)
        self.assertEqual(summary["total_sold_qty"], 15.0)
        self.assertEqual(summary["total_net_sales"], 240.0)
        self.assertEqual(summary["total_purchase_cost"], 170.0)
        self.assertEqual(summary["total_profit"], 70.0)

    def test_04_report_columns_displayed_in_table(self):
        """Verifies all 13 columns and values match on-screen table layout."""
        page = DailyProfitCalculationReportPage()
        page.widget.from_date_edit.setDate(QDate(2026, 10, 10))
        page.widget.to_date_edit.setDate(QDate(2026, 10, 15))
        page.widget.load_data()

        table = page.widget.table
        self.assertEqual(table.columnCount(), 13)

        expected_headers = [
            "Sr. No.",
            "Medicine Name",
            "Company Name",
            "Batch Number",
            "Total Quantity Sold",
            "Actual Selling Rate",
            "Purchase Rate",
            "Free Quantity",
            "Purchase Discount",
            "Actual Net Purchase Cost Per Tablet",
            "Total Net Sales",
            "Total Purchase Cost of Sold Quantity",
            "Total Profit",
        ]
        for c, h in enumerate(expected_headers):
            self.assertEqual(table.horizontalHeaderItem(c).text(), h)

        # 2 data rows + 1 total row = 3 rows
        self.assertEqual(table.rowCount(), 3)

        # Find row for PARACETAMOL
        para_row = 0 if table.item(0, 1).text() == "PARACETAMOL" else 1
        self.assertEqual(table.item(para_row, 1).text(), "PARACETAMOL")
        self.assertEqual(table.item(para_row, 2).text(), "Alpha Pharma")
        self.assertEqual(table.item(para_row, 3).text(), "PARA-B1")
        self.assertEqual(table.item(para_row, 4).text(), "10.00")
        self.assertEqual(table.item(para_row, 5).text(), "12.00")
        self.assertEqual(table.item(para_row, 6).text(), "10.00")
        self.assertEqual(table.item(para_row, 7).text(), "20.00")
        self.assertEqual(table.item(para_row, 8).text(), "10.00%")
        self.assertEqual(table.item(para_row, 9).text(), "7.50")
        self.assertEqual(table.item(para_row, 10).text(), "120.00")
        self.assertEqual(table.item(para_row, 11).text(), "75.00")
        self.assertEqual(table.item(para_row, 12).text(), "45.00")

        # Total Row (Row 2)
        self.assertEqual(table.item(2, 0).text(), "Total :")
        self.assertEqual(table.item(2, 4).text(), "15.00")
        self.assertEqual(table.item(2, 10).text(), "240.00")
        self.assertEqual(table.item(2, 11).text(), "170.00")
        self.assertEqual(table.item(2, 12).text(), "70.00")

    def test_05_filters_medicine_and_company(self):
        """Verifies filtering by Medicine and Company."""
        page = DailyProfitCalculationReportPage()
        page.widget.from_date_edit.setDate(QDate(2026, 10, 10))
        page.widget.to_date_edit.setDate(QDate(2026, 10, 15))

        # Filter by PARACETAMOL only
        idx = page.widget.item_combo.findData(self.item1)
        self.assertGreater(idx, 0)
        page.widget.item_combo.setCurrentIndex(idx)
        page.widget.load_data()

        # 1 data row + 1 total row = 2 rows
        self.assertEqual(page.widget.table.rowCount(), 2)
        self.assertEqual(page.widget.table.item(0, 1).text(), "PARACETAMOL")

        # Clear filters
        page.widget.clear_filters()
        self.assertEqual(page.widget.table.rowCount(), 0)
        self.assertEqual(page.widget.item_combo.currentIndex(), 0)
        self.assertEqual(page.widget.company_combo.currentIndex(), 0)

        # Filter by Beta Labs company only
        c_idx = page.widget.company_combo.findData(self.cid2)
        self.assertGreater(c_idx, 0)
        page.widget.company_combo.setCurrentIndex(c_idx)
        page.widget.from_date_edit.setDate(QDate(2026, 10, 10))
        page.widget.to_date_edit.setDate(QDate(2026, 10, 15))
        page.widget.load_data()

        self.assertEqual(page.widget.table.rowCount(), 2)
        self.assertEqual(page.widget.table.item(0, 1).text(), "AMOXICILLIN")

    def test_06_printing_generates_pages(self):
        """Verifies printable report pages are generated in landscape with headers and totals."""
        page = DailyProfitCalculationReportPage()
        page.widget.from_date_edit.setDate(QDate(2026, 10, 10))
        page.widget.to_date_edit.setDate(QDate(2026, 10, 15))
        page.widget.load_data()

        self.assertTrue(page.widget.btn_print.isEnabled())
        self.assertGreater(len(page.widget._pages), 0)

        rpt_page = page.widget._pages[0]
        self.assertEqual(rpt_page.orientation, "landscape")
        self.assertEqual(rpt_page.header.header_line_1, "DAILY PROFIT CALCULATION")
        self.assertIn("Total Net Sales: ₹240.00", rpt_page.header.header_line_3)
        self.assertIn("Total Profit: ₹70.00", rpt_page.header.header_line_3)

    def test_07_gst_included_according_to_item_master(self):
        """Verifies actual purchase cost and profit calculation include GST according to Item Master."""
        # 1. Item with GST 5% in Item Master
        item_gst5 = ItemDAO.insert(
            item_name="AZITHROMYCIN 500",
            unit_id=self.uid,
            company_id=self.cid1,
            pack_size="1",
            tax_structure="5",
        )
        PurchaseDAO.insert_invoice(
            voucher_no="PUR-GST5",
            voucher_date="2026-10-12",
            voucher_time="10:00:00",
            purchase_type="Credit",
            supplier_id=self.supp_id,
            invoice_no="INV-GST5",
            invoice_date="2026-10-12",
            invoice_net_amount=945.0,
            bill_discount=0.0,
            due_date="2026-11-12",
            total_amount=945.0,
            gst_amount=45.0,
            debit_note_amount=0.0,
            other_amount=0.0,
            paid_amount=0.0,
            round_off=0.0,
            net_amount=945.0,
            remarks="",
            items=[{
                "item_id": item_gst5,
                "batch_no": "AZI-B1",
                "expiry": "2028-12-31",
                "pack_size": "1",
                "pay_qty": 100.0,
                "free_qty": 20.0,
                "rate": 10.0,
                "mrp": 15.0,
                "discount": 10.0,
                "gst_percent": 5.0,
                "gst_amount": 45.0,
                "amount": 900.0,
                "purchase_rate": 10.0,
                "net_rate": 7.88,
                "pp": 25.0,
            }],
        )
        conn = db_conn.get_connection()
        sb_azi = conn.execute("SELECT id FROM stock_batches WHERE item_id = ? AND batch_no = ?", (item_gst5, "AZI-B1")).fetchone()[0]
        conn.close()

        SalesDAO.insert_invoice(
            bill_no="SALE-GST5",
            sale_date="2026-10-12",
            sale_time="11:00:00",
            sale_type="Cash",
            customer_id=self.cust_id,
            patient_name="GST Test Patient",
            doctor_id=None,
            discount=0.0,
            paid_amount=120.0,
            total_amount=120.0,
            round_off=0.0,
            net_amount=120.0,
            remarks="",
            items=[{
                "item_id": item_gst5,
                "stock_batch_id": sb_azi,
                "pack_size": "1",
                "location": "",
                "batch_no": "AZI-B1",
                "expiry": "2028-12-31",
                "mrp": 15.0,
                "sale_qty": 10.0,
                "discount_amount": 0.0,
                "amount": 120.0,
            }],
        )

        # 2. Item with GST 12% in Item Master
        item_gst12 = ItemDAO.insert(
            item_name="CEFIXIME 200",
            unit_id=self.uid,
            company_id=self.cid2,
            pack_size="1",
            tax_structure="12",
        )
        PurchaseDAO.insert_invoice(
            voucher_no="PUR-GST12",
            voucher_date="2026-10-12",
            voucher_time="10:15:00",
            purchase_type="Credit",
            supplier_id=self.supp_id,
            invoice_no="INV-GST12",
            invoice_date="2026-10-12",
            invoice_net_amount=1008.0,
            bill_discount=0.0,
            due_date="2026-11-12",
            total_amount=1008.0,
            gst_amount=108.0,
            debit_note_amount=0.0,
            other_amount=0.0,
            paid_amount=0.0,
            round_off=0.0,
            net_amount=1008.0,
            remarks="",
            items=[{
                "item_id": item_gst12,
                "batch_no": "CEF-B1",
                "expiry": "2028-12-31",
                "pack_size": "1",
                "pay_qty": 100.0,
                "free_qty": 20.0,
                "rate": 10.0,
                "mrp": 15.0,
                "discount": 10.0,
                "gst_percent": 12.0,
                "gst_amount": 108.0,
                "amount": 900.0,
                "purchase_rate": 10.0,
                "net_rate": 8.40,
                "pp": 25.0,
            }],
        )
        conn = db_conn.get_connection()
        sb_cef = conn.execute("SELECT id FROM stock_batches WHERE item_id = ? AND batch_no = ?", (item_gst12, "CEF-B1")).fetchone()[0]
        conn.close()

        SalesDAO.insert_invoice(
            bill_no="SALE-GST12",
            sale_date="2026-10-12",
            sale_time="11:30:00",
            sale_type="Cash",
            customer_id=self.cust_id,
            patient_name="GST Test Patient 2",
            doctor_id=None,
            discount=0.0,
            paid_amount=120.0,
            total_amount=120.0,
            round_off=0.0,
            net_amount=120.0,
            remarks="",
            items=[{
                "item_id": item_gst12,
                "stock_batch_id": sb_cef,
                "pack_size": "1",
                "location": "",
                "batch_no": "CEF-B1",
                "expiry": "2028-12-31",
                "mrp": 15.0,
                "sale_qty": 10.0,
                "discount_amount": 0.0,
                "amount": 120.0,
            }],
        )

        res = SalesReportsDAO.get_daily_profit_cost_calculation("2026-10-12", "2026-10-12")
        rows_by_name = {r["item_name"]: r for r in res["rows"]}

        # Check GST 5% item:
        # Gross = 1000, Disc = 100, Taxable = 900
        # GST @ 5% = 45 -> Net Purchase = 945
        # Total Received = 120 -> Cost per tab = 945 / 120 = 7.88
        # Sold 10 @ 12 = 120. Total Cost = 78.80, Profit = 41.20
        r5 = rows_by_name["AZITHROMYCIN 500"]
        self.assertEqual(r5["gst_percent"], 5.0)
        self.assertEqual(r5["actual_cost_per_tablet"], 7.88)
        self.assertEqual(r5["total_purchase_cost"], 78.80)
        self.assertEqual(r5["total_profit"], 41.20)

        # Check GST 12% item:
        # Gross = 1000, Disc = 100, Taxable = 900
        # GST @ 12% = 108 -> Net Purchase = 1008
        # Total Received = 120 -> Cost per tab = 1008 / 120 = 8.40
        # Sold 10 @ 12 = 120. Total Cost = 84.00, Profit = 36.00
        r12 = rows_by_name["CEFIXIME 200"]
        self.assertEqual(r12["gst_percent"], 12.0)
        self.assertEqual(r12["actual_cost_per_tablet"], 8.40)
        self.assertEqual(r12["total_purchase_cost"], 84.00)
        self.assertEqual(r12["total_profit"], 36.00)

    def test_08_ctrl_o_shortcut_opens_daily_profit_calculation(self):
        """Verifies Ctrl+O shortcut is mapped to Daily Profit Calculation and opens its page."""
        self.assertEqual(MENU_SHORTCUTS.get("Daily Profit Calculation"), "Ctrl+O")

        # Start from Cash Book
        self.win._on_menu_action("Account", "Cash Book")
        self.app.processEvents()
        self.assertIsInstance(self.win._stack.currentWidget(), screens.CashBookPage)

        # Trigger Ctrl+O shortcut
        ev = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_O, Qt.ControlModifier)
        self.app.sendEvent(self.win, ev)
        self.app.processEvents()

        curr = self.win._stack.currentWidget()
        self.assertIsInstance(curr, DailyProfitCalculationReportPage)


if __name__ == "__main__":
    unittest.main()
