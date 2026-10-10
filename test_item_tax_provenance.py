"""Tax provenance tests — legacy_tax_id separates OLD codes from NEW GST.

A. legacy TaxID 12 (legacy_tax_id=12) displays the mapping-required flag.
B. new GST-12 (legacy_tax_id NULL) displays the full GST name — never collides.
C–F. GST 5/18/28/ZERO display correctly.
G. editing legacy without tax change preserves legacy_tax_id.
H. explicit legacy → GST conversion clears legacy_tax_id.
I. no automatic conversion of any legacy code.
J. migrated-shape data (all 10 codes with provenance) stays intact.

Every test runs against a disposable temporary database.
``data/pharmacy.db`` is never used.
"""

import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HAS_PYSIDE6 = False
_PYSIDE_SKIP_REASON = "PySide6 not available"
try:
    from PySide6.QtWidgets import QApplication, QMessageBox

    HAS_PYSIDE6 = True
except ImportError:  # pragma: no cover - environment dependent
    pass


def _fresh_db(tag: str) -> str:
    db_path = os.path.join(tempfile.gettempdir(), f"pharmacy_taxprov_{tag}.db")
    for suffix in ("", "-wal", "-shm"):
        stale = db_path + suffix
        if os.path.exists(stale):
            os.remove(stale)
    os.environ["PHARMACY_DB"] = db_path
    return db_path


class _DBBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = _fresh_db(cls.__name__)
        from database.connection import init_database
        from database import auth

        init_database()
        auth.ensure_auth_schema()

    def setUp(self):
        from database.connection import get_connection

        conn = get_connection()
        for table in ("item_ingredients", "items", "drugs", "units", "companies"):
            conn.execute(f'DELETE FROM "{table}"')
        conn.commit()
        conn.close()


class ProvenanceDisplayTests(_DBBase):
    def test_a_legacy_12_flagged(self):
        from database.item_dao import ItemDAO
        from database.tax_structures import resolve_tax_display

        # Unmapped legacy code with provenance still flags...
        item_id = ItemDAO.insert(item_name="Legacy Eleven", tax_structure="11",
                                 legacy_tax_id=11)
        row = ItemDAO.get_by_id(item_id)
        self.assertEqual(row["legacy_tax_id"], 11)
        self.assertEqual(resolve_tax_display(row["tax_structure"], row["legacy_tax_id"]),
                         "Legacy Tax Code 11 \u2014 Mapping Required")
        # ...while a GST-mapped legacy item shows its GST name.
        mapped = ItemDAO.insert(item_name="Mapped Twelve", tax_structure="12",
                                legacy_tax_id=12)
        mrow = ItemDAO.get_by_id(mapped)
        self.assertEqual(resolve_tax_display(mrow["tax_structure"], mrow["legacy_tax_id"]),
                         "GST @ 12% (CGST-6% & SGST-6%)")

    def test_b_new_gst_12_not_flagged(self):
        from database.item_dao import ItemDAO
        from database.tax_structures import resolve_tax_display

        item_id = ItemDAO.insert(item_name="New GST Twelve", tax_structure="12",
                                 legacy_tax_id=None)
        row = ItemDAO.get_by_id(item_id)
        self.assertIsNone(row["legacy_tax_id"])
        self.assertEqual(resolve_tax_display(row["tax_structure"], row["legacy_tax_id"]),
                         "GST @ 12% (CGST-6% & SGST-6%)")

    def test_cdef_new_rates_display(self):
        from database.tax_structures import resolve_tax_display

        self.assertEqual(resolve_tax_display("5", None),
                         "GST @ 5% (CGST-2.5% & SGST-2.5%)")
        self.assertEqual(resolve_tax_display("18", None),
                         "GST @ 18% (CGST-9% & SGST-9%)")
        self.assertEqual(resolve_tax_display("28", None),
                         "GST @ 28% (CGST-14% & SGST-14%)")
        self.assertEqual(resolve_tax_display("0", None), "ZERO GST")

    def test_j_migrated_shape_intact(self):
        """All 10 legacy codes with provenance: stored, counted, labeled.

        A GST-equal value with provenance shows its GST name (verified
        per-item mapping semantics); other codes show the mapping flag.
        """
        from database.item_dao import ItemDAO
        from database.tax_structures import resolve_tax_display

        for code in ("1", "2", "4", "6", "7", "11", "12", "13", "14", "15"):
            ItemDAO.insert(item_name=f"Migrated {code}", tax_structure=code,
                           legacy_tax_id=int(code))
        rows = ItemDAO.get_all()
        self.assertEqual(len(rows), 10)
        for row in rows:
            with self.subTest(code=row["tax_structure"]):
                self.assertEqual(str(row["legacy_tax_id"]), row["tax_structure"])
                label = resolve_tax_display(row["tax_structure"],
                                            row["legacy_tax_id"])
                if row["tax_structure"] == "12":
                    self.assertIn("GST @ 12%", label)
                else:
                    self.assertIn("Mapping Required", label)


