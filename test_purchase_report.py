"""Phase 5B — Purchase Report tests.

38 tests:
   1-4:   Empty report, single purchase, multiple purchases,
          multiple items per purchase
   5-11:  Filters (dates, supplier, item, company, invoice no, voucher no,
          batch no)
  12-20:  Totals, multiple suppliers, multiple batches
  21-23:  Lifecycle: edited, deleted, persistence
  24-26:  Read-only guarantee, posting unchanged, stock unchanged
  27-38:  Regression — all modules, reports and masters still work
"""

import os
import sqlite3
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.connection import get_connection, init_database, get_db_path
from database.account_roles import ensure_system_ledgers
from database.accounting_posting import SOURCE_PURCHASE_INVOICE, PostingEngine
from database.purchase_report_dao import PurchaseReportDAO
from database.sales_report_dao import SalesReportDAO
from database.trial_balance_dao import TrialBalanceDAO
from database.profit_loss_dao import ProfitLossDAO
from database.balance_sheet_dao import BalanceSheetDAO
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
from database.company_dao import CompanyDAO
from database.unit_dao import UnitDAO
from database.drug_dao import DrugDAO
from database.item_dao import ItemDAO
from database.stock_dao import StockDAO
from database.doctor_dao import DoctorDAO

try:
    from PySide6.QtWidgets import QApplication
    from screens.purchase_report import PurchaseReportPage

    HAS_PYSIDE6 = True
    _PYSIDE_SKIP_REASON = ""
except ImportError as _exc:  # pragma: no cover
    HAS_PYSIDE6 = False
    _PYSIDE_SKIP_REASON = f"PySide6 not available ({_exc})"

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


class _BaseTest(unittest.TestCase):
    _DB_PATH = os.path.join(os.path.dirname(__file__), "_test_purchase_report.db")

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
        self.supplier_b_id = SupplierDAO.insert("SupplierB")
        self.item_id = ItemDAO.insert(
            item_name="ItemA", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="10x10",
        )
        self.item_b_id = ItemDAO.insert(
            item_name="ItemB", unit_id=self.unit_id,
            company_id=self.company_b_id, pack_size="10x10",
        )
        ensure_system_ledgers()

        self.engine = PostingEngine()
        self._pv_count = 0

    # ── helper ───────────────────────────────────────────────────────
    def _purchase(self, *, voucher_date="2026-01-15", voucher_no=None,
                  supplier_id=None, invoice_no="INV-001",
                  invoice_date="2026-01-14", lines=None,
                  bill_discount=0.0, purchase_type="Credit", paid=None):
        """Insert a purchase.

        lines: configs with keys item_id, batch_no, pay_qty, free_qty,
        rate, mrp, discount (stored, not applied), gst_percent.
        Line amount follows the existing calculation:
        (pay_qty + free_qty) × rate.
        """
        self._pv_count += 1
        voucher_no = voucher_no or f"PV-{self._pv_count:04d}"

        items = []
        total = 0.0
        gst_total = 0.0
        for cfg in lines:
            amount = round(
                (cfg["pay_qty"] + cfg["free_qty"]) * cfg["rate"], 2
            )
            gst_amount = round(amount * cfg["gst_percent"] / 100.0, 2)
            total += amount
            gst_total += gst_amount
            items.append({
                "item_id": cfg["item_id"], "pack_size": "10x10",
                "pay_qty": cfg["pay_qty"], "free_qty": cfg["free_qty"],
                "batch_no": cfg["batch_no"], "expiry": "12/27",
                "rate": cfg["rate"], "mrp": cfg["mrp"],
                "discount": cfg.get("discount", 0.0),
                "gst_percent": cfg["gst_percent"],
                "gst_amount": gst_amount, "amount": amount,
                "purchase_rate": cfg["rate"], "net_rate": cfg["rate"],
                "pp": cfg["rate"],
            })
        total = round(total, 2)
        gst_total = round(gst_total, 2)
        net = round(total + gst_total - bill_discount, 2)
        if paid is None:
            paid = net if purchase_type == "Cash" else 0.0

        return PurchaseDAO.insert_invoice(
            voucher_no=voucher_no, voucher_date=voucher_date,
            voucher_time="", purchase_type=purchase_type,
            supplier_id=supplier_id or self.supplier_id,
            invoice_no=invoice_no, invoice_date=invoice_date,
            invoice_net_amount=net, bill_discount=bill_discount,
            due_date="", total_amount=total, gst_amount=gst_total,
            debit_note_amount=0.0, other_amount=0.0,
            paid_amount=paid, round_off=0.0, net_amount=net,
            remarks="", items=items,
        )

    def _line(self, item_id=None, batch_no="BATCH-A", pay_qty=10.0,
              free_qty=2.0, rate=40.0, mrp=50.0, discount=0.0,
              gst_percent=0.0):
        return {
            "item_id": item_id or self.item_id, "batch_no": batch_no,
            "pay_qty": pay_qty, "free_qty": free_qty, "rate": rate,
            "mrp": mrp, "discount": discount, "gst_percent": gst_percent,
        }

    def _stock_qty(self, batch_no="BATCH-A"):
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT stock_qty FROM stock_batches "
                "WHERE batch_no = ? ORDER BY id LIMIT 1",
                (batch_no,),
            ).fetchone()
            return row["stock_qty"] if row else None
        finally:
            conn.close()


