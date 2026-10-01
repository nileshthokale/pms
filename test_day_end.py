"""Phase 6B-5 — Day End report tests (read-only operational summary).

Isolation: every test runs against a throwaway database via PHARMACY_DB
(_test_day_end.db); data/pharmacy.db and any legacy systems are never
touched. GUI tests skip with an explicit dependency reason when
PySide6 is unavailable (they run in the development environment).
"""

import os
import sqlite3
import sys
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.connection import get_connection, init_database
from database.day_end_dao import DayEndDAO, DayEndError
from database.financial_year import (
    active_date_range,
    create_financial_year,
    ensure_default_financial_year,
)
from database import document_printing
from database.cash_book_dao import CashBookDAO
from database.bank_book_dao import BankBookDAO
from database.sales_report_dao import SalesReportDAO
from database.purchase_report_dao import PurchaseReportDAO
from database.trial_balance_dao import TrialBalanceDAO
from database.ledger_dao import LedgerDAO

try:
    from PySide6.QtWidgets import QApplication
    from screens.day_end import DayEndPage

    HAS_PYSIDE6 = True
    _PYSIDE_SKIP_REASON = ""
except ImportError as _exc:  # pragma: no cover
    HAS_PYSIDE6 = False
    _PYSIDE_SKIP_REASON = f"PySide6 not available ({_exc})"

DAY = "2026-06-15"
EMPTY_DAY = "2026-07-01"

