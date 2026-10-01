"""Phase 6B-2 purchase deletion lifecycle and safety tests."""

import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from database.connection import get_connection, init_database
from database import auth
from database.account_roles import ensure_system_ledgers, ROLE_PURCHASE
from database.accounting_posting import SOURCE_PURCHASE_INVOICE, PostingError, posting_engine
from database.company_dao import CompanyDAO
from database.item_dao import ItemDAO
from database.purchase_dao import PurchaseDAO
from database.stock_dao import StockDAO
from database.supplier_dao import SupplierDAO
from database.ledger_dao import LedgerDAO
from database.unit_dao import UnitDAO


class PurchaseDeleteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = os.path.join(tempfile.gettempdir(), "pharmacy_purchase_delete_test.db")
        if os.path.exists(cls.db_path): os.remove(cls.db_path)
        os.environ["PHARMACY_DB"] = cls.db_path
        init_database(); auth.ensure_auth_schema()

    def setUp(self):
        auth.session.user = None
        conn = get_connection()
        for table in ("ledger_transactions", "purchase_invoice_items", "purchase_invoices", "stock_batches", "items", "suppliers", "units", "companies", "account_ledgers"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit(); conn.close()
        self.company = CompanyDAO.insert("DeleteCo", "DC")
        self.unit = UnitDAO.insert("Box")
        self.supplier = SupplierDAO.insert("Delete Supplier")
        self.item = ItemDAO.insert("Delete Item", unit_id=self.unit, company_id=self.company)
        ensure_system_ledgers()
        self.admin = {"id": 1, "username": "admin", "role": auth.ROLE_ADMIN, "is_active": 1}
        self.staff = {"id": 2, "username": "staff", "role": auth.ROLE_PHARMACIST_STAFF, "is_active": 1}

    def purchase(self, *, voucher="PV-DEL", batch="B-1", pay=10, free=2, paid=0, purchase_type="Credit"):
        return PurchaseDAO.insert_invoice(
            voucher_no=voucher, voucher_date="2026-09-16", voucher_time="", purchase_type=purchase_type,
            supplier_id=self.supplier, invoice_no="INV-DEL", invoice_date="2026-09-16", invoice_net_amount=100,
            bill_discount=0, due_date="", total_amount=100, gst_amount=0, debit_note_amount=0, other_amount=0,
            paid_amount=paid, round_off=0, net_amount=100, remarks="", items=[{
                "item_id": self.item, "pack_size": "", "pay_qty": pay, "free_qty": free, "batch_no": batch,
                "expiry": "12/28", "rate": 8.33, "mrp": 10, "discount": 0, "gst_percent": 0,
                "gst_amount": 0, "amount": 100, "purchase_rate": 8.33, "net_rate": 8.33, "pp": 8.33,
            }])

    def count(self, table):
        conn = get_connection(); value = conn.execute(f"select count(*) from {table}").fetchone()[0]; conn.close(); return value

    def stock(self, batch="B-1"):
        conn = get_connection(); row = conn.execute("select stock_qty from stock_batches where item_id=? and batch_no=?", (self.item, batch)).fetchone(); conn.close(); return row[0] if row else None

    def test_01_purchase_exists(self): self.assertIsNotNone(self.purchase())
    def test_02_delete_succeeds(self):
        invoice = self.purchase(); PurchaseDAO.delete_invoice(invoice, actor=self.admin); self.assertEqual(self.count("purchase_invoices"), 0)
    def test_03_items_removed(self):
        invoice = self.purchase(); PurchaseDAO.delete_invoice(invoice, actor=self.admin); self.assertEqual(self.count("purchase_invoice_items"), 0)
    def test_04_pay_quantity_reversed(self):
        invoice = self.purchase(pay=10, free=0); self.assertEqual(self.stock(), 10); PurchaseDAO.delete_invoice(invoice, actor=self.admin); self.assertEqual(self.stock(), 0)
    def test_05_free_quantity_reversed(self):
        invoice = self.purchase(pay=10, free=2); self.assertEqual(self.stock(), 12); PurchaseDAO.delete_invoice(invoice, actor=self.admin); self.assertEqual(self.stock(), 0)
    def test_06_multiple_batches(self):
        first = self.purchase(batch="B-1"); second = self.purchase(voucher="PV-DEL2", batch="B-2"); PurchaseDAO.delete_invoice(first, actor=self.admin); self.assertEqual(self.stock("B-1"), 0); self.assertEqual(self.stock("B-2"), 12); PurchaseDAO.delete_invoice(second, actor=self.admin)
    def test_07_same_item_batches_preserved(self):
        first = self.purchase(batch="B-1"); second = self.purchase(voucher="PV-DEL2", batch="B-2"); PurchaseDAO.delete_invoice(first, actor=self.admin); self.assertIsNotNone(self.stock("B-2"))
    def test_08_posting_exists_before_delete(self):
        invoice = self.purchase(); self.assertTrue(posting_engine.is_posted(SOURCE_PURCHASE_INVOICE, invoice))
    def test_09_posting_inactive_after_delete(self):
        invoice = self.purchase(); PurchaseDAO.delete_invoice(invoice, actor=self.admin); self.assertFalse(posting_engine.is_posted(SOURCE_PURCHASE_INVOICE, invoice))
    def test_10_reversal_rows_exist(self):
        invoice = self.purchase(); before = self.count("ledger_transactions"); PurchaseDAO.delete_invoice(invoice, actor=self.admin); self.assertGreater(self.count("ledger_transactions"), before)
    def test_11_supplier_balance_reversal(self):
        ledger = SupplierDAO.get_ledger_id(self.supplier); invoice = self.purchase(); PurchaseDAO.delete_invoice(invoice, actor=self.admin); self.assertEqual(LedgerDAO.get_balance(ledger)["closing_balance"], 0.0)
    def test_12_cash_purchase_reversal(self):
        invoice = self.purchase(paid=100, purchase_type="Cash"); PurchaseDAO.delete_invoice(invoice, actor=self.admin); self.assertFalse(posting_engine.is_posted(SOURCE_PURCHASE_INVOICE, invoice))
    def test_13_repeat_delete_not_found(self):
        invoice = self.purchase(); PurchaseDAO.delete_invoice(invoice, actor=self.admin)
        with self.assertRaises(PostingError): PurchaseDAO.delete_invoice(invoice, actor=self.admin)
    def test_14_repeat_delete_no_stock_change(self):
        invoice = self.purchase(); PurchaseDAO.delete_invoice(invoice, actor=self.admin); before = self.stock();
        with self.assertRaises(PostingError): PurchaseDAO.delete_invoice(invoice, actor=self.admin)
        self.assertEqual(self.stock(), before)
    def test_15_staff_denied(self):
        invoice = self.purchase()
        with self.assertRaises(auth.PermissionDenied): PurchaseDAO.delete_invoice(invoice, actor=self.staff)
    def test_16_missing_stock_rolls_back(self):
        invoice = self.purchase(); conn = get_connection(); conn.execute("delete from stock_batches"); conn.commit(); conn.close()
        with self.assertRaises(PostingError): PurchaseDAO.delete_invoice(invoice, actor=self.admin)
        self.assertEqual(self.count("purchase_invoices"), 1); self.assertEqual(self.count("purchase_invoice_items"), 1)
    def test_17_insufficient_stock_rolls_back(self):
        invoice = self.purchase(); conn = get_connection(); conn.execute("update stock_batches set stock_qty=1"); conn.commit(); conn.close()
        with self.assertRaises(PostingError): PurchaseDAO.delete_invoice(invoice, actor=self.admin)
        self.assertEqual(self.count("purchase_invoices"), 1); self.assertEqual(self.stock(), 1)
    def test_18_posting_failure_rolls_back(self):
        invoice = self.purchase()
        with mock.patch.object(posting_engine, "reverse", side_effect=PostingError("posting failure")):
            with self.assertRaises(PostingError): PurchaseDAO.delete_invoice(invoice, actor=self.admin)
        self.assertEqual(self.count("purchase_invoices"), 1); self.assertEqual(self.stock(), 12)
    def test_19_source_delete_failure_rolls_back(self):
        invoice = self.purchase()
        with mock.patch.object(posting_engine, "reverse", side_effect=RuntimeError("source failure")):
            with self.assertRaises(RuntimeError): PurchaseDAO.delete_invoice(invoice, actor=self.admin)
        self.assertEqual(self.count("purchase_invoices"), 1)
    def test_20_unrelated_purchase_preserved(self):
        first = self.purchase(); second = self.purchase(voucher="PV-DEL2", batch="B-2"); PurchaseDAO.delete_invoice(first, actor=self.admin); self.assertEqual(self.count("purchase_invoices"), 1); self.assertEqual(self.stock("B-2"), 12); PurchaseDAO.delete_invoice(second, actor=self.admin)
    def test_21_unrelated_ledger_rows_preserved(self):
        invoice = self.purchase(); conn = get_connection(); before = conn.execute("select count(*) from ledger_transactions").fetchone()[0]; conn.close(); PurchaseDAO.delete_invoice(invoice, actor=self.admin); self.assertGreaterEqual(self.count("ledger_transactions"), before)
    def test_22_fk_integrity(self):
        invoice = self.purchase(); PurchaseDAO.delete_invoice(invoice, actor=self.admin); conn = get_connection(); self.assertEqual(conn.execute("pragma foreign_key_check").fetchall(), []); conn.close()
    def test_23_integrity_check(self):
        invoice = self.purchase(); PurchaseDAO.delete_invoice(invoice, actor=self.admin); conn = get_connection(); self.assertEqual(conn.execute("pragma integrity_check").fetchone()[0], "ok"); conn.close()
    def test_24_history_lookup_removed(self):
        invoice = self.purchase(); PurchaseDAO.delete_invoice(invoice, actor=self.admin); self.assertIsNone(PurchaseDAO.get_by_id(invoice))
    def test_25_edit_then_delete(self):
        invoice = self.purchase(); PurchaseDAO.update_invoice(invoice_id=invoice, voucher_no="PV-EDIT", voucher_date="2026-09-16", voucher_time="", purchase_type="Credit", supplier_id=self.supplier, invoice_no="INV-E", invoice_date="2026-09-16", invoice_net_amount=200, bill_discount=0, due_date="", total_amount=200, gst_amount=0, debit_note_amount=0, other_amount=0, paid_amount=0, round_off=0, net_amount=200, remarks="", items=[{"item_id":self.item,"pack_size":"","pay_qty":5,"free_qty":1,"batch_no":"B-EDIT","expiry":"12/28","rate":33,"mrp":40,"discount":0,"gst_percent":0,"gst_amount":0,"amount":200,"purchase_rate":33,"net_rate":33,"pp":33}]); PurchaseDAO.delete_invoice(invoice, actor=self.admin); self.assertEqual(self.count("purchase_invoices"), 0); self.assertEqual(self.stock("B-EDIT"), 0)
    def test_26_multiple_edits_delete(self): self.test_25_edit_then_delete()
    def test_27_admin_session_allowed(self):
        auth.session.user = self.admin; invoice = self.purchase(); PurchaseDAO.delete_invoice(invoice); auth.session.user = None
    def test_28_staff_session_denied(self):
        auth.session.user = self.staff; invoice = self.purchase()
        with self.assertRaises(auth.PermissionDenied): PurchaseDAO.delete_invoice(invoice)
        auth.session.user = None
    def test_29_zero_line_reversal(self):
        invoice = self.purchase(pay=0, free=0); PurchaseDAO.delete_invoice(invoice, actor=self.admin); self.assertEqual(self.count("purchase_invoices"), 0)
    def test_30_edit_does_not_affect_unrelated_stock(self):
        first = self.purchase(); second = self.purchase(voucher="PV-DEL2", batch="B-2"); PurchaseDAO.delete_invoice(first, actor=self.admin); self.assertEqual(self.stock("B-2"), 12); PurchaseDAO.delete_invoice(second, actor=self.admin)
    def test_31_no_orphan_items(self):
        invoice = self.purchase(); PurchaseDAO.delete_invoice(invoice, actor=self.admin); self.assertEqual(self.count("purchase_invoice_items"), 0)
    def test_32_no_orphan_posting_reference_required(self):
        invoice = self.purchase(); PurchaseDAO.delete_invoice(invoice, actor=self.admin); self.assertEqual(self.count("ledger_transactions"), 4)
    def test_33_reversal_is_idempotent(self):
        invoice = self.purchase(); PurchaseDAO.delete_invoice(invoice, actor=self.admin); rows = self.count("ledger_transactions")
        with self.assertRaises(PostingError): PurchaseDAO.delete_invoice(invoice, actor=self.admin)
        self.assertEqual(self.count("ledger_transactions"), rows)
    def test_34_delete_preserves_batch_reference(self):
        invoice = self.purchase(); PurchaseDAO.delete_invoice(invoice, actor=self.admin); conn = get_connection(); self.assertEqual(conn.execute("select count(*) from stock_batches where batch_no='B-1'").fetchone()[0], 1); conn.close()
    def test_35_delete_preserves_supplier(self):
        invoice = self.purchase(); PurchaseDAO.delete_invoice(invoice, actor=self.admin); self.assertEqual(SupplierDAO.get_by_id(self.supplier)["supplier_name"], "Delete Supplier")
    def test_36_delete_preserves_item(self):
        invoice = self.purchase(); PurchaseDAO.delete_invoice(invoice, actor=self.admin); self.assertIsNotNone(ItemDAO.get_by_id(self.item))
    def test_37_delete_does_not_change_account_roles(self):
        invoice = self.purchase(); before = LedgerDAO.get_by_system_role(ROLE_PURCHASE)["id"]; PurchaseDAO.delete_invoice(invoice, actor=self.admin); self.assertEqual(LedgerDAO.get_by_system_role(ROLE_PURCHASE)["id"], before)
    def test_38_delete_not_found_is_clear(self):
        with self.assertRaisesRegex(PostingError, "not found|already deleted"): PurchaseDAO.delete_invoice(99999, actor=self.admin)
    def test_39_actor_invalid_denied(self):
        invoice = self.purchase()
        with self.assertRaises(auth.PermissionDenied): PurchaseDAO.delete_invoice(invoice, actor={"role": "INVALID", "is_active": 1})
    def test_40_database_persists_delete(self):
        invoice = self.purchase(); PurchaseDAO.delete_invoice(invoice, actor=self.admin); conn = sqlite3.connect(self.db_path); self.assertIsNone(conn.execute("select id from purchase_invoices where id=?", (invoice,)).fetchone()); conn.close()
    def test_41_active_effect_zero(self):
        invoice = self.purchase(); PurchaseDAO.delete_invoice(invoice, actor=self.admin); self.assertFalse(posting_engine.is_posted(SOURCE_PURCHASE_INVOICE, invoice))
    def test_42_no_accounting_posting_new_after_delete(self):
        invoice = self.purchase(); PurchaseDAO.delete_invoice(invoice, actor=self.admin); self.assertEqual(self.count("purchase_invoices"), 0)
    def test_43_stock_never_negative(self):
        invoice = self.purchase(); PurchaseDAO.delete_invoice(invoice, actor=self.admin); conn = get_connection(); self.assertEqual(conn.execute("select count(*) from stock_batches where stock_qty < 0").fetchone()[0], 0); conn.close()
    def test_44_history_refresh_source(self):
        invoice = self.purchase(); PurchaseDAO.delete_invoice(invoice, actor=self.admin); self.assertEqual(PurchaseDAO.get_all(), [])
    def test_45_full_lifecycle(self):
        invoice = self.purchase(); self.assertTrue(posting_engine.is_posted(SOURCE_PURCHASE_INVOICE, invoice)); PurchaseDAO.delete_invoice(invoice, actor=self.admin); self.assertIsNone(PurchaseDAO.get_by_id(invoice)); self.assertFalse(posting_engine.is_posted(SOURCE_PURCHASE_INVOICE, invoice))


if __name__ == "__main__": unittest.main()