# ======================================================================
# 1-4: Basics
# ======================================================================

class TestBasics(_BaseTest):

    def test_01_empty_report(self):
        report = PurchaseReportDAO.get_purchase_report()
        self.assertEqual(report["rows"], [])
        self.assertEqual(report["summary"]["total_bills"], 0)
        self.assertEqual(report["summary"]["total_net"], 0.0)

    def test_02_single_purchase(self):
        self._purchase(
            voucher_date="2026-01-15", invoice_no="INV-777",
            invoice_date="2026-01-14",
            lines=[self._line(pay_qty=10, free_qty=2, rate=40,
                              mrp=50, gst_percent=5)],
        )
        report = PurchaseReportDAO.get_purchase_report()
        self.assertEqual(len(report["rows"]), 1)
        r = report["rows"][0]
        self.assertEqual(r["voucher_no"], "PV-0001")
        self.assertEqual(r["voucher_date"], "2026-01-15")
        self.assertEqual(r["invoice_no"], "INV-777")
        self.assertEqual(r["invoice_date"], "2026-01-14")
        self.assertEqual(r["supplier_name"], "SupplierA")
        self.assertEqual(r["item_name"], "ItemA")
        self.assertEqual(r["company_name"], "CompanyA")
        self.assertEqual(r["pack_size"], "10x10")
        self.assertEqual(r["batch_no"], "BATCH-A")
        self.assertEqual(r["expiry"], "12/27")
        self.assertEqual(r["pay_qty"], 10)
        self.assertEqual(r["free_qty"], 2)
        self.assertEqual(r["rate"], 40.0)
        self.assertEqual(r["mrp"], 50.0)
        self.assertEqual(r["gst_percent"], 5)
        self.assertEqual(r["gst_amount"], 24.0)   # 480 × 5%
        self.assertEqual(r["amount"], 480.0)      # 12 × 40
        self.assertEqual(report["summary"]["total_bills"], 1)

    def test_03_multiple_purchases(self):
        self._purchase(voucher_date="2026-01-10",
                       lines=[self._line(pay_qty=5, free_qty=0, rate=40)])
        self._purchase(voucher_date="2026-01-20",
                       lines=[self._line(pay_qty=8, free_qty=1, rate=40)])
        report = PurchaseReportDAO.get_purchase_report()
        self.assertEqual(len(report["rows"]), 2)
        self.assertEqual(report["summary"]["total_bills"], 2)
        self.assertEqual(report["summary"]["total_pay_qty"], 13.0)

    def test_04_multiple_items_one_purchase(self):
        self._purchase(lines=[
            self._line(pay_qty=10, free_qty=0, rate=40),
            self._line(item_id=self.item_b_id, pay_qty=5, free_qty=1,
                       rate=20),
        ])
        report = PurchaseReportDAO.get_purchase_report()
        self.assertEqual(len(report["rows"]), 2)
        self.assertEqual(report["summary"]["total_bills"], 1)
        self.assertEqual(report["summary"]["total_lines"], 2)
        # 400 + 120 = 520 gross
        self.assertEqual(report["summary"]["total_gross"], 520.0)


# ======================================================================
# 5-11: Filters
# ======================================================================