_TABLES = [
    "financial_years",
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


class _BaseTest(unittest.TestCase):
    _DB_PATH = os.path.join(os.path.dirname(__file__), "_test_day_end.db")

    @classmethod
    def setUpClass(cls):
        if os.path.exists(cls._DB_PATH):
            os.remove(cls._DB_PATH)
        os.environ["PHARMACY_DB"] = cls._DB_PATH
        init_database()
        ensure_default_financial_year()

    def setUp(self):
        conn = get_connection()
        try:
            for table in _TABLES:
                conn.execute(f"DELETE FROM {table}")

            cur = conn.execute(
                "INSERT INTO account_ledgers "
                "(ledger_name, system_role, opening_balance, "
                " opening_balance_type) VALUES ('Cash','CASH',100,'Debit')"
            )
            self.cash_ledger_id = cur.lastrowid
            cur = conn.execute(
                "INSERT INTO account_ledgers "
                "(ledger_name, system_role, opening_balance, "
                " opening_balance_type) VALUES ('Bank','BANK',200,'Debit')"
            )
            self.bank_ledger_id = cur.lastrowid

            cur = conn.execute(
                "INSERT INTO customers (customer_name) VALUES ('Customer')"
            )
            self.customer_id = cur.lastrowid
            cur = conn.execute(
                "INSERT INTO suppliers (supplier_name) VALUES ('Supplier')"
            )
            self.supplier_id = cur.lastrowid
            cur = conn.execute("INSERT INTO units (unit_name) VALUES ('Box')")
            unit_id = cur.lastrowid
            cur = conn.execute(
                "INSERT INTO companies (company_name, short_name) "
                "VALUES ('Co','C')"
            )
            company_id = cur.lastrowid
            cur = conn.execute(
                "INSERT INTO items (item_name, unit_id, company_id) "
                "VALUES ('Item',?,?)",
                (unit_id, company_id),
            )
            self.item_id = cur.lastrowid
            cur = conn.execute(
                "INSERT INTO stock_batches (item_id, batch_no, stock_qty) "
                "VALUES (?,'B',10)",
                (self.item_id,),
            )
            self.batch_id = cur.lastrowid

            cur = conn.execute(
                "INSERT INTO sales_invoices "
                "(bill_no, sale_date, sale_type, customer_id, total_amount, "
                " discount, paid_amount, net_amount) "
                "VALUES ('S-1',?,'Cash',?,100,5,95,95)",
                (DAY, self.customer_id),
            )
            self.sale_id = cur.lastrowid
            conn.execute(
                "INSERT INTO sales_invoice_items "
                "(sales_invoice_id, item_id, stock_batch_id, batch_no, "
                " sale_qty, amount) VALUES (?,?,?,'B',2,95)",
                (self.sale_id, self.item_id, self.batch_id),
            )

            cur = conn.execute(
                "INSERT INTO purchase_invoices "
                "(voucher_no, voucher_date, supplier_id, total_amount, "
                " gst_amount, bill_discount, other_amount, round_off, "
                " net_amount) VALUES ('P-1',?,?,80,14,2,1,0.5,93.5)",
                (DAY, self.supplier_id),
            )
            self.purchase_id = cur.lastrowid
            conn.execute(
                "INSERT INTO purchase_invoice_items "
                "(purchase_invoice_id, item_id, pay_qty, free_qty, batch_no, "
                " amount, gst_amount) VALUES (?,?,3,1,'B',80,14)",
                (self.purchase_id, self.item_id),
            )

            cur = conn.execute(
                "INSERT INTO credit_notes "
                "(voucher_no, voucher_date, customer_id, total_amount, "
                " ledger_amount) VALUES ('CN-1',?,?,10,10)",
                (DAY, self.customer_id),
            )
            self.credit_note_id = cur.lastrowid
            conn.execute(
                "INSERT INTO credit_note_items "
                "(credit_note_id, item_id, stock_batch_id, batch_no, "
                " return_qty, amount) VALUES (?,?,?,'B',1,10)",
                (self.credit_note_id, self.item_id, self.batch_id),
            )

            cur = conn.execute(
                "INSERT INTO debit_notes "
                "(voucher_no, voucher_date, supplier_id, total_amount, "
                " ledger_amount) VALUES ('DN-1',?,?,7,7)",
                (DAY, self.supplier_id),
            )
            self.debit_note_id = cur.lastrowid
            conn.execute(
                "INSERT INTO debit_note_items "
                "(debit_note_id, item_id, stock_batch_id, batch_no, "
                " return_qty, amount) VALUES (?,?,?,'B',1,7)",
                (self.debit_note_id, self.item_id, self.batch_id),
            )

            cur = conn.execute(
                "INSERT INTO customer_receipts "
                "(voucher_no, receipt_date, customer_id, receipt_mode, amount) "
                "VALUES ('CR-1',?,?,'Cash',20)",
                (DAY, self.customer_id),
            )
            self.receipt_id = cur.lastrowid
            cur = conn.execute(
                "INSERT INTO supplier_payments "
                "(voucher_no, payment_date, supplier_id, payment_mode, amount) "
                "VALUES ('SP-1',?,?,'Bank',30)",
                (DAY, self.supplier_id),
            )
            self.payment_id = cur.lastrowid

            conn.execute(
                "INSERT INTO ledger_transactions "
                "(ledger_id, transaction_date, voucher_type, voucher_no, "
                " reference_type, reference_id, description, debit, credit) "
                "VALUES (?,?, 'Receipt','CR-1','CUSTOMER_RECEIPT',?,"
                "'Receipt',20,0)",
                (self.cash_ledger_id, DAY, self.receipt_id),
            )
            conn.execute(
                "INSERT INTO ledger_transactions "
                "(ledger_id, transaction_date, voucher_type, voucher_no, "
                " reference_type, reference_id, description, debit, credit) "
                "VALUES (?,?, 'Payment','SP-1','SUPPLIER_PAYMENT',?,"
                "'Payment',0,30)",
                (self.bank_ledger_id, DAY, self.payment_id),
            )
            conn.commit()
        finally:
            conn.close()

        self._tmp = tempfile.mkdtemp(prefix="day_end_test_")
        self.addCleanup(__import__("shutil").rmtree, self._tmp, True)

    # ── helpers ──────────────────────────────────────────────────────
    def report(self, day=DAY):
        return DayEndDAO.get_day_end_report(day)

    def counts(self):
        conn = get_connection()
        try:
            return {
                table: conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                for table in _TABLES
            }
        finally:
            conn.close()

    def snapshot(self, table):
        conn = get_connection()
        try:
            return [
                tuple(r) for r in conn.execute(
                    f"SELECT * FROM {table} ORDER BY id"
                ).fetchall()
            ]
        finally:
            conn.close()


# ======================================================================
# EMPTY state
# ======================================================================

class TestDayEndEmpty(_BaseTest):

    def test_01_empty_date_zero_sales(self):
        self.assertEqual(self.report(EMPTY_DAY)["sales"]["count"], 0)

    def test_02_empty_date_zero_purchases(self):
        self.assertEqual(self.report(EMPTY_DAY)["purchases"]["count"], 0)

    def test_03_empty_date_zero_stock_impact(self):
        stock = self.report(EMPTY_DAY)["stock"]
        self.assertEqual(stock["purchase_added"], 0)
        self.assertEqual(stock["sales_removed"], 0)

    def test_04_empty_historical_date(self):
        report = self.report("2020-01-01")
        self.assertEqual(report["date"], "2020-01-01")
        self.assertEqual(report["receipts"]["total"], 0)
        self.assertEqual(report["payments"]["total"], 0)


# ======================================================================
# SALES
# ======================================================================

class TestDayEndSales(_BaseTest):

    def test_05_sales_count(self):
        self.assertEqual(self.report()["sales"]["count"], 1)

    def test_06_sales_amount(self):
        self.assertEqual(self.report()["sales"]["amount"], 100)

    def test_07_counter_sales_amount(self):
        self.assertEqual(self.report()["sales"]["counter_sales"], 95)

    def test_08_sales_discount(self):
        self.assertEqual(self.report()["sales"]["discount"], 5)

    def test_09_sales_net(self):
        self.assertEqual(self.report()["sales"]["net"], 95)

    def test_10_sales_total_fields_present(self):
        sales = self.report()["sales"]
        for key in ("count", "amount", "counter_sales", "discount", "net"):
            self.assertIn(key, sales)

    def test_11_only_selected_date_counted(self):
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO sales_invoices "
                "(bill_no, sale_date, sale_type, customer_id, total_amount, "
                " discount, paid_amount, net_amount) "
                "VALUES ('S-2','2026-06-16','Cash',?,50,0,50,50)",
                (self.customer_id,),
            )
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(self.report()["sales"]["count"], 1)


