"""Item Master GST tax-structure dropdown tests.

Covers the five GST options, their internal values, new-item defaults and
saving, editing items at each rate, preservation of imported legacy tax
codes, and Purchase Invoice compatibility.

Every test runs against a disposable temporary database.  ``data/pharmacy.db``
is never used: each class points ``PHARMACY_DB`` at its own temp file and
deletes it first.
"""

import os
import sqlite3
import tempfile
import unittest
from unittest import mock

HAS_PYSIDE6 = False
_PYSIDE_SKIP_REASON = "PySide6 not available"
try:
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QDialog,
        QLineEdit,
        QMessageBox,
    )
    HAS_PYSIDE6 = True
except ImportError:  # pragma: no cover - environment dependent
    pass


EXPECTED_OPTIONS = (
    ("GST @ 5% (CGST-2.5% & SGST-2.5%)", "5"),
    ("GST @ 12% (CGST-6% & SGST-6%)", "12"),
    ("GST @ 18% (CGST-9% & SGST-9%)", "18"),
    ("GST @ 28% (CGST-14% & SGST-14%)", "28"),
    ("ZERO GST", "0"),
)

LEGACY_OPTION_TEXTS = (
    "VAT @ 12.50%",
    "VAT @ 5.00%",
    "VAT @ 6.00%",
    "VAT @ 13.50%",
    "NO-TAX",
)


def _fresh_db(tag: str) -> str:
    db_path = os.path.join(tempfile.gettempdir(), f"pharmacy_tax_{tag}.db")
    for suffix in ("", "-wal", "-shm"):
        stale = db_path + suffix
        if os.path.exists(stale):
            os.remove(stale)
    os.environ["PHARMACY_DB"] = db_path
    return db_path


# ======================================================================
# Tax structure definitions (no GUI required)
# ======================================================================

class TaxStructureDefinitionTests(unittest.TestCase):
    def test_01_exactly_five_options(self):
        from database.tax_structures import GST_TAX_STRUCTURES
        self.assertEqual(len(GST_TAX_STRUCTURES), 5)

    def test_02_exact_display_text_and_order(self):
        from database.tax_structures import GST_TAX_STRUCTURES
        self.assertEqual(GST_TAX_STRUCTURES, EXPECTED_OPTIONS)

    def test_03_internal_values(self):
        from database.tax_structures import VALID_TAX_VALUES
        self.assertEqual(VALID_TAX_VALUES, ("5", "12", "18", "28", "0"))

    def test_04_zero_gst_maps_to_zero(self):
        from database.tax_structures import display_for, rate_percent
        self.assertEqual(display_for("0"), "ZERO GST")
        self.assertEqual(rate_percent("0"), 0.0)

    def test_05_each_rate(self):
        from database.tax_structures import rate_percent
        self.assertEqual(rate_percent("5"), 5.0)
        self.assertEqual(rate_percent("12"), 12.0)
        self.assertEqual(rate_percent("18"), 18.0)
        self.assertEqual(rate_percent("28"), 28.0)

    def test_06_legacy_codes_are_not_gst_rates(self):
        """An imported tax code must never be read as a GST percentage."""
        from database.tax_structures import is_gst_rate, rate_percent
        for code in ("1", "2", "4", "6", "7", "11", "13", "14", "15"):
            with self.subTest(code=code):
                self.assertFalse(is_gst_rate(code))
                self.assertIsNone(rate_percent(code),
                                  "legacy code must not invent a GST rate")

    def test_07_display_for_preserves_unknown_values(self):
        from database.tax_structures import display_for
        self.assertEqual(display_for("11"), "11")
        self.assertEqual(display_for(""), "")
        self.assertEqual(display_for(None), "")

    def test_08_default_is_zero_gst(self):
        from database.tax_structures import DEFAULT_TAX_VALUE
        self.assertEqual(DEFAULT_TAX_VALUE, "0")


# ======================================================================
# Item DAO round-trip (no GUI required)
# ======================================================================

class ItemTaxStorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = _fresh_db("dao")
        from database.connection import init_database
        from database import auth
        init_database()
        auth.ensure_auth_schema()

    def _clear(self):
        from database.connection import get_connection
        conn = get_connection()
        conn.execute("DELETE FROM items")
        conn.commit()
        conn.close()

    def setUp(self):
        self._clear()

    def test_10_insert_and_read_back_each_rate(self):
        from database.item_dao import ItemDAO
        for display, value in EXPECTED_OPTIONS:
            with self.subTest(value=value):
                item_id = ItemDAO.insert(item_name=f"Item {value}",
                                         tax_structure=value)
                stored = ItemDAO.get_by_id(item_id)
                self.assertEqual(stored["tax_structure"], value,
                                 "internal value must be stored, not display text")

    def test_11_update_to_each_rate(self):
        from database.item_dao import ItemDAO
        item_id = ItemDAO.insert(item_name="Editable", tax_structure="0")
        for _, value in EXPECTED_OPTIONS:
            with self.subTest(value=value):
                ItemDAO.update(item_id, item_name="Editable",
                               tax_structure=value)
                self.assertEqual(
                    ItemDAO.get_by_id(item_id)["tax_structure"], value)

    def test_12_legacy_value_is_stored_verbatim(self):
        """A legacy code must round-trip unchanged, with no normalisation."""
        from database.item_dao import ItemDAO
        item_id = ItemDAO.insert(item_name="Legacy Item", tax_structure="11")
        self.assertEqual(ItemDAO.get_by_id(item_id)["tax_structure"], "11")

    def test_13_get_all_reports_tax_unchanged(self):
        from database.item_dao import ItemDAO
        ItemDAO.insert(item_name="A", tax_structure="6")
        ItemDAO.insert(item_name="B", tax_structure="18")
        values = {i["item_name"]: i["tax_structure"]
                  for i in ItemDAO.get_all()}
        self.assertEqual(values["A"], "6")
        self.assertEqual(values["B"], "18")


# ======================================================================
# Item Master dialog (GUI)
# ======================================================================

