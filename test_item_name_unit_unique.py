"""Item Master composite uniqueness tests — UNIQUE(item_name, unit_id).

Phase 1 schema decision: the old Pharma-WINNER key is
UNIQUE(UnitID, ItemName), so the same item name across different units is
legitimate data (POWERGESIC as TABLET and as GEL; CALTONVIT across units).
The new rule is the composite UNIQUE(item_name, unit_id):

A. same name + different unit  -> ALLOWED (both records preserved)
B. same name + same unit       -> REJECTED (duplicate)
C. edits respect the rule (conflicting rename rejected, own save allowed)
D. search/autocomplete returns both rows with distinct units
E. Item Master dialog shows the right unit and enforces the rule per unit

Source values are preserved verbatim here (no trimming/normalizing).

Every test runs against a disposable temporary database.
``data/pharmacy.db`` is never used.
"""

import os
import sqlite3
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
    db_path = os.path.join(tempfile.gettempdir(), f"pharmacy_nameunit_{tag}.db")
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

        init_database()

    def setUp(self):
        from database.connection import get_connection

        conn = get_connection()
        for table in ("item_ingredients", "items", "drugs", "units", "companies"):
            conn.execute(f'DELETE FROM "{table}"')
        conn.commit()
        conn.close()

    def _unit(self, name: str) -> int:
        from database.unit_dao import UnitDAO

        return UnitDAO.insert(name)


# ======================================================================
# A/B. database-level rule (no GUI required)
# ======================================================================

class CompositeUniqueStorageTests(_DBBase):
    def test_10_same_name_different_units_allowed(self):
        """A: POWERGESIC + TABLET and POWERGESIC + GEL coexist."""
        from database.item_dao import ItemDAO

        tablet = self._unit("TABLET")
        gel = self._unit("GEL")
        first = ItemDAO.insert(item_name="POWERGESIC", unit_id=tablet)
        second = ItemDAO.insert(item_name="POWERGESIC", unit_id=gel)
        self.assertNotEqual(first, second)
        rows = [r for r in ItemDAO.get_all() if r["item_name"] == "POWERGESIC"]
        self.assertEqual(len(rows), 2)
        by_id = {r["id"]: r for r in rows}
        self.assertEqual(by_id[first]["unit_name"], "TABLET")
        self.assertEqual(by_id[second]["unit_name"], "GEL")

    def test_11_same_name_same_unit_rejected(self):
        """B: POWERGESIC + TABLET twice is a duplicate."""
        from database.item_dao import ItemDAO

        tablet = self._unit("TABLET")
        ItemDAO.insert(item_name="POWERGESIC", unit_id=tablet)
        with self.assertRaises(sqlite3.IntegrityError):
            ItemDAO.insert(item_name="POWERGESIC", unit_id=tablet)
        self.assertEqual(
            len([r for r in ItemDAO.get_all() if r["item_name"] == "POWERGESIC"]), 1)

    def test_12_ids_can_be_preserved_for_both_records(self):
        """Migration inserts explicit legacy IDs (51/920) without conflict."""
        from database.connection import get_connection

        tablet = self._unit("TABLET")
        gel = self._unit("GEL")
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO items (id, item_name, unit_id) VALUES (51, 'POWERGESIC', ?)",
                (tablet,),
            )
            conn.execute(
                "INSERT INTO items (id, item_name, unit_id) VALUES (920, 'POWERGESIC', ?)",
                (gel,),
            )
            conn.commit()
        finally:
            conn.close()
        from database.item_dao import ItemDAO

        self.assertEqual(ItemDAO.get_by_id(51)["unit_name"], "TABLET")
        self.assertEqual(ItemDAO.get_by_id(920)["unit_name"], "GEL")

    def test_13_constraint_is_composite_not_name_only(self):
        """The schema carries UNIQUE(item_name, unit_id), not UNIQUE(item_name)."""
        from database.connection import get_connection

        conn = get_connection()
        try:
            sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'items'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertIn("UNIQUE(item_name, unit_id)", sql)
        self.assertNotIn("NOT NULL UNIQUE", sql)


# ======================================================================
# C. edits + name_exists (no GUI required)
# ======================================================================