# ======================================================================
# PURCHASES
# ======================================================================

class TestDayEndPurchases(_BaseTest):

    def test_12_purchase_count(self):
        self.assertEqual(self.report()["purchases"]["count"], 1)

    def test_13_purchase_amount(self):
        self.assertEqual(self.report()["purchases"]["amount"], 80)

    def test_14_purchase_gst_stored(self):
        self.assertEqual(self.report()["purchases"]["gst"], 14)

    def test_15_purchase_bill_discount(self):
        self.assertEqual(self.report()["purchases"]["discount"], 2)

    def test_16_purchase_other_amount(self):
        self.assertEqual(self.report()["purchases"]["other_amount"], 1)

    def test_17_purchase_round_off(self):
        self.assertEqual(self.report()["purchases"]["round_off"], 0.5)

    def test_18_purchase_net(self):
        self.assertEqual(self.report()["purchases"]["net"], 93.5)

    def test_19_purchase_fields_complete(self):
        purchases = self.report()["purchases"]
        for key in ("count", "amount", "gst", "discount", "other_amount",
                    "round_off", "net"):
            self.assertIn(key, purchases)

    def test_20_purchase_no_invented_fields(self):
        # No GST invention beyond stored fields; no COGS/valuation fields
        purchases = self.report()["purchases"]
        self.assertNotIn("cogs", purchases)
        self.assertNotIn("input_tax_credit", purchases)


# ======================================================================
# RETURNS
# ======================================================================

class TestDayEndReturns(_BaseTest):

    def test_21_credit_note_count(self):
        self.assertEqual(self.report()["returns"]["credit_count"], 1)

    def test_22_credit_note_amount(self):
        self.assertEqual(self.report()["returns"]["credit_amount"], 10)

    def test_23_debit_note_count(self):
        self.assertEqual(self.report()["returns"]["debit_count"], 1)

    def test_24_debit_note_amount(self):
        self.assertEqual(self.report()["returns"]["debit_amount"], 7)

    def test_25_returns_are_separate(self):
        returns = self.report()["returns"]
        self.assertIn("credit_amount", returns)
        self.assertIn("debit_amount", returns)
        self.assertNotEqual(returns["credit_amount"], returns["debit_amount"])


# ======================================================================
# RECEIPTS / PAYMENTS
# ======================================================================