@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class ItemMasterTaxDialogTests(unittest.TestCase):
    """The Tax Structure control in Master -> Item."""

    @classmethod
    def setUpClass(cls):
        _fresh_db("dialog")
        from database.connection import init_database
        from database import auth
        init_database()
        auth.ensure_auth_schema()
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        from database.connection import get_connection
        conn = get_connection()
        conn.execute("DELETE FROM items")
        conn.commit()
        conn.close()

        self.dialog_patches = [
            mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "information", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "critical", return_value=QMessageBox.Ok),
        ]
        for patcher in self.dialog_patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _new_dialog(self):
        from screens.item_master import _ItemDialog
        dialog = _ItemDialog()
        self.addCleanup(dialog.deleteLater)
        return dialog

    def _edit_dialog(self, item_id):
        from database.item_dao import ItemDAO
        from screens.item_master import _ItemDialog
        dialog = _ItemDialog(item=ItemDAO.get_by_id(item_id))
        self.addCleanup(dialog.deleteLater)
        return dialog

    def _options(self, combo):
        return [(combo.itemText(i), combo.itemData(i))
                for i in range(combo.count())]

    # -- the dropdown itself -------------------------------------------
    def test_20_dropdown_has_exactly_five_options(self):
        dialog = self._new_dialog()
        combo = dialog._tax_structure_combo
        self.assertIsInstance(combo, QComboBox)
        self.assertEqual(combo.count(), 5)

    def test_21_dropdown_display_text_and_values(self):
        dialog = self._new_dialog()
        self.assertEqual(self._options(dialog._tax_structure_combo),
                         list(EXPECTED_OPTIONS))

    def test_22_no_legacy_options_for_new_item(self):
        combo = self._new_dialog()._tax_structure_combo
        texts = [combo.itemText(i) for i in range(combo.count())]
        for legacy in LEGACY_OPTION_TEXTS:
            with self.subTest(legacy=legacy):
                self.assertNotIn(legacy, texts)

    def test_23_new_item_defaults_to_zero_gst(self):
        dialog = self._new_dialog()
        self.assertEqual(dialog._tax_structure_combo.currentData(), "0")
        self.assertEqual(dialog._tax_structure_combo.currentText(), "ZERO GST")

    def test_24_dropdown_matches_item_master_styling(self):
        dialog = self._new_dialog()
        self.assertEqual(dialog._tax_structure_combo.styleSheet(),
                         dialog._company_combo.styleSheet())
        self.assertIn("background-color", dialog._tax_structure_combo.styleSheet())

    def test_25_dropdown_is_readable_height(self):
        dialog = self._new_dialog()
        combo = dialog._tax_structure_combo
        self.assertGreaterEqual(combo.sizeHint().height(), 24)

    # -- saving new items ----------------------------------------------
    def _save_with_tax(self, name, value):
        from database.item_dao import ItemDAO
        dialog = self._new_dialog()
        dialog._item_name_edit.setText(name)
        combo = dialog._tax_structure_combo
        index = combo.findData(value)
        self.assertGreaterEqual(index, 0)
        combo.setCurrentIndex(index)
        dialog._on_save()
        self.assertTrue(dialog.was_saved, "save should have been accepted")
        return ItemDAO.search(name)[0]

    def test_30_new_item_saves_each_rate(self):
        for display, value in EXPECTED_OPTIONS:
            with self.subTest(value=value):
                item = self._save_with_tax(f"New Item {value}", value)
                self.assertEqual(item["tax_structure"], value)

    def test_31_new_item_saves_zero_gst_by_default(self):
        from database.item_dao import ItemDAO
        from screens.item_master import _ItemDialog
        dialog = _ItemDialog()
        self.addCleanup(dialog.deleteLater)
        dialog._item_name_edit.setText("Default Tax Item")
        dialog._on_save()
        self.assertTrue(dialog.was_saved)
        self.assertEqual(
            ItemDAO.search("Default Tax Item")[0]["tax_structure"], "0")

    def test_32_renamed_legacy_code_is_rejected_for_new_item(self):
        """Arbitrary text cannot reach the DB through the normal UI."""
        from database.item_dao import ItemDAO
        from screens.item_master import _ItemDialog
        dialog = _ItemDialog()
        self.addCleanup(dialog.deleteLater)
        dialog._item_name_edit.setText("Sneaky Tax Item")
        # Simulate a value that is not one of the five options.
        combo = dialog._tax_structure_combo
        combo.addItem("VAT @ 12.50%", "12.50")
        combo.setCurrentIndex(combo.count() - 1)
        dialog._on_save()
        self.assertFalse(dialog.was_saved,
                         "an unsupported tax value must not be saved")
        self.assertEqual(ItemDAO.search("Sneaky Tax Item"), [])

    # -- editing existing items ----------------------------------------
    def _make_item(self, name, tax):
        from database.item_dao import ItemDAO
        return ItemDAO.insert(item_name=name, tax_structure=tax)

    def test_40_edit_item_with_each_rate(self):
        for _, value in EXPECTED_OPTIONS:
            with self.subTest(value=value):
                item_id = self._make_item(f"Edit Item {value}", value)
                dialog = self._edit_dialog(item_id)
                combo = dialog._tax_structure_combo
                self.assertEqual(combo.count(), 5,
                                 "an existing GST item adds no extra entry")
                self.assertEqual(combo.currentData(), value)
                dialog._item_name_edit.setText(f"Edit Item {value} Renamed")
                dialog._on_save()
                self.assertTrue(dialog.was_saved)

                from database.item_dao import ItemDAO
                saved = ItemDAO.get_by_id(item_id)
                self.assertEqual(saved["tax_structure"], value)

    def test_41_change_rate_from_zero_to_gst(self):
        from database.item_dao import ItemDAO
        item_id = self._make_item("Rate Change Item", "0")
        dialog = self._edit_dialog(item_id)
        dialog._tax_structure_combo.setCurrentIndex(
            dialog._tax_structure_combo.findData("18"))
        dialog._on_save()
        self.assertEqual(ItemDAO.get_by_id(item_id)["tax_structure"], "18")

    def test_42_change_legacy_code_to_gst_rate(self):
        """A user may intentionally move a legacy item onto a GST rate."""
        from database.item_dao import ItemDAO
        item_id = self._make_item("Legacy To Gst", "11")
        dialog = self._edit_dialog(item_id)
        self.assertEqual(dialog._tax_structure_combo.currentData(), "11")
        dialog._tax_structure_combo.setCurrentIndex(
            dialog._tax_structure_combo.findData("12"))
        dialog._on_save()
        self.assertTrue(dialog.was_saved)
        self.assertEqual(ItemDAO.get_by_id(item_id)["tax_structure"], "12")

    # -- legacy / imported items ---------------------------------------
    def test_50_legacy_code_shown_and_preserved_on_edit(self):
        from database.item_dao import ItemDAO
        item_id = self._make_item("Legacy Eleven", "11")
        dialog = self._edit_dialog(item_id)
        combo = dialog._tax_structure_combo
        self.assertEqual(combo.count(), 6,
                         "the legacy value is shown as one extra entry")
        self.assertEqual(combo.currentData(), "11",
                         "the stored legacy value must stay selected")
        self.assertIn("11", combo.currentText())
        self.assertIn("legacy", combo.currentText().lower())

    def test_51_saving_unrelated_field_keeps_legacy_code(self):
        """Editing only the MRP must not convert or destroy the tax value."""
        from database.item_dao import ItemDAO
        item_id = self._make_item("Legacy Untouched", "11")
        dialog = self._edit_dialog(item_id)
        dialog._mrp_edit.setText("199.99")
        dialog._on_save()
        self.assertTrue(dialog.was_saved,
                        "an unrelated edit must not be blocked by tax")
        saved = ItemDAO.get_by_id(item_id)
        self.assertEqual(saved["tax_structure"], "11",
                         "legacy tax value must survive an unrelated edit")
        self.assertEqual(saved["mrp"], 199.99)

    def test_52_no_mass_update_of_legacy_values(self):
        """Opening and saving many legacy items changes no tax value."""
        from database.item_dao import ItemDAO
        codes = ("11", "6", "13", "7", "2")
        for index, code in enumerate(codes):
            self._make_item(f"Bulk Legacy {index}", code)
        for index, code in enumerate(codes):
            dialog = self._edit_dialog(
                ItemDAO.search(f"Bulk Legacy {index}")[0]["id"])
            dialog._reorder_edit.setText("7")
            dialog._on_save()
        for index, code in enumerate(codes):
            item = ItemDAO.search(f"Bulk Legacy {index}")[0]
            self.assertEqual(item["tax_structure"], code)
            self.assertEqual(item["reorder_stock_level"], 7)

    def test_53_grid_shows_readable_label_and_keeps_legacy_raw(self):
        from database.item_dao import ItemDAO
        ItemDAO.insert(item_name="Grid Gst", tax_structure="18")
        ItemDAO.insert(item_name="Grid Legacy", tax_structure="11")
        from screens.item_master import ItemMasterPage
        page = ItemMasterPage()
        self.addCleanup(page.deleteLater)
        page.resize(1200, 600)
        page.show()
        QApplication.processEvents()
        page._refresh()
        QApplication.processEvents()
        cells = {}
        for row in range(page._table.rowCount()):
            name = page._table.item(row, 1).text()
            cells[name] = page._table.item(row, 7).text()
        self.assertEqual(cells["Grid Gst"], "GST @ 18% (CGST-9% & SGST-9%)")
        self.assertEqual(cells["Grid Legacy"], "11")