class TestFilters(_BaseTest):

    def setUp(self):
        super().setUp()
        self._purchase(
            voucher_date="2026-01-10", voucher_no="PV-JAN",
            invoice_no="INV-JAN", invoice_date="",
            lines=[self._line(batch_no="BATCH-JAN", pay_qty=1,
                              free_qty=0, rate=10)],
        )
        self._purchase(
            voucher_date="2026-02-10", voucher_no="PV-FEB",
            invoice_no="INV-FEB", invoice_date="2026-02-09",
            supplier_id=self.supplier_b_id,
            lines=[self._line(item_id=self.item_b_id, batch_no="BATCH-FEB",
                              pay_qty=2, free_qty=0, rate=10)],
        )
        self._purchase(
            voucher_date="2026-03-10", voucher_no="PV-MAR",
            invoice_no="INV-MAR", invoice_date="2026-03-09",
            lines=[self._line(batch_no="BATCH-MAR", pay_qty=3,
                              free_qty=0, rate=10)],
        )

    def test_05_date_filtering(self):
        report = PurchaseReportDAO.get_purchase_report(
            from_date="2026-02-01", to_date="2026-02-28"
        )
        self.assertEqual([r["voucher_no"] for r in report["rows"]], ["PV-FEB"])

        # Inclusive single-day bounds
        report = PurchaseReportDAO.get_purchase_report(
            from_date="2026-02-10", to_date="2026-02-10"
        )
        self.assertEqual(len(report["rows"]), 1)

        # Lower bound inclusive; no dates -> all
        self.assertEqual(
            len(PurchaseReportDAO.get_purchase_report(
                from_date="2026-01-10")["rows"]), 3
        )
        self.assertEqual(
            len(PurchaseReportDAO.get_purchase_report()["rows"]), 3
        )

    def test_06_supplier_filtering(self):
        report = PurchaseReportDAO.get_purchase_report(
            supplier_id=self.supplier_b_id
        )
        self.assertEqual([r["voucher_no"] for r in report["rows"]], ["PV-FEB"])

    def test_07_item_filtering(self):
        report = PurchaseReportDAO.get_purchase_report(item_id=self.item_b_id)
        self.assertEqual([r["voucher_no"] for r in report["rows"]], ["PV-FEB"])

    def test_08_company_filtering(self):
        report = PurchaseReportDAO.get_purchase_report(
            company_id=self.company_b_id
        )
        self.assertEqual(len(report["rows"]), 1)
        self.assertEqual(report["rows"][0]["company_name"], "CompanyB")

    def test_09_invoice_number_filtering(self):
        report = PurchaseReportDAO.get_purchase_report(invoice_no="FEB")
        self.assertEqual([r["voucher_no"] for r in report["rows"]], ["PV-FEB"])

    def test_10_voucher_number_filtering(self):
        report = PurchaseReportDAO.get_purchase_report(voucher_no="MAR")
        self.assertEqual([r["voucher_no"] for r in report["rows"]], ["PV-MAR"])

    def test_11_batch_number_filtering(self):
        report = PurchaseReportDAO.get_purchase_report(batch_no="BATCH-FEB")
        self.assertEqual([r["voucher_no"] for r in report["rows"]], ["PV-FEB"])


# ======================================================================
# 12-20: Totals, suppliers, batches
# ======================================================================