class TestDayEndReceiptsPayments(_BaseTest):

    def test_26_receipt_count(self):
        self.assertEqual(self.report()["receipts"]["count"], 1)

    def test_27_cash_receipt_amount(self):
        self.assertEqual(self.report()["receipts"]["cash"], 20)

    def test_28_bank_receipt_amount(self):
        self.assertEqual(self.report()["receipts"]["bank"], 0)

    def test_29_receipt_total(self):
        self.assertEqual(self.report()["receipts"]["total"], 20)

    def test_30_bank_mode_receipt_bucket(self):
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO customer_receipts "
                "(voucher_no, receipt_date, customer_id, receipt_mode, amount) "
                "VALUES ('CR-2','2026-06-15',?,'UPI',12)",
                (self.customer_id,),
            )
            conn.commit()
        finally:
            conn.close()
        receipts = self.report()["receipts"]
        self.assertEqual(receipts["count"], 2)
        self.assertEqual(receipts["bank"], 12)
        self.assertEqual(receipts["cash"], 20)
        self.assertEqual(receipts["total"], 32)

    def test_31_payment_count(self):
        self.assertEqual(self.report()["payments"]["count"], 1)

    def test_32_cash_payment_amount(self):
        self.assertEqual(self.report()["payments"]["cash"], 0)

    def test_33_bank_payment_amount(self):
        self.assertEqual(self.report()["payments"]["bank"], 30)

    def test_34_payment_total(self):
        self.assertEqual(self.report()["payments"]["total"], 30)

    def test_35_cheque_payment_bucket(self):
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO supplier_payments "
                "(voucher_no, payment_date, supplier_id, payment_mode, amount) "
                "VALUES ('SP-2','2026-06-15',?,'Cheque',15)",
                (self.supplier_id,),
            )
            conn.commit()
        finally:
            conn.close()
        payments = self.report()["payments"]
        self.assertEqual(payments["count"], 2)
        self.assertEqual(payments["bank"], 45)
        self.assertEqual(payments["total"], 45)


# ======================================================================
# CASH / BANK
# ======================================================================

class TestDayEndCashBank(_BaseTest):

    def test_36_cash_daily_debit(self):
        self.assertEqual(self.report()["cash"]["debit"], 20)

    def test_37_cash_daily_credit(self):
        self.assertEqual(self.report()["cash"]["credit"], 0)

    def test_38_cash_opening_balance(self):
        self.assertEqual(self.report()["cash"]["opening"], 100)

    def test_39_cash_net_movement(self):
        self.assertEqual(self.report()["cash"]["net"], 20)

    def test_40_cash_closing_balance(self):
        self.assertEqual(self.report()["cash"]["closing"], 120)

    def test_41_bank_daily_debit(self):
        self.assertEqual(self.report()["bank"]["debit"], 0)

    def test_42_bank_daily_credit(self):
        self.assertEqual(self.report()["bank"]["credit"], 30)

    def test_43_bank_opening_balance(self):
        self.assertEqual(self.report()["bank"]["opening"], 200)

    def test_44_bank_net_movement(self):
        self.assertEqual(self.report()["bank"]["net"], -30)

    def test_45_bank_closing_balance(self):
        self.assertEqual(self.report()["bank"]["closing"], 170)

    def test_46_cash_agrees_with_cash_book(self):
        book = CashBookDAO.get_cash_book(DAY, DAY)
        cash = self.report()["cash"]
        self.assertEqual(cash["opening"], book["opening_balance"])
        self.assertEqual(cash["debit"], book["summary"]["total_debit"])
        self.assertEqual(cash["credit"], book["summary"]["total_credit"])
        self.assertEqual(cash["net"], book["summary"]["net_movement"])
        self.assertEqual(cash["closing"], book["summary"]["closing_balance"])

    def test_47_bank_agrees_with_bank_book(self):
        book = BankBookDAO.get_bank_book(DAY, DAY)
        bank = self.report()["bank"]
        self.assertEqual(bank["opening"], book["opening_balance"])
        self.assertEqual(bank["debit"], book["summary"]["total_debit"])
        self.assertEqual(bank["credit"], book["summary"]["total_credit"])
        self.assertEqual(bank["net"], book["summary"]["net_movement"])
        self.assertEqual(bank["closing"], book["summary"]["closing_balance"])

    def test_48_missing_cash_ledger_clean(self):
        conn = get_connection()
        try:
            conn.execute("DELETE FROM account_ledgers WHERE system_role='CASH'")
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(self.report()["cash"]["debit"], 0)

    def test_49_missing_bank_ledger_clean(self):
        conn = get_connection()
        try:
            conn.execute("DELETE FROM account_ledgers WHERE system_role='BANK'")
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(self.report()["bank"]["credit"], 0)

    def test_50_no_invented_balances(self):
        # Empty day: movement zero, opening/closing still from ledger
        empty = self.report(EMPTY_DAY)
        self.assertEqual(empty["cash"]["debit"], 0)
        self.assertEqual(empty["cash"]["credit"], 0)
        self.assertEqual(empty["cash"]["net"], 0)


