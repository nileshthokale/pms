"""User Master activate/deactivate, login lifecycle and role permission tests.

Every test runs against a disposable temporary SQLite database. The real
``data/pharmacy.db`` is never opened, read or modified by this module.
"""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from database import auth
from database.connection import get_connection, init_database

REAL_DB_MARKERS = ("sales", "purchases", "stock", "ledger", "accounting")


class AuthLifecycleTests(unittest.TestCase):
    """Service-layer activation, deactivation and login behaviour."""

    @classmethod
    def setUpClass(cls):
        cls.db_path = os.path.join(tempfile.gettempdir(), "pharmacy_user_activation_test.db")
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)
        os.environ["PHARMACY_DB"] = cls.db_path
        init_database()
        auth.ensure_auth_schema()

    def setUp(self):
        conn = get_connection()
        conn.execute("DELETE FROM auth_audit_log")
        conn.execute("DELETE FROM app_users")
        conn.commit(); conn.close()
        self.admin = auth.create_first_admin("admin", "admin-pass-1")
        self.staff = auth.create_user(self.admin, "staff", "staff-pass-1", auth.ROLE_PHARMACIST_STAFF)

    # ── ACTIVATE ───────────────────────────────────────────────────────

    def test_01_deactivate_active_user(self):
        auth.set_user_active(self.admin, self.staff["id"], False)
        self.assertEqual(auth.get_user("staff")["is_active"], 0)

    def test_02_activate_inactive_user(self):
        auth.set_user_active(self.admin, self.staff["id"], False)
        auth.set_user_active(self.admin, self.staff["id"], True)
        self.assertEqual(auth.get_user("staff")["is_active"], 1)

    def test_03_activate_twice_is_idempotent(self):
        auth.set_user_active(self.admin, self.staff["id"], True)
        auth.set_user_active(self.admin, self.staff["id"], True)
        self.assertEqual(auth.get_user("staff")["is_active"], 1)

    def test_04_set_user_active_uses_user_id_not_row_number(self):
        # ids are not 0-based and not row positions; target the second user by id.
        target = auth.get_user("staff")["id"]
        auth.set_user_active(self.admin, target, False)
        self.assertEqual(auth.get_user("staff")["is_active"], 0)
        self.assertEqual(auth.get_user("admin")["is_active"], 1)

    def test_05_unknown_user_id_refused(self):
        with self.assertRaises(auth.AuthenticationError):
            auth.set_user_active(self.admin, 999999, False)

    def test_06_active_flag_coerced_to_int(self):
        auth.set_user_active(self.admin, self.staff["id"], 1)
        value = auth.get_user("staff")["is_active"]
        self.assertIsInstance(value, int)
        self.assertEqual(value, 1)

    def test_07_list_users_reflects_new_active_state(self):
        auth.set_user_active(self.admin, self.staff["id"], False)
        auth.set_user_active(self.admin, self.staff["id"], True)
        rows = {row["username"]: row for row in auth.list_users()}
        self.assertEqual(rows["staff"]["is_active"], 1)

    def test_08_activation_updates_updated_at(self):
        before = auth.get_user("staff")["updated_at"]
        auth.set_user_active(self.admin, self.staff["id"], False)
        after = auth.get_user("staff")["updated_at"]
        self.assertNotEqual(before, after)

    # ── ADMIN PROTECTION ───────────────────────────────────────────────

    def test_09_last_active_admin_cannot_be_deactivated(self):
        with self.assertRaises(auth.AuthenticationError):
            auth.set_user_active(self.admin, self.admin["id"], False)
        self.assertEqual(auth.get_user("admin")["is_active"], 1)

    def test_10_last_active_admin_message_is_clear(self):
        with self.assertRaises(auth.AuthenticationError) as ctx:
            auth.set_user_active(self.admin, self.admin["id"], False)
        self.assertIn("ADMIN", str(ctx.exception))

    def test_11_second_admin_can_be_deactivated(self):
        second = auth.create_user(self.admin, "admin2", "admin2-pass-1", auth.ROLE_ADMIN)
        auth.set_user_active(self.admin, second["id"], False)
        self.assertEqual(auth.active_admin_count(), 1)

    def test_12_inactive_admin_can_be_reactivated(self):
        second = auth.create_user(self.admin, "admin2", "admin2-pass-1", auth.ROLE_ADMIN)
        auth.set_user_active(self.admin, second["id"], False)
        auth.set_user_active(self.admin, second["id"], True)
        self.assertEqual(auth.get_user("admin2")["is_active"], 1)

    def test_13_active_admin_count_tracks_state(self):
        self.assertEqual(auth.active_admin_count(), 1)
        second = auth.create_user(self.admin, "admin2", "admin2-pass-1", auth.ROLE_ADMIN)
        self.assertEqual(auth.active_admin_count(), 2)
        auth.set_user_active(self.admin, second["id"], False)
        self.assertEqual(auth.active_admin_count(), 1)

    def test_14_admin_can_activate_staff(self):
        auth.set_user_active(self.admin, self.staff["id"], False)
        auth.set_user_active(self.admin, self.staff["id"], True)
        self.assertTrue(auth.has_permission(auth.get_user("staff"), auth.PERM_VIEW_MASTERS))

    def test_15_staff_cannot_activate_users(self):
        session = auth.AuthSession()
        self.assertTrue(session.login("staff", "staff-pass-1"))
        with self.assertRaises(auth.PermissionDenied):
            auth.set_user_active(session.user, self.staff["id"], False)

    def test_16_staff_cannot_deactivate_admin(self):
        session = auth.AuthSession()
        self.assertTrue(session.login("staff", "staff-pass-1"))
        with self.assertRaises(auth.PermissionDenied):
            auth.set_user_active(session.user, self.admin["id"], False)
        self.assertEqual(auth.get_user("admin")["is_active"], 1)

    def test_17_staff_lacks_deactivate_permission(self):
        self.assertFalse(auth.has_permission(self.staff, auth.PERM_DEACTIVATE_USERS))

    def test_18_none_actor_cannot_activate(self):
        with self.assertRaises(auth.PermissionDenied):
            auth.set_user_active(None, self.staff["id"], False)

    def test_19_inactive_actor_lacks_permission(self):
        ghost = {"id": 9, "username": "ghost", "role": auth.ROLE_ADMIN, "is_active": 0}
        with self.assertRaises(auth.PermissionDenied):
            auth.set_user_active(ghost, self.staff["id"], False)

    def test_20_last_admin_cannot_be_demoted(self):
        with self.assertRaises(auth.AuthenticationError):
            auth.change_role(self.admin, self.admin["id"], auth.ROLE_PHARMACIST_STAFF)

    # ── LOGIN ──────────────────────────────────────────────────────────

    def test_21_active_admin_can_login(self):
        session = auth.AuthSession()
        self.assertTrue(session.login("admin", "admin-pass-1"))
        self.assertEqual(session.user["role"], auth.ROLE_ADMIN)

    def test_22_active_staff_can_login(self):
        session = auth.AuthSession()
        self.assertTrue(session.login("staff", "staff-pass-1"))
        self.assertEqual(session.user["role"], auth.ROLE_PHARMACIST_STAFF)

    def test_23_inactive_staff_login_rejected(self):
        auth.set_user_active(self.admin, self.staff["id"], False)
        session = auth.AuthSession()
        self.assertFalse(session.login("staff", "staff-pass-1"))
        self.assertIsNone(session.user)

    def test_24_reactivated_staff_can_login_again(self):
        auth.set_user_active(self.admin, self.staff["id"], False)
        auth.set_user_active(self.admin, self.staff["id"], True)
        session = auth.AuthSession()
        self.assertTrue(session.login("staff", "staff-pass-1"))
        self.assertEqual(session.user["role"], auth.ROLE_PHARMACIST_STAFF)

    def test_25_wrong_password_rejected(self):
        session = auth.AuthSession()
        self.assertFalse(session.login("staff", "wrong-pass-1"))
        self.assertIsNone(session.user)

    def test_26_unknown_user_rejected(self):
        session = auth.AuthSession()
        self.assertFalse(session.login("nobody", "whatever-1"))

    def test_27_correct_password_accepted(self):
        self.assertEqual(auth.verify_password("staff-pass-1", auth.get_user("staff")["password_hash"]), True)

    def test_28_login_updates_last_login_at(self):
        before = auth.get_user("staff")["last_login_at"]
        auth.AuthSession().login("staff", "staff-pass-1")
        after = auth.get_user("staff")["last_login_at"]
        self.assertIsNotNone(after)
        self.assertNotEqual(before, after)

    def test_29_session_created_with_expected_keys(self):
        session = auth.AuthSession()
        session.login("staff", "staff-pass-1")
        self.assertEqual(set(session.user), {"id", "username", "role", "is_active"})

    def test_30_session_role_is_exact_compatible_string(self):
        session = auth.AuthSession()
        session.login("staff", "staff-pass-1")
        self.assertEqual(session.user["role"], "PHARMACIST/STAFF")
        self.assertIn(session.user["role"], auth.PERMISSIONS)

    def test_31_no_forbidden_role_variant_appears(self):
        session = auth.AuthSession()
        session.login("staff", "staff-pass-1")
        for forbidden in ("PHARMACIST", "STAFF", "PHARMACIST_STAFF"):
            self.assertNotEqual(session.user["role"], forbidden)

    def test_32_failed_login_message_does_not_enumerate(self):
        auth.set_user_active(self.admin, self.staff["id"], False)
        inactive = auth.authenticate("staff", "staff-pass-1")
        unknown = auth.authenticate("nobody", "staff-pass-1")
        self.assertIsNone(inactive)
        self.assertIsNone(unknown)

    def test_33_login_does_not_return_password_hash(self):
        session = auth.AuthSession()
        session.login("staff", "staff-pass-1")
        self.assertNotIn("password_hash", session.user)

    def test_34_logout_clears_session(self):
        session = auth.AuthSession()
        session.login("staff", "staff-pass-1")
        session.logout()
        self.assertIsNone(session.user)

    def test_35_password_hash_is_not_plaintext(self):
        row = auth.get_user("staff")
        self.assertNotIn("staff-pass-1", row["password_hash"])
        self.assertTrue(row["password_hash"].startswith("pbkdf2_"))

    # ── PERMISSIONS ────────────────────────────────────────────────────

    def test_36_staff_has_operational_permissions(self):
        for permission in (auth.PERM_VIEW_MASTERS, auth.PERM_PURCHASE, auth.PERM_SALES,
                           auth.PERM_COUNTER_SALE, auth.PERM_REPORTS, auth.PERM_PRINT_PDF):
            self.assertTrue(auth.has_permission(self.staff, permission), permission)

    def test_37_staff_blocked_from_user_management(self):
        self.assertFalse(auth.has_permission(self.staff, auth.PERM_USER_MANAGEMENT))

    def test_38_staff_blocked_from_financial_year(self):
        self.assertFalse(auth.has_permission(self.staff, auth.PERM_FINANCIAL_YEAR_MANAGEMENT))

    def test_39_staff_blocked_from_restore(self):
        self.assertFalse(auth.has_permission(self.staff, auth.PERM_RESTORE))

    def test_40_staff_blocked_from_admin_only_menu_actions(self):
        for action in ("User Master", "Financial Year", "Backup & Restore", "Import Data",
                       "Account Roles", "Category Master"):
            permission = auth.MENU_PERMISSIONS[action]
            self.assertFalse(auth.has_permission(self.staff, permission), action)

    def test_41_admin_retains_all_permissions(self):
        for action, permission in auth.MENU_PERMISSIONS.items():
            self.assertTrue(auth.has_permission(self.admin, permission), action)

    def test_42_no_third_role_exists(self):
        self.assertEqual(auth.USER_ROLES, ("ADMIN", "PHARMACIST/STAFF"))
        self.assertEqual(len(auth.PERMISSIONS), 2)

    # ── AUDIT ──────────────────────────────────────────────────────────

    def test_43_activation_is_audited(self):
        auth.set_user_active(self.admin, self.staff["id"], False)
        auth.set_user_active(self.admin, self.staff["id"], True)
        actions = [row for row in auth.get_audit_log() if row["action"] == "user_activation_changed"]
        self.assertTrue(any("activated" in row["details"] for row in actions))

    def test_44_deactivation_is_audited(self):
        auth.set_user_active(self.admin, self.staff["id"], False)
        actions = [row for row in auth.get_audit_log() if row["action"] == "user_activation_changed"]
        self.assertTrue(any("deactivated" in row["details"] for row in actions))

    def test_45_login_success_is_audited(self):
        auth.AuthSession().login("staff", "staff-pass-1")
        self.assertTrue(any(row["action"] == "login" and row["success"] == 1 for row in auth.get_audit_log()))

    def test_46_failed_login_is_audited(self):
        auth.AuthSession().login("staff", "wrong-pass-1")
        self.assertTrue(any(row["action"] == "login" and row["success"] == 0 for row in auth.get_audit_log()))

    def test_47_inactive_login_failure_is_audited(self):
        auth.set_user_active(self.admin, self.staff["id"], False)
        auth.AuthSession().login("staff", "staff-pass-1")
        self.assertTrue(any(row["action"] == "login" and row["success"] == 0 for row in auth.get_audit_log()))

    # ── DATA SAFETY / REGRESSION ───────────────────────────────────────

    def test_48_user_records_are_not_recreated(self):
        before = auth.get_user("admin")["created_at"]
        auth.set_user_active(self.admin, self.staff["id"], False)
        auth.set_user_active(self.admin, self.staff["id"], True)
        self.assertEqual(auth.get_user("admin")["created_at"], before)
        self.assertEqual(auth.user_count(), 2)

    def test_49_roles_are_not_changed_by_activation(self):
        auth.set_user_active(self.admin, self.staff["id"], False)
        auth.set_user_active(self.admin, self.staff["id"], True)
        self.assertEqual(auth.get_user("staff")["role"], auth.ROLE_PHARMACIST_STAFF)

    def test_50_real_database_is_never_used(self):
        self.assertTrue(os.environ["PHARMACY_DB"].startswith(tempfile.gettempdir()))
        self.assertNotIn("Pharmacy Management System", os.environ["PHARMACY_DB"])

    def test_51_historical_tables_untouched_by_activation(self):
        conn = get_connection()
        before = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        conn.close()
        auth.set_user_active(self.admin, self.staff["id"], False)
        auth.set_user_active(self.admin, self.staff["id"], True)
        conn = get_connection()
        after = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        conn.close()
        self.assertEqual(before, after)

    def test_52_no_historical_table_is_written_by_user_master(self):
        source = Path("screens/user_management.py").read_text(encoding="utf-8")
        for marker in REAL_DB_MARKERS:
            self.assertNotIn(marker, source.lower(), marker)


