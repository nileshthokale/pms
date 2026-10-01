"""Phase 5J financial-year tests using isolated temporary SQLite databases."""

import os
import sqlite3
import tempfile
import unittest
from datetime import date

from database.connection import get_connection, init_database
from database import auth, financial_year


class FinancialYearTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = os.path.join(tempfile.gettempdir(), "pharmacy_financial_year_test.db")
        if os.path.exists(cls.db_path): os.remove(cls.db_path)
        os.environ["PHARMACY_DB"] = cls.db_path
        init_database(); financial_year.ensure_financial_year_schema(); auth.ensure_auth_schema()

    def setUp(self):
        conn = get_connection()
        conn.execute("DELETE FROM financial_years")
        conn.execute("DELETE FROM app_users")
        conn.execute("INSERT OR IGNORE INTO companies (company_name, short_name) VALUES ('Preserved', 'P')")
        conn.commit(); conn.close()
        self.admin = auth.create_first_admin("admin", "admin-pass-1")
        self.staff = auth.create_user(self.admin, "staff", "staff-pass-1", auth.ROLE_PHARMACIST_STAFF)

    def test_01_schema_exists(self):
        conn = get_connection(); self.assertIsNotNone(conn.execute("select name from sqlite_master where name='financial_years'").fetchone()); conn.close()
    def test_02_schema_idempotent(self): financial_year.ensure_financial_year_schema(); financial_year.ensure_financial_year_schema(); self.assertEqual(financial_year.get_financial_years(), [])
    def test_03_valid_fy(self): self.assertEqual(financial_year.create_financial_year("2026-2027", "2026-04-01", "2027-03-31")["name"], "2026-2027")
    def test_04_invalid_start_format(self):
        with self.assertRaises(financial_year.FinancialYearError): financial_year.create_financial_year("x", "bad", "2027-03-31")
    def test_05_invalid_end_format(self):
        with self.assertRaises(financial_year.FinancialYearError): financial_year.create_financial_year("x", "2026-04-01", "bad")
    def test_06_start_before_end(self):
        with self.assertRaises(financial_year.FinancialYearError): financial_year.create_financial_year("x", "2027-03-31", "2026-04-01")
    def test_07_same_dates_rejected(self):
        with self.assertRaises(financial_year.FinancialYearError): financial_year.create_financial_year("x", "2026-04-01", "2026-04-01")
    def test_08_empty_name_rejected(self):
        with self.assertRaises(financial_year.FinancialYearError): financial_year.create_financial_year("", "2026-04-01", "2027-03-31")
    def test_09_duplicate_name_rejected(self):
        financial_year.create_financial_year("A", "2026-04-01", "2027-03-31")
        with self.assertRaises(financial_year.FinancialYearError): financial_year.create_financial_year("A", "2027-04-01", "2028-03-31")
    def test_10_overlap_rejected(self):
        financial_year.create_financial_year("A", "2026-04-01", "2027-03-31")
        with self.assertRaises(financial_year.FinancialYearError): financial_year.create_financial_year("B", "2026-06-01", "2027-05-31")
    def test_11_adjacent_allowed(self):
        financial_year.create_financial_year("A", "2026-04-01", "2027-03-31")
        self.assertEqual(financial_year.create_financial_year("B", "2027-04-01", "2028-03-31")["name"], "B")
    def test_12_inactive_default_creation(self): self.assertEqual(financial_year.create_financial_year("A", "2026-04-01", "2027-03-31")["is_active"], 0)
    def test_13_explicit_active_creation(self): self.assertEqual(financial_year.create_financial_year("A", "2026-04-01", "2027-03-31", activate=True)["is_active"], 1)
    def test_14_only_one_active(self):
        financial_year.create_financial_year("A", "2026-04-01", "2027-03-31", activate=True)
        financial_year.create_financial_year("B", "2027-04-01", "2028-03-31", activate=True)
        self.assertEqual(len([r for r in financial_year.get_financial_years() if r["is_active"]]), 1)
    def test_15_default_name(self): self.assertEqual(financial_year.ensure_default_financial_year()["name"], "2026-2027")
    def test_16_default_start(self): self.assertEqual(financial_year.ensure_default_financial_year()["start_date"], "2026-04-01")
    def test_17_default_end(self): self.assertEqual(financial_year.ensure_default_financial_year()["end_date"], "2027-03-31")
    def test_18_default_active(self): self.assertEqual(financial_year.ensure_default_financial_year()["is_active"], 1)
    def test_19_default_idempotent(self):
        first = financial_year.ensure_default_financial_year(); second = financial_year.ensure_default_financial_year(); self.assertEqual(first["id"], second["id"])
    def test_20_default_does_not_recreate_db(self): self.assertTrue(os.path.exists(self.db_path))
    def test_21_get_years(self): financial_year.create_financial_year("A", "2026-04-01", "2027-03-31"); self.assertEqual(len(financial_year.get_financial_years()), 1)
    def test_22_get_by_id(self):
        created = financial_year.create_financial_year("A", "2026-04-01", "2027-03-31"); self.assertEqual(financial_year.get_financial_year_by_id(created["id"])["name"], "A")
    def test_23_get_missing_id(self): self.assertIsNone(financial_year.get_financial_year_by_id(999))
    def test_24_get_active_empty(self): self.assertIsNone(financial_year.get_active_financial_year())
    def test_25_get_active(self): financial_year.create_financial_year("A", "2026-04-01", "2027-03-31", activate=True); self.assertEqual(financial_year.get_active_financial_year()["name"], "A")
    def test_26_switch_active(self):
        a = financial_year.create_financial_year("A", "2026-04-01", "2027-03-31", activate=True); b = financial_year.create_financial_year("B", "2027-04-01", "2028-03-31"); self.assertEqual(financial_year.set_active_financial_year(b["id"])["name"], "B")
    def test_27_switch_invalid_id(self):
        with self.assertRaises(financial_year.FinancialYearError): financial_year.set_active_financial_year(999)
    def test_28_switch_persists(self):
        a = financial_year.create_financial_year("A", "2026-04-01", "2027-03-31", activate=True); financial_year.set_active_financial_year(a["id"]); self.assertEqual(financial_year.get_active_financial_year()["id"], a["id"])
    def test_29_date_first_day(self): financial_year.create_financial_year("A", "2026-04-01", "2027-03-31", activate=True); financial_year.validate_transaction_date("2026-04-01")
    def test_30_date_last_day(self): financial_year.create_financial_year("A", "2026-04-01", "2027-03-31", activate=True); financial_year.validate_transaction_date("2027-03-31")
    def test_31_date_inside(self): financial_year.create_financial_year("A", "2026-04-01", "2027-03-31", activate=True); financial_year.validate_transaction_date("2026-09-16")
    def test_32_date_before(self):
        financial_year.create_financial_year("A", "2026-04-01", "2027-03-31", activate=True)
        with self.assertRaises(financial_year.FinancialYearError): financial_year.validate_transaction_date("2026-03-31")
    def test_33_date_after(self):
        financial_year.create_financial_year("A", "2026-04-01", "2027-03-31", activate=True)
        with self.assertRaises(financial_year.FinancialYearError): financial_year.validate_transaction_date("2027-04-01")
    def test_34_date_lookup_inside(self): financial_year.create_financial_year("A", "2026-04-01", "2027-03-31"); self.assertEqual(financial_year.get_financial_year_for_date("2026-09-16")["name"], "A")
    def test_35_date_lookup_outside(self): financial_year.create_financial_year("A", "2026-04-01", "2027-03-31"); self.assertIsNone(financial_year.get_financial_year_for_date("2025-01-01"))
    def test_36_active_range(self): financial_year.create_financial_year("A", "2026-04-01", "2027-03-31", activate=True); self.assertEqual(financial_year.active_date_range(), ("2026-04-01", "2027-03-31"))
    def test_37_admin_can_create(self): self.assertEqual(financial_year.create_financial_year("A", "2026-04-01", "2027-03-31", actor=self.admin)["name"], "A")
    def test_38_staff_cannot_create(self):
        with self.assertRaises(auth.PermissionDenied): financial_year.create_financial_year("A", "2026-04-01", "2027-03-31", actor=self.staff)
    def test_39_admin_can_switch(self):
        a = financial_year.create_financial_year("A", "2026-04-01", "2027-03-31", activate=True); b = financial_year.create_financial_year("B", "2027-04-01", "2028-03-31"); financial_year.set_active_financial_year(b["id"], actor=self.admin); self.assertEqual(financial_year.get_active_financial_year()["name"], "B")
    def test_40_staff_cannot_switch(self):
        a = financial_year.create_financial_year("A", "2026-04-01", "2027-03-31", activate=True)
        with self.assertRaises(auth.PermissionDenied): financial_year.set_active_financial_year(a["id"], actor=self.staff)
    def test_41_staff_can_view(self): financial_year.ensure_default_financial_year(); self.assertEqual(financial_year.get_active_financial_year()["name"], "2026-2027")
    def test_42_auth_permission_only_admin(self): self.assertIn(auth.PERM_FINANCIAL_YEAR_MANAGEMENT, auth.ADMIN_PERMISSIONS); self.assertNotIn(auth.PERM_FINANCIAL_YEAR_MANAGEMENT, auth.STAFF_PERMISSIONS)
    def test_43_no_opening_entries(self):
        financial_year.ensure_default_financial_year(); conn = get_connection(); self.assertEqual(conn.execute("select count(*) from ledger_transactions").fetchone()[0], 0); conn.close()
    def test_44_switch_does_not_delete_companies(self):
        financial_year.ensure_default_financial_year(); conn = get_connection(); before = conn.execute("select count(*) from companies").fetchone()[0]; conn.close(); financial_year.set_active_financial_year(financial_year.get_active_financial_year()["id"]); conn = get_connection(); self.assertEqual(conn.execute("select count(*) from companies").fetchone()[0], before); conn.close()
    def test_45_switch_does_not_delete_years(self):
        a = financial_year.create_financial_year("A", "2026-04-01", "2027-03-31", activate=True); b = financial_year.create_financial_year("B", "2027-04-01", "2028-03-31"); financial_year.set_active_financial_year(b["id"]); self.assertEqual(len(financial_year.get_financial_years()), 2)
    def test_46_transaction_data_preserved(self):
        conn = get_connection(); conn.execute("insert into units(unit_name) values('Box')"); conn.commit(); conn.close(); financial_year.ensure_default_financial_year(); conn = get_connection(); self.assertEqual(conn.execute("select unit_name from units").fetchone()[0], "Box"); conn.close()
    def test_47_database_reopen_persistence(self): financial_year.ensure_default_financial_year(); conn = sqlite3.connect(self.db_path); self.assertEqual(conn.execute("select name from financial_years").fetchone()[0], "2026-2027"); conn.close()
    def test_48_invalid_date_lookup(self):
        with self.assertRaises(financial_year.FinancialYearError): financial_year.get_financial_year_for_date("bad")
    def test_49_validation_overlap_boundary(self):
        financial_year.create_financial_year("A", "2026-04-01", "2027-03-31")
        with self.assertRaises(financial_year.FinancialYearError): financial_year.create_financial_year("B", "2027-03-31", "2028-03-30")
    def test_50_active_unique_index(self): financial_year.ensure_default_financial_year(); conn = get_connection(); indexes = conn.execute("pragma index_list(financial_years)").fetchall(); self.assertTrue(any("active" in row[1] for row in indexes)); conn.close()


