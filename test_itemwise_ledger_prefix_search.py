"""Tests for Medicine / Item autocomplete search in Itemwise Ledger screen.

Requirements verified:
1. Prefix-based search:
   - Search medicine names from the beginning of the name only.
   - e.g. typing 'END' shows 'ENDOFLAM SP', not 'SCAREND' or 'TENDOMAC'.
   - e.g. typing 'TAB' shows medicines starting with 'TAB', not 'BETABEST AM 50' or 'STABIZOL DSR'.
   - Substring matching in middle/end is excluded.
   - Case-insensitive ('end', 'END', 'End').
   - Leading and trailing spaces in input are ignored ('  END  ').
2. Remove company names from suggestions:
   - Dropdown displays only item name ('ENDOFLAM SP', not 'ENDOFLAM SP [TURRET PHARMA PVT LTD]').
   - Company information remains unchanged in database and other screens.
3. Preserve existing functionality:
   - Selecting a medicine loads correct medicine ID and ledger records.
   - Other autocomplete fields (customer ledger, supplier ledger, etc.) remain unchanged.
"""

import sys
import unittest
from PySide6.QtWidgets import QApplication

from screens.itemwise_ledger import ItemwiseLedgerPage
from screens.customer_ledger import CustomerLedgerPage
from screens.supplier_ledger import SupplierLedgerPage
from database.ledger_report_dao import LedgerReportDAO

app = QApplication.instance() or QApplication(sys.argv)


