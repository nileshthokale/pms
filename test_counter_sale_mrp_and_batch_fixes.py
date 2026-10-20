"""Regression test suite for Counter Sale MRP resolution and batch placeholder removal.

Verifies:
1. SOMPRAZ 20 against actual pharmacy database (verifies root cause of ₹85.50 vs ₹123/₹124).
2. Items with multiple batches having differing MRPs.
3. Items with single or uniform batch MRP.
4. Items with empty stock or expired batches.
5. Removal of '-- Select Batch --' placeholder, keeping batch input empty until explicit selection.
6. Typing a batch number matches valid options.
7. Population of MRP, expiry, and stock from the exact selected batch into Counter Sale.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import unittest
from unittest import mock

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from database.connection import get_connection, init_database
from database.drug_dao import DrugDAO
from database.financial_year import ensure_default_financial_year
from database.item_dao import ItemDAO
from database.sales_dao import SalesDAO
from database.account_roles import ensure_system_ledgers
from database.unit_dao import UnitDAO
from screens.counter_sale import CounterSalePage, _ItemEntryBar
from screens.counter_sale_actions import DrugSubstituteDialog


class MRPAndBatchDropdownRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.messages = mock.patch.multiple(
            QMessageBox,
            warning=mock.DEFAULT,
            information=mock.DEFAULT,
            critical=mock.DEFAULT,
            question=mock.DEFAULT,
        )
        self.messages.start()
        self.addCleanup(self.messages.stop)

    # -----------------------------------------------------------------------
    # 1. Verify SOMPRAZ 20 against actual production database (read-only query)
    # -----------------------------------------------------------------------

    def test_01_sompraz_20_against_actual_database(self):
        """SOMPRAZ 20 in pharmacy.db has legacy Item Master MRP=85.5,
        while saleable batches show 123/124. Drug Substitute must reflect
        the saleable batches, NOT the legacy 85.50."""
        # Check if production database file exists
        db_file = os.path.join(os.path.dirname(__file__), "data", "pharmacy.db")
        if not os.path.exists(db_file):
            self.skipTest("data/pharmacy.db not found for production verification")

        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.cursor()
            item = cur.execute(
                "SELECT * FROM items WHERE item_name = 'SOMPRAZ 20'"
            ).fetchone()
            if not item:
                self.skipTest("SOMPRAZ 20 not found in pharmacy.db")

            item_id = item["id"]
            # Confirm legacy MRP is indeed 85.5 in items table
            self.assertEqual(float(item["mrp"]), 85.5)

            # Get saleable batches from actual database
            cur.execute(
                """
                SELECT id, batch_no, expiry, mrp, stock_qty
                FROM stock_batches
                WHERE item_id = ? AND stock_qty > 0
                ORDER BY expiry, batch_no
                """,
                (item_id,),
            )
            raw_batches = [dict(r) for r in cur.fetchall()]
            saleable = [b for b in raw_batches if not SalesDAO.is_expired(b["expiry"] or "")]

            # Available saleable batches must have MRPs 123 and 124
            batch_mrps = sorted(list({float(b["mrp"]) for b in saleable}))
            self.assertIn(123.0, batch_mrps)
            self.assertIn(124.0, batch_mrps)
            min_saleable = min(batch_mrps)
            max_saleable = max(batch_mrps)

            # Resolve drug for SOMPRAZ 20
            cur.execute(
                "SELECT drug_id FROM item_ingredients WHERE item_id = ?",
                (item_id,),
            )
            drug_row = cur.fetchone()
            self.assertIsNotNone(drug_row)
            drug_id = drug_row["drug_id"]
        finally:
            conn.close()

        # Now test DrugDAO.get_substitutes with environment pointing to real db
        old_env = os.environ.get("PHARMACY_DB")
        try:
            os.environ["PHARMACY_DB"] = db_file
            subs = DrugDAO.get_substitutes(drug_id)
            sompraz_sub = next((s for s in subs if s["item_id"] == item_id), None)
            self.assertIsNotNone(sompraz_sub)

            # Crucial check: MRP must NOT be legacy 85.5!
            self.assertNotEqual(sompraz_sub["mrp"], 85.5)
            self.assertEqual(sompraz_sub["min_mrp"], min_saleable)
            self.assertEqual(sompraz_sub["max_mrp"], max_saleable)
            self.assertTrue(sompraz_sub["has_variation"])

            # Verify dialog rendering for SOMPRAZ 20
            dlg = DrugSubstituteDialog(initial_item_id=item_id)
            dlg.show()
            self.app.processEvents()
            self.addCleanup(lambda: (dlg.hide(), dlg.deleteLater()))

            sompraz_row = -1
            for r in range(dlg.table.rowCount()):
                if dlg.table.item(r, 0).text() == "SOMPRAZ 20":
                    sompraz_row = r
                    break
            self.assertGreaterEqual(sompraz_row, 0)

            mrp_text = dlg.table.item(sompraz_row, 2).text()
            # MRP text must show batch variation and must NOT show 85.50
            self.assertNotIn("85.50", mrp_text)
            self.assertNotIn("85.5", mrp_text)
            self.assertIn("123", mrp_text)
            self.assertIn("124", mrp_text)
            self.assertIn("Varies", mrp_text)

            # Tooltip must detail the available batches
            tooltip = dlg.table.item(sompraz_row, 2).toolTip()
            self.assertIn("GTG1275A", tooltip)
            self.assertIn("123.00", tooltip)
            self.assertIn("GTG3112A", tooltip)
            self.assertIn("124.00", tooltip)
        finally:
            if old_env is not None:
                os.environ["PHARMACY_DB"] = old_env
            else:
                os.environ.pop("PHARMACY_DB", None)


class IsolatedMRPAndBatchTests(unittest.TestCase):
    """Isolated test database tests verifying multiple batches, differing MRPs,
    empty stock, batch placeholder removal, and explicit selection."""

    TEST_DB = "test_mrp_batch_isolated.db"

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        if os.path.exists(cls.TEST_DB):
            try:
                os.remove(cls.TEST_DB)
            except Exception:
                pass
        os.environ["PHARMACY_DB"] = cls.TEST_DB
        init_database()
        ensure_system_ledgers()
        ensure_default_financial_year()

        # Seed unit, drug, items
        cls.unit_id = UnitDAO.insert("Tab")
        cls.drug_amox = DrugDAO.insert("AMOXICILLIN 500")

        # Item 1: Multiple batches with differing MRPs (100.0 and 125.0)
        cls.item_multi = ItemDAO.insert(
            item_name="Amox Multi MRP",
            unit_id=cls.unit_id,
            mrp=60.0,  # Legacy item master price
            reorder_stock_level=10,
        )
        ItemDAO.save_ingredients(cls.item_multi, [{"drug_id": cls.drug_amox, "power": "500mg"}])

        # Item 2: Single batch / uniform MRP (80.0)
        cls.item_single = ItemDAO.insert(
            item_name="Amox Uniform MRP",
            unit_id=cls.unit_id,
            mrp=0.0,
            reorder_stock_level=10,
        )
        ItemDAO.save_ingredients(cls.item_single, [{"drug_id": cls.drug_amox, "power": "500mg"}])

        # Item 3: Empty stock (0 stock and expired batch)
        cls.item_empty = ItemDAO.insert(
            item_name="Amox Zero Stock",
            unit_id=cls.unit_id,
            mrp=45.0,
            reorder_stock_level=10,
        )
        ItemDAO.save_ingredients(cls.item_empty, [{"drug_id": cls.drug_amox, "power": "500mg"}])

        # Batches for Item 1 (Multi)
        conn = get_connection()
        try:
            # Batch 1: Exp 2027-12-31, MRP 100.0, Stock 10
            conn.execute(
                """
                INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (?, 'BAT-M1', '2027-12-31', '10', 100.0, 70.0, 75.0, 10.0)
                """,
                (cls.item_multi,),
            )
            # Batch 2: Exp 2028-06-30, MRP 125.0, Stock 25
            conn.execute(
                """
                INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (?, 'BAT-M2', '2028-06-30', '10', 125.0, 85.0, 90.0, 25.0)
                """,
                (cls.item_multi,),
            )

            # Batches for Item 2 (Uniform)
            conn.execute(
                """
                INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (?, 'BAT-U1', '2027-08-31', '10', 80.0, 50.0, 55.0, 15.0)
                """,
                (cls.item_single,),
            )
            conn.execute(
                """
                INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (?, 'BAT-U2', '2027-11-30', '10', 80.0, 50.0, 55.0, 20.0)
                """,
                (cls.item_single,),
            )

            # Batches for Item 3 (Expired or 0 stock)
            conn.execute(
                """
                INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (?, 'BAT-EXP', '2020-01-01', '10', 40.0, 25.0, 30.0, 50.0)
                """,
                (cls.item_empty,),
            )
            conn.execute(
                """
                INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (?, 'BAT-ZERO', '2028-01-01', '10', 45.0, 30.0, 35.0, 0.0)
                """,
                (cls.item_empty,),
            )
            conn.commit()
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("PHARMACY_DB", None)
        if os.path.exists(cls.TEST_DB):
            try:
                os.remove(cls.TEST_DB)
            except Exception:
                pass

    def setUp(self):
        self.messages = mock.patch.multiple(
            QMessageBox,
            warning=mock.DEFAULT,
            information=mock.DEFAULT,
            critical=mock.DEFAULT,
            question=mock.DEFAULT,
        )
        self.messages.start()
        self.addCleanup(self.messages.stop)

    # -----------------------------------------------------------------------
    # 2. Bug 1: Differing MRPs vs Uniform MRPs vs Empty Stock
    # -----------------------------------------------------------------------

    def test_02_drug_substitutes_differing_and_uniform_mrps(self):
        subs = DrugDAO.get_substitutes(self.drug_amox)
        sub_by_id = {s["item_id"]: s for s in subs}

        # Item 1: Multi MRP (100 and 125)
        multi = sub_by_id[self.item_multi]
        self.assertTrue(multi["has_variation"])
        self.assertEqual(multi["min_mrp"], 100.0)
        self.assertEqual(multi["max_mrp"], 125.0)
        self.assertNotEqual(multi["mrp"], 60.0)  # Must NOT use master price 60.0

        # Item 2: Uniform MRP (80)
        uniform = sub_by_id[self.item_single]
        self.assertFalse(uniform["has_variation"])
        self.assertEqual(uniform["min_mrp"], 80.0)
        self.assertEqual(uniform["max_mrp"], 80.0)

        # Item 3: Empty stock
        empty = sub_by_id[self.item_empty]
        self.assertEqual(len(empty["saleable_batches"]), 0)

        # Verify UI rendering in DrugSubstituteDialog
        dlg = DrugSubstituteDialog(initial_item_id=self.item_multi)
        dlg.show()
        self.app.processEvents()
        self.addCleanup(lambda: (dlg.hide(), dlg.deleteLater()))

        mrp_map = {}
        for r in range(dlg.table.rowCount()):
            name = dlg.table.item(r, 0).text()
            mrp_map[name] = dlg.table.item(r, 2).text()

        # Multi MRP row shows variation
        self.assertIn("100", mrp_map["Amox Multi MRP"])
        self.assertIn("125", mrp_map["Amox Multi MRP"])
        self.assertIn("Varies", mrp_map["Amox Multi MRP"])

        # Uniform MRP row shows single price
        self.assertIn("80", mrp_map["Amox Uniform MRP"])
        self.assertNotIn("Varies", mrp_map["Amox Uniform MRP"])

    # -----------------------------------------------------------------------
    # 3. Bug 2: Batch Dropdown Placeholder Removal and Explicit Selection
    # -----------------------------------------------------------------------

    def test_03_batch_dropdown_no_placeholder_and_empty_initially(self):
        page = CounterSalePage()
        page.show()
        self.app.processEvents()
        self.addCleanup(lambda: (page.hide(), page.deleteLater()))

        bar = page._sale_panel._entry_bar

        # Select Item 1 (Multi MRP)
        idx = bar.item_combo.findData(self.item_multi)
        bar.item_combo.setCurrentIndex(idx)
        self.app.processEvents()

        # 1. "-- Select Batch --" must NOT be in the dropdown
        texts = [bar.batch_combo.itemText(i) for i in range(bar.batch_combo.count())]
        self.assertNotIn("-- Select Batch --", texts)
        self.assertEqual(bar.batch_combo.count(), 2)

        # 2. Input must be visually empty
        self.assertEqual(bar.batch_combo.lineEdit().text(), "")
        self.assertEqual(bar.batch_combo.currentIndex(), -1)
        self.assertIsNone(bar.batch_combo.currentData())

        # 3. Must NOT silently select the first batch; staff must explicitly select
        # While empty, get_current_data() returns None
        self.assertIsNone(bar.get_current_data())

        # Attempting to add without selecting batch warns and fails
        bar.add_btn.click()
        self.app.processEvents()
        self.assertEqual(page._sale_panel._table.rowCount(), 0)

    def test_04_batch_selection_populates_exact_batch_mrp_and_details(self):
        page = CounterSalePage()
        page.show()
        self.app.processEvents()
        self.addCleanup(lambda: (page.hide(), page.deleteLater()))

        bar = page._sale_panel._entry_bar
        idx = bar.item_combo.findData(self.item_multi)
        bar.item_combo.setCurrentIndex(idx)
        self.app.processEvents()

        # Explicitly select Batch 1 (MRP 100.0)
        idx_b1 = bar.batch_combo.findText("BAT-M1", Qt.MatchContains)
        self.assertGreaterEqual(idx_b1, 0)
        bar.batch_combo.setCurrentIndex(idx_b1)
        self.app.processEvents()

        self.assertEqual(bar.mrp_edit.text(), "100.00")
        self.assertEqual(bar.expiry_edit.text(), "2027-12-31")
        self.assertEqual(bar.stock_edit.text(), "10")

        # Explicitly select Batch 2 (MRP 125.0)
        idx_b2 = bar.batch_combo.findText("BAT-M2", Qt.MatchContains)
        self.assertGreaterEqual(idx_b2, 0)
        bar.batch_combo.setCurrentIndex(idx_b2)
        self.app.processEvents()

        self.assertEqual(bar.mrp_edit.text(), "125.00")
        self.assertEqual(bar.expiry_edit.text(), "2028-06-30")
        self.assertEqual(bar.stock_edit.text(), "25")

        # Now Add to bill works and calculates correct line amount
        bar.qty_edit.setText("2")
        bar.add_btn.click()
        self.app.processEvents()

        self.assertEqual(page._sale_panel._table.rowCount(), 1)
        bill_row = page._sale_panel._item_rows[0]
        self.assertEqual(bill_row.batch_no, "BAT-M2")
        self.assertEqual(bill_row.mrp, 125.0)
        # 2 units * (125.0 / 10) = 25.0
        self.assertEqual(bill_row.amount, 25.0)

    def test_05_typing_batch_number_matches_and_keyboard_selection(self):
        page = CounterSalePage()
        page.show()
        self.app.processEvents()
        self.addCleanup(lambda: (page.hide(), page.deleteLater()))

        bar = page._sale_panel._entry_bar
        idx = bar.item_combo.findData(self.item_multi)
        bar.item_combo.setCurrentIndex(idx)
        self.app.processEvents()

        # Type "BAT-M1" into batch combo line edit
        bar.batch_combo.lineEdit().setFocus()
        bar.batch_combo.lineEdit().setText("BAT-M1")
        QTest.keyClick(bar.batch_combo.lineEdit(), Qt.Key_Return)
        self.app.processEvents()

        # Exact batch is matched and selected
        data = bar.get_current_data()
        self.assertIsNotNone(data)
        self.assertEqual(data["batch_no"], "BAT-M1")
        self.assertEqual(data["mrp"], 100.0)

    def test_06_empty_stock_item_has_no_saleable_batches(self):
        page = CounterSalePage()
        page.show()
        self.app.processEvents()
        self.addCleanup(lambda: (page.hide(), page.deleteLater()))

        bar = page._sale_panel._entry_bar
        idx = bar.item_combo.findData(self.item_empty)
        bar.item_combo.setCurrentIndex(idx)
        self.app.processEvents()

        # Zero batches available
        self.assertEqual(bar.batch_combo.count(), 0)
        self.assertEqual(bar.batch_combo.lineEdit().text(), "")
        self.assertIsNone(bar.get_current_data())


if __name__ == "__main__":
    unittest.main()
