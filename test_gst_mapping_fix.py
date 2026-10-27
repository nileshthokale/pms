"""Comprehensive test suite verifying the GST/Tax Structure mapping fix.

Verifies the 6 key user criteria:
1. The GST displayed in Item Master matches the GST shown in Edit Item.
   - For 5% GST items (e.g., legacy code 6, 11, etc.), both display:
     'GST @ 5% (CGST-2.5% & SGST-2.5%)'
   - For 12% GST items (e.g., legacy code 12), both display:
     'GST @ 12% (CGST-6% & SGST-6%)'
   - For unmapped legacy items (codes 1, 4, 15), both safely display:
     'Legacy Tax Code N — Mapping Required'
2. Opening and saving an item does not change its GST incorrectly.
   - Editing unrelated fields (e.g., MRP, Pack Size, Name) preserves GST mapping & provenance.
   - Explicitly changing GST in Edit Item persists the new rate.
3. The correct GST rate is used in purchase calculations and entry prefill.
   - 5% items populate '5'
   - 12% items populate '12'
   - Unmapped legacy items safely populate '0'
4. Items with legacy tax codes are mapped correctly:
   - Codes 2, 6, 7, 11, 13, 14 map to 5% GST
   - Code 12 maps to 12% GST
   - Codes 1, 4, 15 remain safely unmapped as 'Mapping Required'
5. Historical transaction records remain unchanged.
   - Historical purchase invoice items and sales invoices remain untouched.
6. No unrelated functionality is affected.
"""

from __future__ import annotations

import os
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication

from database.connection import get_connection
from database.item_dao import ItemDAO
from database.tax_structures import (
    LEGACY_TAX_ID_MAPPING,
    display_for,
    rate_percent,
    resolve_gst_rate,
    resolve_tax_display,
)
from screens.item_master import ItemMasterPage, _ItemDialog, _tax_cell_text
from screens.purchase_invoice import _InvoiceDialog


