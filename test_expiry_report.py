"""Phase 5C — Expiry Report tests.

43 tests. All classification is deterministic: `today` is injected as
2026-09-16 (the DAO defaults to the real current date in production).

Expiry convention under test (mirrors StockDAO._is_expired): month
formats normalize to the FIRST day of the expiry month.
"""

import os
import sqlite3
import sys
import unittest
from datetime import date

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.connection import get_connection, init_database, get_db_path
from database.account_roles import ensure_system_ledgers
from database.expiry_report_dao import (
    ExpiryReportDAO,
    parse_expiry,
    STATUS_ALL,
    STATUS_EXPIRED,
    STATUS_EXPIRING_SOON,
)
from database.ledger_dao import LedgerDAO
from database.customer_dao import CustomerDAO
from database.supplier_dao import SupplierDAO
from database.customer_receipt_dao import CustomerReceiptDAO
from database.supplier_payment_dao import SupplierPaymentDAO
from database.purchase_dao import PurchaseDAO
from database.sales_dao import SalesDAO
from database.credit_note_dao import CreditNoteDAO
from database.debit_note_dao import DebitNoteDAO
from database.journal_dao import JournalDAO
from database.trial_balance_dao import TrialBalanceDAO
from database.profit_loss_dao import ProfitLossDAO
from database.balance_sheet_dao import BalanceSheetDAO
from database.sales_report_dao import SalesReportDAO
from database.purchase_report_dao import PurchaseReportDAO
from database.stock_dao import StockDAO
from database.company_dao import CompanyDAO
from database.unit_dao import UnitDAO
from database.drug_dao import DrugDAO
from database.item_dao import ItemDAO
from database.doctor_dao import DoctorDAO

TABLES = [
    "journal_entry_items", "journal_entries",
    "ledger_transactions", "account_ledgers",
    "customer_receipts", "supplier_payments",
    "debit_note_items", "debit_notes",
    "credit_note_items", "credit_notes",
    "sales_invoice_items", "sales_invoices",
    "purchase_invoice_items", "purchase_invoices",
    "stock_batches", "item_ingredients", "items",
    "doctors", "customers", "suppliers", "drugs", "units", "companies",
]

TODAY = date(2026, 9, 16)


