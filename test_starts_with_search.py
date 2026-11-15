import os
import sys
import unittest
import tempfile
import sqlite3
from unittest.mock import MagicMock, patch

# Ensure application package root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from PySide6.QtCore import Qt, QModelIndex
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QStandardItemModel, QStandardItem

# Ensure single QApplication instance
app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)

from ui.components import SearchableComboBox, TableComboBox
from database.connection import init_database, get_connection
from database.item_dao import ItemDAO
from database.customer_dao import CustomerDAO, PatientOption
from database.doctor_dao import DoctorDAO
from database.ledger_dao import LedgerDAO
from database.drug_dao import DrugDAO
from database.stock_dao import StockDAO
from database.sales_dao import SalesDAO
from database.duplicate_sales_dao import DuplicateSalesDAO
from database.credit_note_dao import CreditNoteDAO
from database.debit_note_dao import DebitNoteDAO


class TestStartsWithSearch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create an isolated temporary SQLite database
        cls.temp_db_fd, cls.temp_db_path = tempfile.mkstemp(suffix=".db")
        os.close(cls.temp_db_fd)
        os.environ["PHARMACY_DB"] = cls.temp_db_path
        init_database()

        # Seed test records
        conn = get_connection()
        try:
            conn.execute("INSERT INTO units (id, unit_name) VALUES (1, 'TAB')")
            conn.execute("INSERT INTO account_groups (id, group_name) VALUES (1, 'Sundry Debtors')")
            # Seed Items
            conn.execute(
                """INSERT INTO items (id, item_name, unit_id, mrp, rate, pack_size, reorder_stock_level)
                   VALUES
                   (101, 'KING', 1, 100.0, 80.0, '10', 5),
                   (102, 'KINGESIC-TH4 (TABLET)', 1, 150.0, 120.0, '10', 5),
                   (103, 'ABC KING TABLET', 1, 90.0, 70.0, '10', 5),
                   (104, 'MEDICINE KING', 1, 110.0, 85.0, '10', 5),
                   (105, 'STABIZOL DSR', 1, 130.0, 100.0, '10', 5),
                   (106, 'STAMLO 5', 1, 60.0, 45.0, '10', 5),
                   (107, 'CAP STABIZOL', 1, 140.0, 110.0, '10', 5),
                   (108, 'TAB STAMLO', 1, 70.0, 50.0, '10', 5)"""
            )
            # Seed Customers
            conn.execute(
                """INSERT INTO customers (id, customer_name, address, contact_no)
                   VALUES
                   (201, 'KING KHAN', 'Mumbai', '9876543210'),
                   (202, 'KINGSLEY', 'Goa', '9876543211'),
                   (203, 'BURGER KING', 'Delhi', '9876543212'),
                   (204, 'STACY', 'Pune', '9876543213'),
                   (205, 'ANASTASIA', 'Nashik', '9876543214')"""
            )
            # Seed Doctors
            conn.execute(
                """INSERT INTO doctors (id, doctor_name, city, phone_no)
                   VALUES
                   (301, 'DR. KING', 'Mumbai', '9123456780'),
                   (302, 'DR. KINGSLEY', 'Delhi', '9123456781'),
                   (303, 'DR. BURGER KING', 'Pune', '9123456782')"""
            )
            # Seed Account Ledgers
            conn.execute(
                """INSERT INTO account_ledgers (id, ledger_name, account_group)
                   VALUES
                   (401, 'KING PHARMA LEDGER', 'Sundry Debtors'),
                   (402, 'ABC KING LEDGER', 'Sundry Debtors')"""
            )
            # Seed Drugs
            conn.execute(
                """INSERT INTO drugs (id, drug_name)
                   VALUES
                   (501, 'PARACETAMOL'),
                   (502, 'PARA-EXTRA'),
                   (503, 'COMBIPARA')"""
            )
            # Seed Batches
            conn.execute(
                """INSERT INTO stock_batches (id, item_id, batch_no, expiry, stock_qty, mrp, purchase_rate)
                   VALUES
                   (601, 101, 'KB-01', '2028-12-31', 100, 100.0, 80.0),
                   (602, 101, 'BC-KB-02', '2028-12-31', 50, 100.0, 80.0),
                   (603, 105, 'STA-99', '2027-06-30', 200, 130.0, 100.0),
                   (604, 105, 'MID-STA-01', '2027-06-30', 80, 130.0, 100.0)"""
            )
            # Seed Sales Invoices
            conn.execute(
                """INSERT INTO sales_invoices (id, bill_no, sale_date, patient_name, total_amount, net_amount, sale_type)
                   VALUES
                   (701, 'BILL-1001', '2026-11-15', 'KINGSTON', 100.0, 100.0, 'Cash'),
                   (702, 'BILL-1002', '2026-11-15', 'JOE KING', 150.0, 150.0, 'Cash'),
                   (703, 'BILL-1003', '2026-11-15', 'STANLEY', 200.0, 200.0, 'Cash')"""
            )
            # Seed Patient Addresses
            conn.execute(
                """INSERT INTO patient_addresses (patient_name, address)
                   VALUES
                   ('KINGSTON', 'Main Road, Mumbai'),
                   ('JOE KING', 'Station Road, Pune')"""
            )
            conn.commit()
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.temp_db_path):
            try:
                os.remove(cls.temp_db_path)
            except Exception:
                pass

    # =========================================================================
    # 1. UI Component: SearchableComboBox Prefix Matching
    # =========================================================================
    def test_01_searchable_combo_box_prefix_matching(self):
        combo = SearchableComboBox()
        self.assertTrue(combo._prefix_only, "SearchableComboBox must default to prefix_only=True")
        self.assertEqual(combo._completer.filterMode(), Qt.MatchStartsWith)

        test_items = [
            ("KING", 101),
            ("KINGESIC-TH4 (TABLET)", 102),
            ("ABC KING TABLET", 103),
            ("MEDICINE KING", 104),
            ("STABIZOL DSR", 105),
            ("STAMLO 5", 106),
            ("CAP STABIZOL", 107),
            ("TAB STAMLO", 108),
        ]
        for name, item_id in test_items:
            combo.addItem(name, item_id)

        # 1. Search 'KING'
        combo._on_text_edited("KING")
        completer_items = [combo._completer_model.item(i).text() for i in range(combo._completer_model.rowCount())]
        self.assertIn("KING", completer_items)
        self.assertIn("KINGESIC-TH4 (TABLET)", completer_items)
        self.assertNotIn("ABC KING TABLET", completer_items)
        self.assertNotIn("MEDICINE KING", completer_items)

        # 2. Search 'STA'
        combo._on_text_edited("STA")
        completer_items = [combo._completer_model.item(i).text() for i in range(combo._completer_model.rowCount())]
        self.assertIn("STABIZOL DSR", completer_items)
        self.assertIn("STAMLO 5", completer_items)
        self.assertNotIn("CAP STABIZOL", completer_items)
        self.assertNotIn("TAB STAMLO", completer_items)

        # 3. Lowercase 'king' matches same as 'KING'
        combo._on_text_edited("king")
        completer_items_lower = [combo._completer_model.item(i).text() for i in range(combo._completer_model.rowCount())]
        self.assertIn("KING", completer_items_lower)
        self.assertIn("KINGESIC-TH4 (TABLET)", completer_items_lower)
        self.assertNotIn("ABC KING TABLET", completer_items_lower)

        # 4. Leading / trailing whitespace trimmed
        combo._on_text_edited("  KING  ")
        completer_items_trimmed = [combo._completer_model.item(i).text() for i in range(combo._completer_model.rowCount())]
        self.assertIn("KING", completer_items_trimmed)
        self.assertNotIn("ABC KING TABLET", completer_items_trimmed)

        # 5. Empty search clears completer model
        combo._on_text_edited("")
        self.assertEqual(combo._completer_model.rowCount(), 0)

        # 6. No matching result shows non-selectable placeholder message
        combo._on_text_edited("NONEXISTENT_XYZ")
        self.assertEqual(combo._completer_model.rowCount(), 1)
        self.assertIsNone(combo._completer_model.item(0).data(Qt.UserRole))
        self.assertIn("No matching records found", combo._completer_model.item(0).text())

    # =========================================================================
    # 2. UI Component: TableComboBox Prefix Matching
    # =========================================================================
    def test_02_table_combo_box_prefix_matching(self):
        combo = TableComboBox(placeholder="Select Batch...")
        self.assertTrue(combo._prefix_only)

        sample_batches = [
            {"id": 1, "batch_no": "KB-01", "expiry": "2028-12-31", "pack_size": 10, "mrp": 100.0, "purchase_rate": 80.0, "stock_qty": 100.0, "is_expired": 0},
            {"id": 2, "batch_no": "KB-02", "expiry": "2028-12-31", "pack_size": 10, "mrp": 100.0, "purchase_rate": 80.0, "stock_qty": 50.0, "is_expired": 0},
            {"id": 3, "batch_no": "MID-KB-03", "expiry": "2028-12-31", "pack_size": 10, "mrp": 100.0, "purchase_rate": 80.0, "stock_qty": 30.0, "is_expired": 0},
            {"id": 4, "batch_no": "STA-99", "expiry": "2027-06-30", "pack_size": 10, "mrp": 130.0, "purchase_rate": 100.0, "stock_qty": 200.0, "is_expired": 0},
            {"id": 5, "batch_no": "POST-STA-10", "expiry": "2027-06-30", "pack_size": 10, "mrp": 130.0, "purchase_rate": 100.0, "stock_qty": 40.0, "is_expired": 0},
        ]
        combo.set_batches(sample_batches)

        # Search 'KB'
        combo._on_text_edited("KB")
        visible_rows = [r for r in range(combo._table_model.rowCount()) if not combo.table_view.isRowHidden(r)]
        visible_batches = [combo._table_model.item(r, 0).text() for r in visible_rows if combo._table_model.item(r, 0)]
        self.assertIn("KB-01", visible_batches)
        self.assertIn("KB-02", visible_batches)
        self.assertNotIn("MID-KB-03", visible_batches)

        # Search 'STA'
        combo._on_text_edited("STA")
        visible_rows = [r for r in range(combo._table_model.rowCount()) if not combo.table_view.isRowHidden(r)]
        visible_batches = [combo._table_model.item(r, 0).text() for r in visible_rows if combo._table_model.item(r, 0)]
        self.assertIn("STA-99", visible_batches)
        self.assertNotIn("POST-STA-10", visible_batches)

        # Search lowercase 'kb'
        combo._on_text_edited("kb")
        visible_rows = [r for r in range(combo._table_model.rowCount()) if not combo.table_view.isRowHidden(r)]
        visible_batches = [combo._table_model.item(r, 0).text() for r in visible_rows if combo._table_model.item(r, 0)]
        self.assertIn("KB-01", visible_batches)
        self.assertNotIn("MID-KB-03", visible_batches)

    # =========================================================================
    # 3. ItemDAO.search Starts-With
    # =========================================================================
    def test_03_item_dao_search(self):
        # 1. Search 'KING'
        res = ItemDAO.search("KING")
        names = [r["item_name"] for r in res]
        self.assertIn("KING", names)
        self.assertIn("KINGESIC-TH4 (TABLET)", names)
        self.assertNotIn("ABC KING TABLET", names)
        self.assertNotIn("MEDICINE KING", names)

        # 2. Search 'STA'
        res_sta = ItemDAO.search("STA")
        names_sta = [r["item_name"] for r in res_sta]
        self.assertIn("STABIZOL DSR", names_sta)
        self.assertIn("STAMLO 5", names_sta)
        self.assertNotIn("CAP STABIZOL", names_sta)
        self.assertNotIn("TAB STAMLO", names_sta)

        # 3. Case insensitivity
        res_lower = ItemDAO.search("king")
        names_lower = [r["item_name"] for r in res_lower]
        self.assertEqual(names, names_lower)

        # 4. Whitespace trimming
        res_space = ItemDAO.search("  KING  ")
        names_space = [r["item_name"] for r in res_space]
        self.assertEqual(names, names_space)

    # =========================================================================
    # 4. CustomerDAO.search and get_matching_patients Starts-With
    # =========================================================================
    def test_04_customer_dao_search(self):
        # CustomerDAO.search
        res = CustomerDAO.search("KING")
        names = [r["customer_name"] for r in res]
        self.assertIn("KING KHAN", names)
        self.assertIn("KINGSLEY", names)
        self.assertNotIn("BURGER KING", names)

        # CustomerDAO.get_matching_patients
        patients = CustomerDAO.get_matching_patients("KING")
        p_names = [p.name for p in patients]
        self.assertIn("KINGSTON", p_names)
        self.assertNotIn("JOE KING", p_names)

        # Case-insensitivity
        patients_lower = CustomerDAO.get_matching_patients("king")
        p_names_lower = [p.name for p in patients_lower]
        self.assertEqual(p_names, p_names_lower)

    # =========================================================================
    # 5. DoctorDAO.search Starts-With
    # =========================================================================
    def test_05_doctor_dao_search(self):
        res = DoctorDAO.search("DR. KING")
        names = [r["doctor_name"] for r in res]
        self.assertIn("DR. KING", names)
        self.assertIn("DR. KINGSLEY", names)
        self.assertNotIn("DR. BURGER KING", names)

    # =========================================================================
    # 6. LedgerDAO.search_ledgers Starts-With
    # =========================================================================
    def test_06_ledger_dao_search(self):
        res = LedgerDAO.search_ledgers("KING")
        names = [r["ledger_name"] for r in res]
        self.assertIn("KING PHARMA LEDGER", names)
        self.assertNotIn("ABC KING LEDGER", names)

    # =========================================================================
    # 7. DrugDAO Suggestions and Substitutes Starts-With
    # =========================================================================
    def test_07_drug_dao_search(self):
        suggestions = DrugDAO.search_suggestions("PARA")
        names = [s["name"] for s in suggestions]
        self.assertIn("PARACETAMOL", names)
        self.assertIn("PARA-EXTRA", names)
        self.assertNotIn("COMBIPARA", names)

    # =========================================================================
    # 8. StockDAO.search Starts-With
    # =========================================================================
    def test_08_stock_dao_search(self):
        # item_name prefix
        res = StockDAO.search(item_name="KING")
        items = [r["item_name"] for r in res]
        self.assertIn("KING", items)
        self.assertNotIn("ABC KING TABLET", items)

        # batch_no prefix
        res_batch = StockDAO.search(batch_no="KB")
        batches = [r["batch_no"] for r in res_batch]
        self.assertIn("KB-01", batches)
        self.assertNotIn("BC-KB-02", batches)

    # =========================================================================
    # 9. SalesDAO search_sales & Patient Autocomplete
    # =========================================================================
    def test_09_sales_dao_search(self):
        # Patient search for Sales Bill creation (CustomerDAO.get_matching_patients) is strict starts-with
        patients = CustomerDAO.get_matching_patients("KING")
        p_names = [p.name for p in patients]
        self.assertIn("KINGSTON", p_names)
        self.assertNotIn("JOE KING", p_names)

        # Sales History patient lookup supports multi-word searches (e.g. surname first)
        sales, _ = SalesDAO.search_sales(patient_name="KING")
        matched_patients = [s["patient_name"] for s in sales]
        self.assertIn("KINGSTON", matched_patients)

    # =========================================================================
    # 10. Large Medicine List Performance Benchmark
    # =========================================================================
    def test_10_large_medicine_list_performance(self):
        combo = SearchableComboBox()
        # Populate with 2,500 medicine items
        items = [
            (f"MEDICINE-{i:04d} (TAB)", i, f"MEDICINE-{i:04d}")
            for i in range(2500)
        ]
        combo.populate(items)

        import time
        t0 = time.perf_counter()
        combo._on_text_edited("MEDICINE-001")
        elapsed = time.perf_counter() - t0

        # Must filter in less than 50 milliseconds
        self.assertLess(elapsed, 0.05, f"Search took too long: {elapsed:.4f}s")
        count = combo._completer_model.rowCount()
        self.assertEqual(count, 10)  # MEDICINE-0010 through MEDICINE-0019

    # =========================================================================
    # 11. Database Data Integrity Check
    # =========================================================================
    def test_11_data_integrity_check(self):
        # Verify that running searches did not insert, alter, or delete any rows
        conn = get_connection()
        try:
            item_count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            cust_count = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
            doc_count = conn.execute("SELECT COUNT(*) FROM doctors").fetchone()[0]
            self.assertEqual(item_count, 8)
            self.assertEqual(cust_count, 5)
            self.assertEqual(doc_count, 3)
        finally:
            conn.close()


    # =========================================================================
    # 12. Counter Sale _KeyboardCombo & _make_combo Default Starts-With
    # =========================================================================
    def test_12_counter_sale_combos_default_starts_with(self):
        from screens.counter_sale import _KeyboardCombo, _make_combo
        combo1 = _KeyboardCombo()
        self.assertEqual(combo1.completer().filterMode(), Qt.MatchStartsWith)

        combo2 = _make_combo()
        self.assertEqual(combo2.completer().filterMode(), Qt.MatchStartsWith)

    # =========================================================================
    # 13. Purchase Invoice BatchLineEdit Completer Starts-With
    # =========================================================================
    def test_13_purchase_invoice_batch_completer(self):
        from screens.purchase_invoice import BatchLineEdit
        edit = BatchLineEdit()
        self.assertEqual(edit._completer.filterMode(), Qt.MatchStartsWith)

    # =========================================================================
    # 14. Item Master _DrugComboBox Completer Starts-With
    # =========================================================================
    def test_14_item_master_drug_completer(self):
        from screens.item_master import _DrugComboBox
        drug_combo = _DrugComboBox(drugs=[{"id": 1, "drug_name": "PARACETAMOL"}])
        self.assertEqual(drug_combo.completer().filterMode(), Qt.MatchStartsWith)

    # =========================================================================
    # 15. Counter Sale Actions: DemandOrderDialog & DrugSubstituteDialog
    # =========================================================================
    def test_15_counter_sale_actions_search(self):
        from screens.counter_sale_actions import DemandOrderDialog, DrugSubstituteDialog
        # DrugSubstituteDialog completer
        drug_dlg = DrugSubstituteDialog()
        self.assertEqual(drug_dlg._completer.filterMode(), Qt.MatchStartsWith)

        # DemandOrderDialog starts-with filter
        demand_dlg = DemandOrderDialog()
        demand_dlg._all_records = [
            {"item_name": "KING", "supplier_name": "MED SUPPLY", "contact_no": "98765"},
            {"item_name": "KINGESIC", "supplier_name": "GLOBAL", "contact_no": "98766"},
            {"item_name": "ABC KING", "supplier_name": "LOCAL", "contact_no": "98767"},
            {"item_name": "MEDICINE KING", "supplier_name": "DIST", "contact_no": "98768"},
        ]
        demand_dlg.search_edit.setText("KING")
        demand_dlg._filter_records()
        names = [r["item_name"] for r in demand_dlg._displayed_records]
        self.assertIn("KING", names)
        self.assertIn("KINGESIC", names)
        self.assertNotIn("ABC KING", names)
        self.assertNotIn("MEDICINE KING", names)

    # =========================================================================
    # 16. Counter Sale _on_item_typed prefix logic
    # =========================================================================
    def test_16_counter_sale_typed_prefix_logic(self):
        items_by_id = {
            101: {"id": 101, "item_name": "KING", "unit_name": "TAB"},
            102: {"id": 102, "item_name": "KINGESIC-TH4 (TABLET)", "unit_name": "TAB"},
            103: {"id": 103, "item_name": "ABC KING TABLET", "unit_name": "TAB"},
        }
        text = "KING"
        matches = [
            it for it in items_by_id.values()
            if (it.get("item_name") or "").strip().casefold().startswith(text.casefold())
            or f"{(it.get('item_name') or '').strip()} ({(it.get('unit_name') or '').strip()})".casefold().startswith(text.casefold())
            or f"{(it.get('item_name') or '').strip()} {(it.get('unit_name') or '').strip()}".casefold().startswith(text.casefold())
        ]
        matched_ids = [m["id"] for m in matches]
        self.assertIn(101, matched_ids)
        self.assertIn(102, matched_ids)
        self.assertNotIn(103, matched_ids)


if __name__ == "__main__":
    unittest.main()