class ProvenanceEditTests(_DBBase):
    def test_g_edit_preserves_provenance(self):
        from database.item_dao import ItemDAO

        item_id = ItemDAO.insert(item_name="Legacy Six", tax_structure="6",
                                 legacy_tax_id=6, mrp=10.0)
        ItemDAO.update(item_id, "Legacy Six", tax_structure="6", mrp=12.0)
        row = ItemDAO.get_by_id(item_id)
        self.assertEqual((row["tax_structure"], row["legacy_tax_id"], row["mrp"]),
                         ("6", 6, 12.0))

    def test_h_explicit_conversion_clears_provenance(self):
        from database.item_dao import ItemDAO

        item_id = ItemDAO.insert(item_name="Convert Me", tax_structure="11",
                                 legacy_tax_id=11)
        ItemDAO.update(item_id, "Convert Me", tax_structure="18", legacy_tax_id=None)
        row = ItemDAO.get_by_id(item_id)
        self.assertEqual((row["tax_structure"], row["legacy_tax_id"]), ("18", None))

    def test_i_no_automatic_conversion(self):
        from database.item_dao import ItemDAO

        codes = ("1", "2", "4", "6", "7", "11", "12", "13", "14", "15")
        ids = [ItemDAO.insert(item_name=f"Bulk {c}", tax_structure=c,
                              legacy_tax_id=int(c)) for c in codes]
        for item_id, code in zip(ids, codes):
            ItemDAO.update(item_id, f"Bulk {code} Renamed", tax_structure=code,
                           reorder_stock_level=9)
        for item_id, code in zip(ids, codes):
            row = ItemDAO.get_by_id(item_id)
            self.assertEqual((row["tax_structure"], row["legacy_tax_id"]),
                             (code, int(code)))