# ======================================================================
# STOCK IMPACT
# ======================================================================

class TestDayEndStock(_BaseTest):

    def test_51_purchase_quantity_added(self):
        self.assertEqual(self.report()["stock"]["purchase_added"], 4)

    def test_52_sales_quantity_removed(self):
        self.assertEqual(self.report()["stock"]["sales_removed"], 2)

    def test_53_customer_return_added(self):
        self.assertEqual(self.report()["stock"]["customer_return_added"], 1)

    def test_54_supplier_return_removed(self):
        self.assertEqual(self.report()["stock"]["supplier_return_removed"], 1)

    def test_55_stock_impact_has_no_valuation(self):
        stock = self.report()["stock"]
        self.assertNotIn("value", stock)
        self.assertNotIn("cogs", stock)
        self.assertNotIn("closing_stock", stock)


# ======================================================================
# DATE / FILTER behavior
# ======================================================================

class TestDayEndDates(_BaseTest):

    def test_56_date_preserved(self):
        self.assertEqual(self.report()["date"], DAY)

    def test_57_day_summary_alias(self):
        self.assertEqual(DayEndDAO.get_day_summary(DAY), self.report())

    def test_58_invalid_date_rejected(self):
        with self.assertRaises(DayEndError):
            DayEndDAO.get_day_end_report("bad")

    def test_59_empty_string_date_rejected(self):
        with self.assertRaises(DayEndError):
            DayEndDAO.get_day_end_report("")

    def test_60_invalid_format_rejected(self):
        with self.assertRaises(DayEndError):
            DayEndDAO.get_day_end_report("15/06/2026")

    def test_61_boundary_previous_day_excluded(self):
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO sales_invoices "
                "(bill_no, sale_date, sale_type, customer_id, total_amount, "
                " discount, paid_amount, net_amount) "
                "VALUES ('S-PREV','2026-06-14','Cash',?,999,0,999,999)",
                (self.customer_id,),
            )
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(self.report()["sales"]["amount"], 100)

    def test_62_boundary_next_day_excluded(self):
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO sales_invoices "
                "(bill_no, sale_date, sale_type, customer_id, total_amount, "
                " discount, paid_amount, net_amount) "
                "VALUES ('S-NEXT','2026-06-16','Cash',?,777,0,777,777)",
                (self.customer_id,),
            )
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(self.report()["sales"]["amount"], 100)

    def test_63_historical_date_view_allowed(self):
        report = DayEndDAO.get_day_end_report("2025-01-01")
        self.assertEqual(report["date"], "2025-01-01")


# ======================================================================
# FINANCIAL YEAR safe default
# ======================================================================

class TestDayEndFinancialYear(_BaseTest):

    def test_64_default_date_within_active_fy(self):
        start, end = active_date_range()
        default = DayEndDAO.default_date()
        self.assertGreaterEqual(default, start)
        self.assertLessEqual(default, end)

    def test_65_default_uses_today_when_inside_fy(self):
        conn = get_connection()
        try:
            conn.execute("DELETE FROM financial_years")
            conn.commit()
        finally:
            conn.close()
        create_financial_year("Wide FY", "2020-04-01", "2035-03-31",
                              activate=True)
        from datetime import datetime
        self.assertEqual(
            DayEndDAO.default_date(), datetime.now().strftime("%Y-%m-%d")
        )

    def test_66_default_falls_back_to_fy_end_outside_fy(self):
        conn = get_connection()
        try:
            conn.execute("DELETE FROM financial_years")
            conn.commit()
        finally:
            conn.close()
        create_financial_year("Past FY", "2001-04-01", "2002-03-31",
                              activate=True)
        self.assertEqual(DayEndDAO.default_date(), "2002-03-31")

    def test_67_historical_view_does_not_require_active_fy(self):
        # Historical dates can be viewed regardless of the active FY range
        self.assertEqual(
            DayEndDAO.get_day_end_report("2019-12-31")["date"], "2019-12-31"
        )


# ======================================================================
# READ-ONLY guarantees
# ======================================================================