# ======================================================================
# Purchase Invoice compatibility
# ======================================================================

@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class PurchaseInvoiceTaxCompatibilityTests(unittest.TestCase):
    """Purchase GST still reads 0/5/12/18/28 and never guesses."""

    @classmethod
    def setUpClass(cls):
        _fresh_db("purchase")
        from database.connection import init_database
        from database import auth, financial_year
        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        from database.connection import get_connection
        conn = get_connection()
        for table in ("purchase_invoice_items", "purchase_invoices", "items"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
        conn.close()
        self.patches = [
            mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "information", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "critical", return_value=QMessageBox.Ok),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _dialog(self):
        """The purchase entry bar lives on the add-invoice dialog."""
        from screens.purchase_invoice import _InvoiceDialog
        dialog = _InvoiceDialog()
        self.addCleanup(dialog.deleteLater)
        dialog.resize(1200, 700)
        dialog.show()
        QApplication.processEvents()
        return dialog

    def _select_item(self, dialog, item_id):
        entry = dialog._entry_bar
        entry.item_combo.setCurrentIndex(entry.item_combo.findData(item_id))
        dialog._on_item_changed(entry.item_combo.currentIndex())
        return entry

    def test_60_purchase_prefills_each_gst_rate(self):
        from database.item_dao import ItemDAO
        for _, value in EXPECTED_OPTIONS:
            with self.subTest(value=value):
                item_id = ItemDAO.insert(item_name=f"Pur Item {value}",
                                         tax_structure=value)
                dialog = self._dialog()
                entry = self._select_item(dialog, item_id)
                # ZERO GST pre-fills an explicit 0; a legacy code pre-fills
                # nothing at all, so no rate is ever guessed.
                self.assertEqual(entry.gst_edit.text(), value)
                dialog.hide()

    def test_61_purchase_does_not_invent_tax_for_legacy_item(self):
        from database.item_dao import ItemDAO
        item_id = ItemDAO.insert(item_name="Pur Legacy", tax_structure="11")
        dialog = self._dialog()
        entry = self._select_item(dialog, item_id)
        self.assertEqual(entry.gst_edit.text(), "",
                         "a legacy code must not produce a GST percentage")
        dialog.hide()

    def test_62_purchase_gst_arithmetic_unchanged(self):
        """amount x gst% / 100 still produces the same GST amount."""
        from screens.purchase_invoice import _round2
        for rate, amount, expected in ((5, 480.0, 24.0),
                                       (12, 100.0, 12.0),
                                       (18, 1000.0, 180.0),
                                       (28, 250.0, 70.0),
                                       (0, 999.0, 0.0)):
            with self.subTest(rate=rate):
                self.assertEqual(_round2(amount * rate / 100.0), expected)

    def test_63_purchase_gst_box_remains_user_overridable(self):
        from database.item_dao import ItemDAO
        item_id = ItemDAO.insert(item_name="Override Item",
                                 tax_structure="18")
        dialog = self._dialog()
        entry = dialog._entry_bar
        entry.gst_edit.setText("5")
        self._select_item(dialog, item_id)
        self.assertEqual(entry.gst_edit.text(), "5",
                         "an existing user entry must not be overwritten")
        dialog.hide()

    def test_64_stored_purchase_gst_values_are_not_touched(self):
        """Adding a GST item leaves existing purchase GST rows unchanged."""
        from database.item_dao import ItemDAO
        from database.purchase_dao import PurchaseDAO
        from database.supplier_dao import SupplierDAO
        from database.account_roles import ensure_system_ledgers

        item_id = ItemDAO.insert(item_name="Hist Item", tax_structure="5")
        supplier_id = SupplierDAO.insert("Hist Supplier")
        ensure_system_ledgers()
        PurchaseDAO.insert_invoice(
            voucher_no="GST-HIST-1", voucher_date="2026-09-16",
            voucher_time="", purchase_type="Credit",
            supplier_id=supplier_id, invoice_no="INV-H1",
            invoice_date="2026-09-16", invoice_net_amount=100,
            bill_discount=0, due_date="", total_amount=100, gst_amount=24.0,
            debit_note_amount=0, other_amount=0, paid_amount=0, round_off=0,
            net_amount=124.0, remarks="",
            items=[{"item_id": item_id, "pack_size": "", "pay_qty": 1,
                    "free_qty": 0, "batch_no": "B-GH", "expiry": "12/28",
                    "rate": 100, "mrp": 120, "discount": 0,
                    "gst_percent": 5, "gst_amount": 24.0, "amount": 100,
                    "purchase_rate": 100, "net_rate": 100, "pp": 100}])

        from database.connection import get_connection
        conn = get_connection()
        row = conn.execute(
            "SELECT gst_percent, gst_amount FROM purchase_invoice_items "
            "WHERE purchase_invoice_id = (SELECT id FROM purchase_invoices "
            "WHERE voucher_no = 'GST-HIST-1')").fetchone()
        conn.close()
        self.assertEqual(row["gst_percent"], 5)
        self.assertEqual(row["gst_amount"], 24.0)


# ======================================================================
# Data safety
# ======================================================================

class TaxDataSafetyTests(unittest.TestCase):
    """The real imported database must be untouched by this feature."""

    def test_70_no_migration_or_schema_change(self):
        """No tax master table or column may have been introduced."""
        source = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "data", "pharmacy.db")
        if not os.path.exists(source):
            self.skipTest("no real database present")
        conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        try:
            names = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")]
            self.assertNotIn("taxes", names)
            self.assertNotIn("tax_structures", names)
            columns = [r[1] for r in conn.execute("PRAGMA table_info(items)")]
            self.assertIn("tax_structure", columns)
            self.assertEqual(columns.count("tax_structure"), 1)
        finally:
            conn.close()

    def test_71_imported_tax_codes_are_still_legacy_values(self):
        """Imported items keep their original legacy codes in place."""
        source = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "data", "pharmacy.db")
        if not os.path.exists(source):
            self.skipTest("no real database present")
        conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        try:
            values = [r[0] for r in conn.execute(
                "SELECT DISTINCT tax_structure FROM items")]
        finally:
            conn.close()
        self.assertTrue(values, "items table should not be empty")
        # Every imported value is a bare legacy code; none was rewritten to a
        # "GST @ n%" label by this change.
        for value in values:
            with self.subTest(value=value):
                self.assertNotIn("GST", str(value).upper())

    def test_72_no_legacy_migration_code_was_modified(self):
        """The migration still copies itemmst.TaxID verbatim."""
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "database", "legacy_migration.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("GST_TAX_STRUCTURES", source)
        self.assertNotIn("tax_structures", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)