"""Phase 5I authentication tests; all data uses a temporary SQLite database."""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from database.connection import get_connection, init_database
from database import auth


class AuthenticationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = os.path.join(tempfile.gettempdir(), "pharmacy_auth_test.db")
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)
        os.environ["PHARMACY_DB"] = cls.db_path
        init_database()
        auth.ensure_auth_schema()

    def setUp(self):
        conn = get_connection()
        conn.execute("DELETE FROM auth_audit_log")
        conn.execute("DELETE FROM app_users")
        conn.execute("INSERT OR IGNORE INTO companies (company_name, short_name) VALUES ('Preserved', 'P')")
        conn.commit(); conn.close()
        self.admin = auth.create_first_admin("admin", "admin-pass-1")
        self.session = auth.AuthSession(); self.assertTrue(self.session.login("admin", "admin-pass-1"))
        self.staff = auth.create_user(self.admin, "staff", "staff-pass-1", auth.ROLE_PHARMACIST_STAFF)

    def test_01_roles_exact(self): self.assertEqual(auth.USER_ROLES, ("ADMIN", "PHARMACIST/STAFF"))
    def test_02_permission_map_exact_roles(self): self.assertEqual(set(auth.PERMISSIONS), set(auth.USER_ROLES))
    def test_03_admin_role_constant(self): self.assertEqual(auth.ROLE_ADMIN, "ADMIN")
    def test_04_staff_role_constant(self): self.assertEqual(auth.ROLE_PHARMACIST_STAFF, "PHARMACIST/STAFF")
    def test_05_no_forbidden_role_text_in_service(self):
        source = Path(auth.__file__).read_text(encoding="utf-8")
        self.assertNotIn("MANAGER", source); self.assertNotIn("VIEWER", source)
    def test_06_no_extra_roles(self): self.assertEqual(len(auth.USER_ROLES), 2)
    def test_07_password_hash_not_plaintext(self):
        encoded = auth.hash_password("secret-123")
        self.assertNotEqual(encoded, "secret-123"); self.assertIn("pbkdf2_sha256", encoded)
    def test_08_password_hash_salted(self): self.assertNotEqual(auth.hash_password("secret-123"), auth.hash_password("secret-123"))
    def test_09_password_verify_true(self):
        encoded = auth.hash_password("secret-123"); self.assertTrue(auth.verify_password("secret-123", encoded))
    def test_10_password_verify_false(self):
        encoded = auth.hash_password("secret-123"); self.assertFalse(auth.verify_password("wrong-123", encoded))
    def test_11_short_password_rejected(self):
        with self.assertRaises(auth.AuthenticationError): auth.hash_password("short")
    def test_12_malformed_hash_rejected(self): self.assertFalse(auth.verify_password("anything", "bad"))
    def test_13_first_admin_created(self): self.assertEqual(self.admin["role"], auth.ROLE_ADMIN)
    def test_14_first_admin_active(self): self.assertEqual(self.admin["is_active"], 1)
    def test_15_first_admin_only_once(self):
        with self.assertRaises(auth.AuthenticationError): auth.create_first_admin("second", "password-2")
    def test_16_first_admin_password_hashed(self): self.assertNotEqual(auth.get_user("admin")["password_hash"], "admin-pass-1")
    def test_17_username_required_first_admin(self):
        with self.assertRaises(auth.AuthenticationError): auth.create_first_admin("", "password-1")
    def test_18_first_admin_preserves_existing_data(self):
        conn = get_connection(); self.assertEqual(conn.execute("select company_name from companies where company_name='Preserved'").fetchone()[0], "Preserved"); conn.close()
    def test_19_schema_idempotent(self): auth.ensure_auth_schema(); auth.ensure_auth_schema(); self.assertEqual(auth.user_count(), 2)
    def test_20_login_success(self): self.assertTrue(self.session.user["username"] == "admin")
    def test_21_login_wrong_password(self):
        session = auth.AuthSession(); self.assertFalse(session.login("admin", "wrong-pass")); self.assertIsNone(session.user)
    def test_22_login_unknown_user(self):
        session = auth.AuthSession(); self.assertFalse(session.login("missing", "wrong-pass"))
    def test_23_login_case_insensitive_username(self):
        session = auth.AuthSession(); self.assertTrue(session.login("ADMIN", "admin-pass-1"))
    def test_24_logout_clears_session(self): self.session.logout(); self.assertIsNone(self.session.user)
    def test_25_logout_audited(self): self.session.logout(); self.assertEqual(auth.get_audit_log()[0]["action"], "logout")
    def test_26_login_success_audited(self): self.assertTrue(any(row["action"] == "login" and row["success"] for row in auth.get_audit_log()))
    def test_27_login_failure_audited(self):
        auth.authenticate("admin", "wrong-pass"); self.assertTrue(any(row["action"] == "login" and not row["success"] for row in auth.get_audit_log()))
    def test_28_staff_login(self):
        session = auth.AuthSession(); self.assertTrue(session.login("staff", "staff-pass-1")); self.assertEqual(session.user["role"], auth.ROLE_PHARMACIST_STAFF)
    def test_29_admin_all_operational(self):
        for permission in auth.STAFF_PERMISSIONS: self.assertTrue(auth.has_permission(self.admin, permission))
    def test_30_admin_edit(self): self.assertTrue(auth.has_permission(self.admin, auth.PERM_EDIT_TRANSACTIONS))
    def test_31_admin_delete(self): self.assertTrue(auth.has_permission(self.admin, auth.PERM_DELETE_TRANSACTIONS))
    def test_32_admin_import(self): self.assertTrue(auth.has_permission(self.admin, auth.PERM_IMPORT_DATA))
    def test_33_admin_backup(self): self.assertTrue(auth.has_permission(self.admin, auth.PERM_BACKUP))
    def test_34_admin_restore(self): self.assertTrue(auth.has_permission(self.admin, auth.PERM_RESTORE))
    def test_35_admin_users(self): self.assertTrue(auth.has_permission(self.admin, auth.PERM_USER_MANAGEMENT))
    def test_36_admin_security(self): self.assertTrue(auth.has_permission(self.admin, auth.PERM_SECURITY_AUDIT))
    def test_37_staff_masters(self): self.assertTrue(auth.has_permission(self.staff, auth.PERM_VIEW_MASTERS))
    def test_38_staff_purchase(self): self.assertTrue(auth.has_permission(self.staff, auth.PERM_PURCHASE))
    def test_39_staff_sales(self): self.assertTrue(auth.has_permission(self.staff, auth.PERM_SALES))
    def test_40_staff_counter_sale(self): self.assertTrue(auth.has_permission(self.staff, auth.PERM_COUNTER_SALE))
    def test_41_staff_credit_note(self): self.assertTrue(auth.has_permission(self.staff, auth.PERM_CREDIT_NOTE))
    def test_42_staff_debit_note(self): self.assertTrue(auth.has_permission(self.staff, auth.PERM_DEBIT_NOTE))
    def test_43_staff_receipt(self): self.assertTrue(auth.has_permission(self.staff, auth.PERM_CUSTOMER_RECEIPT))
    def test_44_staff_payment(self): self.assertTrue(auth.has_permission(self.staff, auth.PERM_SUPPLIER_PAYMENT))
    def test_45_staff_reports(self): self.assertTrue(auth.has_permission(self.staff, auth.PERM_REPORTS))
    def test_46_staff_print(self): self.assertTrue(auth.has_permission(self.staff, auth.PERM_PRINT_PDF))
    def test_47_staff_no_edit(self): self.assertFalse(auth.has_permission(self.staff, auth.PERM_EDIT_TRANSACTIONS))
    def test_48_staff_no_delete(self): self.assertFalse(auth.has_permission(self.staff, auth.PERM_DELETE_TRANSACTIONS))
    def test_49_staff_no_import(self): self.assertFalse(auth.has_permission(self.staff, auth.PERM_IMPORT_DATA))
    def test_50_staff_no_backup(self): self.assertFalse(auth.has_permission(self.staff, auth.PERM_BACKUP))
    def test_51_staff_no_restore(self): self.assertFalse(auth.has_permission(self.staff, auth.PERM_RESTORE))
    def test_52_staff_no_users(self): self.assertFalse(auth.has_permission(self.staff, auth.PERM_USER_MANAGEMENT))
    def test_53_staff_no_roles(self): self.assertFalse(auth.has_permission(self.staff, auth.PERM_ROLE_ADMINISTRATION))
    def test_54_staff_no_security(self): self.assertFalse(auth.has_permission(self.staff, auth.PERM_SECURITY_AUDIT))
    def test_55_staff_no_reset(self): self.assertFalse(auth.has_permission(self.staff, auth.PERM_PASSWORD_RESET_OTHERS))
    def test_56_staff_no_deactivate(self): self.assertFalse(auth.has_permission(self.staff, auth.PERM_DEACTIVATE_USERS))
    def test_57_require_allows_admin(self): self.session.require(auth.PERM_USER_MANAGEMENT)
    def test_58_require_denies_staff(self):
        session = auth.AuthSession(); session.user = self.staff
        with self.assertRaises(auth.PermissionDenied): session.require(auth.PERM_USER_MANAGEMENT)
    def test_59_create_user_admin_only(self):
        created = auth.create_user(self.admin, "staff2", "staff-pass-2", auth.ROLE_PHARMACIST_STAFF); self.assertEqual(created["role"], auth.ROLE_PHARMACIST_STAFF)
    def test_60_create_user_staff_denied(self):
        with self.assertRaises(auth.PermissionDenied): auth.create_user(self.staff, "other", "password-2", auth.ROLE_ADMIN)
    def test_61_create_user_invalid_role_denied(self):
        with self.assertRaises(auth.AuthenticationError): auth.create_user(self.admin, "other", "password-2", "INVALID")
    def test_62_create_user_duplicate_denied(self):
        with self.assertRaises(auth.AuthenticationError): auth.create_user(self.admin, "staff", "password-2", auth.ROLE_PHARMACIST_STAFF)
    def test_63_change_role_to_admin(self): auth.change_role(self.admin, self.staff["id"], auth.ROLE_ADMIN); self.assertEqual(auth.get_user("staff")["role"], auth.ROLE_ADMIN)
    def test_64_change_role_to_staff(self):
        created = auth.create_user(self.admin, "admin2", "admin-pass-2", auth.ROLE_ADMIN); auth.change_role(self.admin, created["id"], auth.ROLE_PHARMACIST_STAFF); self.assertEqual(auth.get_user("admin2")["role"], auth.ROLE_PHARMACIST_STAFF)
    def test_65_staff_cannot_change_role(self):
        with self.assertRaises(auth.PermissionDenied): auth.change_role(self.staff, self.admin["id"], auth.ROLE_PHARMACIST_STAFF)
    def test_66_invalid_role_change_denied(self):
        with self.assertRaises(auth.AuthenticationError): auth.change_role(self.admin, self.staff["id"], "INVALID")
    def test_67_deactivate_staff(self): auth.set_user_active(self.admin, self.staff["id"], False); self.assertEqual(auth.get_user("staff")["is_active"], 0)
    def test_68_inactive_staff_cannot_login(self): auth.set_user_active(self.admin, self.staff["id"], False); self.assertIsNone(auth.authenticate("staff", "staff-pass-1"))
    def test_69_staff_cannot_deactivate(self):
        with self.assertRaises(auth.PermissionDenied): auth.set_user_active(self.staff, self.admin["id"], False)
    def test_70_last_admin_cannot_deactivate(self):
        with self.assertRaises(auth.AuthenticationError): auth.set_user_active(self.admin, self.admin["id"], False)
    def test_71_last_admin_cannot_demote(self):
        with self.assertRaises(auth.AuthenticationError): auth.change_role(self.admin, self.admin["id"], auth.ROLE_PHARMACIST_STAFF)
    def test_72_second_admin_can_be_deactivated(self):
        second = auth.create_user(self.admin, "admin2", "admin-pass-2", auth.ROLE_ADMIN); auth.set_user_active(self.admin, second["id"], False); self.assertEqual(auth.active_admin_count(), 1)
    def test_73_last_admin_protection_after_second_removed(self):
        second = auth.create_user(self.admin, "admin2", "admin-pass-2", auth.ROLE_ADMIN); auth.set_user_active(self.admin, second["id"], False)
        with self.assertRaises(auth.AuthenticationError): auth.change_role(self.admin, self.admin["id"], auth.ROLE_PHARMACIST_STAFF)
    def test_74_reset_password_admin(self):
        auth.reset_password(self.admin, self.staff["id"], "new-staff-pass"); self.assertIsNotNone(auth.authenticate("staff", "new-staff-pass"))
    def test_75_reset_password_staff_denied(self):
        with self.assertRaises(auth.PermissionDenied): auth.reset_password(self.staff, self.admin["id"], "new-pass-123")
    def test_76_reset_short_password_rejected(self):
        with self.assertRaises(auth.AuthenticationError): auth.reset_password(self.admin, self.staff["id"], "short")
    def test_77_list_users(self): self.assertEqual({row["username"] for row in auth.list_users()}, {"admin", "staff"})
    def test_78_user_count(self): self.assertEqual(auth.user_count(), 2)
    def test_79_active_admin_count(self): self.assertEqual(auth.active_admin_count(), 1)
    def test_80_audit_user_created(self): self.assertTrue(any(row["action"] == "user_created" for row in auth.get_audit_log()))
    def test_81_audit_role_changed(self): auth.change_role(self.admin, self.staff["id"], auth.ROLE_ADMIN); self.assertTrue(any(row["action"] == "role_changed" for row in auth.get_audit_log()))
    def test_82_audit_deactivation(self): auth.set_user_active(self.admin, self.staff["id"], False); self.assertTrue(any(row["action"] == "user_activation_changed" for row in auth.get_audit_log()))
    def test_83_audit_password_reset(self): auth.reset_password(self.admin, self.staff["id"], "reset-pass-1"); self.assertTrue(any(row["action"] == "password_reset" for row in auth.get_audit_log()))
    def test_84_existing_data_preserved_after_auth(self):
        conn = sqlite3.connect(self.db_path); self.assertEqual(conn.execute("select company_name from companies where company_name='Preserved'").fetchone()[0], "Preserved"); conn.close()


if __name__ == "__main__": unittest.main()