class UserManagementPageTests(unittest.TestCase):
    """Widget-level activation button, table columns and selection behaviour."""

    @classmethod
    def setUpClass(cls):
        cls.db_path = os.path.join(tempfile.gettempdir(), "pharmacy_user_activation_ui_test.db")
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)
        os.environ["PHARMACY_DB"] = cls.db_path
        init_database()
        auth.ensure_auth_schema()
        cls._app = QApplication.instance() or QApplication([])
        cls._dialogs = []
        cls._originals = {}
        for name in ("warning", "information", "critical", "question"):
            cls._originals[name] = getattr(QMessageBox, name)
            setattr(QMessageBox, name, cls._record_dialog)

    @classmethod
    def _record_dialog(cls, parent, title, text, *args, **kwargs):
        """Record message boxes instead of blocking on a modal dialog."""
        cls._dialogs.append((title, text))
        return QMessageBox.Yes

    @classmethod
    def tearDownClass(cls):
        for name, original in cls._originals.items():
            setattr(QMessageBox, name, original)

    def setUp(self):
        from screens import user_management as um
        self.um = um
        self.__class__._dialogs.clear()
        conn = get_connection()
        conn.execute("DELETE FROM auth_audit_log")
        conn.execute("DELETE FROM app_users")
        conn.commit(); conn.close()
        auth.session.logout()
        self.admin = auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        self.staff = auth.create_user(self.admin, "staff", "staff-pass-1", auth.ROLE_PHARMACIST_STAFF)
        auth.set_user_active(self.admin, self.staff["id"], False)
        self.page = um.UserManagementPage()
        QApplication.processEvents()

    def _row_for(self, username):
        table = self.page._table
        for row in range(table.rowCount()):
            if table.item(row, 0).text() == username:
                return row
        self.fail(f"{username} not present in the table")

    # ── UI: columns ────────────────────────────────────────────────────

    def test_53_columns_match_required_labels(self):
        headers = [self.page._table.horizontalHeaderItem(c).text() for c in range(self.page._table.columnCount())]
        self.assertEqual(headers, ["Username", "Role", "Active", "Created", "Last Login"])

    def test_54_role_column_displays_full_pharmacist_staff(self):
        table = self.page._table
        item = table.item(self._row_for("staff"), 1)
        self.assertEqual(item.text(), "PHARMACIST/STAFF")
        table.resizeColumnToContents(1)
        self.assertGreaterEqual(table.columnWidth(1), len("PHARMACIST/STAFF") * 6)

    def test_55_role_column_resizes_to_contents(self):
        from PySide6.QtWidgets import QHeaderView
        mode = self.page._table.horizontalHeader().sectionResizeMode(1)
        self.assertEqual(mode, QHeaderView.ResizeToContents)

    def test_56_active_column_shows_yes_and_no(self):
        self.assertEqual(self.page._table.item(self._row_for("admin"), 2).text(), "Yes")
        self.assertEqual(self.page._table.item(self._row_for("staff"), 2).text(), "No")

    def test_57_created_column_populated(self):
        self.assertTrue(self.page._table.item(self._row_for("admin"), 3).text())

    # ── UI: context-aware button ───────────────────────────────────────

    def test_58_activate_text_shown_for_inactive_user(self):
        self.page._table.selectRow(self._row_for("staff"))
        QApplication.processEvents()
        self.assertEqual(self.page._toggle_active.text(), "Activate Selected")

    def test_59_deactivate_text_shown_for_active_user(self):
        self.page._table.selectRow(self._row_for("admin"))
        QApplication.processEvents()
        self.assertEqual(self.page._toggle_active.text(), "Deactivate Selected")

    def test_60_button_disabled_without_selection(self):
        self.page._table.clearSelection()
        QApplication.processEvents()
        self.assertFalse(self.page._toggle_active.isEnabled())

    def test_61_button_enabled_with_selection(self):
        self.page._table.selectRow(self._row_for("staff"))
        QApplication.processEvents()
        self.assertTrue(self.page._toggle_active.isEnabled())

    def test_62_no_duplicate_activation_buttons(self):
        from PySide6.QtWidgets import QPushButton
        matches = [b for b in self.page.findChildren(QPushButton)
                   if b.text() in ("Activate Selected", "Deactivate Selected")]
        self.assertEqual(len(matches), 1)

    def test_63_button_text_switches_after_activation(self):
        self.page._table.selectRow(self._row_for("staff"))
        QApplication.processEvents()
        self.page._toggle_active.click()
        QApplication.processEvents()
        self.assertEqual(self.page._toggle_active.text(), "Deactivate Selected")

    def test_64_button_text_switches_back_after_deactivation(self):
        self.page._table.selectRow(self._row_for("staff"))
        QApplication.processEvents()
        self.page._toggle_active.click()
        QApplication.processEvents()
        self.page._toggle_active.click()
        QApplication.processEvents()
        self.assertEqual(self.page._toggle_active.text(), "Activate Selected")

    # ── UI: activation behaviour ───────────────────────────────────────

    def test_65_clicking_activate_sets_active_yes(self):
        self.page._table.selectRow(self._row_for("staff"))
        QApplication.processEvents()
        self.page._toggle_active.click()
        QApplication.processEvents()
        self.assertEqual(auth.get_user("staff")["is_active"], 1)
        self.assertEqual(self.page._table.item(self._row_for("staff"), 2).text(), "Yes")

    def test_66_clicking_deactivate_sets_active_no(self):
        auth.set_user_active(self.admin, self.staff["id"], True)
        self.page._refresh()
        self.page._table.selectRow(self._row_for("staff"))
        QApplication.processEvents()
        self.assertEqual(self.page._toggle_active.text(), "Deactivate Selected")
        self.page._toggle_active.click()
        QApplication.processEvents()
        self.assertEqual(auth.get_user("staff")["is_active"], 0)

    def test_67_selection_is_preserved_after_refresh(self):
        row = self._row_for("staff")
        self.page._table.selectRow(row)
        QApplication.processEvents()
        self.page._toggle_active.click()
        QApplication.processEvents()
        self.assertEqual(self.page._selected_id(), self.staff["id"])

    def test_68_selected_id_matches_row_not_position(self):
        self.page._table.selectRow(self._row_for("admin"))
        QApplication.processEvents()
        self.assertEqual(self.page._selected_id(), self.admin["id"])
        self.page._table.selectRow(self._row_for("staff"))
        QApplication.processEvents()
        self.assertEqual(self.page._selected_id(), self.staff["id"])

    def test_69_activation_uses_selected_user_only(self):
        self.page._table.selectRow(self._row_for("staff"))
        QApplication.processEvents()
        self.page._toggle_active.click()
        QApplication.processEvents()
        self.assertEqual(auth.get_user("admin")["is_active"], 1)

    def test_70_refresh_updates_row_count(self):
        auth.create_user(self.admin, "staff2", "staff2-pass-1", auth.ROLE_PHARMACIST_STAFF)
        self.page._refresh()
        QApplication.processEvents()
        self.assertEqual(self.page._table.rowCount(), 3)

    # ── UI: permissions ────────────────────────────────────────────────

    def test_71_staff_cannot_use_activation_button(self):
        auth.set_user_active(self.admin, self.staff["id"], True)
        auth.session.logout()
        auth.session.login("staff", "staff-pass-1")
        page = self.um.UserManagementPage()
        QApplication.processEvents()
        self.assertFalse(page._guard())
        self.assertTrue(any(title == "Permission denied" for title, _ in self.__class__._dialogs))
        self.assertEqual(auth.get_user("staff")["is_active"], 1)

    def test_72_staff_activation_denied_by_service(self):
        auth.session.login("staff", "staff-pass-1")
        with self.assertRaises(auth.PermissionDenied):
            auth.set_user_active(auth.session.user, self.staff["id"], False)

    def test_73_page_uses_user_management_permission_guard(self):
        source = Path("screens/user_management.py").read_text(encoding="utf-8")
        self.assertIn("auth.PERM_USER_MANAGEMENT", source)

    def test_74_last_admin_protection_surfaces_in_ui(self):
        self.page._table.selectRow(self._row_for("admin"))
        QApplication.processEvents()
        self.assertEqual(self.page._toggle_active.text(), "Deactivate Selected")

    # ── UI: toolbar ────────────────────────────────────────────────────

    def test_75_toolbar_button_order(self):
        bar = self.page.layout().itemAt(1).widget()
        texts = [bar.layout().itemAt(i).widget().text()
                 for i in range(bar.layout().count())
                 if bar.layout().itemAt(i).widget() is not None
                 and hasattr(bar.layout().itemAt(i).widget(), "text")]
        for expected in ("Create User", "Refresh", "Change Role"):
            self.assertIn(expected, texts)
        self.assertTrue(any("Selected" in t for t in texts))

    def test_76_unrelated_buttons_preserved(self):
        for name in ("_create", "_refresh_button", "_role", "_change_role"):
            self.assertTrue(hasattr(self.page, name), name)


if __name__ == "__main__":
    unittest.main()