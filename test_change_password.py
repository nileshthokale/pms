"""Tests for Change Password functionality in database/auth.py and screens/user_management.py.

Covers:
1. Admin changing own password (verifying current password, old password invalidated, new works).
2. Staff changing own password (verifying current password, old password invalidated, new works).
3. Admin resetting another user's password (verifying admin password, new works for target user).
4. Unauthorized staff attempt to reset another user's password blocked with PermissionDenied.
5. Incorrect current password rejected (own password and admin password for another user).
6. Password policy enforcement (length >= 8, non-whitespace, different from current for self-change).
7. ChangePasswordDialog UI verification (read-only username, show/hide passwords toggle, validation messages).
8. Dialog retention on failure (does not close on error).
9. UserManagementPage toolbar button enablement based on table selection.
10. Audit logging verification (actions logged without credentials).
11. Data preservation (roles, active status, and other tables untouched).
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QMessageBox

from database import auth
from database.connection import get_connection, init_database
from screens.user_management import ChangePasswordDialog, UserManagementPage


class ChangePasswordServiceTests(unittest.TestCase):
    """Backend service-layer tests for auth.change_password."""

    @classmethod
    def setUpClass(cls):
        cls.db_path = os.path.join(tempfile.gettempdir(), "pharmacy_change_password_test.db")
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)
        os.environ["PHARMACY_DB"] = cls.db_path
        init_database()
        auth.ensure_auth_schema()

    def setUp(self):
        conn = get_connection()
        conn.execute("DELETE FROM auth_audit_log")
        conn.execute("DELETE FROM app_users")
        conn.commit()
        conn.close()

        self.admin = auth.create_first_admin("admin", "admin-pass-1")
        self.staff1 = auth.create_user(self.admin, "staff1", "staff1-pass-1", auth.ROLE_PHARMACIST_STAFF)
        self.staff2 = auth.create_user(self.admin, "staff2", "staff2-pass-1", auth.ROLE_PHARMACIST_STAFF)

    # ── 1. Admin Changing Own Password ─────────────────────────────────

    def test_01_admin_change_own_password_success(self):
        auth.change_password(self.admin, self.admin["id"], "admin-pass-1", "new-admin-pass-99")
        # Old password no longer works
        self.assertIsNone(auth.authenticate("admin", "admin-pass-1"))
        # New password works
        auth_res = auth.authenticate("admin", "new-admin-pass-99")
        self.assertIsNotNone(auth_res)
        self.assertEqual(auth_res["username"], "admin")

    def test_02_admin_change_own_password_wrong_current(self):
        old_hash = auth.get_user("admin")["password_hash"]
        with self.assertRaises(auth.AuthenticationError) as ctx:
            auth.change_password(self.admin, self.admin["id"], "wrong-current-pass", "new-admin-pass-99")
        self.assertIn("Current password is incorrect", str(ctx.exception))
        # Hash remains unchanged
        self.assertEqual(auth.get_user("admin")["password_hash"], old_hash)
        self.assertIsNotNone(auth.authenticate("admin", "admin-pass-1"))

    # ── 2. Staff Changing Own Password ─────────────────────────────────

    def test_03_staff_change_own_password_success(self):
        auth.change_password(self.staff1, self.staff1["id"], "staff1-pass-1", "new-staff-pass-99")
        self.assertIsNone(auth.authenticate("staff1", "staff1-pass-1"))
        auth_res = auth.authenticate("staff1", "new-staff-pass-99")
        self.assertIsNotNone(auth_res)
        self.assertEqual(auth_res["username"], "staff1")

    def test_04_staff_change_own_password_wrong_current(self):
        old_hash = auth.get_user("staff1")["password_hash"]
        with self.assertRaises(auth.AuthenticationError) as ctx:
            auth.change_password(self.staff1, self.staff1["id"], "wrong-pass", "new-staff-pass-99")
        self.assertIn("Current password is incorrect", str(ctx.exception))
        self.assertEqual(auth.get_user("staff1")["password_hash"], old_hash)
        self.assertIsNotNone(auth.authenticate("staff1", "staff1-pass-1"))

    # ── 3. Admin Resetting Another User's Password ─────────────────────

    def test_05_admin_reset_staff_password_success(self):
        auth.change_password(self.admin, self.staff1["id"], "admin-pass-1", "staff1-fresh-pass")
        # Old staff password invalid
        self.assertIsNone(auth.authenticate("staff1", "staff1-pass-1"))
        # New staff password valid
        self.assertIsNotNone(auth.authenticate("staff1", "staff1-fresh-pass"))
        # Admin password untouched
        self.assertIsNotNone(auth.authenticate("admin", "admin-pass-1"))

    def test_06_admin_reset_staff_password_wrong_admin_password(self):
        old_hash = auth.get_user("staff1")["password_hash"]
        with self.assertRaises(auth.AuthenticationError) as ctx:
            auth.change_password(self.admin, self.staff1["id"], "wrong-admin-pass", "staff1-fresh-pass")
        self.assertIn("Current administrator password is incorrect", str(ctx.exception))
        self.assertEqual(auth.get_user("staff1")["password_hash"], old_hash)

    # ── 4. Unauthorized Users Blocked From Resetting Others ────────────

    def test_07_staff_cannot_reset_admin_password(self):
        with self.assertRaises(auth.PermissionDenied) as ctx:
            auth.change_password(self.staff1, self.admin["id"], "staff1-pass-1", "hacked-admin-pass")
        self.assertIn("Permission required: password_reset_others", str(ctx.exception))
        self.assertIsNotNone(auth.authenticate("admin", "admin-pass-1"))

    def test_08_staff_cannot_reset_another_staff_password(self):
        with self.assertRaises(auth.PermissionDenied) as ctx:
            auth.change_password(self.staff1, self.staff2["id"], "staff1-pass-1", "hacked-staff2-pass")
        self.assertIn("Permission required: password_reset_others", str(ctx.exception))
        self.assertIsNotNone(auth.authenticate("staff2", "staff2-pass-1"))

    def test_09_inactive_admin_cannot_change_passwords(self):
        admin2 = auth.create_user(self.admin, "admin2", "admin2-pass-1", auth.ROLE_ADMIN)
        auth.set_user_active(self.admin, admin2["id"], False)
        inactive_admin = auth.get_user("admin2")
        with self.assertRaises(auth.AuthenticationError):
            auth.change_password(inactive_admin, self.staff1["id"], "admin2-pass-1", "new-pass-12345")

    def test_10_missing_target_user_raises_error(self):
        with self.assertRaises(auth.AuthenticationError) as ctx:
            auth.change_password(self.admin, 999999, "admin-pass-1", "valid-new-pass")
        self.assertIn("User not found", str(ctx.exception))

    # ── 5. Password Policy & Strength ──────────────────────────────────

    def test_11_short_password_rejected(self):
        with self.assertRaises(auth.AuthenticationError) as ctx:
            auth.change_password(self.admin, self.admin["id"], "admin-pass-1", "short")
        self.assertIn("at least 8 characters", str(ctx.exception))

    def test_12_whitespace_password_rejected(self):
        with self.assertRaises(auth.AuthenticationError) as ctx:
            auth.change_password(self.admin, self.admin["id"], "admin-pass-1", "        ")
        self.assertIn("whitespace", str(ctx.exception))

    def test_13_same_password_rejected_for_self_change(self):
        with self.assertRaises(auth.AuthenticationError) as ctx:
            auth.change_password(self.admin, self.admin["id"], "admin-pass-1", "admin-pass-1")
        self.assertIn("different from current password", str(ctx.exception))

    # ── 6. Audit Logging ───────────────────────────────────────────────

    def test_14_audit_log_records_self_change(self):
        auth.change_password(self.admin, self.admin["id"], "admin-pass-1", "new-admin-pass-99")
        log = auth.get_audit_log()
        self.assertTrue(any(r["action"] == "password_changed" and r["success"] == 1 for r in log))
        # Ensure password is not in details
        for r in log:
            self.assertNotIn("new-admin-pass-99", r.get("details", ""))
            self.assertNotIn("admin-pass-1", r.get("details", ""))

    def test_15_audit_log_records_admin_reset(self):
        auth.change_password(self.admin, self.staff1["id"], "admin-pass-1", "new-staff1-pass-99")
        log = auth.get_audit_log()
        self.assertTrue(any(r["action"] == "password_reset" and r["success"] == 1 for r in log))

    def test_16_audit_log_records_failed_attempt(self):
        try:
            auth.change_password(self.admin, self.admin["id"], "wrong-current-pass", "new-pass-12345")
        except auth.AuthenticationError:
            pass
        log = auth.get_audit_log()
        self.assertTrue(any("failed" in r["action"] and r["success"] == 0 for r in log))

    # ── 7. Data Preservation ───────────────────────────────────────────

    def test_17_user_roles_and_status_preserved(self):
        admin_before = auth.get_user("admin")
        staff_before = auth.get_user("staff1")
        auth.change_password(self.admin, self.staff1["id"], "admin-pass-1", "new-staff1-pass-99")
        admin_after = auth.get_user("admin")
        staff_after = auth.get_user("staff1")

        self.assertEqual(admin_before["role"], admin_after["role"])
        self.assertEqual(admin_before["is_active"], admin_after["is_active"])
        self.assertEqual(staff_before["role"], staff_after["role"])
        self.assertEqual(staff_before["is_active"], staff_after["is_active"])
        self.assertEqual(staff_before["username"], staff_after["username"])


class ChangePasswordUITests(unittest.TestCase):
    """UI tests for ChangePasswordDialog and UserManagementPage integration."""

    @classmethod
    def setUpClass(cls):
        cls.db_path = os.path.join(tempfile.gettempdir(), "pharmacy_change_password_ui_test.db")
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)
        os.environ["PHARMACY_DB"] = cls.db_path
        init_database()
        auth.ensure_auth_schema()
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._dialogs = []
        conn = get_connection()
        conn.execute("DELETE FROM auth_audit_log")
        conn.execute("DELETE FROM app_users")
        conn.commit()
        conn.close()

        auth.session.logout()
        self.admin = auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        self.staff = auth.create_user(self.admin, "staff", "staff-pass-1", auth.ROLE_PHARMACIST_STAFF)

    def _record_msgbox(self, parent, title, text, *args, **kwargs):
        self._dialogs.append((title, text))
        return QMessageBox.Ok

    # ── Toolbar button enablement ──────────────────────────────────────

    def test_18_change_password_button_exists_in_toolbar(self):
        page = UserManagementPage()
        QApplication.processEvents()
        self.assertTrue(hasattr(page, "_change_password"))
        self.assertEqual(page._change_password.text(), "Change Password")

    def test_19_button_disabled_when_no_selection(self):
        page = UserManagementPage()
        page._table.clearSelection()
        QApplication.processEvents()
        self.assertFalse(page._change_password.isEnabled())

    def test_20_button_enabled_when_user_selected(self):
        page = UserManagementPage()
        page._table.selectRow(0)
        QApplication.processEvents()
        self.assertTrue(page._change_password.isEnabled())

    # ── Dialog elements and behavior ───────────────────────────────────

    def test_21_dialog_initial_state(self):
        dlg = ChangePasswordDialog(user_id=self.staff["id"], username="staff")
        self.assertEqual(dlg.username_field.text(), "staff")
        self.assertTrue(dlg.username_field.isReadOnly())
        self.assertEqual(dlg.current_password.echoMode(), QLineEdit.Password)
        self.assertEqual(dlg.new_password.echoMode(), QLineEdit.Password)
        self.assertEqual(dlg.confirm_password.echoMode(), QLineEdit.Password)
        self.assertFalse(dlg.show_passwords_cb.isChecked())

    def test_22_show_passwords_toggle(self):
        dlg = ChangePasswordDialog(user_id=self.staff["id"], username="staff")
        # Check toggling to True -> Normal
        dlg.show_passwords_cb.setChecked(True)
        self.assertEqual(dlg.current_password.echoMode(), QLineEdit.Normal)
        self.assertEqual(dlg.new_password.echoMode(), QLineEdit.Normal)
        self.assertEqual(dlg.confirm_password.echoMode(), QLineEdit.Normal)

        # Toggle back to False -> Password
        dlg.show_passwords_cb.setChecked(False)
        self.assertEqual(dlg.current_password.echoMode(), QLineEdit.Password)
        self.assertEqual(dlg.new_password.echoMode(), QLineEdit.Password)
        self.assertEqual(dlg.confirm_password.echoMode(), QLineEdit.Password)

    def test_23_validation_empty_current_password_keeps_dialog_open(self):
        dlg = ChangePasswordDialog(user_id=self.admin["id"], username="admin")
        dlg.new_password.setText("new-admin-pass-99")
        dlg.confirm_password.setText("new-admin-pass-99")

        with mock.patch.object(QMessageBox, "warning", side_effect=self._record_msgbox):
            dlg.save_btn.click()
            QApplication.processEvents()

        self.assertTrue(any("current password" in text.lower() for _, text in self._dialogs))
        self.assertNotEqual(dlg.result(), QDialog.Accepted)

    def test_24_validation_mismatched_confirm_keeps_dialog_open(self):
        dlg = ChangePasswordDialog(user_id=self.admin["id"], username="admin")
        dlg.current_password.setText("admin-pass-1")
        dlg.new_password.setText("new-admin-pass-99")
        dlg.confirm_password.setText("different-confirm")

        with mock.patch.object(QMessageBox, "warning", side_effect=self._record_msgbox):
            dlg.save_btn.click()
            QApplication.processEvents()

        self.assertTrue(any("not match" in text.lower() for _, text in self._dialogs))
        self.assertNotEqual(dlg.result(), QDialog.Accepted)

    def test_25_validation_short_password_keeps_dialog_open(self):
        dlg = ChangePasswordDialog(user_id=self.admin["id"], username="admin")
        dlg.current_password.setText("admin-pass-1")
        dlg.new_password.setText("short")
        dlg.confirm_password.setText("short")

        with mock.patch.object(QMessageBox, "warning", side_effect=self._record_msgbox):
            dlg.save_btn.click()
            QApplication.processEvents()

        self.assertTrue(any("8 characters" in text.lower() for _, text in self._dialogs))
        self.assertNotEqual(dlg.result(), QDialog.Accepted)

    def test_26_validation_wrong_current_password_shows_warning_and_keeps_dialog_open(self):
        dlg = ChangePasswordDialog(user_id=self.admin["id"], username="admin")
        dlg.current_password.setText("wrong-admin-password")
        dlg.new_password.setText("new-valid-password-99")
        dlg.confirm_password.setText("new-valid-password-99")

        with mock.patch.object(QMessageBox, "warning", side_effect=self._record_msgbox):
            dlg.save_btn.click()
            QApplication.processEvents()

        self.assertTrue(any("incorrect" in text.lower() for _, text in self._dialogs))
        self.assertNotEqual(dlg.result(), QDialog.Accepted)
        # Verify old password still works
        self.assertIsNotNone(auth.authenticate("admin", "admin-pass-1"))

    def test_27_successful_change_shows_info_and_accepts_dialog(self):
        dlg = ChangePasswordDialog(user_id=self.staff["id"], username="staff")
        dlg.current_password.setText("admin-pass-1")  # admin resetting staff
        dlg.new_password.setText("staff-new-pass-99")
        dlg.confirm_password.setText("staff-new-pass-99")

        with mock.patch.object(QMessageBox, "information", side_effect=self._record_msgbox):
            dlg.save_btn.click()
            QApplication.processEvents()

        self.assertTrue(any("successfully" in text.lower() for _, text in self._dialogs))
        self.assertEqual(dlg.result(), QDialog.Accepted)
        self.assertIsNotNone(auth.authenticate("staff", "staff-new-pass-99"))


if __name__ == "__main__":
    unittest.main()
