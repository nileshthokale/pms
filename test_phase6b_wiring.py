"""Phase 6B-1 focused tests for existing Master menu wiring."""

import os
import tempfile
import unittest
import importlib.util
from pathlib import Path

from database.connection import init_database
from database import auth

_MENU_SPEC = importlib.util.spec_from_file_location("phase6b_menu_data", Path("ui/menu_data.py"))
_MENU_MODULE = importlib.util.module_from_spec(_MENU_SPEC)
_MENU_SPEC.loader.exec_module(_MENU_MODULE)
MENUS = _MENU_MODULE.MENUS


class MasterMenuWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = os.path.join(tempfile.gettempdir(), "pharmacy_phase6b_wiring.db")
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)
        os.environ["PHARMACY_DB"] = cls.db_path
        init_database(); auth.ensure_auth_schema()

    def setUp(self):
        conn = __import__("database.connection", fromlist=["get_connection"]).get_connection()
        conn.execute("DELETE FROM app_users"); conn.commit(); conn.close()
        self.admin = auth.create_first_admin("admin", "admin-pass-1")
        self.staff = auth.create_user(self.admin, "staff", "staff-pass-1", auth.ROLE_PHARMACIST_STAFF)

    def test_01_user_master_exists_once(self):
        self.assertEqual(MENUS["Master"].count("User Master"), 1)

    def test_02_account_group_is_master_entry_once(self):
        self.assertEqual(MENUS["Master"].count("Account Group"), 1)

    def test_03_no_duplicate_master_entries(self):
        self.assertEqual(len(MENUS["Master"]), len(set(MENUS["Master"])))

    def test_04_user_master_permission_is_existing_permission(self):
        self.assertEqual(auth.MENU_PERMISSIONS["User Master"], auth.PERM_USER_MANAGEMENT)

    def test_05_admin_can_open_user_management_permission(self):
        self.assertTrue(auth.has_permission(self.admin, auth.PERM_USER_MANAGEMENT))

    def test_06_staff_is_blocked_from_user_management(self):
        self.assertFalse(auth.has_permission(self.staff, auth.PERM_USER_MANAGEMENT))

    def test_07_account_group_page_exported(self):
        try:
            import screens
        except ModuleNotFoundError as exc:
            if exc.name != "PySide6":
                raise
            self.skipTest("PySide6 not available")
        self.assertTrue(hasattr(screens, "AccountGroupMasterPage"))

    def test_08_main_window_maps_existing_pages(self):
        source = Path("ui/main_window.py").read_text(encoding="utf-8")
        self.assertIn('item_name == "User Master"', source)
        self.assertIn("screens.UserManagementPage()", source)
        self.assertIn('item_name == "Account Group"', source)
        self.assertIn("screens.AccountGroupMasterPage()", source)

    def test_09_no_second_user_screen_added(self):
        self.assertEqual(len(list(Path("screens").glob("user_management.py"))), 1)
        self.assertTrue(Path("screens/user_management.py").exists())

    def test_10_account_group_feature_source_is_reused(self):
        source = Path("screens/account_group_master.py").read_text(encoding="utf-8")
        self.assertIn("class AccountGroupMasterPage", source)


if __name__ == "__main__":
    unittest.main()