class TestTotals(_BaseTest):

    def test_12_total_pay_qty(self):
        self._purchase(lines=[
            self._line(pay_qty=10, free_qty=0),
            self._line(item_id=self.item_b_id, pay_qty=5, free_qty=0),
        ])
        self.assertEqual(
            PurchaseReportDAO.get_summary()["total_pay_qty"], 15.0
        )

    def test_13_total_free_qty(self):
        self._purchase(lines=[
            self._line(pay_qty=10, free_qty=2),
            self._line(item_id=self.item_b_id, pay_qty=5, free_qty=3),
        ])
        self.assertEqual(
            PurchaseReportDAO.get_summary()["total_free_qty"], 5.0
        )

    def test_14_total_quantity(self):
        self._purchase(lines=[
            self._line(pay_qty=10, free_qty=2),
            self._line(item_id=self.item_b_id, pay_qty=5, free_qty=3),
        ])
        s = PurchaseReportDAO.get_summary()
        self.assertEqual(s["total_qty"], 20.0)  # pay + free

    def test_15_gross_amount(self):
        # gross = Σ line amount = Σ (pay+free) × rate
        self._purchase(lines=[
            self._line(pay_qty=10, free_qty=2, rate=40, gst_percent=5),
            self._line(item_id=self.item_b_id, pay_qty=5, free_qty=0,
                       rate=20, gst_percent=12),
        ])
        s = PurchaseReportDAO.get_summary()
        self.assertEqual(s["total_gross"], 580.0)  # 480 + 100

    def test_16_gst_amount(self):
        self._purchase(lines=[
            self._line(pay_qty=10, free_qty=2, rate=40, gst_percent=5),
            self._line(item_id=self.item_b_id, pay_qty=5, free_qty=0,
                       rate=20, gst_percent=12),
        ])
        # 480×5% = 24.00 ; 100×12% = 12.00
        self.assertEqual(
            PurchaseReportDAO.get_summary()["total_gst"], 36.0
        )

    def test_17_discount(self):
        # Stored line discount (not applied to amount) + bill discount
        self._purchase(
            bill_discount=4.0,
            lines=[self._line(pay_qty=10, free_qty=2, rate=40,
                              discount=6.0)],
        )
        report = PurchaseReportDAO.get_purchase_report()
        # column shows the stored line discount
        self.assertEqual(report["rows"][0]["discount"], 6.0)
        # summary = line discounts + bill discount
        self.assertEqual(report["summary"]["total_discount"], 10.0)

    def test_18_net_amount(self):
        # net = total_amount + gst − bill_discount (stored formula)
        self._purchase(
            bill_discount=4.0,
            lines=[self._line(pay_qty=10, free_qty=2, rate=40,
                              gst_percent=5)],
        )
        # 480 + 24 − 4 = 500
        self.assertEqual(PurchaseReportDAO.get_summary()["total_net"], 500.0)

    def test_19_multiple_suppliers(self):
        self._purchase(voucher_no="PV-S1", supplier_id=self.supplier_id,
                       lines=[self._line(pay_qty=1, free_qty=0, rate=10)])
        self._purchase(voucher_no="PV-S2", supplier_id=self.supplier_b_id,
                       lines=[self._line(pay_qty=1, free_qty=0, rate=20)])
        report = PurchaseReportDAO.get_purchase_report()
        names = {r["voucher_no"]: r["supplier_name"] for r in report["rows"]}
        self.assertEqual(names["PV-S1"], "SupplierA")
        self.assertEqual(names["PV-S2"], "SupplierB")
        # Filter by each
        self.assertEqual(
            len(PurchaseReportDAO.get_purchase_report(
                supplier_id=self.supplier_id)["rows"]), 1
        )

    def test_20_multiple_batches(self):
        self._purchase(lines=[
            self._line(batch_no="BATCH-A", pay_qty=1, free_qty=0, rate=10),
            self._line(batch_no="BATCH-B", pay_qty=1, free_qty=0, rate=10),
        ])
        report = PurchaseReportDAO.get_purchase_report()
        batches = sorted(r["batch_no"] for r in report["rows"])
        self.assertEqual(batches, ["BATCH-A", "BATCH-B"])
        self.assertEqual(report["summary"]["total_net"], 20.0)


# ======================================================================
# 21-23: Lifecycle
# ======================================================================

class TestLifecycle(_BaseTest):

    def test_21_edited_purchase_current_values(self):
        inv_id = self._purchase(
            voucher_no="PV-EDIT",
            lines=[self._line(pay_qty=10, free_qty=0, rate=40)],
        )
        # Edit: 10 -> 25 pay qty (amount 1000)
        PurchaseDAO.update_invoice(
            invoice_id=inv_id, voucher_no="PV-EDIT",
            voucher_date="2026-01-15", voucher_time="",
            purchase_type="Credit", supplier_id=self.supplier_id,
            invoice_no="INV-EDIT", invoice_date="2026-01-14",
            invoice_net_amount=1000.0, bill_discount=0.0, due_date="",
            total_amount=1000.0, gst_amount=0.0, debit_note_amount=0.0,
            other_amount=0.0, paid_amount=0.0, round_off=0.0,
            net_amount=1000.0, remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": 25, "free_qty": 0, "batch_no": "BATCH-A",
                "expiry": "12/27", "rate": 40.0, "mrp": 50.0,
                "discount": 0, "gst_percent": 0, "gst_amount": 0,
                "amount": 1000.0, "purchase_rate": 40.0,
                "net_rate": 40.0, "pp": 40.0,
            }],
        )
        report = PurchaseReportDAO.get_purchase_report()
        self.assertEqual(len(report["rows"]), 1)
        self.assertEqual(report["rows"][0]["pay_qty"], 25)
        self.assertEqual(report["rows"][0]["amount"], 1000.0)
        self.assertEqual(report["summary"]["total_net"], 1000.0)

    def test_22_deleted_purchase_excluded(self):
        self._purchase(voucher_no="PV-KEEP",
                       lines=[self._line(pay_qty=1, free_qty=0, rate=10)])
        drop = self._purchase(
            voucher_no="PV-DROP",
            lines=[self._line(batch_no="BATCH-DROP", pay_qty=1,
                              free_qty=0, rate=20)],
        )
        PurchaseDAO.delete_invoice(drop)

        report = PurchaseReportDAO.get_purchase_report()
        self.assertEqual([r["voucher_no"] for r in report["rows"]], ["PV-KEEP"])
        self.assertEqual(report["summary"]["total_bills"], 1)
        self.assertEqual(report["summary"]["total_net"], 10.0)

    def test_23_persistence_after_restart(self):
        self._purchase(voucher_no="PV-PERSIST",
                       lines=[self._line(pay_qty=4, free_qty=1, rate=10)])
        report = PurchaseReportDAO.get_purchase_report()

        fresh = sqlite3.connect(get_db_path())
        fresh.row_factory = sqlite3.Row
        try:
            row = fresh.execute(
                "SELECT COUNT(*) AS n FROM purchase_invoice_items"
            ).fetchone()
        finally:
            fresh.close()

        self.assertEqual(row["n"], len(report["rows"]))
        again = PurchaseReportDAO.get_purchase_report()
        self.assertEqual(again["summary"], report["summary"])
        self.assertEqual(again["rows"], report["rows"])