class TestDayEndReadOnly(_BaseTest):

    def test_68_no_row_count_changes(self):
        before = self.counts()
        self.report()
        self.report(EMPTY_DAY)
        self.assertEqual(before, self.counts())

    def test_69_no_table_content_changes(self):
        before_ledger = self.snapshot("ledger_transactions")
        before_stock = self.snapshot("stock_batches")
        before_ledgers = self.snapshot("account_ledgers")
        self.report()
        self.assertEqual(self.snapshot("ledger_transactions"), before_ledger)
        self.assertEqual(self.snapshot("stock_batches"), before_stock)
        self.assertEqual(self.snapshot("account_ledgers"), before_ledgers)

    def test_70_no_stock_change(self):
        before = self.snapshot("stock_batches")
        self.report()
        self.assertEqual(self.snapshot("stock_batches"), before)

    def test_71_no_ledger_change(self):
        before = self.snapshot("ledger_transactions")
        self.report()
        self.assertEqual(self.snapshot("ledger_transactions"), before)

    def test_72_no_accounting_postings(self):
        before = self.counts()["ledger_transactions"]
        self.report()
        self.assertEqual(self.counts()["ledger_transactions"], before)

    def test_73_repeated_generation_unchanged(self):
        self.assertEqual(self.report(), self.report())

    def test_74_no_date_locking_artifacts(self):
        # Nothing in the report writes a lock/closing marker anywhere
        before = self.counts()
        self.report()
        self.assertEqual(before, self.counts())

    def test_75_ledger_balance_unchanged(self):
        cash = LedgerDAO.get_by_system_role("CASH")
        before = LedgerDAO.get_balance(cash["id"])
        self.report()
        self.assertEqual(LedgerDAO.get_balance(cash["id"]), before)


# ======================================================================
# RECONCILIATION
# ======================================================================

class TestDayEndReconciliation(_BaseTest):

    def test_76_reconciliation_section_present(self):
        self.assertIn("reconciliation", self.report())

    def test_77_reconciliation_related_totals(self):
        recon = self.report()["reconciliation"]
        self.assertEqual(recon["sales_net"], 95)
        self.assertEqual(recon["receipts_total"], 20)
        self.assertEqual(recon["cash_movement"], 20)
        self.assertEqual(recon["bank_movement"], -30)

    def test_78_no_invented_difference(self):
        recon = self.report()["reconciliation"]
        self.assertEqual(
            recon["difference"], "Not available from current stored data."
        )

    def test_79_no_difference_in_overall(self):
        self.assertNotIn("difference", self.report()["overall"])

    def test_80_reconciliation_getter_matches(self):
        self.assertEqual(
            DayEndDAO.get_reconciliation(DAY), self.report()["reconciliation"]
        )


# ======================================================================
# PRINT / PDF (headless — reportlab)
# ======================================================================

class TestDayEndPrint(_BaseTest):

    def _items(self, report):
        items = []
        for key in ("sales", "purchases", "returns", "receipts", "payments",
                    "cash", "bank", "stock", "overall", "reconciliation"):
            for metric, value in report[key].items():
                items.append({"item_name": f"{key} | {metric} | {value}"})
        return items

    def _record(self, report):
        return {"voucher_no": report["date"], "voucher_date": report["date"]}

    def test_81_pdf_generation(self):
        report = self.report()
        path = os.path.join(self._tmp, "day_end.pdf")
        output = document_printing.generate_document(
            "Day End", self._record(report), self._items(report), path
        )
        self.assertTrue(os.path.isfile(output))
        with open(output, "rb") as fh:
            self.assertEqual(fh.read(4), b"%PDF")

    def test_82_pdf_preview_contains_title_and_date(self):
        report = self.report()
        preview = document_printing.preview_document(
            "Day End", self._record(report), self._items(report)
        )
        self.assertIn("Day End", preview)
        self.assertIn(DAY, preview)

    def test_83_pdf_contains_all_sections(self):
        report = self.report()
        preview = document_printing.preview_document(
            "Day End", self._record(report), self._items(report)
        )
        for section in ("sales", "purchases", "returns", "receipts",
                        "payments", "cash", "bank", "stock", "overall"):
            self.assertIn(section, preview)

    def test_84_long_report_generation(self):
        # Multi-page capable: many lines generate without error
        items = [{"item_name": f"Line {i} | metric | {i}.00"}
                 for i in range(300)]
        path = os.path.join(self._tmp, "long.pdf")
        output = document_printing.generate_document(
            "Day End", {"voucher_no": DAY, "voucher_date": DAY},
            items, path,
        )
        self.assertTrue(os.path.isfile(output))
        self.assertGreater(os.path.getsize(output), 1000)

    def test_85_longer_report_larger_than_short(self):
        short_items = self._items(self.report())
        long_items = short_items + [
            {"item_name": f"Extra {i} | x | {i}"} for i in range(400)
        ]
        short_path = os.path.join(self._tmp, "short.pdf")
        long_path = os.path.join(self._tmp, "long2.pdf")
        document_printing.generate_document(
            "Day End", self._record(self.report()), short_items, short_path
        )
        document_printing.generate_document(
            "Day End", self._record(self.report()), long_items, long_path
        )
        self.assertGreater(
            os.path.getsize(long_path), os.path.getsize(short_path)
        )

    def test_86_no_mysql_reference_in_dao(self):
        dao_path = __import__(
            "database.day_end_dao", fromlist=["__file__"]
        ).__file__
        text = open(dao_path, encoding="utf-8").read().lower()
        self.assertNotIn("mysql", text)


