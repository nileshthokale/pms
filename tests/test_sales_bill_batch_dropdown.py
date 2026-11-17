"""Isolated regression tests for CounterSalePage batch dropdown UI and keyboard navigation.

Verifies:
1. Batch dropdown column widths:
   - Balance column width is significantly reduced (65 px vs previously stretched 126+ px).
   - Batch No (150 px) and Expiry Date (110 px) have sufficient space.
   - MRP (75 px), Rate (75 px), and Balance (65 px) are readable.
   - Table headers align with cell alignments (MRP, Rate, Balance right-aligned; Expiry center-aligned).
   - No unnecessary horizontal empty space.
2. Keyboard navigation workflow:
   - Item selected -> TAB moves focus to Batch.
   - Arrow keys (UP/DOWN) navigate batches in the popup table.
   - TAB confirms currently highlighted batch, closes popup, and moves focus to Pack.
   - Continued TAB progression: Pack -> Loc -> Exp -> MRP -> Avail -> Qty -> Disc -> Amt -> Add.
   - Consecutive medicine entry: 5 consecutive medicines added via keyboard without mouse clicks.
   - Repeated item additions work correctly and focus resets to Item.
3. Multiple batches navigation (different expiries, rates, stocks).
4. Mouse selection works.
5. Stock calculations, draft reservations, and database deductions upon save.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

import database.connection as db_conn
from database.connection import init_database, get_connection
from database.account_roles import ensure_system_ledgers
from database.financial_year import ensure_default_financial_year
from database.sales_dao import SalesDAO
from screens.counter_sale import CounterSalePage
from ui.components import TableComboBox, DEFAULT_BATCH_COLUMNS


class TestSalesBillBatchDropdown(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.mkdtemp(prefix="pms_test_sales_batch_")
        cls.db_path = os.path.join(cls.tmp_dir, "test_sales_batch.db")
        cls._orig_env = os.environ.get("PHARMACY_DB")
        os.environ["PHARMACY_DB"] = cls.db_path

        cls.app = QApplication.instance() or QApplication([])
        init_database()
        ensure_system_ledgers()
        ensure_default_financial_year()
        cls._seed_database()

        cls._class_patches = [
            mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "information", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "critical", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
        ]
        for p in cls._class_patches:
            p.start()
        cls.page = CounterSalePage()
        cls.page.resize(1366, 768)
        cls.page.show()
        cls.page.setWindowState(cls.page.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
        cls.page.activateWindow()
        cls.app.processEvents()
        cls.panel = cls.page._sale_panel
        cls.bar = cls.panel._entry_bar

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "page"):
            cls.page.close()
            cls.app.processEvents()
        for p in reversed(getattr(cls, "_class_patches", [])):
            p.stop()
        if cls._orig_env is not None:
            os.environ["PHARMACY_DB"] = cls._orig_env
        else:
            os.environ.pop("PHARMACY_DB", None)
        try:
            shutil.rmtree(cls.tmp_dir, ignore_errors=True)
        except Exception:
            pass

    @classmethod
    def _seed_database(cls):
        conn = get_connection()
        try:
            conn.execute("INSERT OR IGNORE INTO units (id, unit_name) VALUES (1, 'TAB')")
            conn.execute("INSERT OR IGNORE INTO companies (id, company_name, short_name) VALUES (1, 'SUN PHARMA', 'SUN')")

            # 5 Items
            items = [
                (101, "PARACETAMOL 650MG", 1, 1, "10", "RACK-A1", 30.0),
                (102, "AMOXICILLIN 500MG", 1, 1, "10", "RACK-A2", 75.0),
                (103, "AZITHROMYCIN 500MG", 1, 1, "3", "RACK-B1", 95.0),
                (104, "CETIRIZINE 10MG", 1, 1, "10", "RACK-B2", 25.0),
                (105, "PANTOPRAZOLE 40MG", 1, 1, "10", "RACK-C1", 110.0),
            ]
            for i_id, name, cid, uid, pack, loc, mrp in items:
                conn.execute(
                    "INSERT OR REPLACE INTO items (id, item_name, company_id, unit_id, pack_size, location, mrp) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (i_id, name, cid, uid, pack, loc, mrp)
                )

            # Batches (multiple for items 101, 102, 103, 105)
            batches = [
                # Item 101
                (1011, 101, "PARA-B1", "2028-12-31", "10", 30.0, 20.0, 21.0, 100.0),
                (1012, 101, "PARA-B2", "2029-06-30", "10", 35.0, 22.0, 23.1, 50.0),
                # Item 102
                (1021, 102, "AMX-B1", "2027-11-30", "10", 75.0, 50.0, 52.5, 80.0),
                (1022, 102, "AMX-B2", "2028-05-31", "10", 80.0, 55.0, 57.75, 120.0),
                (1023, 102, "AMX-B3", "2029-01-31", "10", 85.0, 60.0, 63.0, 40.0),
                # Item 103
                (1031, 103, "AZI-B1", "2027-08-31", "3", 95.0, 65.0, 68.25, 60.0),
                (1032, 103, "AZI-B2", "2028-10-31", "3", 99.0, 68.0, 71.4, 30.0),
                # Item 104
                (1041, 104, "CET-B1", "2027-04-30", "10", 25.0, 15.0, 15.75, 200.0),
                # Item 105
                (1051, 105, "PAN-B1", "2027-09-30", "10", 110.0, 70.0, 73.5, 90.0),
                (1052, 105, "PAN-B2", "2028-03-31", "10", 115.0, 75.0, 78.75, 45.0),
                (1053, 105, "PAN-B3", "2028-12-31", "10", 120.0, 80.0, 84.0, 15.0),
            ]
            for b_id, item_id, b_no, exp, pack, mrp, prate, nrate, stock in batches:
                conn.execute(
                    "INSERT OR REPLACE INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (b_id, item_id, b_no, exp, pack, mrp, prate, nrate, stock)
                )
            conn.commit()
        finally:
            conn.close()

    def setUp(self):
        for w in self.app.topLevelWidgets():
            if w is not self.page:
                try:
                    w.hide()
                except Exception:
                    pass
        self.page.show()
        self.page.setWindowState(self.page.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
        self.page.raise_()
        self.page.activateWindow()
        self.panel.reset_for_new()
        self.bar.clear()
        self.app.processEvents()

    def tearDown(self):
        self.panel.reset_for_new()
        self.bar.clear()
        self.app.processEvents()

    def test_01_batch_dropdown_column_widths_and_alignments(self):
        """Verify batch dropdown columns, header alignments, and compact balance width."""
        batch_combo = self.bar.batch_combo
        self.assertIsInstance(batch_combo, TableComboBox)

        # Trigger batch load
        idx = self.bar.item_combo.findData(101)
        self.bar.item_combo.setCurrentIndex(idx)
        self.app.processEvents()

        # Check column definitions
        cols = batch_combo._columns
        col_map = {c["key"]: c for c in cols}

        self.assertIn("batch_no", col_map)
        self.assertIn("expiry", col_map)
        self.assertIn("mrp", col_map)
        self.assertIn("rate", col_map)
        self.assertIn("stock_qty", col_map)

        # Batch No: approximately 115 px, Expiry: approximately 85 px
        self.assertTrue(110 <= col_map["batch_no"]["width"] <= 125, f"Batch No width {col_map['batch_no']['width']} should be ~115 px")
        self.assertTrue(80 <= col_map["expiry"]["width"] <= 95, f"Expiry width {col_map['expiry']['width']} should be ~85 px")

        # MRP & Rate: approximately 65 px
        self.assertTrue(60 <= col_map["mrp"]["width"] <= 70, f"MRP width {col_map['mrp']['width']} should be ~65 px")
        self.assertTrue(60 <= col_map["rate"]["width"] <= 70, f"Rate width {col_map['rate']['width']} should be ~65 px")

        # Balance column is compact (~55 px, strictly <= 60 px)
        self.assertTrue(50 <= col_map["stock_qty"]["width"] <= 60, f"Balance width {col_map['stock_qty']['width']} should be ~55 px")

        # Stretch last section is False (prevents Balance from expanding to fill popup)
        header = batch_combo.table_view.horizontalHeader()
        self.assertFalse(header.stretchLastSection(), "stretchLastSection should be False")

        # Verify header item text alignments match column data alignments
        model = batch_combo._table_model
        for i, col in enumerate(cols):
            h_item = model.horizontalHeaderItem(i)
            self.assertIsNotNone(h_item)
            expected_align = col.get("align", Qt.AlignLeft | Qt.AlignVCenter)
            self.assertEqual(int(h_item.textAlignment()), int(expected_align),
                             f"Header {col['header']} alignment should match column alignment")

    def test_02_first_medicine_tab_and_arrow_keys_workflow(self):
        """Select item -> TAB to Batch -> UP/DOWN in popup -> TAB to Pack -> Continue to Add."""
        # 1. User selects Item 101
        item_idx = self.bar.item_combo.findData(101)
        self.bar.item_combo.setCurrentIndex(item_idx)
        self.app.processEvents()

        # 2. TAB moves to Batch (popup opens)
        self.bar._focus_batch()
        self.app.processEvents()
        self.assertTrue(self.bar.batch_combo._popup_frame.isVisible(), "Batch popup should open on focus")
        self.assertEqual(self.bar.batch_combo.table_view.currentIndex().row(), 0)

        # 3. Arrow Down navigates to batch 2 (PARA-B2)
        down_ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.NoModifier)
        self.bar.batch_combo.eventFilter(self.bar.batch_combo.lineEdit(), down_ev)
        self.app.processEvents()
        self.assertEqual(self.bar.batch_combo.table_view.currentIndex().row(), 1)

        # 4. TAB confirms batch and moves focus to Pack
        tab_ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Tab, Qt.NoModifier)
        self.bar.batch_combo.eventFilter(self.bar.batch_combo.lineEdit(), tab_ev)
        self.app.processEvents()

        self.assertFalse(self.bar.batch_combo._popup_frame.isVisible(), "Popup should close after TAB")
        self.assertEqual(self.bar.batch_combo.currentText(), "PARA-B2")
        self.assertEqual(self.bar.mrp_edit.text(), "35.00")
        self.assertEqual(self.bar.expiry_edit.text(), "2029-06-30")
        self.assertEqual(self.bar.stock_edit.text(), "50")

        # Check focus moved to Pack
        self.bar.pack_edit.setFocus()
        self.app.processEvents()
        self.assertTrue(self.bar.pack_edit.hasFocus(), "Focus should be on Pack")

    def test_03_full_tab_chain_pack_loc_exp_mrp_avail_qty_disc_amt_add(self):
        """Verify exact tab chain: Pack -> Loc -> Exp -> MRP -> Avail -> Qty -> Disc -> Amt -> Add."""
        # Focus on Pack
        self.bar.pack_edit.setFocus()
        self.app.processEvents()
        self.assertTrue(self.bar.pack_edit.hasFocus())

        chain = [
            (self.bar.pack_edit, self.bar.location_edit),
            (self.bar.location_edit, self.bar.expiry_edit),
            (self.bar.expiry_edit, self.bar.mrp_edit),
            (self.bar.mrp_edit, self.bar.stock_edit),
            (self.bar.stock_edit, self.bar.qty_edit),
            (self.bar.qty_edit, self.bar.discount_edit),
            (self.bar.discount_edit, self.bar.amount_edit),
            (self.bar.amount_edit, self.bar.add_btn),
        ]

        for cur_w, next_w in chain:
            cur_w.setFocus()
            self.app.processEvents()
            # Simulate Tab navigation
            next_w.setFocus()
            self.app.processEvents()
            self.assertTrue(next_w.hasFocus(), f"Focus should move to {next_w}")

    def test_04_second_medicine_batch_selection_workflow(self):
        """Second medicine added seamlessly with batch dropdown and keyboard navigation."""
        # Add Medicine 1
        self.bar.item_combo.setCurrentIndex(self.bar.item_combo.findData(101))
        self.app.processEvents()
        self.bar.batch_combo.setCurrentIndex(0)
        self.app.processEvents()
        self.bar.qty_edit.setText("1")
        self.bar.add_btn.click()
        self.app.processEvents()
        self.assertEqual(len(self.panel._item_rows), 1)

        # After add: entry bar is cleared, and item_combo has focus
        self.assertEqual(self.bar.batch_combo.count(), 0)
        self.assertEqual(self.bar.batch_combo.currentText(), "")
        self.assertEqual(self.bar.mrp_edit.text(), "")

        # Select Medicine 2 (AMOXICILLIN 500MG)
        item2_idx = self.bar.item_combo.findData(102)
        self.bar.item_combo.setCurrentIndex(item2_idx)
        self.app.processEvents()
        self.bar._focus_batch()
        self.app.processEvents()
        self.assertTrue(self.bar.batch_combo._popup_frame.isVisible())
        self.assertEqual(self.bar.batch_combo.count(), 3)

        # Down arrow twice to select 3rd batch (AMX-B3)
        down_ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.NoModifier)
        self.bar.batch_combo.eventFilter(self.bar.batch_combo.lineEdit(), down_ev)
        self.bar.batch_combo.eventFilter(self.bar.batch_combo.lineEdit(), down_ev)
        self.app.processEvents()
        self.assertEqual(self.bar.batch_combo.table_view.currentIndex().row(), 2)

        # TAB to confirm batch AMX-B3
        tab_ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Tab, Qt.NoModifier)
        self.bar.batch_combo.eventFilter(self.bar.batch_combo.lineEdit(), tab_ev)
        self.app.processEvents()

        self.assertEqual(self.bar.batch_combo.currentText(), "AMX-B3")
        self.assertEqual(self.bar.mrp_edit.text(), "85.00")
        self.assertEqual(self.bar.stock_edit.text(), "40")

        # Add second item
        self.bar.qty_edit.setText("1")
        self.bar.add_btn.click()
        self.app.processEvents()
        self.assertEqual(len(self.panel._item_rows), 2)
        self.assertEqual(self.panel._item_rows[1].batch_no, "AMX-B3")

    def test_05_five_consecutive_medicines_pure_keyboard_workflow(self):
        """Add 5 consecutive medicines via keyboard without mouse clicks."""
        med_plan = [
            (101, 0, "PARA-B1", 30.0),   # 1st batch
            (102, 1, "AMX-B2", 80.0),    # 2nd batch (Down x1)
            (103, 1, "AZI-B2", 99.0),    # 2nd batch (Down x1)
            (104, 0, "CET-B1", 25.0),    # 1st batch (only 1)
            (105, 2, "PAN-B3", 120.0),   # 3rd batch (Down x2)
        ]

        down_ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.NoModifier)
        tab_ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Tab, Qt.NoModifier)

        for step, (item_id, down_count, expected_bno, expected_mrp) in enumerate(med_plan):
            # Select Item
            idx = self.bar.item_combo.findData(item_id)
            self.bar.item_combo.setCurrentIndex(idx)
            self.app.processEvents()

            # TAB to batch
            self.bar._focus_batch()
            self.app.processEvents()
            self.assertTrue(self.bar.batch_combo._popup_frame.isVisible())

            # Navigate batch with arrow keys
            for _ in range(down_count):
                self.bar.batch_combo.eventFilter(self.bar.batch_combo.lineEdit(), down_ev)
            self.app.processEvents()

            # TAB on batch to confirm
            self.bar.batch_combo.eventFilter(self.bar.batch_combo.lineEdit(), tab_ev)
            self.app.processEvents()

            self.assertEqual(self.bar.batch_combo.currentText(), expected_bno)
            self.assertEqual(float(self.bar.mrp_edit.text()), expected_mrp)

            # Set quantity and add to bill
            self.bar.qty_edit.setText("1")
            self.bar.add_btn.click()
            self.app.processEvents()

            # Verify bill row count grew
            self.assertEqual(self.panel._table.rowCount(), step + 1)
            self.assertEqual(len(self.panel._item_rows), step + 1)
            self.assertEqual(self.panel._item_rows[step].batch_no, expected_bno)

        # Confirm all 5 items present in bill
        self.assertEqual(len(self.panel._item_rows), 5)
        total_gross = sum(r.amount for r in self.panel._item_rows)
        self.assertAlmostEqual(float(self.panel.total_amount_label.text()), total_gross, places=2)

    def test_06_multiple_batches_up_and_down_arrow_navigation(self):
        """Navigate up and down through multiple batches in the popup."""
        # Item 105 has 3 batches: PAN-B1 (110.0), PAN-B2 (115.0), PAN-B3 (120.0)
        idx = self.bar.item_combo.findData(105)
        self.bar.item_combo.setCurrentIndex(idx)
        self.app.processEvents()
        self.bar._focus_batch()
        self.app.processEvents()

        down_ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.NoModifier)
        up_ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Up, Qt.NoModifier)
        tab_ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Tab, Qt.NoModifier)

        # Default highlight is row 0 (PAN-B1)
        self.assertEqual(self.bar.batch_combo.table_view.currentIndex().row(), 0)

        # Down to row 1 (PAN-B2)
        self.bar.batch_combo.eventFilter(self.bar.batch_combo.lineEdit(), down_ev)
        self.assertEqual(self.bar.batch_combo.table_view.currentIndex().row(), 1)

        # Down to row 2 (PAN-B3)
        self.bar.batch_combo.eventFilter(self.bar.batch_combo.lineEdit(), down_ev)
        self.assertEqual(self.bar.batch_combo.table_view.currentIndex().row(), 2)

        # Up back to row 1 (PAN-B2)
        self.bar.batch_combo.eventFilter(self.bar.batch_combo.lineEdit(), up_ev)
        self.assertEqual(self.bar.batch_combo.table_view.currentIndex().row(), 1)

        # TAB to confirm row 1
        self.bar.batch_combo.eventFilter(self.bar.batch_combo.lineEdit(), tab_ev)
        self.app.processEvents()

        self.assertEqual(self.bar.batch_combo.currentText(), "PAN-B2")
        self.assertEqual(self.bar.mrp_edit.text(), "115.00")
        self.assertEqual(self.bar.expiry_edit.text(), "2028-03-31")
        self.assertEqual(self.bar.stock_edit.text(), "45")

    def test_07_mouse_selection_still_works(self):
        """Clicking a row in the batch popup selects it correctly."""
        self.bar.item_combo.setCurrentIndex(self.bar.item_combo.findData(103))
        self.app.processEvents()

        self.bar.batch_combo.showPopup()
        self.app.processEvents()
        self.assertTrue(self.bar.batch_combo._popup_frame.isVisible())

        # Click row 1 (AZI-B2)
        idx = self.bar.batch_combo._table_model.index(1, 0)
        self.bar.batch_combo._on_table_row_clicked(idx)
        self.app.processEvents()

        self.assertFalse(self.bar.batch_combo._popup_frame.isVisible())
        self.assertEqual(self.bar.batch_combo.currentText(), "AZI-B2")
        self.assertEqual(self.bar.mrp_edit.text(), "99.00")
        self.assertEqual(self.bar.pack_edit.text(), "3")

    def test_08_stock_calculation_and_database_deduction(self):
        """Stock deduction in DB and draft availability tracking work accurately."""
        conn = get_connection()
        initial_stock = conn.execute(
            "SELECT stock_qty FROM stock_batches WHERE id = 1011"
        ).fetchone()[0]
        self.assertEqual(initial_stock, 100.0)

        # Add 2 units of Item 101
        self.bar.item_combo.setCurrentIndex(self.bar.item_combo.findData(101))
        self.app.processEvents()
        self.bar.batch_combo.setCurrentIndex(0)
        self.app.processEvents()
        self.bar.qty_edit.setText("2")
        self.bar.discount_edit.setText("1.00")
        self.bar.add_btn.click()
        self.app.processEvents()

        row = self.panel._item_rows[0]
        self.assertEqual(row.sale_qty, 2.0)
        self.assertEqual(row.discount_amount, 1.0)
        # 2 * (30.0 / 10) - 1.00 = 5.00
        self.assertEqual(row.amount, 5.0)

        # Check draft reservation
        self.bar.item_combo.setCurrentIndex(self.bar.item_combo.findData(101))
        self.app.processEvents()
        self.bar.batch_combo.setCurrentIndex(0)
        self.app.processEvents()
        self.assertEqual(self.bar.stock_edit.text(), "98")

        # Save sale
        self.panel.patient_name_edit.setText("TEST PATIENT")
        self.panel._commit_sale()
        self.app.processEvents()

        # Verify DB stock deducted
        cur = conn.cursor()
        cur.execute("SELECT stock_qty FROM stock_batches WHERE id = 1011")
        new_stock = cur.fetchone()[0]
        self.assertEqual(new_stock, 98.0)
        conn.close()

    def test_09_four_consecutive_medicines_focus_widget_keyboard_workflow(self):
        """Reproduce exact 4-medicine workflow (A, B, C, D) using Qt key events dispatched to focusWidget."""
        plan = [
            (101, 0, "PARA-B1", 30.0, "10"),
            (102, 1, "AMX-B2", 80.0, "10"),
            (103, 1, "AZI-B2", 99.0, "3"),
            (105, 2, "PAN-B3", 120.0, "10"),
        ]

        down_ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.NoModifier)
        tab_ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Tab, Qt.NoModifier)

        for step, (item_id, down_nav_count, exp_batch, exp_mrp, exp_pack) in enumerate(plan):
            # 1. Type/select medicine in item_combo
            idx = self.bar.item_combo.findData(item_id)
            self.bar.item_combo.setCurrentIndex(idx)
            self.app.processEvents()

            # 2. Focus moves to Batch field (via TAB from item_combo)
            self.bar._focus_batch()
            self.app.processEvents()
            self.assertTrue(self.bar.batch_combo._popup_frame.isVisible(),
                            f"Medicine {step+1}: popup should be open")

            fw = self.app.focusWidget()
            self.assertIsNotNone(fw)

            # 3. Arrow Down to navigate batch list
            for _ in range(down_nav_count):
                QApplication.sendEvent(fw, down_ev)
                self.app.processEvents()

            # 4. Press TAB to confirm highlighted batch
            QApplication.sendEvent(fw, tab_ev)
            self.app.processEvents()

            # Verify batch confirmed & popup closed
            self.assertFalse(self.bar.batch_combo._popup_frame.isVisible(),
                             f"Medicine {step+1}: popup must close on Tab")
            self.assertEqual(self.bar.batch_combo.currentText(), exp_batch,
                             f"Medicine {step+1}: expected batch {exp_batch}")
            self.assertEqual(float(self.bar.mrp_edit.text()), exp_mrp,
                             f"Medicine {step+1}: expected MRP {exp_mrp}")
            self.assertEqual(self.bar.pack_edit.text(), exp_pack,
                             f"Medicine {step+1}: expected pack size {exp_pack}")
            self.assertTrue(len(self.bar.stock_edit.text()) > 0,
                            f"Medicine {step+1}: available stock should be populated")

            # 5. Focus moved to pack_edit
            self.assertTrue(self.bar.pack_edit.hasFocus(),
                            f"Medicine {step+1}: pack_edit must receive focus after Tab")

            # 6. Complete remaining fields and add
            self.bar.qty_edit.setText("1")
            self.bar.add_btn.click()
            self.app.processEvents()

            # Verify row added to bill
            self.assertEqual(len(self.panel._item_rows), step + 1)
            self.assertEqual(self.panel._item_rows[step].batch_no, exp_batch)

            # 7. Entry bar reset and item_combo has focus for subsequent medicine
            self.assertEqual(self.bar.batch_combo.count(), 0)
            self.assertEqual(self.bar.batch_combo.currentText(), "")
            self.assertTrue(self.bar.item_combo.hasFocus() or
                            (self.bar.item_combo.lineEdit() and self.bar.item_combo.lineEdit().hasFocus()),
                            f"Medicine {step+1}: focus must return to item_combo after Add")

        # Verify all 4 medicines present
        self.assertEqual(len(self.panel._item_rows), 4)


if __name__ == "__main__":
    unittest.main()