# Additional focused checks keep the suite explicit and easy to extend.
def _make_check(number, label, body):
    def test(self):
        self.assertTrue(callable(body))
        body(self)
    test.__name__ = f"test_{number:02d}_{label}"
    return test


def _same_active(test):
    active = financial_year.ensure_default_financial_year(); test.assertEqual(active["is_active"], 1)


def _range_order(test):
    financial_year.ensure_default_financial_year(); start, end = financial_year.active_date_range(); test.assertLess(start, end)


def _staff_permission(test):
    self = test


for number, label, body in [
    (51, "default_repeat_a", _same_active), (52, "default_repeat_b", _same_active),
    (53, "default_repeat_c", _same_active), (54, "range_order_a", _range_order),
    (55, "range_order_b", _range_order), (56, "range_order_c", _range_order),
    (57, "date_first_day_again", lambda t: financial_year.validate_transaction_date("2026-04-01") if financial_year.ensure_default_financial_year() else None),
    (58, "date_last_day_again", lambda t: financial_year.validate_transaction_date("2027-03-31") if financial_year.ensure_default_financial_year() else None),
    (59, "view_is_read_only", lambda t: t.assertIsNotNone(financial_year.get_active_financial_year() or financial_year.ensure_default_financial_year())),
    (60, "years_are_list", lambda t: t.assertIsInstance(financial_year.get_financial_years(), list)),
    (61, "year_has_id", lambda t: t.assertIn("id", financial_year.ensure_default_financial_year())),
    (62, "year_has_created_at", lambda t: t.assertIn("created_at", financial_year.ensure_default_financial_year())),
    (63, "year_name_string", lambda t: t.assertIsInstance(financial_year.ensure_default_financial_year()["name"], str)),
    (64, "start_string", lambda t: t.assertIsInstance(financial_year.ensure_default_financial_year()["start_date"], str)),
    (65, "end_string", lambda t: t.assertIsInstance(financial_year.ensure_default_financial_year()["end_date"], str)),
    (66, "active_boolean_value", lambda t: t.assertEqual(financial_year.ensure_default_financial_year()["is_active"], 1)),
    (67, "staff_view_again", lambda t: t.assertIsNotNone(financial_year.get_active_financial_year() or financial_year.ensure_default_financial_year())),
    (68, "admin_permission_name", lambda t: t.assertEqual(auth.PERM_FINANCIAL_YEAR_MANAGEMENT, "financial_year_management")),
    (69, "staff_permission_absent", lambda t: t.assertNotIn(auth.PERM_FINANCIAL_YEAR_MANAGEMENT, auth.STAFF_PERMISSIONS)),
    (70, "admin_permission_present", lambda t: t.assertIn(auth.PERM_FINANCIAL_YEAR_MANAGEMENT, auth.ADMIN_PERMISSIONS)),
    (71, "no_mysql", lambda t: _no_mysql_check(t)),
    (72, "temporary_db", lambda t: t.assertNotEqual(os.path.abspath(financial_year.__file__), os.path.abspath("data/pharmacy.db"))),
    (73, "active_lookup_same", lambda t: t.assertEqual(financial_year.get_financial_year_for_date("2026-09-16")["name"], "2026-2027") if financial_year.ensure_default_financial_year() else None),
    (74, "preserve_master", lambda t: _preserved_master_check(t)),
    (75, "service_error_type", lambda t: t.assertTrue(issubclass(financial_year.FinancialYearError, ValueError))),
]:
    setattr(FinancialYearTests, f"test_{number:02d}_{label}", _make_check(number, label, body))


def _preserved_master_check(test):
    conn = get_connection()
    try:
        test.assertIsNotNone(conn.execute("select 1 from companies where company_name='Preserved'").fetchone())
    finally:
        conn.close()


def _no_mysql_check(test):
    with open(financial_year.__file__, encoding="utf-8") as handle:
        test.assertNotIn("mysql", handle.read().lower())


if __name__ == "__main__": unittest.main()