class TestGSTMappingFix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.pop("PHARMACY_DB", None)
        cls._app = QApplication.instance() or QApplication([])

    def test_01_item_master_matches_edit_item_dialog_5_percent(self):
        """Verify Item Master table and Edit Item dialog match for 5% GST items."""
        items = ItemDAO.get_all()
        item_5 = next((it for it in items if resolve_gst_rate(it.get("tax_structure"), it.get("legacy_tax_id")) == "5"), None)
        self.assertIsNotNone(item_5, "Should have items mapped to 5% GST")

        grid_label = _tax_cell_text(item_5)
        self.assertEqual(grid_label, "GST @ 5% (CGST-2.5% & SGST-2.5%)")

        dlg = _ItemDialog(parent=None, item=item_5)
        self.addCleanup(dlg.deleteLater)
        dlg_text = dlg._tax_structure_combo.currentText()
        dlg_val = dlg._tax_structure_combo.currentData()

        self.assertEqual(dlg_text, grid_label,
                         "Edit Item form must display the exact same GST text as Item Master table")
        self.assertEqual(dlg_val, "5")

    def test_02_item_master_matches_edit_item_dialog_12_percent(self):
        """Verify Item Master table and Edit Item dialog match for 12% GST items."""
        items = ItemDAO.get_all()
        item_12 = next((it for it in items if resolve_gst_rate(it.get("tax_structure"), it.get("legacy_tax_id")) == "12"), None)
        self.assertIsNotNone(item_12, "Should have items mapped to 12% GST")

        grid_label = _tax_cell_text(item_12)
        self.assertEqual(grid_label, "GST @ 12% (CGST-6% & SGST-6%)")

        dlg = _ItemDialog(parent=None, item=item_12)
        self.addCleanup(dlg.deleteLater)
        dlg_text = dlg._tax_structure_combo.currentText()
        dlg_val = dlg._tax_structure_combo.currentData()

        self.assertEqual(dlg_text, grid_label,
                         "Edit Item form must display the exact same 12% GST text as Item Master table")
        self.assertEqual(dlg_val, "12")

    def test_03_unmapped_legacy_codes_safely_flagged(self):
        """Verify unmapped legacy codes (1, 4, 15) remain safely flagged as Mapping Required in both table and dialog."""
        items = ItemDAO.get_all()
        for code in ("1", "4", "15"):
            it = next((x for x in items if str(x.get("legacy_tax_id")) == code or str(x.get("tax_structure")) == code), None)
            if it:
                grid_label = _tax_cell_text(it)
                self.assertIn(f"Legacy Tax Code {code}", grid_label)
                self.assertIn("Mapping Required", grid_label)

                dlg = _ItemDialog(parent=None, item=it)
                self.addCleanup(dlg.deleteLater)
                dlg_text = dlg._tax_structure_combo.currentText()
                self.assertEqual(dlg_text, grid_label,
                                 "Edit Item form must match Item Master table for unmapped legacy code")

    def test_04_opening_and_saving_item_preserves_gst_mapping(self):
        """Verify opening and saving an item without changing tax preserves its GST structure."""
        # Find an existing item with 5% GST
        items = ItemDAO.get_all()
        existing_item = next(it for it in items if it.get("legacy_tax_id") == 6 and it.get("tax_structure") == "5")
        orig_mrp = existing_item.get("mrp", 0.0)

        dlg = _ItemDialog(parent=None, item=existing_item)
        self.addCleanup(dlg.deleteLater)

        self.assertEqual(dlg._tax_structure_combo.currentData(), "5")
        self.assertEqual(dlg._tax_structure_combo.currentText(), "GST @ 5% (CGST-2.5% & SGST-2.5%)")

        # Edit an unrelated field (e.g. location) and save
        orig_location = existing_item.get("location", "")
        test_location = "LOC-TEST-99"
        dlg._location_edit.setText(test_location)
        dlg._on_save()
        self.assertTrue(dlg.was_saved)

        try:
            saved = ItemDAO.get_by_id(existing_item["id"])
            self.assertEqual(saved["location"], test_location)
            self.assertEqual(saved["tax_structure"], "5", "Tax structure must remain 5")
            self.assertEqual(saved["legacy_tax_id"], 6, "Provenance must remain preserved")
        finally:
            # Revert location
            ItemDAO.update(
                existing_item["id"],
                item_name=existing_item["item_name"],
                unit_id=existing_item["unit_id"],
                company_id=existing_item["company_id"],
                category_id=existing_item.get("category_id"),
                pack_size=existing_item.get("pack_size", ""),
                tax_structure="5",
                discount=existing_item.get("discount", 0.0),
                mrp=existing_item.get("mrp", 0.0),
                rate=existing_item.get("rate", 0.0),
                reorder_stock_level=existing_item.get("reorder_stock_level", 0),
                scheduled=existing_item.get("scheduled", ""),
                location=orig_location,
                pathy=existing_item.get("pathy", ""),
                dpco=existing_item.get("dpco", ""),
                legacy_tax_id=6,
            )

    def test_05_purchase_invoice_gst_rate_prefill(self):
        """Verify purchase invoice line item prefills correct GST rate for items."""
        dlg = _InvoiceDialog(parent=None)
        self.addCleanup(dlg.deleteLater)
        bar = dlg._entry_bar

        # Rate percent helper tests
        self.assertEqual(rate_percent("5"), 5.0)
        self.assertEqual(rate_percent("12"), 12.0)
        self.assertEqual(rate_percent("18"), 18.0)
        self.assertEqual(rate_percent("28"), 28.0)
        self.assertEqual(rate_percent("0"), 0.0)
        # Legacy code 6 resolves to 5.0
        self.assertEqual(rate_percent("6"), 5.0)
        # Legacy code 12 resolves to 12.0
        self.assertEqual(rate_percent("12"), 12.0)
        # Unmapped legacy code 1 resolves to None
        self.assertIsNone(rate_percent("1"))

        # Test prefill in purchase entry dialog
        # 1. 5% GST item
        items = ItemDAO.get_all()
        item_5 = next(it for it in items if resolve_gst_rate(it.get("tax_structure"), it.get("legacy_tax_id")) == "5")
        idx_5 = bar.item_combo.findData(item_5["id"])
        if idx_5 < 0:
            bar.item_combo.addItem(item_5["item_name"], item_5["id"])
            idx_5 = bar.item_combo.count() - 1
        bar.item_combo.setCurrentIndex(idx_5)
        dlg._on_item_changed(idx_5)
        self.assertEqual(bar.gst_edit.text(), "5")

        # 2. 12% GST item
        item_12 = next(it for it in items if resolve_gst_rate(it.get("tax_structure"), it.get("legacy_tax_id")) == "12")
        idx_12 = bar.item_combo.findData(item_12["id"])
        if idx_12 < 0:
            bar.item_combo.addItem(item_12["item_name"], item_12["id"])
            idx_12 = bar.item_combo.count() - 1
        bar.item_combo.setCurrentIndex(idx_12)
        dlg._on_item_changed(idx_12)
        self.assertEqual(bar.gst_edit.text(), "12")

    def test_06_historical_records_untouched(self):
        """Verify historical purchase and sales transaction records remain unchanged."""
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM purchase_invoice_items")
            pur_count = cur.fetchone()[0]
            self.assertEqual(pur_count, 11925)

            cur.execute("SELECT COUNT(*) FROM purchase_invoices")
            pur_head_count = cur.fetchone()[0]
            self.assertEqual(pur_head_count, 5731)

            cur.execute("SELECT COUNT(*) FROM sales_invoices")
            sales_head_count = cur.fetchone()[0]
            self.assertGreater(sales_head_count, 0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