@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class ProvenanceDialogTests(_DBBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        patches = mock.patch.multiple(
            QMessageBox, warning=mock.DEFAULT, information=mock.DEFAULT,
            critical=mock.DEFAULT,
        )
        patches.start()
        self.addCleanup(patches.stop)

    def _save_new(self, name, gst_value):
        from screens.item_master import _ItemDialog

        dialog = _ItemDialog()
        self.addCleanup(dialog.deleteLater)
        dialog._item_name_edit.setText(name)
        combo = dialog._tax_structure_combo
        combo.setCurrentIndex(combo.findData(gst_value))
        dialog._on_save()
        return dialog

    def test_b_dialog_new_gst12_selects_gst_option(self):
        from database.item_dao import ItemDAO

        dialog = self._save_new("Dialog GST Twelve", "12")
        self.assertTrue(dialog.was_saved)
        row = ItemDAO.search("Dialog GST Twelve")[0]
        self.assertEqual((row["tax_structure"], row["legacy_tax_id"]), ("12", None))
        from screens.item_master import _ItemDialog

        reopened = _ItemDialog(item=ItemDAO.get_by_id(row["id"]))
        self.addCleanup(reopened.deleteLater)
        combo = reopened._tax_structure_combo
        self.assertEqual(combo.count(), 5)
        self.assertEqual(combo.currentText(), "GST @ 12% (CGST-6% & SGST-6%)")

    def test_mapped_gst_item_displays_gst_and_preserves_on_edit(self):
        """GST-mapped legacy item: GST name shown, value+provenance kept."""
        from database.item_dao import ItemDAO
        from database.tax_structures import resolve_tax_display
        from screens.item_master import ItemMasterPage, _ItemDialog

        item_id = ItemDAO.insert(item_name="Mapped GST Item", tax_structure="12",
                                 legacy_tax_id=12)
        row = ItemDAO.get_by_id(item_id)
        self.assertEqual(resolve_tax_display(row["tax_structure"], row["legacy_tax_id"]),
                         "GST @ 12% (CGST-6% & SGST-6%)")
        page = ItemMasterPage()
        self.addCleanup(page.deleteLater)
        page._refresh([row])
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()
        self.assertEqual(page._table.item(0, 7).text(),
                         "GST @ 12% (CGST-6% & SGST-6%)")
        dialog = _ItemDialog(item=row)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog._tax_structure_combo.count(), 5)
        dialog._mrp_edit.setText("77.0")
        dialog._on_save()
        self.assertTrue(dialog.was_saved)
        saved = ItemDAO.get_by_id(item_id)
        self.assertEqual((saved["tax_structure"], saved["legacy_tax_id"],
                          saved["mrp"]), ("12", 12, 77.0))

    def test_empty_item_displays_blank_and_preserves_on_edit(self):
        """EMPTY (VAT-only) legacy item: blank cell, values preserved."""
        from database.item_dao import ItemDAO
        from database.tax_structures import resolve_tax_display
        from screens.item_master import ItemMasterPage, _ItemDialog

        item_id = ItemDAO.insert(item_name="Empty VAT Item", tax_structure="",
                                 legacy_tax_id=6)
        row = ItemDAO.get_by_id(item_id)
        self.assertEqual(resolve_tax_display(row["tax_structure"], row["legacy_tax_id"]), "")
        page = ItemMasterPage()
        self.addCleanup(page.deleteLater)
        page._refresh([row])
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()
        self.assertEqual(page._table.item(0, 7).text(), "")
        dialog = _ItemDialog(item=row)
        self.addCleanup(dialog.deleteLater)
        dialog._mrp_edit.setText("10.0")
        dialog._on_save()
        self.assertTrue(dialog.was_saved)
        saved = ItemDAO.get_by_id(item_id)
        self.assertEqual((saved["tax_structure"], saved["legacy_tax_id"]),
                         ("", 6))

    def test_a_dialog_legacy12_shows_flag(self):
        from database.item_dao import ItemDAO
        from screens.item_master import _ItemDialog

        item_id = ItemDAO.insert(item_name="Dialog Legacy Eleven",
                                 tax_structure="11", legacy_tax_id=11)
        dialog = _ItemDialog(item=ItemDAO.get_by_id(item_id))
        self.addCleanup(dialog.deleteLater)
        self.assertIn("Mapping Required",
                      dialog._tax_structure_combo.currentText())

    def test_g_dialog_unrelated_edit_preserves(self):
        from database.item_dao import ItemDAO
        from screens.item_master import _ItemDialog

        item_id = ItemDAO.insert(item_name="Dialog Legacy", tax_structure="6",
                                 legacy_tax_id=6)
        dialog = _ItemDialog(item=ItemDAO.get_by_id(item_id))
        self.addCleanup(dialog.deleteLater)
        dialog._mrp_edit.setText("55.0")
        dialog._on_save()
        self.assertTrue(dialog.was_saved)
        row = ItemDAO.get_by_id(item_id)
        self.assertEqual((row["tax_structure"], row["legacy_tax_id"], row["mrp"]),
                         ("6", 6, 55.0))

    def test_h_dialog_explicit_conversion_clears(self):
        from database.item_dao import ItemDAO
        from screens.item_master import _ItemDialog

        item_id = ItemDAO.insert(item_name="Dialog Convert", tax_structure="11",
                                 legacy_tax_id=11)
        dialog = _ItemDialog(item=ItemDAO.get_by_id(item_id))
        self.addCleanup(dialog.deleteLater)
        combo = dialog._tax_structure_combo
        combo.setCurrentIndex(combo.findData("18"))
        dialog._on_save()
        self.assertTrue(dialog.was_saved)
        row = ItemDAO.get_by_id(item_id)
        self.assertEqual((row["tax_structure"], row["legacy_tax_id"]), ("18", None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