class _BaseTest(unittest.TestCase):
    _DB_PATH = os.path.join(os.path.dirname(__file__), "_test_expiry_report.db")

    @classmethod
    def setUpClass(cls):
        if os.path.exists(cls._DB_PATH):
            os.remove(cls._DB_PATH)
        os.environ["PHARMACY_DB"] = cls._DB_PATH
        init_database()

    def setUp(self):
        conn = get_connection()
        try:
            for tbl in TABLES:
                conn.execute(f"DELETE FROM {tbl}")
            conn.commit()
        finally:
            conn.close()

        self.company_id = CompanyDAO.insert("CompanyA", "CA")
        self.company_b_id = CompanyDAO.insert("CompanyB", "CB")
        self.unit_id = UnitDAO.insert("Pcs")
        self.drug_id = DrugDAO.insert("Paracetamol")
        self.customer_id = CustomerDAO.insert("CustomerA")
        self.doctor_id = DoctorDAO.insert("Dr. Alpha")
        self.supplier_id = SupplierDAO.insert("SupplierA")
        self.item_id = ItemDAO.insert(
            item_name="ItemA", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="10x10",
            reorder_stock_level=10,
        )
        self.item_b_id = ItemDAO.insert(
            item_name="ItemB", unit_id=self.unit_id,
            company_id=self.company_b_id, pack_size="10x10",
            reorder_stock_level=5,
        )
        ensure_system_ledgers()

    # ── helper: direct batch insert (no accounting side effects) ──────
    def _batch(self, item_id=None, batch_no="BATCH-A", expiry="12/27",
               qty=10.0, rate=40.0, mrp=50.0, net_rate=None):
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                INSERT INTO stock_batches
                    (item_id, batch_no, expiry, pack_size, mrp,
                     purchase_rate, net_rate, stock_qty)
                VALUES (?, ?, ?, '10x10', ?, ?, ?, ?)
                """,
                (
                    item_id or self.item_id, batch_no, expiry, mrp, rate,
                    net_rate if net_rate is not None else rate, qty,
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def _report(self, **kwargs):
        kwargs.setdefault("today", TODAY)
        return ExpiryReportDAO.get_expiry_report(**kwargs)


# ======================================================================
# 1-8: Basics and date windows
# ======================================================================

class TestBasics(_BaseTest):

    def test_01_empty_report(self):
        report = self._report(status=STATUS_ALL)
        self.assertEqual(report["rows"], [])
        s = report["summary"]
        self.assertEqual(s["total_batches"], 0)
        self.assertEqual(s["total_qty"], 0.0)
        self.assertEqual(s["estimated_value"], 0.0)

    def test_02_valid_future_batch(self):
        self._batch(expiry="01/28")
        report = self._report(status=STATUS_ALL)
        self.assertEqual(len(report["rows"]), 1)
        row = report["rows"][0]
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["status_label"], "OK")
        self.assertEqual(row["expiry_date"], "2028-01-01")
        # Defensive alternate formats parse too (not app-produced)
        self.assertEqual(parse_expiry("01/2028"), date(2028, 1, 1))
        self.assertEqual(parse_expiry("2027-12-31"), date(2027, 12, 31))

    def test_03_expired_batch(self):
        self._batch(expiry="08/26")  # 2026-08-01 < 2026-09-16
        report = self._report(status=STATUS_ALL)
        row = report["rows"][0]
        self.assertEqual(row["status"], STATUS_EXPIRED)
        self.assertEqual(row["status_label"], "Expired")
        self.assertEqual(row["expiry_date"], "2026-08-01")

    def test_04_within_30_days(self):
        self._batch(expiry="10/26")  # 2026-10-01 within 30d of 09-16
        rows = self._report(status=STATUS_EXPIRING_SOON, within_days=30)["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], STATUS_EXPIRING_SOON)

    def test_05_within_60_days(self):
        self._batch(batch_no="B60", expiry="11/26")  # 11-01 within 60
        # Not within 30
        self.assertEqual(
            len(self._report(status=STATUS_EXPIRING_SOON,
                             within_days=30)["rows"]), 0
        )
        rows = self._report(status=STATUS_EXPIRING_SOON, within_days=60)["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["batch_no"], "B60")

    def test_06_within_90_days(self):
        self._batch(batch_no="B90", expiry="12/26")  # 12-01 <= 12-15 cutoff
        rows = self._report(status=STATUS_EXPIRING_SOON, within_days=90)["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["batch_no"], "B90")

    def test_07_beyond_selected_period(self):
        self._batch(batch_no="BFAR", expiry="06/27")  # 2027-06-01
        self.assertEqual(
            len(self._report(status=STATUS_EXPIRING_SOON,
                             within_days=90)["rows"]), 0
        )
        # Still present in "All" with status ok
        report = self._report(status=STATUS_ALL)
        self.assertEqual(report["rows"][0]["status"], "ok")

    def test_08_expired_excluded_from_expiring_soon(self):
        self._batch(batch_no="BOLD", expiry="08/26")
        soon = self._report(status=STATUS_EXPIRING_SOON,
                            within_days=90)["rows"]
        self.assertEqual(len(soon), 0)
        expired = self._report(status=STATUS_EXPIRED)["rows"]
        self.assertEqual(len(expired), 1)
        self.assertEqual(expired[0]["batch_no"], "BOLD")


# ======================================================================
# 9-11: Status filters
# ======================================================================

class TestStatusFilters(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch(batch_no="B-EXP", expiry="08/26", qty=5)
        self._batch(batch_no="B-SOON", expiry="10/26", qty=7)
        self._batch(batch_no="B-OK", expiry="06/27", qty=9)

    def test_09_expired_filter(self):
        rows = self._report(status=STATUS_EXPIRED)["rows"]
        self.assertEqual([r["batch_no"] for r in rows], ["B-EXP"])

    def test_10_expiring_soon_filter(self):
        rows = self._report(status=STATUS_EXPIRING_SOON)["rows"]
        self.assertEqual([r["batch_no"] for r in rows], ["B-SOON"])

    def test_11_all_status(self):
        rows = self._report(status=STATUS_ALL)["rows"]
        self.assertEqual(len(rows), 3)
        statuses = {r["batch_no"]: r["status"] for r in rows}
        self.assertEqual(statuses["B-EXP"], STATUS_EXPIRED)
        self.assertEqual(statuses["B-SOON"], STATUS_EXPIRING_SOON)
        self.assertEqual(statuses["B-OK"], "ok")


# ======================================================================
# 12-16: Filters
# ======================================================================

class TestFilters(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch(batch_no="B-A", expiry="10/26", qty=5)
        self._batch(item_id=self.item_b_id, batch_no="B-B",
                    expiry="11/26", qty=7)
        self._batch(batch_no="B-ZERO", expiry="10/26", qty=0)

    def test_12_item_filter(self):
        rows = self._report(status=STATUS_ALL, item_name="ItemB")["rows"]
        self.assertEqual([r["batch_no"] for r in rows], ["B-B"])

    def test_13_company_filter(self):
        rows = self._report(status=STATUS_ALL,
                            company_id=self.company_b_id)["rows"]
        self.assertEqual([r["batch_no"] for r in rows], ["B-B"])

    def test_14_batch_filter(self):
        rows = self._report(status=STATUS_ALL, batch_no="B-A")["rows"]
        self.assertEqual([r["batch_no"] for r in rows], ["B-A"])
        # Zero-stock batches match the batch filter only when included
        rows = self._report(status=STATUS_ALL, batch_no="B-Z",
                            include_zero=True)["rows"]
        self.assertEqual([r["batch_no"] for r in rows], ["B-ZERO"])

    def test_15_zero_stock_excluded_by_default(self):
        rows = self._report(status=STATUS_ALL)["rows"]
        self.assertNotIn("B-ZERO", [r["batch_no"] for r in rows])

    def test_16_include_zero_stock(self):
        rows = self._report(status=STATUS_ALL,
                            include_zero=True)["rows"]
        self.assertIn("B-ZERO", [r["batch_no"] for r in rows])
        zero_row = [r for r in rows if r["batch_no"] == "B-ZERO"][0]
        self.assertEqual(zero_row["stock_qty"], 0.0)


# ======================================================================
# 17-18: Malformed / empty expiry
# ======================================================================

class TestParsingSafety(_BaseTest):

    def test_17_malformed_expiry(self):
        self.assertIsNone(parse_expiry("ABC"))
        self.assertIsNone(parse_expiry("13/26"))   # month out of range
        self.assertIsNone(parse_expiry("12/"))     # missing year

        self._batch(batch_no="B-BAD", expiry="ABC")
        report = self._report(status=STATUS_ALL)
        row = report["rows"][0]
        self.assertEqual(row["status"], "invalid")
        self.assertEqual(row["status_label"], "Invalid")
        self.assertIsNone(row["expiry_date"])
        self.assertEqual(report["summary"]["invalid_count"], 1)

    def test_18_empty_expiry(self):
        self.assertIsNone(parse_expiry(""))
        self.assertIsNone(parse_expiry(None))

        self._batch(batch_no="B-EMPTY", expiry="")
        report = self._report(status=STATUS_ALL)
        row = report["rows"][0]
        self.assertEqual(row["status"], "invalid")
        self.assertEqual(row["expiry"], "")
        # Not misclassified as expired or expiring soon
        self.assertEqual(
            len(self._report(status=STATUS_EXPIRED)["rows"]), 0
        )
        self.assertEqual(
            len(self._report(status=STATUS_EXPIRING_SOON)["rows"]), 0
        )


# ======================================================================
# 19-25: Grouping, sorting, summary, stock source
# ======================================================================

class TestDetailChecks(_BaseTest):

    def test_19_multiple_batches_same_item(self):
        self._batch(batch_no="B1", expiry="10/26")
        self._batch(batch_no="B2", expiry="11/26")
        rows = self._report(status=STATUS_ALL)["rows"]
        self.assertEqual([r["batch_no"] for r in rows], ["B1", "B2"])
        self.assertTrue(all(r["item_name"] == "ItemA" for r in rows))

    def test_20_multiple_companies(self):
        self._batch(batch_no="B-A", expiry="10/26")
        self._batch(item_id=self.item_b_id, batch_no="B-B", expiry="10/26")
        rows = self._report(status=STATUS_ALL)["rows"]
        companies = {r["batch_no"]: r["company_name"] for r in rows}
        self.assertEqual(companies["B-A"], "CompanyA")
        self.assertEqual(companies["B-B"], "CompanyB")

    def test_21_expiry_ascending_sorting(self):
        self._batch(batch_no="B-FAR", expiry="06/27", qty=1)
        self._batch(batch_no="B-OLD", expiry="08/26", qty=1)
        self._batch(batch_no="B-NEXT", expiry="10/26", qty=1)
        self._batch(batch_no="B-BAD", expiry="ABC", qty=1)
        rows = self._report(status=STATUS_ALL)["rows"]
        self.assertEqual(
            [r["batch_no"] for r in rows],
            ["B-OLD", "B-NEXT", "B-FAR", "B-BAD"],  # invalid last
        )

        # Secondary sort by item name for equal expiry dates
        self._batch(item_id=self.item_b_id, batch_no="B-B2", expiry="10/26",
                    qty=1)
        rows = self._report(status=STATUS_ALL)["rows"]
        same_expiry = [r["item_name"] for r in rows if r["expiry"] == "10/26"]
        self.assertEqual(same_expiry, ["ItemA", "ItemB"])

    def test_22_summary_batch_count(self):
        self._batch(batch_no="B-EXP", expiry="08/26")
        self._batch(batch_no="B-SOON", expiry="10/26")
        self._batch(batch_no="B-OK", expiry="06/27")
        s = self._report(status=STATUS_ALL)["summary"]
        self.assertEqual(s["total_batches"], 3)
        self.assertEqual(s["expired_count"], 1)
        self.assertEqual(s["expiring_soon_count"], 1)

    def test_23_summary_quantity(self):
        self._batch(batch_no="B1", expiry="10/26", qty=5.5)
        self._batch(batch_no="B2", expiry="11/26", qty=4.5)
        s = self._report(status=STATUS_ALL)["summary"]
        self.assertEqual(s["total_qty"], 10.0)

    def test_24_summary_stock_value(self):
        # stock_qty × purchase_rate, e.g. 10 × 40 = 400 ; 5 × 20 = 100
        self._batch(batch_no="B1", expiry="10/26", qty=10, rate=40)
        self._batch(batch_no="B2", expiry="11/26", qty=5, rate=20)
        s = self._report(status=STATUS_ALL)["summary"]
        self.assertEqual(s["estimated_value"], 500.0)

    def test_25_current_stock_source_is_stock_batches(self):
        self._batch(batch_no="B1", expiry="10/26", qty=7)
        rows = self._report(status=STATUS_ALL)["rows"]
        self.assertEqual(rows[0]["stock_qty"], 7.0)

        # Directly changing stock_batches changes the report
        # (proves the report reads current stock_batches, not invoices)
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE stock_batches SET stock_qty = 3 WHERE batch_no = 'B1'"
            )
            conn.commit()
        finally:
            conn.close()
        rows = self._report(status=STATUS_ALL)["rows"]
        self.assertEqual(rows[0]["stock_qty"], 3.0)


# ======================================================================
# 26-29: Safety and persistence
# ======================================================================

class TestSafety(_BaseTest):

    def test_26_report_is_read_only(self):
        self._batch(batch_no="B1", expiry="10/26")
        conn = get_connection()
        try:
            counts_before = {
                t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in TABLES
            }
        finally:
            conn.close()

        self._report(status=STATUS_ALL)
        self._report(status=STATUS_EXPIRED)
        ExpiryReportDAO.get_expired(today=TODAY)

        conn = get_connection()
        try:
            counts_after = {
                t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in TABLES
            }
        finally:
            conn.close()
        self.assertEqual(counts_before, counts_after)

    def test_27_purchase_data_unchanged(self):
        self._batch(batch_no="B1", expiry="10/26")
        conn = get_connection()
        try:
            before = [
                tuple(r) for r in conn.execute(
                    "SELECT * FROM purchase_invoices ORDER BY id"
                ).fetchall()
            ] + [
                tuple(r) for r in conn.execute(
                    "SELECT * FROM purchase_invoice_items ORDER BY id"
                ).fetchall()
            ]
        finally:
            conn.close()

        self._report(status=STATUS_ALL)

        conn = get_connection()
        try:
            after = [
                tuple(r) for r in conn.execute(
                    "SELECT * FROM purchase_invoices ORDER BY id"
                ).fetchall()
            ] + [
                tuple(r) for r in conn.execute(
                    "SELECT * FROM purchase_invoice_items ORDER BY id"
                ).fetchall()
            ]
        finally:
            conn.close()
        self.assertEqual(before, after)

    def test_28_stock_data_unchanged(self):
        self._batch(batch_no="B1", expiry="10/26", qty=7)
        conn = get_connection()
        try:
            before = [
                tuple(r) for r in conn.execute(
                    "SELECT id, batch_no, expiry, stock_qty FROM stock_batches "
                    "ORDER BY id"
                ).fetchall()
            ]
        finally:
            conn.close()

        self._report(status=STATUS_ALL)

        conn = get_connection()
        try:
            after = [
                tuple(r) for r in conn.execute(
                    "SELECT id, batch_no, expiry, stock_qty FROM stock_batches "
                    "ORDER BY id"
                ).fetchall()
            ]
        finally:
            conn.close()
        self.assertEqual(before, after)

    def test_29_persistence(self):
        self._batch(batch_no="B1", expiry="10/26", qty=7)
        report = self._report(status=STATUS_ALL)

        fresh = sqlite3.connect(get_db_path())
        fresh.row_factory = sqlite3.Row
        try:
            row = fresh.execute(
                "SELECT COUNT(*) AS n FROM stock_batches"
            ).fetchone()
        finally:
            fresh.close()

        self.assertEqual(row["n"], len(report["rows"]))
        again = self._report(status=STATUS_ALL)
        self.assertEqual(again["summary"], report["summary"])
        self.assertEqual(again["rows"], report["rows"])


# ======================================================================
# 30-43: Regression
# ======================================================================

class TestRegression(_BaseTest):

    def _seed_via_purchase(self, qty=10.0, rate=40.0):
        """Real purchase insert (used where a stock-safety check matters)."""
        PurchaseDAO.insert_invoice(
            voucher_no="PV-0001", voucher_date="2026-02-01",
            voucher_time="", purchase_type="Cash",
            supplier_id=self.supplier_id, invoice_no="INV-0001",
            invoice_date="2026-02-01", invoice_net_amount=qty * rate,
            bill_discount=0, due_date="", total_amount=qty * rate,
            gst_amount=0, debit_note_amount=0, other_amount=0,
            paid_amount=qty * rate, round_off=0, net_amount=qty * rate,
            remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": qty, "free_qty": 0, "batch_no": "BATCH-P",
                "expiry": "12/27", "rate": rate, "mrp": 50.0, "discount": 0,
                "gst_percent": 0, "gst_amount": 0, "amount": qty * rate,
                "purchase_rate": rate, "net_rate": rate, "pp": rate,
            }],
        )

    def test_30_counter_sale_still_works(self):
        self._seed_via_purchase()
        batch = StockDAO.get_stock_batches_for_item(self.item_id)[0]
        sid = SalesDAO.insert_invoice(
            bill_no="CS-0001", sale_date="2026-02-02", sale_time="",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="", doctor_id=None, discount=0, paid_amount=50,
            total_amount=50, round_off=0, net_amount=50, remarks="",
            items=[{
                "item_id": self.item_id, "stock_batch_id": batch["id"],
                "pack_size": "10x10", "location": "", "batch_no": "BATCH-P",
                "expiry": "12/27", "mrp": 50, "sale_qty": 1,
                "discount_amount": 0, "amount": 50,
            }],
        )
        self.assertGreater(sid, 0)

    def test_31_purchase_still_works(self):
        self._seed_via_purchase()
        purchases = PurchaseDAO.get_all()
        self.assertEqual(len(purchases), 1)
        self.assertEqual(purchases[0]["net_amount"], 400.0)

    def test_32_credit_note_still_works(self):
        self._seed_via_purchase()
        batch = StockDAO.get_stock_batches_for_item(self.item_id)[0]
        cn_id = CreditNoteDAO.insert_credit_note(
            {"voucher_date": "2026-02-03", "cn_date": "2026-02-03",
             "cn_type": "Customer", "customer_id": self.customer_id,
             "total_amount": 40.0, "ledger_amount": 40.0, "remarks": ""},
            [{
                "item_id": self.item_id, "stock_batch_id": batch["id"],
                "batch_no": "BATCH-P", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40, "mrp": 50,
                "return_qty": 1, "less_amount": 0, "amount": 40,
                "return_reason": "", "price_factor": 1.0,
            }],
        )
        self.assertGreater(cn_id, 0)

    def test_33_debit_note_still_works(self):
        self._seed_via_purchase()
        batch = StockDAO.get_stock_batches_for_item(self.item_id)[0]
        dn_id = DebitNoteDAO.insert_debit_note(
            {"voucher_date": "2026-02-04", "voucher_time": "",
             "dn_date": "2026-02-04", "dn_type": "Supplier",
             "supplier_id": self.supplier_id, "total_amount": 60.0,
             "ledger_amount": 60.0, "remarks": ""},
            [{
                "item_id": self.item_id, "stock_batch_id": batch["id"],
                "batch_no": "BATCH-P", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40, "mrp": 50,
                "return_qty": 1.5, "less_amount": 0, "amount": 60,
                "return_reason": "", "price_factor": 1.0,
            }],
        )
        self.assertGreater(dn_id, 0)

    def test_34_supplier_payment_still_works(self):
        pid = SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-02-05", "payment_time": "",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 30.0, "reference_no": "", "remarks": "",
        })
        self.assertGreater(pid, 0)

    def test_35_customer_receipt_still_works(self):
        rid = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-02-05", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 20.0, "reference_no": "", "remarks": "",
        })
        self.assertGreater(rid, 0)

    def test_36_journal_entry_still_works(self):
        cash = LedgerDAO.get_by_system_role("CASH")
        bank = LedgerDAO.get_by_system_role("BANK")
        je_id = JournalDAO.insert_entry(
            {"entry_date": "2026-02-05", "narration": "Reg"},
            [
                {"ledger_id": cash["id"], "description": "",
                 "debit": 10.0, "credit": 0.0},
                {"ledger_id": bank["id"], "description": "",
                 "debit": 0.0, "credit": 10.0},
            ],
        )
        self.assertGreater(je_id, 0)

    def test_37_trial_balance_still_works(self):
        self._seed_via_purchase()
        self.assertTrue(TrialBalanceDAO.verify_balanced())
        self.assertGreater(
            TrialBalanceDAO.get_trial_balance()["totals"]["total_debit"], 0.0
        )

    def test_38_profit_loss_still_works(self):
        self._seed_via_purchase()
        self.assertIn("totals", ProfitLossDAO.get_profit_loss())
        self.assertIsInstance(ProfitLossDAO.get_totals(), dict)

    def test_39_balance_sheet_still_works(self):
        self._seed_via_purchase()
        self.assertIn("totals", BalanceSheetDAO.get_balance_sheet())
        self.assertIsInstance(BalanceSheetDAO.get_totals(), dict)

    def test_40_sales_report_still_works(self):
        self._seed_via_purchase()
        batch = StockDAO.get_stock_batches_for_item(self.item_id)[0]
        SalesDAO.insert_invoice(
            bill_no="CS-0001", sale_date="2026-02-02", sale_time="",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="", doctor_id=None, discount=0, paid_amount=50,
            total_amount=50, round_off=0, net_amount=50, remarks="",
            items=[{
                "item_id": self.item_id, "stock_batch_id": batch["id"],
                "pack_size": "10x10", "location": "", "batch_no": "BATCH-P",
                "expiry": "12/27", "mrp": 50, "sale_qty": 1,
                "discount_amount": 0, "amount": 50,
            }],
        )
        report = SalesReportDAO.get_sales_report()
        self.assertEqual(len(report["rows"]), 1)
        self.assertEqual(report["summary"]["total_net"], 50.0)

    def test_41_purchase_report_still_works(self):
        self._seed_via_purchase()
        report = PurchaseReportDAO.get_purchase_report()
        self.assertEqual(len(report["rows"]), 1)
        self.assertEqual(report["summary"]["total_net"], 400.0)

    def test_42_stock_master_still_works(self):
        self._seed_via_purchase()
        all_stock = StockDAO.get_all()
        self.assertEqual(len(all_stock), 1)
        self.assertEqual(all_stock[0]["stock_qty"], 10.0)
        # Stock Master's Expired filter and this report agree: both use
        # the MM/YY first-of-month convention
        expired_in_master = StockDAO.search(stock_status="Expired")
        expired_here = ExpiryReportDAO.get_expired(today=TODAY)
        self.assertEqual(len(expired_here), 0)
        self.assertEqual(len(expired_in_master), 0)

    def test_43_all_master_screens_still_work(self):
        self.assertGreater(len(CompanyDAO.get_all()), 0)
        self.assertGreater(len(UnitDAO.get_all()), 0)
        self.assertGreater(len(DrugDAO.get_all()), 0)
        self.assertGreater(len(SupplierDAO.get_all()), 0)
        self.assertGreater(len(CustomerDAO.get_all()), 0)
        self.assertGreater(len(DoctorDAO.get_all()), 0)
        self.assertGreater(len(ItemDAO.get_all()), 0)
        self.assertGreater(len(LedgerDAO.get_all_ledgers()), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
