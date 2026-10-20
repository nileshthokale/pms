"""Comprehensive test suite for Counter Sale Quick-Action Features:
1. Drug Substitute
2. Items Demand Order
3. Customer Balance List
4. Supplier Balance List

Runs with an isolated test database offscreen.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QTableWidgetItem

from database.connection import get_connection, init_database
from database import auth, financial_year
from database.company_dao import CompanyDAO
from database.customer_dao import CustomerDAO
from database.doctor_dao import DoctorDAO
from database.drug_dao import DrugDAO
from database.item_dao import ItemDAO
from database.ledger_dao import LedgerDAO
from database.purchase_dao import PurchaseDAO
from database.sales_dao import SalesDAO
from database.stock_dao import StockDAO
from database.supplier_dao import SupplierDAO
from database.unit_dao import UnitDAO
from database.account_roles import ensure_system_ledgers
from database.party_wise_report_dao import PartyWiseReportDAO

from screens.counter_sale import CounterSalePage
from screens.counter_sale_actions import (
    CustomerBalanceDialog,
    DemandOrderDialog,
    DrugSubstituteDialog,
    NumericTableWidgetItem,
    SupplierBalanceDialog,
    generate_customer_balance_report_pages,
    generate_supplier_balance_report_pages,
)
from ui.theme import theme_manager


class CounterSaleQuickActionsTests(unittest.TestCase):
    _DB_PATH = os.path.join(tempfile.gettempdir(), "_test_cs_quick_actions.db")

    @classmethod
    def setUpClass(cls):
        if os.path.exists(cls._DB_PATH):
            os.remove(cls._DB_PATH)
        os.environ["PHARMACY_DB"] = cls._DB_PATH
        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_financial_year_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        ensure_system_ledgers()
        cls._app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("PHARMACY_DB", None)
        try:
            if os.path.exists(cls._DB_PATH):
                os.remove(cls._DB_PATH)
        except OSError:
            pass

    def setUp(self):
        conn = get_connection()
        try:
            for tbl in (
                "ledger_transactions", "sales_invoice_items", "sales_invoices",
                "purchase_invoice_items", "purchase_invoices", "stock_batches",
                "hold_bill_items", "hold_bills", "item_ingredients", "items",
                "customers", "doctors", "suppliers", "drugs", "units",
                "companies", "financial_years",
            ):
                try:
                    conn.execute(f"DELETE FROM {tbl}")
                except Exception:
                    pass
            conn.commit()
        finally:
            conn.close()

        financial_year.ensure_default_financial_year()
        ensure_system_ledgers()

        # Seed basic masters
        self.company_id = CompanyDAO.insert("TestPharma", "TP")
        self.unit_tab_id = UnitDAO.insert("Tablet")
        self.unit_cap_id = UnitDAO.insert("Capsule")

        self.drug_amox = DrugDAO.insert("AMOXICILLIN & CLAV")
        self.drug_para = DrugDAO.insert("PARACETAMOL")

        self.supplier_a = SupplierDAO.insert(
            supplier_name="Alpha Pharma Suppliers",
            address="123 Alpha Road",
            city="Pune",
            contact_no="020-11112222",
            opening_balance=5000.0,  # 5000 Credit
        )
        self.supplier_b = SupplierDAO.insert(
            supplier_name="Beta Distributing",
            address="456 Beta Lane",
            city="Mumbai",
            contact_no="022-33334444",
            opening_balance=-200.0,  # 200 Debit (advance)
        )
        self.supplier_zero = SupplierDAO.insert(
            supplier_name="Zero Balance Agency",
            address="789 Zero Ave",
            city="Nashik",
            contact_no="0253-5555666",
            opening_balance=0.0,
        )

        self.customer_a = CustomerDAO.insert(
            customer_name="John Doe",
            address="Flat 1, MG Road",
            city="Rahuri",
            contact_no="9876543210",
            opening_balance=1500.0,  # 1500 Debit (owes money)
        )
        self.customer_b = CustomerDAO.insert(
            customer_name="Jane Smith",
            address="Station Road",
            city="Ahmednagar",
            contact_no="9123456789",
            opening_balance=-350.0,  # 350 Credit (advance)
        )
        self.customer_zero = CustomerDAO.insert(
            customer_name="Zero Balance Patient",
            address="Main Street",
            city="Rahuri",
            contact_no="9000000000",
            opening_balance=0.0,
        )

        # Seed items
        self.item_amox_tab = ItemDAO.insert(
            item_name="Augmentin 625",
            unit_id=self.unit_tab_id,
            company_id=self.company_id,
            pack_size="1",
            mrp=200.0,
            reorder_stock_level=50,
        )
        ItemDAO.save_ingredients(self.item_amox_tab, [{"drug_id": self.drug_amox, "power": "625mg"}])

        self.item_amox_cap = ItemDAO.insert(
            item_name="Moxclav 625",
            unit_id=self.unit_cap_id,
            company_id=self.company_id,
            pack_size="1",
            mrp=150.0,
            reorder_stock_level=30,
        )
        ItemDAO.save_ingredients(self.item_amox_cap, [{"drug_id": self.drug_amox, "power": "625mg"}])

        self.item_crocin = ItemDAO.insert(
            item_name="Crocin 500",
            unit_id=self.unit_tab_id,
            company_id=self.company_id,
            pack_size="1",
            mrp=30.0,
            reorder_stock_level=100,
        )
        ItemDAO.save_ingredients(self.item_crocin, [{"drug_id": self.drug_para, "power": "500mg"}])

        # Stock batches & purchase records
        # Augmentin: reorder level 50, current stock 20 (<= 50, needs reorder!)
        # Purchased from Alpha Pharma and Beta Distributing
        PurchaseDAO.insert_invoice(
            voucher_no="PV-001", voucher_date="2026-05-01", voucher_time="10:00",
            purchase_type="Credit", supplier_id=self.supplier_a,
            invoice_no="INV-A1", invoice_date="2026-05-01",
            invoice_net_amount=3000.0, bill_discount=0, due_date="",
            total_amount=3000.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=0.0, round_off=0,
            net_amount=3000.0, remarks="",
            items=[{
                "item_id": self.item_amox_tab, "pack_size": "1",
                "pay_qty": 20.0, "free_qty": 0, "batch_no": "AUG-B1",
                "expiry": "12/28", "rate": 150.0, "mrp": 200.0,
                "discount": 0, "gst_percent": 0, "gst_amount": 0,
                "amount": 3000.0, "purchase_rate": 150.0,
                "net_rate": 150.0, "pp": 150.0,
            }],
        )
        PurchaseDAO.insert_invoice(
            voucher_no="PV-002", voucher_date="2026-06-01", voucher_time="11:00",
            purchase_type="Credit", supplier_id=self.supplier_b,
            invoice_no="INV-B1", invoice_date="2026-06-01",
            invoice_net_amount=1500.0, bill_discount=0, due_date="",
            total_amount=1500.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=0.0, round_off=0,
            net_amount=1500.0, remarks="",
            items=[{
                "item_id": self.item_amox_tab, "pack_size": "1",
                "pay_qty": 0.0, "free_qty": 0, "batch_no": "AUG-B2",
                "expiry": "12/28", "rate": 150.0, "mrp": 200.0,
                "discount": 0, "gst_percent": 0, "gst_amount": 0,
                "amount": 0.0, "purchase_rate": 150.0,
                "net_rate": 150.0, "pp": 150.0,
            }],
        )

        # Moxclav: reorder level 30, stock is 40 (> 30, does NOT need reorder!)
        PurchaseDAO.insert_invoice(
            voucher_no="PV-003", voucher_date="2026-07-01", voucher_time="12:00",
            purchase_type="Credit", supplier_id=self.supplier_a,
            invoice_no="INV-A2", invoice_date="2026-07-01",
            invoice_net_amount=4000.0, bill_discount=0, due_date="",
            total_amount=4000.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=0.0, round_off=0,
            net_amount=4000.0, remarks="",
            items=[{
                "item_id": self.item_amox_cap, "pack_size": "1",
                "pay_qty": 40.0, "free_qty": 0, "batch_no": "MOX-B1",
                "expiry": "11/27", "rate": 100.0, "mrp": 150.0,
                "discount": 0, "gst_percent": 0, "gst_amount": 0,
                "amount": 4000.0, "purchase_rate": 100.0,
                "net_rate": 100.0, "pp": 100.0,
            }],
        )

    def _pump(self, n: int = 3):
        for _ in range(n):
            self._app.processEvents()

    # -----------------------------------------------------------------------
    # Requirement 1 & 5: Buttons in Header Strip of Counter Sale
    # -----------------------------------------------------------------------

    def test_01_quick_action_buttons_exist_in_counter_sale_header(self):
        page = CounterSalePage()
        page.show()
        self._pump()
        self.addCleanup(lambda: (page.hide(), page.deleteLater()))

        for attr, text in (
            ("_btn_supplier_balance", "Supplier Balance"),
            ("_btn_customer_balance", "Customer Balance"),
            ("_btn_demand_order", "Demand Order"),
            ("_btn_drug_substitute", "Drug Substitute"),
        ):
            btn = getattr(page, attr, None)
            self.assertIsNotNone(btn, f"{attr} must exist on CounterSalePage")
            self.assertEqual(btn.text(), text)
            self.assertTrue(btn.isEnabled())
            self.assertIs(btn.parent(), page._header_strip)

        # Buttons are styled and remain styled under Day and Night modes
        for mode in ("dark", "light"):
            theme_manager.set_mode(mode)
            page.refresh_theme()
            self._pump()
            for attr in (
                "_btn_supplier_balance", "_btn_customer_balance",
                "_btn_demand_order", "_btn_drug_substitute",
            ):
                btn = getattr(page, attr)
                self.assertTrue(bool(btn.styleSheet()))

    # -----------------------------------------------------------------------
    # Requirement 1: Drug Substitute Dialog
    # -----------------------------------------------------------------------

    def test_02_drug_substitute_loads_matches_and_empty_state(self):
        dlg = DrugSubstituteDialog()
        dlg.show()
        self._pump()
        self.addCleanup(lambda: (dlg.hide(), dlg.deleteLater()))

        # Combo contains seeded drugs
        combo_texts = [dlg.drug_combo.itemText(i) for i in range(dlg.drug_combo.count())]
        self.assertIn("AMOXICILLIN & CLAV", combo_texts)
        self.assertIn("PARACETAMOL", combo_texts)

        # Select AMOXICILLIN & CLAV and click Show
        amox_idx = dlg.drug_combo.findText("AMOXICILLIN & CLAV")
        dlg.drug_combo.setCurrentIndex(amox_idx)
        dlg.show_btn.click()
        self._pump()

        # Both Augmentin (Tablet) and Moxclav (Capsule) match
        self.assertEqual(dlg.table.rowCount(), 2)
        items_shown = {dlg.table.item(r, 0).text(): (dlg.table.item(r, 1).text(), dlg.table.item(r, 2).text())
                       for r in range(dlg.table.rowCount())}
        self.assertIn("Augmentin 625", items_shown)
        self.assertIn("Moxclav 625", items_shown)
        self.assertEqual(items_shown["Augmentin 625"][0], "Tablet")
        self.assertEqual(items_shown["Moxclav 625"][0], "Capsule")
        self.assertFalse(dlg.empty_label.isVisible())

        # Select a drug with no items -> empty state is visible
        unused_drug_id = DrugDAO.insert("ORPHAN DRUG")
        dlg._load_drugs()
        orphan_idx = dlg.drug_combo.findText("ORPHAN DRUG")
        dlg.drug_combo.setCurrentIndex(orphan_idx)
        dlg.show_btn.click()
        self._pump()

        self.assertEqual(dlg.table.rowCount(), 0)
        self.assertTrue(dlg.empty_label.isVisible())
        self.assertIn("No matching products", dlg.empty_label.text())

    def test_03_drug_substitute_select_populates_counter_sale_entry(self):
        page = CounterSalePage()
        page.show()
        self._pump()
        self.addCleanup(lambda: (page.hide(), page.deleteLater()))

        # Open substitute dialog with Moxclav ID and select Augmentin
        dlg = DrugSubstituteDialog(page, initial_item_id=self.item_amox_cap)
        dlg.show()
        self._pump()

        # Dialog auto-selected AMOXICILLIN & CLAV and populated items
        self.assertEqual(dlg.drug_combo.currentText(), "AMOXICILLIN & CLAV")
        self.assertEqual(dlg.table.rowCount(), 2)

        # Find row for Augmentin 625 and double click / select
        row_aug = -1
        for r in range(dlg.table.rowCount()):
            if dlg.table.item(r, 0).text() == "Augmentin 625":
                row_aug = r
                break
        self.assertGreaterEqual(row_aug, 0)
        dlg.table.selectRow(row_aug)
        dlg.select_btn.click()
        self._pump()

        self.assertEqual(dlg.result(), QDialog.Accepted)
        self.assertEqual(dlg.selected_item_id, self.item_amox_tab)

        # Simulate selection into counter sale
        page._select_substitute_item(dlg.selected_item_id)
        self._pump()

        # Counter sale entry bar now has Augmentin 625 selected
        bar = page._sale_panel._entry_bar
        self.assertEqual(bar.item_combo.currentData(), self.item_amox_tab)
        self.assertEqual(bar.item_combo.currentText(), "Augmentin 625")

    # -----------------------------------------------------------------------
    # Requirement 2: Items Demand Order Dialog
    # -----------------------------------------------------------------------

    def test_04_demand_order_actual_stock_suppliers_and_empty_state(self):
        dlg = DemandOrderDialog()
        dlg.show()
        self._pump()
        self.addCleanup(lambda: (dlg.hide(), dlg.deleteLater()))

        # Augmentin has stock 20 <= reorder 50 -> must appear
        # Crocin has stock 0 <= reorder 100 -> must appear
        # Moxclav has stock 40 > reorder 30 -> must NOT appear!
        item_names = [dlg.table.item(r, 0).text() for r in range(dlg.table.rowCount())]
        self.assertIn("Augmentin 625", item_names)
        self.assertIn("Crocin 500", item_names)
        self.assertNotIn("Moxclav 625", item_names)

        # Augmentin was purchased from two suppliers: Alpha and Beta
        # Both supplier rows appear with the item's actual stock (20), no stock duplication
        aug_rows = [
            (dlg.table.item(r, 2).text(), dlg.table.item(r, 3).text(),
             dlg.table.item(r, 4).text(), dlg.table.item(r, 5).text())
            for r in range(dlg.table.rowCount())
            if dlg.table.item(r, 0).text() == "Augmentin 625"
        ]
        self.assertEqual(len(aug_rows), 2)
        for stock_str, reorder_str, sup, contact in aug_rows:
            self.assertEqual(stock_str, "20")
            self.assertEqual(reorder_str, "50")
        suppliers_listed = {r[2] for r in aug_rows}
        self.assertEqual(suppliers_listed, {"Alpha Pharma Suppliers", "Beta Distributing"})

        # Test search filter
        dlg.search_edit.setText("Beta")
        self._pump()
        self.assertEqual(dlg.table.rowCount(), 1)
        self.assertEqual(dlg.table.item(0, 4).text(), "Beta Distributing")

        dlg.search_edit.setText("Nonexistent")
        self._pump()
        self.assertEqual(dlg.table.rowCount(), 0)
        self.assertTrue(dlg.empty_label.isVisible())

        # Clear search
        dlg.search_edit.clear()
        self._pump()
        self.assertGreater(dlg.table.rowCount(), 0)

    # -----------------------------------------------------------------------
    # Requirement 3: Customer Balance Dialog
    # -----------------------------------------------------------------------

    def test_05_customer_balance_ledger_rules_search_and_totals(self):
        dlg = CustomerBalanceDialog()
        dlg.show()
        self._pump()
        self.addCleanup(lambda: (dlg.hide(), dlg.deleteLater()))

        # John Doe (1500 Dr), Jane Smith (-350 Cr), Zero Balance Patient (0)
        self.assertEqual(dlg.table.rowCount(), 3)
        cust_rows = {
            dlg.table.item(r, 1).text(): (
                dlg.table.item(r, 2).text(),
                dlg.table.item(r, 3).text(),
                dlg.table.item(r, 4).text(),
            )
            for r in range(dlg.table.rowCount())
        }
        self.assertIn("John Doe", cust_rows)
        self.assertIn("Jane Smith", cust_rows)
        self.assertIn("Zero Balance Patient", cust_rows)

        # John Doe: address combined "Flat 1, MG Road Rahuri", balance 1500
        self.assertEqual(cust_rows["John Doe"][0], "Flat 1, MG Road Rahuri")
        self.assertEqual(cust_rows["John Doe"][1], "9876543210")
        self.assertEqual(cust_rows["John Doe"][2], "1500")

        # Jane Smith: address "Station Road Ahmednagar", balance -350
        self.assertEqual(cust_rows["Jane Smith"][0], "Station Road Ahmednagar")
        self.assertEqual(cust_rows["Jane Smith"][2], "-350")

        # Total outstanding is 1500 + (-350) + 0 = 1150 Dr
        self.assertIn("1,150", dlg.total_lbl.text())
        self.assertIn("Dr", dlg.total_lbl.text())

        # Test search
        dlg.search_edit.setText("Jane")
        self._pump()
        self.assertEqual(dlg.table.rowCount(), 1)
        self.assertIn("-350", dlg.total_lbl.text())
        self.assertIn("Cr", dlg.total_lbl.text())

        # Crystal Report generator works
        pages = generate_customer_balance_report_pages(dlg._displayed_records)
        self.assertGreaterEqual(len(pages), 1)
        self.assertEqual(pages[0].header.header_line_2, "SUNDRY DEBTORS")

    # -----------------------------------------------------------------------
    # Requirement 4: Supplier Balance Dialog
    # -----------------------------------------------------------------------

    def test_06_supplier_balance_ledger_rules_search_and_totals(self):
        dlg = SupplierBalanceDialog()
        dlg.show()
        self._pump()
        self.addCleanup(lambda: (dlg.hide(), dlg.deleteLater()))

        # Alpha Pharma: Opening 5000 Cr + Purchase PV-001 (3000 Cr) + PV-003 (4000 Cr) = 12000 Cr
        # Beta Distributing: Opening -200 Dr + Purchase PV-002 (1500 Cr) = 1300 Cr
        # Zero Balance Agency: 0
        self.assertEqual(dlg.table.rowCount(), 3)
        sup_rows = {
            dlg.table.item(r, 1).text(): (
                dlg.table.item(r, 2).text(),
                dlg.table.item(r, 3).text(),
                dlg.table.item(r, 4).text(),
            )
            for r in range(dlg.table.rowCount())
        }
        self.assertIn("Alpha Pharma Suppliers", sup_rows)
        self.assertIn("Beta Distributing", sup_rows)
        self.assertIn("Zero Balance Agency", sup_rows)

        self.assertEqual(sup_rows["Alpha Pharma Suppliers"][0], "123 Alpha Road Pune")
        self.assertEqual(sup_rows["Alpha Pharma Suppliers"][2], "12000")

        self.assertEqual(sup_rows["Beta Distributing"][0], "456 Beta Lane Mumbai")
        self.assertEqual(sup_rows["Beta Distributing"][2], "1300")

        self.assertEqual(sup_rows["Zero Balance Agency"][2], "0")
        # Zero balance tooltip identifies no transactions / opening
        zero_item = None
        for r in range(dlg.table.rowCount()):
            if dlg.table.item(r, 1).text() == "Zero Balance Agency":
                zero_item = dlg.table.item(r, 4)
                break
        self.assertIsNotNone(zero_item)
        self.assertIn("No ledger transactions or opening balance recorded", zero_item.toolTip())

        # Total balance: 12000 + 1300 = 13300 Cr
        self.assertIn("13,300", dlg.total_lbl.text())
        self.assertIn("Cr", dlg.total_lbl.text())

        # Test search
        dlg.search_edit.setText("Alpha")
        self._pump()
        self.assertEqual(dlg.table.rowCount(), 1)
        self.assertIn("12,000", dlg.total_lbl.text())

        # Crystal Report generator works
        pages = generate_supplier_balance_report_pages(dlg._displayed_records)
        self.assertGreaterEqual(len(pages), 1)
        self.assertEqual(pages[0].header.header_line_2, "SUNDRY CREDITORS")

    # -----------------------------------------------------------------------
    # Sorting Verification for all numeric columns
    # -----------------------------------------------------------------------

    def test_07_numeric_sorting(self):
        item_small = NumericTableWidgetItem("2", 2)
        item_large = NumericTableWidgetItem("10", 10)
        self.assertTrue(item_small < item_large)
        self.assertFalse(item_large < item_small)

        item_neg = NumericTableWidgetItem("-50", -50)
        item_pos = NumericTableWidgetItem("20", 20)
        self.assertTrue(item_neg < item_pos)


if __name__ == "__main__":
    unittest.main()
