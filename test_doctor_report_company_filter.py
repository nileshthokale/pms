"""Unit and integration tests for Doctorwise Item Sale Details Report Company Name filter."""

from __future__ import annotations

import os
import sys
import unittest
import tempfile
from typing import Any, Dict, List

os.environ["QT_QPA_PLATFORM"] = "offscreen"
TEST_DB_PATH = os.path.join(tempfile.gettempdir(), "_test_doc_comp_filter.db")
if os.path.exists(TEST_DB_PATH):
    try:
        os.remove(TEST_DB_PATH)
    except OSError:
        pass
os.environ["PHARMACY_DB"] = TEST_DB_PATH

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

from database.connection import get_connection, init_database
from database import auth, financial_year
from database.account_roles import ensure_system_ledgers
from database.doctor_dao import DoctorDAO
from database.item_dao import ItemDAO
from database.unit_dao import UnitDAO
from database.customer_dao import CustomerDAO
from database.sales_dao import SalesDAO
from database.doctor_reports_dao import DoctorReportsDAO
from screens.doctor_reports import DoctorwiseItemSaleDetailsPage, BlockKind


class TestDoctorReportCompanyFilter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_financial_year_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        ensure_system_ledgers()

        cls.db_path = TEST_DB_PATH

        # 1. Units
        unit_tab_id = UnitDAO.insert("TAB")
        unit_syr_id = UnitDAO.insert("SYRUP")

        # 2. Doctors
        cls.doc1_id = DoctorDAO.insert("Dr. Sharma", city="Pune", specialty="Cardiology")
        cls.doc2_id = DoctorDAO.insert("Dr. Patel", city="Mumbai", specialty="Pediatrics")

        # 3. Companies
        conn = get_connection()
        try:
            cur = conn.execute("INSERT INTO companies (company_name, short_name) VALUES ('CIPLA LTD', 'CIP')")
            cls.comp_cipla_id = cur.lastrowid
            cur = conn.execute("INSERT INTO companies (company_name, short_name) VALUES ('SUN PHARMA', 'SUN')")
            cls.comp_sun_id = cur.lastrowid
            cur = conn.execute("INSERT INTO companies (company_name, short_name) VALUES ('LUPIN LTD', 'LUP')")
            cls.comp_lupin_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()

        # 4. Items with company_id
        cls.item_ciplox_id = ItemDAO.insert(
            item_name="CIPLOX 500",
            unit_id=unit_tab_id,
            pack_size="10",
            mrp=50.0,
            rate=40.0,
            company_id=cls.comp_cipla_id,
        )
        cls.item_asthalin_id = ItemDAO.insert(
            item_name="ASTHALIN INHALER",
            unit_id=unit_syr_id,
            pack_size="1",
            mrp=120.0,
            rate=100.0,
            company_id=cls.comp_cipla_id,
        )
        cls.item_volini_id = ItemDAO.insert(
            item_name="VOLINI GEL",
            unit_id=unit_syr_id,
            pack_size="1",
            mrp=120.0,
            rate=80.0,
            company_id=cls.comp_sun_id,
        )
        cls.item_pantocid_id = ItemDAO.insert(
            item_name="PANTOCID 40",
            unit_id=unit_tab_id,
            pack_size="10",
            mrp=80.0,
            rate=60.0,
            company_id=cls.comp_sun_id,
        )
        cls.item_lupisulide_id = ItemDAO.insert(
            item_name="LUPISULIDE",
            unit_id=unit_tab_id,
            pack_size="10",
            mrp=35.0,
            rate=25.0,
            company_id=cls.comp_lupin_id,
        )

        # 5. Batches
        conn = get_connection()
        try:
            cur1 = conn.execute(
                """INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, purchase_rate, net_rate, mrp, stock_qty)
                   VALUES (?, 'C101', '2028-12-31', '10', 40.0, 40.0, 50.0, 100.0)""",
                (cls.item_ciplox_id,),
            )
            batch1_id = cur1.lastrowid

            cur2 = conn.execute(
                """INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, purchase_rate, net_rate, mrp, stock_qty)
                   VALUES (?, 'V201', '2027-10-31', '1', 80.0, 80.0, 120.0, 100.0)""",
                (cls.item_volini_id,),
            )
            batch2_id = cur2.lastrowid

            cur3 = conn.execute(
                """INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, purchase_rate, net_rate, mrp, stock_qty)
                   VALUES (?, 'P202', '2028-06-30', '10', 60.0, 60.0, 80.0, 100.0)""",
                (cls.item_pantocid_id,),
            )
            batch3_id = cur3.lastrowid
            conn.commit()
        finally:
            conn.close()

        # Customers with linked ledgers
        cls.cust1_id = CustomerDAO.insert(customer_name="Ramesh Kumar", address="12 MG Road", city="Pune", contact_no="9123456780")
        cls.cust2_id = CustomerDAO.insert(customer_name="Suresh Patil", address="45 Station Rd", city="Mumbai", contact_no="9123456781")

        # 6. Sales
        # Sale 1: Dr. Sharma, Ciplox 500 (Cipla)
        SalesDAO.insert_invoice(
            bill_no="INV-001",
            sale_date="2026-05-10",
            sale_time="10:00:00",
            sale_type="Cash",
            customer_id=cls.cust1_id,
            patient_name="Ramesh Kumar",
            doctor_id=cls.doc1_id,
            discount=0.0,
            paid_amount=100.0,
            total_amount=100.0,
            round_off=0.0,
            net_amount=100.0,
            remarks="",
            items=[{
                "item_id": cls.item_ciplox_id,
                "stock_batch_id": batch1_id,
                "pack_size": "10",
                "location": "",
                "batch_no": "C101",
                "expiry": "2028-12-31",
                "mrp": 50.0,
                "sale_qty": 2.0,
                "discount_amount": 0.0,
                "amount": 100.0,
            }],
        )

        # Sale 2: Dr. Sharma, Volini Gel (Sun Pharma)
        SalesDAO.insert_invoice(
            bill_no="INV-002",
            sale_date="2026-05-15",
            sale_time="11:30:00",
            sale_type="Cash",
            customer_id=cls.cust2_id,
            patient_name="Suresh Patil",
            doctor_id=cls.doc1_id,
            discount=0.0,
            paid_amount=120.0,
            total_amount=120.0,
            round_off=0.0,
            net_amount=120.0,
            remarks="",
            items=[{
                "item_id": cls.item_volini_id,
                "stock_batch_id": batch2_id,
                "pack_size": "1",
                "location": "",
                "batch_no": "V201",
                "expiry": "2027-10-31",
                "mrp": 120.0,
                "sale_qty": 1.0,
                "discount_amount": 0.0,
                "amount": 120.0,
            }],
        )

        # Sale 3: Dr. Patel, Pantocid 40 (Sun Pharma)
        SalesDAO.insert_invoice(
            bill_no="INV-003",
            sale_date="2026-05-20",
            sale_time="14:00:00",
            sale_type="Cash",
            customer_id=cls.cust1_id,
            patient_name="Ramesh Kumar",
            doctor_id=cls.doc2_id,
            discount=0.0,
            paid_amount=240.0,
            total_amount=240.0,
            round_off=0.0,
            net_amount=240.0,
            remarks="",
            items=[{
                "item_id": cls.item_pantocid_id,
                "stock_batch_id": batch3_id,
                "pack_size": "10",
                "location": "",
                "batch_no": "P202",
                "expiry": "2028-06-30",
                "mrp": 80.0,
                "sale_qty": 3.0,
                "discount_amount": 0.0,
                "amount": 240.0,
            }],
        )

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.db_path):
            try:
                os.remove(cls.db_path)
            except OSError:
                pass

    def test_01_dao_get_companies_list(self):
        """DoctorReportsDAO.get_companies_list returns sorted unique companies."""
        comps = DoctorReportsDAO.get_companies_list()
        self.assertGreaterEqual(len(comps), 3)
        names = [c["company_name"] for c in comps]
        self.assertIn("CIPLA LTD", names)
        self.assertIn("LUPIN LTD", names)
        self.assertIn("SUN PHARMA", names)
        # Check alphabetical sorting
        self.assertEqual(names, sorted(names, key=lambda s: s.upper()))

    def test_02_dao_get_all_master_items_with_company_filter(self):
        """DoctorReportsDAO.get_all_master_items filters accurately by company_id."""
        # Unfiltered returns all master items
        all_items = DoctorReportsDAO.get_all_master_items()
        self.assertEqual(len(all_items), 5)

        # Filter by Cipla
        cipla_items = DoctorReportsDAO.get_all_master_items(company_id=self.comp_cipla_id)
        self.assertEqual(len(cipla_items), 2)
        self.assertTrue(all(it["company_id"] == self.comp_cipla_id for it in cipla_items))
        self.assertEqual([it["item_name"] for it in cipla_items], ["ASTHALIN INHALER", "CIPLOX 500"])

        # Filter by Sun Pharma
        sun_items = DoctorReportsDAO.get_all_master_items(company_id=self.comp_sun_id)
        self.assertEqual(len(sun_items), 2)
        self.assertTrue(all(it["company_id"] == self.comp_sun_id for it in sun_items))

        # Filter by Lupin
        lupin_items = DoctorReportsDAO.get_all_master_items(company_id=self.comp_lupin_id)
        self.assertEqual(len(lupin_items), 1)
        self.assertEqual(lupin_items[0]["item_name"], "LUPISULIDE")

    def test_03_dao_get_items_for_doctor_with_company_filter(self):
        """DoctorReportsDAO.get_items_for_doctor filters by company_id."""
        # Dr. Sharma sold Ciplox 500 (Cipla) and Volini Gel (Sun Pharma)
        sharma_all = DoctorReportsDAO.get_items_for_doctor("2026-05-01", "2026-05-31", self.doc1_id)
        self.assertEqual(len(sharma_all), 2)

        # Filter Dr. Sharma by Cipla -> only Ciplox 500
        sharma_cipla = DoctorReportsDAO.get_items_for_doctor(
            "2026-05-01", "2026-05-31", self.doc1_id, company_id=self.comp_cipla_id
        )
        self.assertEqual(len(sharma_cipla), 1)
        self.assertEqual(sharma_cipla[0]["item_name"], "CIPLOX 500")

        # Filter Dr. Sharma by Lupin -> no items sold
        sharma_lupin = DoctorReportsDAO.get_items_for_doctor(
            "2026-05-01", "2026-05-31", self.doc1_id, company_id=self.comp_lupin_id
        )
        self.assertEqual(len(sharma_lupin), 0)

    def test_04_dao_get_item_company_id(self):
        """DoctorReportsDAO.get_item_company_id returns correct company ID or None."""
        self.assertEqual(DoctorReportsDAO.get_item_company_id(self.item_ciplox_id), self.comp_cipla_id)
        self.assertEqual(DoctorReportsDAO.get_item_company_id(self.item_volini_id), self.comp_sun_id)
        self.assertIsNone(DoctorReportsDAO.get_item_company_id(99999))

    def test_05_company_combo_initial_state(self):
        """Page initializes with 'All Companies' and full item list in tree."""
        page = DoctorwiseItemSaleDetailsPage()
        self.assertIsNotNone(page.company_combo)
        self.assertEqual(page.company_combo.currentText(), "All Companies")
        self.assertIsNone(page.get_selected_company_id())
        self.assertEqual(page.get_selected_company_name(), "All Companies")

        # Tree shows root ★ (All Items) plus all 5 seeded items
        self.assertEqual(page.item_tree.topLevelItemCount(), 6)
        self.assertIn("All Items", page.item_tree.topLevelItem(0).text(0))

    def test_06_selecting_company_filters_item_tree(self):
        """Selecting a company in company_combo filters the left tree to that company."""
        page = DoctorwiseItemSaleDetailsPage()

        # Select CIPLA LTD
        idx = page.company_combo.findData(self.comp_cipla_id)
        self.assertGreaterEqual(idx, 0)
        page.company_combo.setCurrentIndex(idx)
        self.assertEqual(page.get_selected_company_id(), self.comp_cipla_id)

        # Tree should now have ★ (All Items) + 2 Cipla medicines = 3 items
        self.assertEqual(page.item_tree.topLevelItemCount(), 3)
        item_names = [page.item_tree.topLevelItem(i).text(0) for i in range(1, page.item_tree.topLevelItemCount())]
        self.assertEqual(item_names, ["ASTHALIN INHALER", "CIPLOX 500"])

        # Select LUPIN LTD
        idx_lupin = page.company_combo.findData(self.comp_lupin_id)
        page.company_combo.setCurrentIndex(idx_lupin)
        self.assertEqual(page.get_selected_company_id(), self.comp_lupin_id)
        self.assertEqual(page.item_tree.topLevelItemCount(), 2)
        self.assertEqual(page.item_tree.topLevelItem(1).text(0), "LUPISULIDE")

        # Switch back to All Companies (idx=0)
        page.company_combo.setCurrentIndex(0)
        self.assertIsNone(page.get_selected_company_id())
        self.assertEqual(page.item_tree.topLevelItemCount(), 6)

    def test_07_item_search_within_filtered_company(self):
        """Preserve item search functionality within the company-filtered list."""
        page = DoctorwiseItemSaleDetailsPage()

        # Select CIPLA LTD
        idx = page.company_combo.findData(self.comp_cipla_id)
        page.company_combo.setCurrentIndex(idx)

        # Search for 'ciplox'
        page.item_search.setText("ciplox")

        # Root ★ (All Items) is never hidden
        self.assertFalse(page.item_tree.topLevelItem(0).isHidden())

        # ASTHALIN INHALER should be hidden
        self.assertTrue(page.item_tree.topLevelItem(1).isHidden())
        # CIPLOX 500 should be visible
        self.assertFalse(page.item_tree.topLevelItem(2).isHidden())

        # Clear search
        page.item_search.setText("")
        self.assertFalse(page.item_tree.topLevelItem(1).isHidden())
        self.assertFalse(page.item_tree.topLevelItem(2).isHidden())

    def test_08_company_change_clears_incompatible_selected_item(self):
        """When company changes, an incompatible selected item is cleared and ★ (All Items) selected."""
        page = DoctorwiseItemSaleDetailsPage()

        # Select CIPLA LTD
        idx_cipla = page.company_combo.findData(self.comp_cipla_id)
        page.company_combo.setCurrentIndex(idx_cipla)

        # Select CIPLOX 500 in tree
        ciplox_node = None
        for i in range(page.item_tree.topLevelItemCount()):
            n = page.item_tree.topLevelItem(i)
            if n.data(0, Qt.UserRole) == self.item_ciplox_id:
                ciplox_node = n
                break
        self.assertIsNotNone(ciplox_node)
        page._on_item_tree_clicked(ciplox_node, 0)
        self.assertEqual(page._selected_item_id, self.item_ciplox_id)

        # Switch to SUN PHARMA
        idx_sun = page.company_combo.findData(self.comp_sun_id)
        page.company_combo.setCurrentIndex(idx_sun)

        # CIPLOX 500 does NOT belong to SUN PHARMA -> must be cleared to None
        self.assertIsNone(page._selected_item_id)
        current = page.item_tree.currentItem()
        self.assertIsNotNone(current)
        self.assertIn("All Items", current.text(0))

    def test_09_company_change_retains_compatible_selected_item(self):
        """When switching to a company that owns the selected item, it remains selected."""
        page = DoctorwiseItemSaleDetailsPage()

        # In All Companies, select VOLINI GEL (Sun Pharma)
        volini_node = None
        for i in range(page.item_tree.topLevelItemCount()):
            node = page.item_tree.topLevelItem(i)
            if node.data(0, Qt.UserRole) == self.item_volini_id:
                volini_node = node
                break
        self.assertIsNotNone(volini_node)
        page._on_item_tree_clicked(volini_node, 0)
        self.assertEqual(page._selected_item_id, self.item_volini_id)

        # Switch to SUN PHARMA
        idx_sun = page.company_combo.findData(self.comp_sun_id)
        page.company_combo.setCurrentIndex(idx_sun)

        # VOLINI GEL belongs to Sun Pharma, so selection must be retained
        self.assertEqual(page._selected_item_id, self.item_volini_id)
        current = page.item_tree.currentItem()
        self.assertIsNotNone(current)
        self.assertEqual(current.data(0, Qt.UserRole), self.item_volini_id)
        self.assertEqual(current.text(0), "VOLINI GEL")

    def test_10_report_generation_preserves_layout_and_calculations(self):
        """Report generation produces identical layout, columns, subtotals, and calculations."""
        page = DoctorwiseItemSaleDetailsPage()
        page.from_date_edit.setDate(QDate(2026, 5, 1))
        page.to_date_edit.setDate(QDate(2026, 5, 31))

        # Select Dr. Sharma
        doc_idx = page.doctor_combo.findData(self.doc1_id)
        page.doctor_combo.setCurrentIndex(doc_idx)

        # Select CIPLA LTD
        comp_idx = page.company_combo.findData(self.comp_cipla_id)
        page.company_combo.setCurrentIndex(comp_idx)

        # Select CIPLOX 500 in tree
        ciplox_node = None
        for i in range(page.item_tree.topLevelItemCount()):
            n = page.item_tree.topLevelItem(i)
            if n.data(0, Qt.UserRole) == self.item_ciplox_id:
                ciplox_node = n
                break
        self.assertIsNotNone(ciplox_node)
        page._on_item_tree_clicked(ciplox_node, 0)

        # Generate report
        page.generate_report()
        self.assertGreater(len(page._pages), 0)

        p0 = page._pages[0]
        # Verify exact columns: ["SrNo", "VhType", "BillNo", "PatientName", "Address", "MRP", "SalesQty", "TotSalesAmt"]
        hdr_blocks = [b for b in p0.blocks if b.kind == BlockKind.TABLE_HEADER]
        self.assertGreater(len(hdr_blocks), 0)
        self.assertEqual(
            hdr_blocks[0].data["columns"],
            ["SrNo", "VhType", "BillNo", "PatientName", "Address", "MRP", "SalesQty", "TotSalesAmt"],
        )

        # Verify Data rows
        data_blocks = [b for b in p0.blocks if b.kind == BlockKind.DATA_ROW]
        self.assertEqual(len(data_blocks), 1)
        cells = data_blocks[0].data["cells"]
        # cells: [SrNo, VhType, BillNo, PatientName, Address, MRP, SalesQty, TotSalesAmt]
        self.assertEqual(cells[0], "1")
        self.assertEqual(cells[1], "Cash")
        self.assertEqual(cells[2], "001")
        self.assertEqual(cells[3], "Ramesh Kumar")
        self.assertEqual(cells[4], "12 MG Road")
        self.assertEqual(cells[5], "50.00")
        self.assertEqual(cells[6], "2")
        self.assertEqual(cells[7], "100.00")

        # Verify Subtotal row
        subtotals = [b for b in p0.blocks if b.kind == BlockKind.ITEM_SUBTOTAL]
        self.assertEqual(len(subtotals), 1)
        st_cells = subtotals[0].data["custom_cells"]
        self.assertEqual(st_cells[0]["text"], "Total :")
        self.assertEqual(st_cells[1]["text"], "2")
        self.assertEqual(st_cells[2]["text"], "100.00")

        # Buttons enabled
        self.assertTrue(page.btn_panel_print.isEnabled())
        self.assertTrue(page.btn_panel_export.isEnabled())

    def test_11_doctor_and_date_filtering_continue_working(self):
        """Doctor and Date filtering continue to work normally."""
        page = DoctorwiseItemSaleDetailsPage()

        # Date validation: From > To
        page.from_date_edit.setDate(QDate(2026, 6, 1))
        page.to_date_edit.setDate(QDate(2026, 5, 1))
        doc_idx = page.doctor_combo.findData(self.doc1_id)
        page.doctor_combo.setCurrentIndex(doc_idx)
        page.generate_report()
        self.assertEqual(len(page._pages), 0)
        self.assertIn("From Date must be earlier", page.lbl_msg.text())

        # Reset dates
        page.from_date_edit.setDate(QDate(2026, 5, 1))
        page.to_date_edit.setDate(QDate(2026, 5, 31))

        # Doctor validation: No doctor selected
        page.doctor_combo.setCurrentIndex(0)
        page.generate_report()
        self.assertEqual(len(page._pages), 0)
        self.assertIn("Please select a Doctor", page.lbl_msg.text())

        # Select Dr. Patel
        doc2_idx = page.doctor_combo.findData(self.doc2_id)
        page.doctor_combo.setCurrentIndex(doc2_idx)
        page.generate_report()
        self.assertGreater(len(page._pages), 0)
        p0 = page._pages[0]
        # Dr. Patel only sold Pantocid 40
        group_headers = [b for b in p0.blocks if b.kind == BlockKind.GROUP_HEADER]
        self.assertEqual(len(group_headers), 1)
        self.assertIn("PANTOCID 40", group_headers[0].data["text"])

    def test_12_no_database_records_or_schemas_altered(self):
        """Verify no changes to schema or record counts in companies, items, or sales."""
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM companies")
            self.assertEqual(cur.fetchone()[0], 3)
            cur.execute("SELECT COUNT(*) FROM items")
            self.assertEqual(cur.fetchone()[0], 5)
            cur.execute("SELECT COUNT(*) FROM doctors")
            self.assertEqual(cur.fetchone()[0], 2)
            cur.execute("SELECT COUNT(*) FROM sales_invoices")
            self.assertEqual(cur.fetchone()[0], 3)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