# ======================================================================
# 24-26: Read-only, posting, stock
# ======================================================================

class TestSafety(_BaseTest):

    def test_24_report_is_read_only(self):
        self._purchase(lines=[self._line()])
        conn = get_connection()
        try:
            counts_before = {
                t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in TABLES
            }
            purchases_before = [
                tuple(r) for r in conn.execute(
                    "SELECT * FROM purchase_invoices ORDER BY id"
                ).fetchall()
            ]
        finally:
            conn.close()

        # Generate the report with several filter combinations
        PurchaseReportDAO.get_purchase_report()
        PurchaseReportDAO.get_purchase_report(batch_no="BATCH-A")
        PurchaseReportDAO.get_summary()

        conn = get_connection()
        try:
            counts_after = {
                t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in TABLES
            }
            purchases_after = [
                tuple(r) for r in conn.execute(
                    "SELECT * FROM purchase_invoices ORDER BY id"
                ).fetchall()
            ]
        finally:
            conn.close()

        self.assertEqual(counts_before, counts_after)
        self.assertEqual(purchases_before, purchases_after)

    def test_25_purchase_posting_unchanged(self):
        inv_id = self._purchase(
            lines=[self._line(pay_qty=10, free_qty=2, rate=40,
                              gst_percent=5)],
        )
        # Credit purchase: PURCHASE debit + supplier credit, net = 504
        rows = self.engine.get_posting_rows(SOURCE_PURCHASE_INVOICE, inv_id)
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(r["debit"] for r in rows), 504.0)
        self.assertEqual(sum(r["credit"] for r in rows), 504.0)
        self.assertTrue(self.engine.is_posted(SOURCE_PURCHASE_INVOICE, inv_id))

    def test_26_stock_unchanged(self):
        self._purchase(lines=[self._line(pay_qty=10, free_qty=2, rate=40)])
        # stock = pay + free (existing behavior)
        self.assertEqual(self._stock_qty(), 12.0)
        # Generating the report changes nothing
        PurchaseReportDAO.get_purchase_report()
        self.assertEqual(self._stock_qty(), 12.0)


# ======================================================================
# 27-38: Regression
# ======================================================================