# ======================================================================
# REGRESSION: other reports/books unchanged by Day End generation
# ======================================================================

class TestDayEndRegression(_BaseTest):

    def test_87_cash_book_unchanged(self):
        before = CashBookDAO.get_cash_book(DAY, DAY)
        self.report()
        self.assertEqual(CashBookDAO.get_cash_book(DAY, DAY), before)

    def test_88_bank_book_unchanged(self):
        before = BankBookDAO.get_bank_book(DAY, DAY)
        self.report()
        self.assertEqual(BankBookDAO.get_bank_book(DAY, DAY), before)

    def test_89_sales_report_unchanged(self):
        before = SalesReportDAO.get_sales_report()
        self.report()
        self.assertEqual(SalesReportDAO.get_sales_report(), before)

    def test_90_purchase_report_unchanged(self):
        before = PurchaseReportDAO.get_purchase_report()
        self.report()
        self.assertEqual(PurchaseReportDAO.get_purchase_report(), before)

    def test_91_trial_balance_unchanged(self):
        before = TrialBalanceDAO.get_trial_balance()
        self.report()
        self.assertEqual(TrialBalanceDAO.get_trial_balance(), before)

    def test_92_trial_balance_unchanged_by_day_end(self):
        # The raw fixture holds unposted source rows, so the Trial Balance
        # is not expected to be balanced — but generating Day End must not
        # change it in any way.
        before = TrialBalanceDAO.verify_balanced()
        report_before = TrialBalanceDAO.get_trial_balance()
        self.report()
        self.assertEqual(TrialBalanceDAO.verify_balanced(), before)
        self.assertEqual(TrialBalanceDAO.get_trial_balance(), report_before)

    def test_93_day_end_does_not_import_posting_engine(self):
        source = open(
            __import__("database.day_end_dao", fromlist=["__file__"]).__file__,
            encoding="utf-8",
        ).read()
        self.assertNotIn("accounting_posting", source)
        self.assertNotIn("posting_engine", source)


# ======================================================================
# UI (skip without PySide6; run in the development environment)
# ======================================================================

@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class TestDayEndUI(_BaseTest):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.app = QApplication.instance() or QApplication([])

    def test_94_page_opens(self):
        page = DayEndPage()
        self.assertIsNotNone(page)

    def test_95_page_has_business_date_and_buttons(self):
        from PySide6.QtWidgets import QDateEdit, QPushButton
        page = DayEndPage()
        self.assertIsNotNone(page.findChild(QDateEdit))
        texts = {b.text() for b in page.findChildren(QPushButton)}
        self.assertIn("Generate / Refresh", texts)
        self.assertIn("Print / PDF", texts)
        self.assertIn("Generate", texts)

    def test_96_page_renders_rows_for_selected_date(self):
        from PySide6.QtCore import QDate
        page = DayEndPage()
        page._date.setDate(QDate(2026, 6, 15))
        self.assertGreater(page._table.rowCount(), 0)
        self.assertIn("Business Date: 2026-06-15", page._summary.text())

    def test_97_page_empty_state_message(self):
        from PySide6.QtCore import QDate
        page = DayEndPage()
        page._date.setDate(QDate(2026, 7, 1))
        self.assertIn(
            "No transactions found for the selected date.", page._summary.text()
        )

    def test_98_page_shows_read_only_note(self):
        from PySide6.QtCore import QDate
        page = DayEndPage()
        page._date.setDate(QDate(2026, 6, 15))
        self.assertIn("Read-only", page._summary.text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
