"""Phase 6B-7 Category Master tests; always uses a throwaway SQLite file."""

import os
import sqlite3
import tempfile
import unittest
import importlib.util
from pathlib import Path

from database.connection import get_connection, init_database
from database.category_dao import CategoryDAO, CategoryError
from database.item_dao import ItemDAO
from database import auth, import_service

_MENU_SPEC = importlib.util.spec_from_file_location("category_menu_data", Path("ui/menu_data.py"))
_MENU_MODULE = importlib.util.module_from_spec(_MENU_SPEC)
_MENU_SPEC.loader.exec_module(_MENU_MODULE)
MENUS = _MENU_MODULE.MENUS


class CategoryMasterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = os.path.join(tempfile.gettempdir(), "pharmacy_category_master_test.db")
        if os.path.exists(cls.db_path): os.remove(cls.db_path)
        os.environ["PHARMACY_DB"] = cls.db_path
        init_database(); auth.ensure_auth_schema()
        cls.admin = auth.create_first_admin("category-admin", "category-pass-1")
        cls.staff = auth.create_user(cls.admin, "category-staff", "category-pass-2", auth.ROLE_PHARMACIST_STAFF)

    def setUp(self):
        conn = get_connection()
        for table in ("sales_invoice_items", "sales_invoices", "purchase_invoice_items", "purchase_invoices", "stock_batches", "item_ingredients", "items", "ledger_transactions", "account_ledgers", "categories"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit(); conn.close()

    def category(self, name="Tablets", **kwargs): return CategoryDAO.create_category(name, **kwargs)
    def item(self, name="Paracetamol", category_id=None): return ItemDAO.insert(name, category_id=category_id)

    # Schema and migration safety
    def test_01_categories_table_created(self):
        conn = get_connection(); self.assertIsNotNone(conn.execute("SELECT name FROM sqlite_master WHERE name='categories'").fetchone()); conn.close()
    def test_02_categories_schema_columns(self):
        conn = get_connection(); names = {r[1] for r in conn.execute("PRAGMA table_info(categories)")}; conn.close(); self.assertTrue({"id", "category_name", "description", "is_active", "created_at", "updated_at"} <= names)
    def test_03_items_category_id_migrated(self):
        conn = get_connection(); self.assertIn("category_id", {r[1] for r in conn.execute("PRAGMA table_info(items)")}); conn.close()
    def test_04_initialization_is_idempotent(self): init_database(); init_database(); self.assertEqual(CategoryDAO.get_all_categories(), [])
    def test_05_category_fk_rejects_unknown_id(self):
        conn = get_connection()
        with self.assertRaises(sqlite3.IntegrityError): conn.execute("INSERT INTO items (item_name, category_id) VALUES (?, ?)", ("Bad FK", 99999))
        conn.close()
    def test_06_category_delete_sets_item_category_null(self):
        category_id = self.category(); item_id = self.item(category_id=category_id); conn = get_connection(); conn.execute("DELETE FROM categories WHERE id = ?", (category_id,)); conn.commit(); self.assertIsNone(conn.execute("SELECT category_id FROM items WHERE id = ?", (item_id,)).fetchone()[0]); conn.close()
    def test_07_existing_null_category_item_is_readable(self):
        item_id = self.item(); self.assertIsNone(ItemDAO.get_by_id(item_id)["category_id"])
    def test_08_category_migration_preserves_item_fields(self):
        item_id = ItemDAO.insert("Preserve", rate=55.5, location="Rack 1"); init_database(); item = ItemDAO.get_by_id(item_id); self.assertEqual((item["rate"], item["location"], item["category_id"]), (55.5, "Rack 1", None))

    # CRUD and validation
    def test_09_create_category(self): self.assertEqual(CategoryDAO.get_category(self.category())["category_name"], "Tablets")
    def test_10_create_description(self): self.assertEqual(CategoryDAO.get_category(self.category(description="Oral solid dosage"))["description"], "Oral solid dosage")
    def test_11_create_inactive(self): self.assertFalse(CategoryDAO.get_category(self.category(is_active=False))["is_active"])
    def test_12_blank_name_rejected(self):
        with self.assertRaises(CategoryError): self.category("   ")
    def test_13_name_whitespace_normalised(self): self.assertEqual(CategoryDAO.get_category(self.category("  Oral   Care "))["category_name"], "Oral Care")
    def test_14_duplicate_case_rejected(self): self.category("Tablets"); self.assertRaises(CategoryError, self.category, "tablets")
    def test_15_duplicate_whitespace_rejected(self): self.category("Oral Care"); self.assertRaises(CategoryError, self.category, " Oral   Care ")
    def test_16_category_exists_normalised(self): self.category("Topical Cream"); self.assertTrue(CategoryDAO.category_exists(" topical   cream "))
    def test_17_update_category(self):
        category_id = self.category(); CategoryDAO.update_category(category_id, "Capsules", "Gelatin"); category = CategoryDAO.get_category(category_id); self.assertEqual((category["category_name"], category["description"]), ("Capsules", "Gelatin"))
    def test_18_update_duplicate_rejected(self):
        first = self.category("Tablets"); self.category("Capsules"); self.assertRaises(CategoryError, CategoryDAO.update_category, first, "capsules")
    def test_19_update_missing_rejected(self): self.assertRaises(CategoryError, CategoryDAO.update_category, 9999, "Missing")
    def test_20_search_name(self): self.category("Tablets"); self.category("Capsules"); self.assertEqual([r["category_name"] for r in CategoryDAO.search_categories("tab")], ["Tablets"])
    def test_21_search_description(self): self.category("Topical", description="Skin use"); self.assertEqual(len(CategoryDAO.search_categories("skin")), 1)
    def test_22_active_listing_excludes_inactive(self): self.category("Active"); self.category("Inactive", is_active=False); self.assertEqual([r["category_name"] for r in CategoryDAO.get_all_categories(False)], ["Active"])
    def test_23_deactivate_category(self): category_id = self.category(); CategoryDAO.deactivate_category(category_id); self.assertFalse(CategoryDAO.get_category(category_id)["is_active"])
    def test_24_activate_category(self): category_id = self.category(is_active=False); CategoryDAO.activate_category(category_id); self.assertTrue(CategoryDAO.get_category(category_id)["is_active"])
    def test_25_toggle_missing_rejected(self): self.assertRaises(CategoryError, CategoryDAO.deactivate_category, 9999)
    def test_26_timestamps_present(self): category = CategoryDAO.get_category(self.category()); self.assertTrue(category["created_at"] and category["updated_at"])

    # Item integration and safety
    def test_27_item_category_assignment(self): category_id = self.category(); self.assertEqual(ItemDAO.get_by_id(self.item(category_id=category_id))["category_name"], "Tablets")
    def test_28_item_category_lookup(self): category_id = self.category(); item_id = self.item(category_id=category_id); self.assertEqual(CategoryDAO.get_items_using_category(category_id)[0]["id"], item_id)
    def test_29_item_category_update(self):
        first, second = self.category("One"), self.category("Two"); item_id = self.item(category_id=first); ItemDAO.update(item_id, "Paracetamol", category_id=second); self.assertEqual(ItemDAO.get_by_id(item_id)["category_id"], second)
    def test_30_blank_category_remains_valid(self): item_id = self.item(); ItemDAO.update(item_id, "Paracetamol", category_id=None); self.assertIsNone(ItemDAO.get_by_id(item_id)["category_id"])
    def test_31_new_item_cannot_use_inactive_category(self): category_id = self.category(is_active=False); self.assertRaises(ValueError, self.item, "New", category_id)
    def test_32_existing_item_can_retain_inactive_category(self):
        category_id = self.category(); item_id = self.item(category_id=category_id); CategoryDAO.deactivate_category(category_id); ItemDAO.update(item_id, "Renamed", category_id=category_id); self.assertEqual(ItemDAO.get_by_id(item_id)["item_name"], "Renamed")
    def test_33_existing_item_cannot_switch_to_other_inactive_category(self):
        active, inactive = self.category("Active"), self.category("Inactive", is_active=False); item_id = self.item(category_id=active); self.assertRaises(ValueError, ItemDAO.update, item_id, "Paracetamol", category_id=inactive)
    def test_34_item_search_by_category(self):
        first, second = self.category("One"), self.category("Two"); self.item("A", first); self.item("B", second); self.assertEqual([r["item_name"] for r in ItemDAO.search("", first)], ["A"])
    def test_35_item_search_without_category_still_works(self): self.item("Searchable"); self.assertEqual(ItemDAO.search("Search")[0]["item_name"], "Searchable")
    def test_36_deactivation_preserves_item_reference(self): category_id = self.category(); item_id = self.item(category_id=category_id); CategoryDAO.deactivate_category(category_id); self.assertEqual(ItemDAO.get_by_id(item_id)["category_id"], category_id)
    def test_37_stock_preserved_by_category_change(self):
        category_id = self.category(); item_id = self.item(category_id=category_id); conn = get_connection(); conn.execute("INSERT INTO stock_batches (item_id, batch_no, stock_qty) VALUES (?, ?, ?)", (item_id, "B1", 9)); conn.commit(); CategoryDAO.deactivate_category(category_id); self.assertEqual(conn.execute("SELECT stock_qty FROM stock_batches WHERE item_id = ?", (item_id,)).fetchone()[0], 9); conn.close()
    def test_38_sales_preserved_by_category_change(self):
        category_id = self.category(); item_id = self.item(category_id=category_id); conn = get_connection(); batch = conn.execute("INSERT INTO stock_batches (item_id, batch_no, stock_qty) VALUES (?, ?, ?)", (item_id, "B1", 4)).lastrowid; sale = conn.execute("INSERT INTO sales_invoices (bill_no, sale_date) VALUES (?, ?)", ("S-1", "2026-01-01")).lastrowid; conn.execute("INSERT INTO sales_invoice_items (sales_invoice_id, item_id, stock_batch_id, batch_no) VALUES (?, ?, ?, ?)", (sale, item_id, batch, "B1")); conn.commit(); CategoryDAO.deactivate_category(category_id); self.assertEqual(conn.execute("SELECT COUNT(*) FROM sales_invoice_items").fetchone()[0], 1); conn.close()
    def test_39_purchase_preserved_by_category_change(self):
        category_id = self.category(); item_id = self.item(category_id=category_id); conn = get_connection(); purchase = conn.execute("INSERT INTO purchase_invoices (voucher_no, voucher_date) VALUES (?, ?)", ("P-1", "2026-01-01")).lastrowid; conn.execute("INSERT INTO purchase_invoice_items (purchase_invoice_id, item_id) VALUES (?, ?)", (purchase, item_id)); conn.commit(); CategoryDAO.deactivate_category(category_id); self.assertEqual(conn.execute("SELECT COUNT(*) FROM purchase_invoice_items").fetchone()[0], 1); conn.close()
    def test_40_ledger_preserved_by_category_change(self):
        category_id = self.category(); self.item(category_id=category_id); conn = get_connection(); ledger = conn.execute("INSERT INTO account_ledgers (ledger_name) VALUES (?)", ("Cash",)).lastrowid; conn.execute("INSERT INTO ledger_transactions (ledger_id, transaction_date, voucher_type, voucher_no) VALUES (?, ?, ?, ?)", (ledger, "2026-01-01", "Opening", "O-1")); conn.commit(); CategoryDAO.deactivate_category(category_id); self.assertEqual(conn.execute("SELECT COUNT(*) FROM ledger_transactions").fetchone()[0], 1); conn.close()

    # Import compatibility, permission policy and wiring
    def test_41_item_import_with_category(self):
        self.category("Tablets"); data = {"headers": ["Item Name", "Category"], "rows": [{"Item Name": "Imported", "Category": "Tablets"}]}; result = import_service.preview_import("item", data); self.assertEqual(import_service.import_rows("item", result, confirm=True)["inserted"], 1); self.assertEqual(ItemDAO.get_all()[0]["category_name"], "Tablets")
    def test_42_item_import_without_category(self):
        data = {"headers": ["Item Name"], "rows": [{"Item Name": "Imported"}]}; result = import_service.preview_import("item", data); self.assertEqual(import_service.import_rows("item", result, confirm=True)["inserted"], 1); self.assertIsNone(ItemDAO.get_all()[0]["category_id"])
    def test_43_import_invalid_category_rejected(self):
        result = import_service.preview_import("item", {"headers": ["Item Name", "Category"], "rows": [{"Item Name": "Bad", "Category": "Unknown"}]}); self.assertGreater(result["invalid_rows"], 0)
    def test_44_import_inactive_category_rejected(self):
        self.category("Old", is_active=False); result = import_service.preview_import("item", {"headers": ["Item Name", "Category"], "rows": [{"Item Name": "Bad", "Category": "Old"}]}); self.assertGreater(result["invalid_rows"], 0)
    def test_45_import_update_without_category_preserves_assignment(self):
        category_id = self.category(); self.item("Existing", category_id); data = {"headers": ["Item Name", "Rate"], "rows": [{"Item Name": "Existing", "Rate": "7"}]}; result = import_service.preview_import("item", data); import_service.import_rows("item", result, duplicate_mode="update", confirm=True); self.assertEqual(ItemDAO.get_all()[0]["category_id"], category_id)
    def test_46_admin_has_category_management(self): self.assertTrue(auth.has_permission(self.admin, auth.PERM_CATEGORY_MANAGEMENT))
    def test_47_staff_cannot_manage_categories(self): self.assertFalse(auth.has_permission(self.staff, auth.PERM_CATEGORY_MANAGEMENT))
    def test_48_staff_can_view_masters_and_select_categories(self): self.assertTrue(auth.has_permission(self.staff, auth.PERM_VIEW_MASTERS))
    def test_49_category_menu_mapping_exists_once(self): self.assertEqual(MENUS["Master"].count("Category Master"), 1); self.assertEqual(auth.MENU_PERMISSIONS["Category Master"], auth.PERM_CATEGORY_MANAGEMENT)
    def test_50_category_page_export_and_mapping(self):
        self.assertIn("CategoryMasterPage", Path("screens/__init__.py").read_text(encoding="utf-8")); source = Path("ui/main_window.py").read_text(encoding="utf-8"); self.assertIn('item_name == "Category Master"', source); self.assertIn("screens.CategoryMasterPage()", source)
    def test_51_posting_engine_not_modified_by_feature(self): self.assertFalse(Path("database/accounting_posting.py").read_text(encoding="utf-8").find("Category Master") >= 0)
    def test_52_persistence_after_reopen(self):
        category_id = self.category("Persistent"); conn = sqlite3.connect(self.db_path); self.assertEqual(conn.execute("SELECT category_name FROM categories WHERE id = ?", (category_id,)).fetchone()[0], "Persistent"); conn.close()
    def test_53_gui_page_imports_when_pyside_is_available(self):
        try:
            from screens.category_master import CategoryMasterPage
        except ModuleNotFoundError as exc:
            if exc.name == "PySide6": self.skipTest("PySide6 not available")
            raise
        self.assertEqual(CategoryMasterPage.__name__, "CategoryMasterPage")


if __name__ == "__main__":
    unittest.main()
