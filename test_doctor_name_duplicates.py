"""Doctor duplicate-name tests — doctor_name is NOT UNIQUE.

Old doctormst legitimately holds SELF twice (IDs 3 and 6, different
details); every consumer keys doctors by id.

A. two SELF records coexist
B. IDs 3 and 6 are preserved
C. search returns both
D. selecting by ID resolves the correct doctor
E. existing normal doctor behavior remains unchanged

Every test runs against a disposable temporary database.
``data/pharmacy.db`` is never used.
"""

import os
import sqlite3
import tempfile
import unittest


def _fresh_db(tag: str) -> str:
    db_path = os.path.join(tempfile.gettempdir(), f"pharmacy_doctor_{tag}.db")
    for suffix in ("", "-wal", "-shm"):
        stale = db_path + suffix
        if os.path.exists(stale):
            os.remove(stale)
    os.environ["PHARMACY_DB"] = db_path
    return db_path


class DoctorDuplicateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = _fresh_db("dup")
        from database.connection import init_database

        init_database()

    def setUp(self):
        from database.connection import get_connection

        conn = get_connection()
        conn.execute("DELETE FROM doctors")
        conn.commit()
        conn.close()

    def _self_pair(self):
        from database.doctor_dao import DoctorDAO

        first = DoctorDAO.insert("SELF", city="RAHURI")
        second = DoctorDAO.insert("SELF", city="SELF", specialty="SELF",
                                  phone_no="SELF")
        return first, second

    def test_a_two_self_records_coexist(self):
        from database.doctor_dao import DoctorDAO

        first, second = self._self_pair()
        self.assertNotEqual(first, second)
        rows = [r for r in DoctorDAO.get_all() if r["doctor_name"] == "SELF"]
        self.assertEqual(len(rows), 2)

    def test_b_ids_preserved_with_explicit_inserts(self):
        from database.connection import get_connection

        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO doctors (id, doctor_name, city) VALUES (3, 'SELF', 'RAHURI')")
            conn.execute(
                "INSERT INTO doctors (id, doctor_name, city, specialty, phone_no)"
                " VALUES (6, 'SELF', 'SELF', 'SELF', 'SELF')")
            conn.commit()
        finally:
            conn.close()
        from database.doctor_dao import DoctorDAO

        self.assertEqual(DoctorDAO.get_by_id(3)["city"], "RAHURI")
        self.assertEqual(DoctorDAO.get_by_id(6)["specialty"], "SELF")

    def test_c_search_returns_both(self):
        from database.doctor_dao import DoctorDAO

        self._self_pair()
        hits = DoctorDAO.search("SELF")
        self.assertEqual(len(hits), 2)
        self.assertEqual(len({h["id"] for h in hits}), 2)

    def test_d_select_by_id_resolves_correct_doctor(self):
        from database.doctor_dao import DoctorDAO

        first, second = self._self_pair()
        self.assertEqual(DoctorDAO.get_by_id(first)["city"], "RAHURI")
        self.assertEqual(DoctorDAO.get_by_id(second)["phone_no"], "SELF")
        self.assertNotEqual(DoctorDAO.get_by_id(first)["city"],
                            DoctorDAO.get_by_id(second)["city"])

    def test_e_normal_doctor_behavior_unchanged(self):
        from database.doctor_dao import DoctorDAO

        did = DoctorDAO.insert("DR K N GHORPADE", city="RAHURI",
                               specialty="M S ORTHO", phone_no="7588541206")
        row = DoctorDAO.get_by_id(did)
        self.assertEqual((row["doctor_name"], row["city"], row["specialty"],
                          row["phone_no"]),
                         ("DR K N GHORPADE", "RAHURI", "M S ORTHO", "7588541206"))
        self.assertTrue(DoctorDAO.name_exists("DR K N GHORPADE"))
        DoctorDAO.update(did, "DR K N GHORPADE", city="PUNE",
                         specialty="M S ORTHO", phone_no="7588541206")
        self.assertEqual(DoctorDAO.get_by_id(did)["city"], "PUNE")
        self.assertEqual(len(DoctorDAO.search("GHORPADE")), 1)

    def test_f_schema_has_no_name_unique_constraint(self):
        from database.connection import get_connection

        conn = get_connection()
        try:
            sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='doctors'"
            ).fetchone()[0]
            uniques = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='doctors'"
                " AND sql IS NOT NULL").fetchall()
        finally:
            conn.close()
        self.assertNotIn("UNIQUE", sql)
        self.assertEqual([r[0] for r in uniques], [])


class EmptyTaxPreservationTests(unittest.TestCase):
    """An untouched edit must preserve an EMPTY tax value and provenance."""

    @classmethod
    def setUpClass(cls):
        cls.db_path = _fresh_db("emptytax")
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

    def test_untouched_edit_preserves_empty_tax(self):
        from database.connection import get_connection
        from database.item_dao import ItemDAO

        conn = get_connection()
        conn.execute(
            "INSERT INTO items (item_name, tax_structure, legacy_tax_id)"
            " VALUES ('Empty Tax Item', '', 6)")
        item_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()
        # DAO-level untouched update keeps both fields.
        ItemDAO.update(item_id, "Empty Tax Item", tax_structure="",
                       reorder_stock_level=3)
        row = ItemDAO.get_by_id(item_id)
        self.assertEqual((row["tax_structure"], row["legacy_tax_id"],
                          row["reorder_stock_level"]), ("", 6, 3))
        # Explicit conversion still clears provenance.
        ItemDAO.update(item_id, "Empty Tax Item", tax_structure="5",
                       legacy_tax_id=None)
        row = ItemDAO.get_by_id(item_id)
        self.assertEqual((row["tax_structure"], row["legacy_tax_id"]), ("5", None))


HAS_PYSIDE6 = False
try:
    from PySide6.QtWidgets import QApplication, QMessageBox

    HAS_PYSIDE6 = True
except ImportError:  # pragma: no cover - environment dependent
    pass


@unittest.skipUnless(HAS_PYSIDE6, "PySide6 not available")
class EmptyTaxDialogTests(unittest.TestCase):
    """Dialog-level: saving an EMPTY-tax item untouched changes nothing."""

    @classmethod
    def setUpClass(cls):
        from database.connection import init_database
        from database import auth

        _fresh_db("emptydialog")
        init_database()
        auth.ensure_auth_schema()
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from unittest import mock

        patches = mock.patch.multiple(
            QMessageBox, warning=mock.DEFAULT, information=mock.DEFAULT,
            critical=mock.DEFAULT,
        )
        patches.start()
        self.addCleanup(patches.stop)

    def test_dialog_untouched_edit_preserves_empty_tax(self):
        from database.connection import get_connection
        from database.item_dao import ItemDAO
        from screens.item_master import _ItemDialog

        conn = get_connection()
        conn.execute("DELETE FROM items")
        conn.execute(
            "INSERT INTO items (item_name, tax_structure, legacy_tax_id)"
            " VALUES ('Dialog Empty', '', 6)")
        item_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()

        dialog = _ItemDialog(item=ItemDAO.get_by_id(item_id))
        self.addCleanup(dialog.deleteLater)
        dialog._mrp_edit.setText("99.0")
        dialog._on_save()
        self.assertTrue(dialog.was_saved)
        row = ItemDAO.get_by_id(item_id)
        self.assertEqual(row["tax_structure"], "")
        self.assertEqual(row["legacy_tax_id"], 6)
        self.assertEqual(row["mrp"], 99.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