class CompositeUniqueEditTests(_DBBase):
    def test_20_name_exists_is_unit_aware(self):
        from database.item_dao import ItemDAO

        tablet = self._unit("TABLET")
        gel = self._unit("GEL")
        item_id = ItemDAO.insert(item_name="POWERGESIC", unit_id=tablet)
        self.assertTrue(ItemDAO.name_exists("POWERGESIC", tablet))
        self.assertFalse(ItemDAO.name_exists("POWERGESIC", gel))
        self.assertFalse(ItemDAO.name_exists("OTHER", tablet))
        self.assertFalse(
            ItemDAO.name_exists("POWERGESIC", tablet, exclude_id=item_id))
        self.assertTrue(
            ItemDAO.name_exists("POWERGESIC", tablet, exclude_id=99999))

    def test_21_update_to_conflicting_name_unit_rejected(self):
        from database.item_dao import ItemDAO

        tablet = self._unit("TABLET")
        gel = self._unit("GEL")
        ItemDAO.insert(item_name="POWERGESIC", unit_id=tablet)
        other = ItemDAO.insert(item_name="OTHER", unit_id=gel)
        with self.assertRaises(sqlite3.IntegrityError):
            ItemDAO.update(other, "POWERGESIC", unit_id=tablet)

    def test_22_update_own_record_allowed(self):
        """Saving an item unchanged (or touching other fields) works."""
        from database.item_dao import ItemDAO

        tablet = self._unit("TABLET")
        item_id = ItemDAO.insert(item_name="POWERGESIC", unit_id=tablet, mrp=10.0)
        ItemDAO.update(item_id, "POWERGESIC", unit_id=tablet, mrp=12.0)
        self.assertEqual(ItemDAO.get_by_id(item_id)["mrp"], 12.0)

    def test_23_update_name_to_new_unit_allowed(self):
        from database.item_dao import ItemDAO

        tablet = self._unit("TABLET")
        gel = self._unit("GEL")
        ItemDAO.insert(item_name="POWERGESIC", unit_id=tablet)
        other = ItemDAO.insert(item_name="OTHER", unit_id=gel)
        ItemDAO.update(other, "POWERGESIC", unit_id=gel)
        self.assertEqual(ItemDAO.get_by_id(other)["item_name"], "POWERGESIC")


# ======================================================================
# D. search / listing distinguishes duplicates (no GUI required)
# ======================================================================

class CompositeUniqueSearchTests(_DBBase):
    def test_30_search_returns_both_units(self):
        from database.item_dao import ItemDAO

        tablet = self._unit("TABLET")
        gel = self._unit("GEL")
        ItemDAO.insert(item_name="POWERGESIC", unit_id=tablet)
        ItemDAO.insert(item_name="POWERGESIC", unit_id=gel)
        hits = ItemDAO.search("POWERGESIC")
        self.assertEqual(len(hits), 2)
        self.assertEqual(
            sorted(h["unit_name"] for h in hits), ["GEL", "TABLET"])
        self.assertEqual(len({h["id"] for h in hits}), 2)

    def test_31_get_all_carries_correct_unit_per_row(self):
        """E (data level): each duplicate row displays its own unit."""
        from database.item_dao import ItemDAO

        powder = self._unit("POWDER")
        tablet = self._unit("TABLET")
        ItemDAO.insert(item_name="CALTONVIT", unit_id=tablet)
        ItemDAO.insert(item_name="CALTONVIT", unit_id=powder)
        rows = [r for r in ItemDAO.get_all() if r["item_name"] == "CALTONVIT"]
        self.assertEqual(len(rows), 2)
        unit_by_id = {r["id"]: r["unit_name"] for r in rows}
        self.assertEqual(sorted(unit_by_id.values()), ["POWDER", "TABLET"])


# ======================================================================
# E. dialog-level rule (GUI only)
# ======================================================================

@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class CompositeUniqueDialogTests(_DBBase):
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

    def _new_dialog(self):
        from screens.item_master import _ItemDialog

        dialog = _ItemDialog()
        self.addCleanup(dialog.deleteLater)
        return dialog

    def _save_named(self, name, unit_name):
        from database.item_dao import ItemDAO

        dialog = self._new_dialog()
        dialog._item_name_edit.setText(name)
        combo = dialog._unit_combo
        index = combo.findData(
            next(u["id"] for u in self._units() if u["unit_name"] == unit_name))
        self.assertGreaterEqual(index, 0, f"unit {unit_name} missing in dialog")
        combo.setCurrentIndex(index)
        dialog._on_save()
        return dialog

    def _units(self):
        from database.unit_dao import UnitDAO

        return UnitDAO.get_all()

    def test_40_dialog_allows_same_name_other_unit(self):
        from database.item_dao import ItemDAO

        self._unit("TABLET")
        self._unit("GEL")
        first = self._save_named("POWERGESIC", "TABLET")
        self.assertTrue(first.was_saved)
        second = self._save_named("POWERGESIC", "GEL")
        self.assertTrue(second.was_saved, "same name + other unit must save")
        self.assertEqual(
            len([r for r in ItemDAO.get_all() if r["item_name"] == "POWERGESIC"]), 2)

    def test_41_dialog_rejects_same_name_same_unit(self):
        from database.item_dao import ItemDAO

        self._unit("TABLET")
        self.assertTrue(self._save_named("POWERGESIC", "TABLET").was_saved)
        retry = self._save_named("POWERGESIC", "TABLET")
        self.assertFalse(retry.was_saved, "same name + same unit must be rejected")
        self.assertEqual(
            len([r for r in ItemDAO.get_all() if r["item_name"] == "POWERGESIC"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