class TestRegression(_BaseTest):

    def test_27_counter_sale_still_works(self):
        self._purchase(lines=[self._line(pay_qty=10, free_qty=0, rate=40)])
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        sid = SalesDAO.insert_invoice(
            bill_no="CS-0001", sale_date="2026-02-01", sale_time="",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="", doctor_id=None, discount=0, paid_amount=50,
            total_amount=50, round_off=0, net_amount=50, remarks="",
            items=[{
                "item_id": self.item_id, "stock_batch_id": batches[0]["id"],
                "pack_size": "10x10", "location": "", "batch_no": "BATCH-A",
                "expiry": "12/27", "mrp": 50, "sale_qty": 1,
                "discount_amount": 0, "amount": 50,
            }],
        )
        self.assertGreater(sid, 0)

    def test_28_credit_note_still_works(self):
        self._purchase(lines=[self._line(pay_qty=10, free_qty=0, rate=40)])
        batch = StockDAO.get_stock_batches_for_item(self.item_id)[0]
        cn_id = CreditNoteDAO.insert_credit_note(
            {"voucher_date": "2026-02-01", "cn_date": "2026-02-01",
             "cn_type": "Customer", "customer_id": self.customer_id,
             "total_amount": 40.0, "ledger_amount": 40.0, "remarks": ""},
            [{
                "item_id": self.item_id, "stock_batch_id": batch["id"],
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40, "mrp": 50,
                "return_qty": 1, "less_amount": 0, "amount": 40,
                "return_reason": "", "price_factor": 1.0,
            }],
        )
        self.assertGreater(cn_id, 0)

    def test_29_debit_note_still_works(self):
        self._purchase(lines=[self._line(pay_qty=10, free_qty=0, rate=40)])
        batch = StockDAO.get_stock_batches_for_item(self.item_id)[0]
        dn_id = DebitNoteDAO.insert_debit_note(
            {"voucher_date": "2026-02-01", "voucher_time": "",
             "dn_date": "2026-02-01", "dn_type": "Supplier",
             "supplier_id": self.supplier_id, "total_amount": 60.0,
             "ledger_amount": 60.0, "remarks": ""},
            [{
                "item_id": self.item_id, "stock_batch_id": batch["id"],
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40, "mrp": 50,
                "return_qty": 1.5, "less_amount": 0, "amount": 60,
                "return_reason": "", "price_factor": 1.0,
            }],
        )
        self.assertGreater(dn_id, 0)

    def test_30_supplier_payment_still_works(self):
        pid = SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-02-01", "payment_time": "",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 30.0, "reference_no": "", "remarks": "",
        })
        self.assertGreater(pid, 0)

    def test_31_customer_receipt_still_works(self):
        rid = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-02-01", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 20.0, "reference_no": "", "remarks": "",
        })
        self.assertGreater(rid, 0)

    def test_32_journal_entry_still_works(self):
        cash = LedgerDAO.get_by_system_role("CASH")
        bank = LedgerDAO.get_by_system_role("BANK")
        je_id = JournalDAO.insert_entry(
            {"entry_date": "2026-02-01", "narration": "Reg"},
            [
                {"ledger_id": cash["id"], "description": "",
                 "debit": 10.0, "credit": 0.0},
                {"ledger_id": bank["id"], "description": "",
                 "debit": 0.0, "credit": 10.0},
            ],
        )
        self.assertGreater(je_id, 0)

    def test_33_trial_balance_still_works(self):
        self._purchase(lines=[self._line()])
        self.assertTrue(TrialBalanceDAO.verify_balanced())
        report = TrialBalanceDAO.get_trial_balance()
        self.assertGreater(report["totals"]["total_debit"], 0.0)

    def test_34_profit_loss_still_works(self):
        self._purchase(lines=[self._line()])
        report = ProfitLossDAO.get_profit_loss()
        self.assertIn("totals", report)
        self.assertIsInstance(ProfitLossDAO.get_totals(), dict)

    def test_35_balance_sheet_still_works(self):
        self._purchase(lines=[self._line()])
        report = BalanceSheetDAO.get_balance_sheet()
        self.assertIn("totals", report)
        self.assertIsInstance(BalanceSheetDAO.get_totals(), dict)

    def test_36_stock_master_still_works(self):
        self._purchase(lines=[self._line(pay_qty=10, free_qty=2, rate=40)])
        all_stock = StockDAO.get_all()
        self.assertEqual(len(all_stock), 1)
        self.assertEqual(all_stock[0]["stock_qty"], 12.0)

    def test_37_sales_report_still_works(self):
        self._purchase(lines=[self._line(pay_qty=10, free_qty=0, rate=40)])
        batch = StockDAO.get_stock_batches_for_item(self.item_id)[0]
        SalesDAO.insert_invoice(
            bill_no="CS-0001", sale_date="2026-02-01", sale_time="",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="", doctor_id=None, discount=0, paid_amount=50,
            total_amount=50, round_off=0, net_amount=50, remarks="",
            items=[{
                "item_id": self.item_id, "stock_batch_id": batch["id"],
                "pack_size": "10x10", "location": "", "batch_no": "BATCH-A",
                "expiry": "12/27", "mrp": 50, "sale_qty": 1,
                "discount_amount": 0, "amount": 50,
            }],
        )
        report = SalesReportDAO.get_sales_report()
        self.assertEqual(len(report["rows"]), 1)
        self.assertEqual(report["summary"]["total_net"], 50.0)

    def test_38_all_master_screens_still_work(self):
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