class TestItemwiseLedgerPrefixSearch(unittest.TestCase):
    def setUp(self):
        self.page = ItemwiseLedgerPage()
        self.combo = self.page._item_selector

    def tearDown(self):
        self.page.close()

    def test_01_no_company_in_dropdown_suggestions(self):
        """Dropdown options and suggestions display only item_name without company in brackets."""
        self.assertGreater(self.combo.count(), 100)

        # Ensure no item in the dropdown has company brackets
        for i in range(self.combo.count()):
            text = self.combo.itemText(i)
            self.assertNotIn("[", text, f"Found opening bracket in suggestion: {text}")
            self.assertNotIn("]", text, f"Found closing bracket in suggestion: {text}")

        # Specifically check ENDOFLAM SP
        idx = self.combo.findText("ENDOFLAM SP")
        self.assertGreaterEqual(idx, 0)
        self.assertEqual(self.combo.itemText(idx), "ENDOFLAM SP")
        self.assertEqual(self.combo.itemData(idx), 1739)

    def test_02_prefix_search_end_matches_only_beginning(self):
        """Typing 'END' matches medicines starting with END, excluding middle/end matches."""
        self.combo.lineEdit().setText("END")
        self.combo.lineEdit().textEdited.emit("END")
        app.processEvents()

        model = self.combo._completer_model
        matched_texts = [model.item(r).text() for r in range(model.rowCount())]

        # ENDOFLAM SP starts with END
        self.assertIn("ENDOFLAM SP", matched_texts)

        # SCAREND (ends with END) and TENDOMAC (middle END) must NOT match
        self.assertNotIn("SCAREND", matched_texts)
        self.assertNotIn("TENDOMAC", matched_texts)

        for text in matched_texts:
            self.assertTrue(text.upper().startswith("END"), f"{text} does not start with END")

    def test_03_prefix_search_tab_excludes_substring_matches(self):
        """Typing 'TAB' excludes middle matches like 'BETABEST AM 50' and 'STABIZOL DSR'."""
        self.combo.lineEdit().setText("TAB")
        self.combo.lineEdit().textEdited.emit("TAB")
        app.processEvents()

        model = self.combo._completer_model
        matched_texts = [model.item(r).text() for r in range(model.rowCount())]

        # Middle matches must not be included
        self.assertNotIn("BETABEST AM 50", matched_texts)
        self.assertNotIn("STABIZOL DSR", matched_texts)

        # Since no items currently start with TAB, it should show 'No matching records found'
        self.assertEqual(len(matched_texts), 1)
        self.assertIn("No matching records found", matched_texts[0])

    def test_04_prefix_search_case_insensitive(self):
        """Prefix search matches regardless of case ('end', 'END', 'End', 'eNd')."""
        for variant in ["end", "END", "End", "eNd"]:
            self.combo.lineEdit().setText(variant)
            self.combo.lineEdit().textEdited.emit(variant)
            app.processEvents()

            model = self.combo._completer_model
            matched_texts = [model.item(r).text() for r in range(model.rowCount())]
            self.assertIn("ENDOFLAM SP", matched_texts, f"Failed to match for variant '{variant}'")
            self.assertNotIn("SCAREND", matched_texts)

    def test_05_prefix_search_ignores_leading_and_trailing_spaces(self):
        """Leading and trailing spaces in the search input are trimmed and ignored."""
        inputs = ["  END", "END  ", "   END   ", "\tEND\t"]
        for inp in inputs:
            self.combo.lineEdit().setText(inp)
            self.combo.lineEdit().textEdited.emit(inp)
            app.processEvents()

            model = self.combo._completer_model
            matched_texts = [model.item(r).text() for r in range(model.rowCount())]
            self.assertIn("ENDOFLAM SP", matched_texts, f"Failed for input '{inp}'")
            self.assertNotIn("SCAREND", matched_texts)
            self.assertNotIn("TENDOMAC", matched_texts)

    def test_06_prefix_search_other_medicine_prefixes(self):
        """Prefix search works for other medicines (e.g. 'CIP', 'ACE', 'DOLO')."""
        # CIP: matches CIPLOX etc., must NOT match NICIP
        self.combo.lineEdit().setText("CIP")
        self.combo.lineEdit().textEdited.emit("CIP")
        app.processEvents()

        cip_texts = [self.combo._completer_model.item(r).text() for r in range(self.combo._completer_model.rowCount())]
        self.assertTrue(len(cip_texts) > 0)
        self.assertNotIn("NICIP", cip_texts)
        self.assertNotIn("NICIP P", cip_texts)
        for t in cip_texts:
            self.assertTrue(t.upper().startswith("CIP"), f"{t} does not start with CIP")

        # ACE: must NOT match ANKLE BRACE
        self.combo.lineEdit().setText("ACE")
        self.combo.lineEdit().textEdited.emit("ACE")
        app.processEvents()

        ace_texts = [self.combo._completer_model.item(r).text() for r in range(self.combo._completer_model.rowCount())]
        self.assertTrue(len(ace_texts) > 0)
        self.assertNotIn("ANKLE BRACE", ace_texts)
        self.assertNotIn("CLAVICAL BRACE", ace_texts)
        for t in ace_texts:
            self.assertTrue(t.upper().startswith("ACE"), f"{t} does not start with ACE")

    def test_07_selecting_medicine_loads_correct_id_and_ledger(self):
        """Selecting a medicine by ID or by typing resolves correct item ID and populates ledger."""
        idx = self.combo.findText("ENDOFLAM SP")
        self.assertGreaterEqual(idx, 0)

        # Select ENDOFLAM SP
        self.combo.setCurrentIndex(idx)
        self.assertEqual(self.combo.selected_id, 1739)
        self.assertEqual(self.combo.currentText(), "ENDOFLAM SP")

        # Generate report
        self.page._on_generate()
        self.assertEqual(self.page._item_selector.selected_id, 1739)
        self.assertIn("ENDOFLAM SP", self.page._info_item.text())
        # Summary card shows item info
        self.assertTrue(self.page._btn_print.isEnabled())

    def test_08_resolve_text_single_prefix_match(self):
        """Typing exact or unique prefix and resolving sets selected_id."""
        self.combo.lineEdit().setText("ENDOFLAM SP")
        self.combo.resolve_text()
        self.assertEqual(self.combo.selected_id, 1739)

    def test_09_other_screens_unaffected(self):
        """Customer Ledger and Supplier Ledger still use contains-match and show subtitles."""
        cust_page = CustomerLedgerPage()
        cust_combo = cust_page._customer_selector
        self.assertFalse(getattr(cust_combo, "_prefix_only", False))
        # Customers have city in brackets
        has_sub = any("[" in cust_combo.itemText(i) for i in range(cust_combo.count()))
        self.assertTrue(has_sub, "Customer ledger dropdown should still show city subtitles")
        cust_page.close()

        supp_page = SupplierLedgerPage()
        supp_combo = supp_page._supplier_selector
        self.assertFalse(getattr(supp_combo, "_prefix_only", False))
        supp_page.close()

    def test_10_database_records_and_schema_unmodified(self):
        """LedgerReportDAO.get_item_options still returns full metadata (company_name, unit_name)."""
        opts = LedgerReportDAO.get_item_options()
        endoflam = next((o for o in opts if o["id"] == 1739), None)
        self.assertIsNotNone(endoflam)
        self.assertEqual(endoflam["item_name"], "ENDOFLAM SP")
        self.assertEqual(endoflam["company_name"], "TURRET PHARMA PVT LTD")
        self.assertEqual(endoflam["unit_name"], "TABLET")
        self.assertEqual(endoflam["pack_size"], "10")


if __name__ == "__main__":
    unittest.main()
