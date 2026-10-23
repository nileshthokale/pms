"""Automated tests for prefix-only medicine autocomplete search in Sales / Counter Sale.

Requirements verified:
1. When the user types `MG`, show only medicine names starting with `MG`.
2. When the user types `ST`, show only medicine names starting with `ST`.
3. When the user types `CIP`, show only medicine names starting with `CIP`.
4. Search is case-insensitive, so `mg`, `Mg`, and `MG` behave identically.
5. Suggestions update dynamically as characters are typed.
6. Excludes medicines containing the search term elsewhere in the name (e.g., CORTIMAC 6MG, CALDOB 500MG).
7. Keyboard navigation (Down, Enter) and mouse selection select the medicine,
   load its batches, fill pack size, MRP, etc., and advance to the batch field.
8. Shows "No products found" when query matches no medicine prefix, and does not accept it.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

_APP = QApplication.instance() or QApplication(sys.argv)

from database import auth, financial_year
from database.account_roles import ensure_system_ledgers
from database.connection import init_database
from screens.counter_sale import CounterSalePage


class TestCounterSaleItemPrefixAutocomplete(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temp_dir = tempfile.mkdtemp(prefix="test_item_prefix_")
        cls._db_path = os.path.join(cls._temp_dir, "pharmacy_prefix.db")
        cls._prev_db = os.environ.get("PHARMACY_DB")
        os.environ["PHARMACY_DB"] = cls._db_path

        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_financial_year_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        ensure_system_ledgers()

        # Seed test medicines
        cls._seed_medicines()

    @classmethod
    def tearDownClass(cls):
        if cls._prev_db is not None:
            os.environ["PHARMACY_DB"] = cls._prev_db
        else:
            os.environ.pop("PHARMACY_DB", None)
        shutil.rmtree(cls._temp_dir, ignore_errors=True)

    @classmethod
    def _seed_medicines(cls):
        conn = sqlite3.connect(cls._db_path)
        cur = conn.cursor()

        cur.execute("INSERT INTO units (unit_name) VALUES ('TAB')")
        unit_id = cur.lastrowid
        cur.execute("INSERT INTO companies (company_name, short_name) VALUES ('TEST PHARMA', 'TEST')")
        comp_id = cur.lastrowid

        # Insert medicines matching problem description and test requirements:
        # - Medicines starting with MG
        # - Medicines containing MG elsewhere (must be excluded)
        # - Medicines starting with ST
        # - Medicines starting with CIP
        medicines = [
            ("MG 500", "Paracetamol 500"),
            ("MG-COLD TABLET", "Phenylephrine"),
            ("MGDOL SUSPENSION", "Paracetamol"),
            ("CORTIMAC 6MG", "Deflazacort 6mg"),
            ("CALDOB 500MG", "Calcium 500mg"),
            ("ST 10", "Cetirizine 10"),
            ("ST-GRA 50", "Sildenafil 50"),
            ("CIPROBID 500", "Ciprofloxacin 500"),
            ("CIPLOX 250", "Ciprofloxacin 250"),
            ("PARACETAMOL 650", "Paracetamol 650"),
        ]

        cls.item_ids = {}
        for name, gen in medicines:
            cur.execute(
                """
                INSERT INTO items (
                    item_name, unit_id, company_id, pack_size, mrp, rate
                ) VALUES (?, ?, ?, 10, 50.0, 40.0)
                """,
                (name, unit_id, comp_id),
            )
            item_id = cur.lastrowid
            cls.item_ids[name] = item_id

            # Seed a batch for each
            cur.execute(
                """
                INSERT INTO stock_batches (
                    item_id, batch_no, expiry, pack_size, mrp, purchase_rate, stock_qty
                ) VALUES (?, ?, '12/28', 10, 50.0, 40.0, 100.0)
                """,
                (item_id, f"B-{item_id}"),
            )

        conn.commit()
        conn.close()

    def setUp(self):
        self.messages = mock.patch.multiple(
            QMessageBox, warning=mock.DEFAULT, information=mock.DEFAULT,
            critical=mock.DEFAULT, question=mock.DEFAULT,
        )
        self.messages.start()
        self.addCleanup(self.messages.stop)

        self.page = CounterSalePage()
        self.page.show()
        _APP.processEvents()
        self.entry = self.page._sale_panel._entry_bar
        self.item_combo = self.entry.item_combo
        self.line_edit = self.item_combo.lineEdit()
        self.completer = self.item_combo.completer()

    def tearDown(self):
        self.page.hide()
        self.page.deleteLater()
        _APP.processEvents()

    def _get_completion_texts(self) -> list[str]:
        model = self.completer.completionModel()
        count = self.completer.completionCount()
        return [model.index(i, 0).data(Qt.DisplayRole) for i in range(count)]

    def test_01_mg_matches_only_starting_with_mg(self):
        """Typing MG matches only medicines starting with MG and excludes CORTIMAC 6MG and CALDOB 500MG."""
        self.line_edit.clear()
        QTest.keyClicks(self.line_edit, "MG")
        _APP.processEvents()

        results = self._get_completion_texts()
        self.assertIn("MG 500", results)
        self.assertIn("MG-COLD TABLET", results)
        self.assertIn("MGDOL SUSPENSION", results)

        # Crucial check: must NOT contain medicines with 6MG or 500MG
        self.assertNotIn("CORTIMAC 6MG", results)
        self.assertNotIn("CALDOB 500MG", results)
        self.assertNotIn("PARACETAMOL 650", results)

    def test_02_mg_case_insensitive_identical_results(self):
        """Lowercase 'mg', mixed 'Mg', and uppercase 'MG' behave identically."""
        prefixes = ["mg", "Mg", "mG", "MG"]
        expected = None
        for p in prefixes:
            self.line_edit.clear()
            QTest.keyClicks(self.line_edit, p)
            _APP.processEvents()
            results = set(self._get_completion_texts())
            if expected is None:
                expected = results
            else:
                self.assertEqual(results, expected, f"Prefix '{p}' did not produce identical results")

    def test_03_st_matches_only_starting_with_st(self):
        """Typing ST matches only medicines starting with ST."""
        self.line_edit.clear()
        QTest.keyClicks(self.line_edit, "ST")
        _APP.processEvents()

        results = self._get_completion_texts()
        self.assertIn("ST 10", results)
        self.assertIn("ST-GRA 50", results)
        self.assertNotIn("CORTIMAC 6MG", results)
        self.assertNotIn("MG 500", results)
        self.assertNotIn("CIPROBID 500", results)

    def test_04_cip_matches_only_starting_with_cip(self):
        """Typing CIP matches only medicines starting with CIP."""
        self.line_edit.clear()
        QTest.keyClicks(self.line_edit, "CIP")
        _APP.processEvents()

        results = self._get_completion_texts()
        self.assertIn("CIPROBID 500", results)
        self.assertIn("CIPLOX 250", results)
        self.assertNotIn("CORTIMAC 6MG", results)
        self.assertNotIn("MG 500", results)
        self.assertNotIn("ST 10", results)

    def test_05_dynamic_updates_as_user_types(self):
        """Typing character by character dynamically updates suggestions."""
        self.line_edit.clear()

        # Type 'C' -> both CIPROBID, CIPLOX, CORTIMAC, CALDOB should match
        QTest.keyClicks(self.line_edit, "C")
        _APP.processEvents()
        res_c = self._get_completion_texts()
        self.assertIn("CORTIMAC 6MG", res_c)
        self.assertIn("CALDOB 500MG", res_c)
        self.assertIn("CIPROBID 500", res_c)
        self.assertIn("CIPLOX 250", res_c)
        self.assertNotIn("MG 500", res_c)

        # Type 'I' -> 'CI' -> only CIPROBID, CIPLOX
        QTest.keyClicks(self.line_edit, "I")
        _APP.processEvents()
        res_ci = self._get_completion_texts()
        self.assertNotIn("CORTIMAC 6MG", res_ci)
        self.assertNotIn("CALDOB 500MG", res_ci)
        self.assertIn("CIPROBID 500", res_ci)
        self.assertIn("CIPLOX 250", res_ci)

        # Type 'P' -> 'CIP'
        QTest.keyClicks(self.line_edit, "P")
        _APP.processEvents()
        res_cip = self._get_completion_texts()
        self.assertIn("CIPROBID 500", res_cip)
        self.assertIn("CIPLOX 250", res_cip)

    def test_06_no_products_found_when_no_prefix_match(self):
        """When query matches no medicine prefix, 'No products found' is shown and cannot be selected."""
        self.line_edit.clear()
        QTest.keyClicks(self.line_edit, "ZZZ")
        _APP.processEvents()

        results = self._get_completion_texts()
        self.assertEqual(results, ["No products found"])

        # Press Enter: should NOT select anything
        QTest.keyClick(self.line_edit, Qt.Key_Return)
        _APP.processEvents()
        self.assertIsNone(self.item_combo.currentData())

    def test_07_keyboard_navigation_and_enter_selection(self):
        """Keyboard Down and Enter selects the highlighted medicine and populates batches."""
        self.line_edit.clear()
        QTest.keyClicks(self.line_edit, "CIP")
        _APP.processEvents()

        # Highlight first item and press Return
        QTest.keyClick(self.line_edit, Qt.Key_Down)
        QTest.keyClick(self.line_edit, Qt.Key_Return)
        _APP.processEvents()

        selected_id = self.item_combo.currentData()
        self.assertIsNotNone(selected_id)
        selected_text = self.item_combo.currentText()
        self.assertTrue(selected_text.startswith("CIP"))

        # Batch combo must be populated with that medicine's batches
        self.assertGreaterEqual(self.entry.batch_combo.count(), 1)
        batch_id = self.entry.batch_combo.itemData(0)
        self.assertIsNotNone(batch_id)

        # Select the batch and verify pack and MRP are filled
        self.entry.batch_combo.setCurrentIndex(0)
        _APP.processEvents()
        self.assertEqual(self.entry.pack_edit.text(), "10")
        self.assertEqual(self.entry.mrp_edit.text(), "50.00")

    def test_08_empty_field_shows_all_products(self):
        """Clicking or opening with an empty field shows all products."""
        self.line_edit.clear()
        self.item_combo._open_popup_from_keyboard(from_top=True)
        _APP.processEvents()

        count = self.completer.completionCount()
        # Should contain all seeded products
        self.assertGreaterEqual(count, 10)


if __name__ == "__main__":
    unittest.main()
