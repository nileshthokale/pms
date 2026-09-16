"""Phase 5E — GST Report tests.

41 tests:
    1-4:   Empty report, single purchase GST, multiple purchases, multiple items
    5-12:  Filters (dates, supplier, item, company, GST %, invoice, voucher, combo)
   13-19:  Totals, rate summary, multiple suppliers, multiple rates
   20-22:  Lifecycle: edited, deleted, persistence
   23-27:  Read-only guarantee, no invented data, posting unchanged, stock unchanged
   28-41:  Regression — all modules, reports and masters still work
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
from database.gst_report_dao import GSTReportDAO
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
    from screens.gst_report import GSTReportPage

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
    _DB_PATH = os.path.join(os.path.dirname(__file__), "_test_gst_report.db")

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
        """Insert a purchase with GST amounts stored per line."""
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
        report = GSTReportDAO.get_purchase_gst_report()
        self.assertEqual(report["rows"], [])
        self.assertEqual(report["summary"]["total_bills"], 0)
        self.assertEqual(report["summary"]["total_gst"], 0.0)

    def test_02_single_purchase_gst(self):
        self._purchase(
            voucher_date="2026-01-15", invoice_no="INV-777",
            invoice_date="2026-01-14",
            lines=[self._line(pay_qty=10, free_qty=2, rate=40,
                              mrp=50, gst_percent=5)],
        )
        report = GSTReportDAO.get_purchase_gst_report()
        self.assertEqual(len(report["rows"]), 1)
        r = report["rows"][0]
        self.assertEqual(r["voucher_no"], "PV-0001")
        self.assertEqual(r["voucher_date"], "2026-01-15")
        self.assertEqual(r["invoice_no"], "INV-777")
        self.assertEqual(r["invoice_date"], "2026-01-14")
        self.assertEqual(r["supplier_name"], "SupplierA")
        self.assertEqual(r["item_name"], "ItemA")
        self.assertEqual(r["company_name"], "CompanyA")
        self.assertEqual(r["batch_no"], "BATCH-A")
        self.assertEqual(r["pay_qty"], 10)
        self.assertEqual(r["free_qty"], 2)
        self.assertEqual(r["gst_percent"], 5)
        # taxable_amount = (10+2)*40 = 480
        self.assertEqual(r["taxable_amount"], 480.0)
        # gst_amount = round(480 * 5 / 100) = 24
        self.assertEqual(r["gst_amount"], 24.0)
        self.assertEqual(r["amount"], 480.0)
        self.assertEqual(report["summary"]["total_bills"], 1)
        self.assertEqual(report["summary"]["total_gst"], 24.0)

    def test_03_multiple_purchases(self):
        self._purchase(voucher_date="2026-01-10",
                       lines=[self._line(pay_qty=5, free_qty=0, rate=40,
                                         gst_percent=5)])
        self._purchase(voucher_date="2026-01-20",
                       lines=[self._line(pay_qty=8, free_qty=1, rate=40,
                                         gst_percent=5)])
        report = GSTReportDAO.get_purchase_gst_report()
        self.assertEqual(len(report["rows"]), 2)
        self.assertEqual(report["summary"]["total_bills"], 2)

    def test_04_multiple_items_one_purchase(self):
        self._purchase(lines=[
            self._line(pay_qty=10, free_qty=0, rate=40, gst_percent=5),
            self._line(item_id=self.item_b_id, pay_qty=5, free_qty=1,
                       rate=100, mrp=120, gst_percent=12),
        ])
        report = GSTReportDAO.get_purchase_gst_report()
        self.assertEqual(len(report["rows"]), 2)
        # ItemA: (10+0)*40 = 400, gst = 20
        # ItemB: (5+1)*100 = 600, gst = 72
        self.assertAlmostEqual(report["summary"]["total_taxable"], 1000.0)
        self.assertAlmostEqual(report["summary"]["total_gst"], 92.0)


# ======================================================================
# 5-12: Filters
# ======================================================================

class TestFilters(_BaseTest):

    def test_05_date_from(self):
        self._purchase(voucher_date="2026-01-10",
                       lines=[self._line(gst_percent=5)])
        self._purchase(voucher_date="2026-02-10",
                       lines=[self._line(gst_percent=5)])
        report = GSTReportDAO.get_purchase_gst_report(from_date="2026-02-01")
        self.assertEqual(len(report["rows"]), 1)
        self.assertEqual(report["rows"][0]["voucher_date"], "2026-02-10")

    def test_06_date_to(self):
        self._purchase(voucher_date="2026-01-10",
                       lines=[self._line(gst_percent=5)])
        self._purchase(voucher_date="2026-02-10",
                       lines=[self._line(gst_percent=5)])
        report = GSTReportDAO.get_purchase_gst_report(to_date="2026-01-31")
        self.assertEqual(len(report["rows"]), 1)
        self.assertEqual(report["rows"][0]["voucher_date"], "2026-01-10")

    def test_07_supplier_filter(self):
        self._purchase(supplier_id=self.supplier_id,
                       lines=[self._line(gst_percent=5)])
        self._purchase(supplier_id=self.supplier_b_id,
                       lines=[self._line(gst_percent=5)])
        report = GSTReportDAO.get_purchase_gst_report(
            supplier_id=self.supplier_id
        )
        self.assertEqual(len(report["rows"]), 1)
        self.assertEqual(report["rows"][0]["supplier_name"], "SupplierA")

    def test_08_item_filter(self):
        self._purchase(lines=[
            self._line(item_id=self.item_id, gst_percent=5),
        ])
        self._purchase(lines=[
            self._line(item_id=self.item_b_id, gst_percent=5),
        ])
        report = GSTReportDAO.get_purchase_gst_report(item_id=self.item_id)
        self.assertEqual(len(report["rows"]), 1)
        self.assertEqual(report["rows"][0]["item_name"], "ItemA")

    def test_09_company_filter(self):
        self._purchase(lines=[
            self._line(item_id=self.item_id, gst_percent=5),
        ])
        self._purchase(lines=[
            self._line(item_id=self.item_b_id, gst_percent=5),
        ])
        report = GSTReportDAO.get_purchase_gst_report(
            company_id=self.company_id
        )
        self.assertEqual(len(report["rows"]), 1)
        self.assertEqual(report["rows"][0]["company_name"], "CompanyA")

    def test_10_gst_percent_filter(self):
        self._purchase(lines=[self._line(gst_percent=5)])
        self._purchase(lines=[self._line(gst_percent=12)])
        report = GSTReportDAO.get_purchase_gst_report(gst_percent=5.0)
        self.assertEqual(len(report["rows"]), 1)
        self.assertEqual(report["rows"][0]["gst_percent"], 5)

    def test_11_invoice_no_filter(self):
        self._purchase(invoice_no="GST-111",
                       lines=[self._line(gst_percent=5)])
        self._purchase(invoice_no="GST-222",
                       lines=[self._line(gst_percent=5)])
        report = GSTReportDAO.get_purchase_gst_report(invoice_no="GST-111")
        self.assertEqual(len(report["rows"]), 1)
        self.assertEqual(report["rows"][0]["invoice_no"], "GST-111")

    def test_12_voucher_no_filter(self):
        self._purchase(voucher_no="PV-1001",
                       lines=[self._line(gst_percent=5)])
        self._purchase(voucher_no="PV-2001",
                       lines=[self._line(gst_percent=5)])
        report = GSTReportDAO.get_purchase_gst_report(voucher_no="PV-1001")
        self.assertEqual(len(report["rows"]), 1)
        self.assertEqual(report["rows"][0]["voucher_no"], "PV-1001")


# ======================================================================
# 13-19: Totals, rate summary, multiple suppliers/rates
# ======================================================================

class TestTotalsAndRateSummary(_BaseTest):

    def test_13_totals_single_invoice(self):
        self._purchase(
            voucher_date="2026-01-15",
            lines=[self._line(pay_qty=10, free_qty=2, rate=40,
                              gst_percent=5)],
        )
        s = GSTReportDAO.get_summary()
        # taxable = 480, gst = 24
        self.assertEqual(s["total_bills"], 1)
        self.assertEqual(s["total_lines"], 1)
        self.assertEqual(s["total_taxable"], 480.0)
        self.assertEqual(s["total_gst"], 24.0)

    def test_14_totals_multi_line_invoice(self):
        self._purchase(lines=[
            self._line(pay_qty=10, free_qty=0, rate=40, gst_percent=5),
            self._line(item_id=self.item_b_id, pay_qty=5, free_qty=0,
                       rate=100, mrp=120, gst_percent=12),
        ])
        s = GSTReportDAO.get_summary()
        # ItemA: 400, gst 20; ItemB: 500, gst 60
        self.assertEqual(s["total_bills"], 1)
        self.assertEqual(s["total_lines"], 2)
        self.assertEqual(s["total_taxable"], 900.0)
        self.assertEqual(s["total_gst"], 80.0)

    def test_15_rate_summary_groups_by_gst_percent(self):
        self._purchase(lines=[
            self._line(pay_qty=10, free_qty=0, rate=40, gst_percent=5),
        ])
        self._purchase(lines=[
            self._line(pay_qty=5, free_qty=0, rate=100, mrp=120,
                       gst_percent=12),
        ])
        summary = GSTReportDAO.get_gst_rate_summary()
        self.assertEqual(len(summary), 2)
        self.assertEqual(summary[0]["gst_percent"], 5)
        self.assertEqual(summary[0]["taxable_amount"], 400.0)
        self.assertEqual(summary[0]["gst_amount"], 20.0)
        self.assertEqual(summary[1]["gst_percent"], 12)
        self.assertEqual(summary[1]["taxable_amount"], 500.0)
        self.assertEqual(summary[1]["gst_amount"], 60.0)

    def test_16_rate_summary_empty(self):
        summary = GSTReportDAO.get_gst_rate_summary()
        self.assertEqual(summary, [])

    def test_17_rate_summary_with_filters(self):
        self._purchase(supplier_id=self.supplier_id,
                       lines=[self._line(gst_percent=5)])
        self._purchase(supplier_id=self.supplier_b_id,
                       lines=[self._line(gst_percent=12)])
        summary = GSTReportDAO.get_gst_rate_summary(
            supplier_id=self.supplier_id
        )
        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0]["gst_percent"], 5)

    def test_18_multiple_suppliers(self):
        self._purchase(supplier_id=self.supplier_id,
                       lines=[self._line(gst_percent=5)])
        self._purchase(supplier_id=self.supplier_b_id,
                       lines=[self._line(gst_percent=12)])
        report = GSTReportDAO.get_purchase_gst_report()
        self.assertEqual(len(report["rows"]), 2)
        names = {r["supplier_name"] for r in report["rows"]}
        self.assertEqual(names, {"SupplierA", "SupplierB"})

    def test_19_multiple_gst_rates(self):
        self._purchase(lines=[
            self._line(gst_percent=5),
        ])
        self._purchase(lines=[
            self._line(gst_percent=12),
        ])
        self._purchase(lines=[
            self._line(gst_percent=18),
        ])
        report = GSTReportDAO.get_purchase_gst_report()
        self.assertEqual(len(report["rows"]), 3)
        rates = {r["gst_percent"] for r in report["rows"]}
        self.assertEqual(rates, {5, 12, 18})


# ======================================================================
# 20-22: Lifecycle
# ======================================================================

class TestLifecycle(_BaseTest):

    def test_20_edited_purchase_shows_current_values(self):
        inv_id = self._purchase(
            invoice_no="INV-OLD",
            lines=[self._line(pay_qty=10, free_qty=2, rate=40,
                              gst_percent=5)],
        )
        # Original: taxable=480, gst=24
        report1 = GSTReportDAO.get_purchase_gst_report()
        self.assertEqual(report1["rows"][0]["taxable_amount"], 480.0)
        self.assertEqual(report1["rows"][0]["gst_amount"], 24.0)

        # Edit the invoice: change qty from 12→20 (taxable=800, gst=40, net=840)
        old_items = PurchaseDAO.get_invoice_items(inv_id)
        new_total = 800.0
        new_gst = 40.0
        new_net = 840.0
        PurchaseDAO.update_invoice(
            invoice_id=inv_id,
            voucher_no="PV-0001", voucher_date="2026-01-15",
            voucher_time="", purchase_type="Credit",
            supplier_id=self.supplier_id,
            invoice_no="INV-NEW", invoice_date="2026-01-14",
            invoice_net_amount=new_net, bill_discount=0,
            due_date="", total_amount=new_total, gst_amount=new_gst,
            debit_note_amount=0, other_amount=0,
            paid_amount=0, round_off=0, net_amount=new_net,
            remarks="",
            items=[{
                "id": old_items[0]["id"],
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": 20, "free_qty": 0,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "rate": 40, "mrp": 50, "discount": 0,
                "gst_percent": 5,
                "gst_amount": 40.0, "amount": 800.0,
                "purchase_rate": 40, "net_rate": 40, "pp": 40,
            }],
        )
        report2 = GSTReportDAO.get_purchase_gst_report()
        self.assertEqual(report2["rows"][0]["taxable_amount"], 800.0)
        self.assertEqual(report2["rows"][0]["gst_amount"], 40.0)

    def test_21_deleted_purchase_not_shown(self):
        inv_id = self._purchase(
            lines=[self._line(pay_qty=10, free_qty=2, rate=40,
                              gst_percent=5)],
        )
        report1 = GSTReportDAO.get_purchase_gst_report()
        self.assertEqual(len(report1["rows"]), 1)

        PurchaseDAO.delete_invoice(inv_id)
        report2 = GSTReportDAO.get_purchase_gst_report()
        self.assertEqual(len(report2["rows"]), 0)
        self.assertEqual(report2["summary"]["total_bills"], 0)

    def test_22_persistence(self):
        self._purchase(
            lines=[self._line(pay_qty=10, free_qty=2, rate=40,
                              gst_percent=5)],
        )
        report = GSTReportDAO.get_purchase_gst_report()
        again = GSTReportDAO.get_purchase_gst_report()
        self.assertEqual(again["rows"], report["rows"])
        self.assertEqual(again["summary"], report["summary"])


# ======================================================================
# 23-27: Read-only guarantee, no invented data
# ======================================================================

class TestSafety(_BaseTest):

    def test_23_report_is_read_only(self):
        self._purchase(lines=[self._line(gst_percent=5)])
        conn = get_connection()
        try:
            counts_before = {
                t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in TABLES
            }
        finally:
            conn.close()

        GSTReportDAO.get_purchase_gst_report()
        GSTReportDAO.get_gst_rate_summary()
        GSTReportDAO.get_summary()
        GSTReportDAO.get_filter_options()

        conn = get_connection()
        try:
            counts_after = {
                t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in TABLES
            }
        finally:
            conn.close()

        self.assertEqual(counts_before, counts_after)

    def test_24_no_invented_gst_values(self):
        """GST amounts come only from stored line data, never invented."""
        self._purchase(
            lines=[self._line(pay_qty=10, free_qty=2, rate=40,
                              gst_percent=5)],
        )
        report = GSTReportDAO.get_purchase_gst_report()
        r = report["rows"][0]
        # Verify stored values match what we inserted
        expected_taxable = (10 + 2) * 40  # 480
        expected_gst = round(480 * 5 / 100)  # 24
        self.assertEqual(r["taxable_amount"], expected_taxable)
        self.assertEqual(r["gst_amount"], expected_gst)

    def test_25_no_gst_when_zero_rate(self):
        """Lines with gst_percent=0 should show 0 GST, not invented."""
        self._purchase(
            lines=[self._line(pay_qty=10, free_qty=0, rate=40,
                              gst_percent=0)],
        )
        report = GSTReportDAO.get_purchase_gst_report()
        r = report["rows"][0]
        self.assertEqual(r["gst_percent"], 0)
        self.assertEqual(r["gst_amount"], 0.0)

    def test_26_purchase_posting_unchanged(self):
        inv_id = self._purchase(
            lines=[self._line(pay_qty=10, free_qty=2, rate=40,
                              gst_percent=5)],
        )
        rows = self.engine.get_posting_rows(SOURCE_PURCHASE_INVOICE, inv_id)
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(r["debit"] for r in rows), 504.0)
        self.assertEqual(sum(r["credit"] for r in rows), 504.0)
        self.assertTrue(self.engine.is_posted(SOURCE_PURCHASE_INVOICE, inv_id))

    def test_27_stock_unchanged(self):
        self._purchase(lines=[self._line(pay_qty=10, free_qty=2, rate=40)])
        self.assertEqual(self._stock_qty(), 12.0)
        GSTReportDAO.get_purchase_gst_report()
        self.assertEqual(self._stock_qty(), 12.0)


# ======================================================================
# 28-41: Regression
# ======================================================================

class TestRegression(_BaseTest):

    def test_28_counter_sale_still_works(self):
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

    def test_29_credit_note_still_works(self):
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

    def test_30_debit_note_still_works(self):
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

    def test_31_supplier_payment_still_works(self):
        pid = SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-02-01", "payment_time": "",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 30.0, "reference_no": "", "remarks": "",
        })
        self.assertGreater(pid, 0)

    def test_32_customer_receipt_still_works(self):
        rid = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-02-01", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 20.0, "reference_no": "", "remarks": "",
        })
        self.assertGreater(rid, 0)

    def test_33_journal_entry_still_works(self):
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

    def test_34_trial_balance_still_works(self):
        self._purchase(lines=[self._line()])
        self.assertTrue(TrialBalanceDAO.verify_balanced())
        report = TrialBalanceDAO.get_trial_balance()
        self.assertGreater(report["totals"]["total_debit"], 0.0)

    def test_35_profit_loss_still_works(self):
        self._purchase(lines=[self._line()])
        report = ProfitLossDAO.get_profit_loss()
        self.assertIn("totals", report)
        self.assertIsInstance(ProfitLossDAO.get_totals(), dict)

    def test_36_balance_sheet_still_works(self):
        self._purchase(lines=[self._line()])
        report = BalanceSheetDAO.get_balance_sheet()
        self.assertIn("totals", report)
        self.assertIsInstance(BalanceSheetDAO.get_totals(), dict)

    def test_37_stock_master_still_works(self):
        self._purchase(lines=[self._line(pay_qty=10, free_qty=2, rate=40)])
        all_stock = StockDAO.get_all()
        self.assertEqual(len(all_stock), 1)
        self.assertEqual(all_stock[0]["stock_qty"], 12.0)

    def test_38_sales_report_still_works(self):
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

    def test_39_purchase_report_still_works(self):
        self._purchase(
            lines=[self._line(pay_qty=10, free_qty=2, rate=40,
                              gst_percent=5)],
        )
        report = PurchaseReportDAO.get_purchase_report()
        self.assertEqual(len(report["rows"]), 1)
        self.assertEqual(report["summary"]["total_gst"], 24.0)

    def test_40_all_master_screens_still_work(self):
        self.assertIsNotNone(CompanyDAO.get_all())
        self.assertIsNotNone(UnitDAO.get_all())
        self.assertIsNotNone(DrugDAO.get_all())
        self.assertIsNotNone(SupplierDAO.get_all())
        self.assertIsNotNone(CustomerDAO.get_all())
        self.assertIsNotNone(DoctorDAO.get_all())
        self.assertIsNotNone(ItemDAO.get_all())

    def test_41_all_report_daos_still_work(self):
        self._purchase(lines=[self._line()])
        self.assertIsInstance(
            TrialBalanceDAO.get_trial_balance(), dict
        )
        self.assertIsInstance(
            ProfitLossDAO.get_profit_loss(), dict
        )
        self.assertIsInstance(
            BalanceSheetDAO.get_balance_sheet(), dict
        )
        self.assertIsInstance(
            PurchaseReportDAO.get_purchase_report(), dict
        )
        self.assertIsInstance(
            SalesReportDAO.get_sales_report(), dict
        )
        self.assertIsInstance(
            GSTReportDAO.get_purchase_gst_report(), dict
        )
        self.assertIsInstance(
            GSTReportDAO.get_gst_rate_summary(), list
        )
        self.assertIsInstance(
            GSTReportDAO.get_filter_options(), dict
        )


# ======================================================================
# PySide6 screen smoke test (optional)
# ======================================================================

@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class TestScreen(unittest.TestCase):
    _DB_PATH = os.path.join(os.path.dirname(__file__), "_test_gst_report_screen.db")

    @classmethod
    def setUpClass(cls):
        if os.path.exists(cls._DB_PATH):
            os.remove(cls._DB_PATH)
        os.environ["PHARMACY_DB"] = cls._DB_PATH
        init_database()
        if not QApplication.instance():
            cls._app = QApplication(sys.argv)
        else:
            cls._app = QApplication.instance()

    def test_screen_instantiates(self):
        page = GSTReportPage()
        self.assertIsInstance(page, GSTReportPage)


if __name__ == "__main__":
    unittest.main()
