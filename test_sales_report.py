"""Phase 5A — Sales Report tests.

27 tests:
   1-4:   Empty report, one sale, multiple sales, multiple items per sale
   5-11:  Filters (dates, customer, item, company, doctor, bill no, patient)
  12-16:  Totals, deleted, edited, multiple customers, multiple batches
  17-21:  Regression: counter sale, purchase, credit note, debit note,
          accounting postings unchanged
  22-26:  Regression: Trial Balance, P&L, Balance Sheet, Stock, Masters
  27:     Persistence after restart
"""

import os
import sqlite3
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.connection import get_connection, init_database, get_db_path
from database.account_roles import ensure_system_ledgers
from database.accounting_posting import SOURCE_COUNTER_SALE, PostingEngine
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
    from screens.sales_report import SalesReportPage

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
    _DB_PATH = os.path.join(os.path.dirname(__file__), "_test_sales_report.db")

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
        self.customer_b_id = CustomerDAO.insert("CustomerB")
        self.doctor_id = DoctorDAO.insert("Dr. Alpha")
        self.doctor_b_id = DoctorDAO.insert("Dr. Beta")
        self.supplier_id = SupplierDAO.insert("TestSupplier")
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
        self._cs_count = 0

    # ── helpers ──────────────────────────────────────────────────────
    def _seed_stock(self, item_id=None, batch_no="BATCH-A",
                    qty=100.0, rate=40.0, mrp=50.0, date="2026-01-05"):
        self._pv_count += 1
        PurchaseDAO.insert_invoice(
            voucher_no=f"PV-{self._pv_count:04d}", voucher_date=date,
            voucher_time="", purchase_type="Cash",
            supplier_id=self.supplier_id, invoice_no=f"INV-{self._pv_count:04d}",
            invoice_date=date, invoice_net_amount=qty * rate,
            bill_discount=0, due_date="", total_amount=qty * rate,
            gst_amount=0, debit_note_amount=0, other_amount=0,
            paid_amount=qty * rate, round_off=0, net_amount=qty * rate,
            remarks="",
            items=[{
                "item_id": item_id or self.item_id, "pack_size": "10x10",
                "pay_qty": qty, "free_qty": 0, "batch_no": batch_no,
                "expiry": "12/27", "rate": rate, "mrp": mrp, "discount": 0,
                "gst_percent": 0, "gst_amount": 0, "amount": qty * rate,
                "purchase_rate": rate, "net_rate": rate, "pp": rate,
            }],
        )
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT id FROM stock_batches WHERE item_id = ? AND batch_no = ?",
                (item_id or self.item_id, batch_no),
            ).fetchone()
        finally:
            conn.close()
        return row["id"]

    def _sale(self, *, date="2026-02-01", bill_no=None,
              customer_id="__default__", doctor_id=None, patient="",
              lines=None, bill_discount=0.0, sale_type="Credit",
              paid=None):
        """Insert a sale. lines: [(batch_id, item_id, qty, mrp, discount)]."""
        self._cs_count += 1
        bill_no = bill_no or f"CS-{self._cs_count:04d}"
        cid = self.customer_id if customer_id == "__default__" else customer_id

        items = []
        conn = get_connection()
        try:
            for batch_id, item_id, qty, mrp, discount in lines:
                batch = conn.execute(
                    "SELECT batch_no, expiry FROM stock_batches WHERE id = ?",
                    (batch_id,),
                ).fetchone()
                items.append({
                    "item_id": item_id, "stock_batch_id": batch_id,
                    "pack_size": "10x10", "location": "",
                    "batch_no": batch["batch_no"], "expiry": batch["expiry"],
                    "mrp": mrp, "sale_qty": qty,
                    "discount_amount": discount,
                    "amount": round(qty * mrp - discount, 2),
                })
        finally:
            conn.close()
        total = round(sum(i["amount"] for i in items), 2)
        net = round(total - bill_discount, 2)
        if paid is None:
            paid = net if sale_type == "Cash" else 0.0

        return SalesDAO.insert_invoice(
            bill_no=bill_no, sale_date=date, sale_time="",
            sale_type=sale_type, customer_id=cid, patient_name=patient,
            doctor_id=doctor_id, discount=bill_discount, paid_amount=paid,
            total_amount=total, round_off=0.0, net_amount=net,
            remarks="", items=items,
        )

    def _stock_tuple(self, batch_no="BATCH-A", item_id=None,
                     qty=100.0, rate=40.0, mrp=50.0):
        batch_id = self._seed_stock(item_id=item_id, batch_no=batch_no,
                                    qty=qty, rate=rate, mrp=mrp)
        return batch_id


# ======================================================================
# 1-4: Basics
# ======================================================================

class TestBasics(_BaseTest):

    def test_01_empty_report(self):
        report = SalesReportDAO.get_sales_report()
        self.assertEqual(report["rows"], [])
        self.assertEqual(report["summary"]["total_bills"], 0)
        self.assertEqual(report["summary"]["total_net"], 0.0)

    def test_02_one_sale(self):
        batch = self._stock_tuple()
        self._sale(
            date="2026-02-05", customer_id=self.customer_id,
            doctor_id=self.doctor_id, patient="John Doe",
            lines=[(batch, self.item_id, 2, 100.0, 0.0)],
        )
        report = SalesReportDAO.get_sales_report()
        self.assertEqual(len(report["rows"]), 1)
        row = report["rows"][0]
        self.assertEqual(row["bill_no"], "CS-0001")
        self.assertEqual(row["sale_date"], "2026-02-05")
        self.assertEqual(row["customer_name"], "CustomerA")
        self.assertEqual(row["patient_name"], "John Doe")
        self.assertEqual(row["doctor_name"], "Dr. Alpha")
        self.assertEqual(row["item_name"], "ItemA")
        self.assertEqual(row["batch_no"], "BATCH-A")
        self.assertEqual(row["expiry"], "12/27")
        self.assertEqual(row["mrp"], 100.0)
        self.assertEqual(row["sale_qty"], 2)
        self.assertEqual(row["amount"], 200.0)
        s = report["summary"]
        self.assertEqual(s["total_bills"], 1)
        self.assertEqual(s["total_lines"], 1)
        self.assertEqual(s["total_net"], 200.0)

    def test_03_multiple_sales(self):
        batch = self._stock_tuple()
        self._sale(date="2026-02-01",
                   lines=[(batch, self.item_id, 1, 50.0, 0.0)])
        self._sale(date="2026-02-02",
                   lines=[(batch, self.item_id, 2, 50.0, 0.0)])
        report = SalesReportDAO.get_sales_report()
        self.assertEqual(len(report["rows"]), 2)
        self.assertEqual(report["summary"]["total_bills"], 2)
        self.assertEqual(report["summary"]["total_net"], 150.0)

    def test_04_multiple_items_one_sale(self):
        batch = self._stock_tuple()
        self._sale(lines=[
            (batch, self.item_id, 1, 100.0, 0.0),
            (batch, self.item_b_id, 2, 25.0, 0.0),
        ])
        report = SalesReportDAO.get_sales_report()
        self.assertEqual(len(report["rows"]), 2)
        self.assertEqual(report["summary"]["total_bills"], 1)   # one bill
        self.assertEqual(report["summary"]["total_lines"], 2)
        self.assertEqual(report["summary"]["total_qty"], 3)
        self.assertEqual(report["summary"]["total_net"], 150.0)  # 100 + 50


# ======================================================================
# 5-11: Filters
# ======================================================================

class TestFilters(_BaseTest):

    def setUp(self):
        super().setUp()
        self.batch = self._stock_tuple()
        # Jan / Feb / Mar sales for filtering
        self._sale(date="2026-01-10", bill_no="CS-JAN",
                   lines=[(self.batch, self.item_id, 1, 10.0, 0.0)])
        self._sale(date="2026-02-10", bill_no="CS-FEB",
                   doctor_id=self.doctor_id, patient="Alice Smith",
                   lines=[(self.batch, self.item_id, 2, 10.0, 0.0)])
        self._sale(date="2026-03-10", bill_no="CS-MAR",
                   customer_id=self.customer_b_id,
                   doctor_id=self.doctor_b_id, patient="Bob Jones",
                   lines=[(self.batch, self.item_b_id, 3, 10.0, 0.0)])

    def test_05_date_filtering(self):
        # Inclusive from/to
        report = SalesReportDAO.get_sales_report(
            from_date="2026-02-01", to_date="2026-02-28"
        )
        self.assertEqual([r["bill_no"] for r in report["rows"]], ["CS-FEB"])

        # Exact single-day inclusive bounds
        report = SalesReportDAO.get_sales_report(
            from_date="2026-02-10", to_date="2026-02-10"
        )
        self.assertEqual(len(report["rows"]), 1)

        # Bounds are edges: Jan 10 included from Jan 10
        report = SalesReportDAO.get_sales_report(from_date="2026-01-10")
        self.assertEqual(len(report["rows"]), 3)

        # No dates -> all
        self.assertEqual(len(SalesReportDAO.get_sales_report()["rows"]), 3)

    def test_06_customer_filtering(self):
        report = SalesReportDAO.get_sales_report(customer_id=self.customer_b_id)
        self.assertEqual([r["bill_no"] for r in report["rows"]], ["CS-MAR"])

    def test_07_item_filtering(self):
        report = SalesReportDAO.get_sales_report(item_id=self.item_b_id)
        self.assertEqual([r["bill_no"] for r in report["rows"]], ["CS-MAR"])

    def test_08_company_filtering(self):
        # ItemB belongs to CompanyB
        report = SalesReportDAO.get_sales_report(company_id=self.company_b_id)
        self.assertEqual(len(report["rows"]), 1)
        self.assertEqual(report["rows"][0]["company_name"], "CompanyB")

    def test_09_doctor_filtering(self):
        report = SalesReportDAO.get_sales_report(doctor_id=self.doctor_id)
        self.assertEqual([r["bill_no"] for r in report["rows"]], ["CS-FEB"])

    def test_10_bill_number_filtering(self):
        # Partial match
        report = SalesReportDAO.get_sales_report(bill_no="FEB")
        self.assertEqual([r["bill_no"] for r in report["rows"]], ["CS-FEB"])

    def test_11_patient_filtering(self):
        report = SalesReportDAO.get_sales_report(patient="Alice")
        self.assertEqual([r["bill_no"] for r in report["rows"]], ["CS-FEB"])


# ======================================================================
# 12-16: Totals and lifecycle
# ======================================================================

class TestTotalsAndLifecycle(_BaseTest):

    def test_12_totals(self):
        batch = self._stock_tuple()
        # Bill 1: two lines + bill discount
        self._sale(bill_no="CS-T1", bill_discount=40.0, lines=[
            (batch, self.item_id, 2, 100.0, 0.0),   # gross 200, net 200
            (batch, self.item_id, 1, 50.0, 10.0),   # gross 50, net 40
        ])
        # Bill 2: one line
        self._sale(bill_no="CS-T2",
                   lines=[(batch, self.item_id, 3, 20.0, 0.0)])  # 60

        s = SalesReportDAO.get_summary()
        self.assertEqual(s["total_bills"], 2)
        self.assertEqual(s["total_lines"], 3)
        self.assertEqual(s["total_qty"], 6)
        self.assertEqual(s["total_gross"], 310.0)     # 200 + 50 + 60
        self.assertEqual(s["total_discount"], 50.0)   # line 10 + bill 40
        self.assertEqual(s["total_net"], 260.0)       # 200 + 40 + 60 − 40

    def test_13_deleted_sale_excluded(self):
        batch = self._stock_tuple()
        keep = self._sale(bill_no="CS-KEEP",
                          lines=[(batch, self.item_id, 1, 10.0, 0.0)])
        drop = self._sale(bill_no="CS-DROP",
                          lines=[(batch, self.item_id, 1, 20.0, 0.0)])
        SalesDAO.delete_invoice(drop)

        report = SalesReportDAO.get_sales_report()
        self.assertEqual([r["bill_no"] for r in report["rows"]], ["CS-KEEP"])
        self.assertEqual(report["summary"]["total_bills"], 1)
        self.assertEqual(report["summary"]["total_net"], 10.0)

    def test_14_edited_sale_reflects_current_state(self):
        batch = self._stock_tuple()
        sale_id = self._sale(bill_no="CS-EDIT",
                             lines=[(batch, self.item_id, 1, 10.0, 0.0)])
        # Edit: qty 1 -> 1 line of 5 units at 10
        SalesDAO.update_invoice(
            invoice_id=sale_id, bill_no="CS-EDIT", sale_date="2026-02-01",
            sale_time="", sale_type="Credit", customer_id=self.customer_id,
            patient_name="", doctor_id=None, discount=0.0, paid_amount=0.0,
            total_amount=50.0, round_off=0.0, net_amount=50.0, remarks="",
            items=[{
                "item_id": self.item_id, "stock_batch_id": batch,
                "pack_size": "10x10", "location": "", "batch_no": "B",
                "expiry": "12/27", "mrp": 10.0, "sale_qty": 5,
                "discount_amount": 0.0, "amount": 50.0,
            }],
        )
        report = SalesReportDAO.get_sales_report()
        self.assertEqual(len(report["rows"]), 1)
        self.assertEqual(report["rows"][0]["sale_qty"], 5)
        self.assertEqual(report["rows"][0]["amount"], 50.0)
        self.assertEqual(report["summary"]["total_net"], 50.0)

    def test_15_multiple_customers(self):
        batch = self._stock_tuple()
        self._sale(bill_no="CS-C1", customer_id=self.customer_id,
                   lines=[(batch, self.item_id, 1, 10.0, 0.0)])
        self._sale(bill_no="CS-C2", customer_id=self.customer_b_id,
                   lines=[(batch, self.item_id, 1, 20.0, 0.0)])
        report = SalesReportDAO.get_sales_report()
        self.assertEqual(len(report["rows"]), 2)
        names = {r["bill_no"]: r["customer_name"] for r in report["rows"]}
        self.assertEqual(names["CS-C1"], "CustomerA")
        self.assertEqual(names["CS-C2"], "CustomerB")

    def test_16_multiple_batches(self):
        batch_a = self._stock_tuple(batch_no="BATCH-A")
        batch_b = self._stock_tuple(batch_no="BATCH-B")
        self._sale(lines=[
            (batch_a, self.item_id, 1, 10.0, 0.0),
            (batch_b, self.item_id, 1, 10.0, 0.0),
        ])
        report = SalesReportDAO.get_sales_report()
        batches = sorted(
            r["batch_no"] for r in report["rows"]
        )
        self.assertEqual(batches, ["BATCH-A", "BATCH-B"])
        self.assertEqual(report["summary"]["total_net"], 20.0)


# ======================================================================
# 17-21: Module + accounting regression
# ======================================================================

class TestRegressionModules(_BaseTest):

    def test_17_counter_sale_still_works(self):
        batch = self._stock_tuple()
        sid = self._sale(lines=[(batch, self.item_id, 1, 10.0, 0.0)])
        self.assertGreater(sid, 0)
        self.assertEqual(SalesDAO.get_by_id(sid)["net_amount"], 10.0)

    def test_18_purchase_still_works(self):
        self._seed_stock()  # inserts a purchase invoice
        purchases = PurchaseDAO.get_all()
        self.assertEqual(len(purchases), 1)
        self.assertEqual(purchases[0]["net_amount"], 4000.0)

    def test_19_credit_note_still_works(self):
        batch = self._stock_tuple()
        cn_id = CreditNoteDAO.insert_credit_note(
            {"voucher_date": "2026-02-01", "cn_date": "2026-02-01",
             "cn_type": "Customer", "customer_id": self.customer_id,
             "total_amount": 40.0, "ledger_amount": 40.0, "remarks": ""},
            [{
                "item_id": self.item_id, "stock_batch_id": batch,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40, "mrp": 50,
                "return_qty": 1, "less_amount": 0, "amount": 40,
                "return_reason": "", "price_factor": 1.0,
            }],
        )
        self.assertGreater(cn_id, 0)

    def test_20_debit_note_still_works(self):
        batch = self._stock_tuple()
        dn_id = DebitNoteDAO.insert_debit_note(
            {"voucher_date": "2026-02-01", "voucher_time": "",
             "dn_date": "2026-02-01", "dn_type": "Supplier",
             "supplier_id": self.supplier_id, "total_amount": 60.0,
             "ledger_amount": 60.0, "remarks": ""},
            [{
                "item_id": self.item_id, "stock_batch_id": batch,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40, "mrp": 50,
                "return_qty": 1.5, "less_amount": 0, "amount": 60,
                "return_reason": "", "price_factor": 1.0,
            }],
        )
        self.assertGreater(dn_id, 0)

    def test_21_accounting_postings_unchanged(self):
        batch = self._stock_tuple()
        sale_id = self._sale(bill_no="CS-POST",
                             lines=[(batch, self.item_id, 2, 100.0, 0.0)])
        rows = self.engine.get_posting_rows(SOURCE_COUNTER_SALE, sale_id)
        self.assertEqual(len(rows), 2)  # credit sale: customer + sales
        self.assertEqual(sum(r["debit"] for r in rows), 200.0)
        self.assertEqual(sum(r["credit"] for r in rows), 200.0)
        self.assertTrue(self.engine.is_posted(SOURCE_COUNTER_SALE, sale_id))


# ======================================================================
# 22-26: Financial / master regression
# ======================================================================

class TestRegressionReports(_BaseTest):

    def test_22_trial_balance_still_works(self):
        batch = self._stock_tuple()
        self._sale(lines=[(batch, self.item_id, 1, 100.0, 0.0)])
        self.assertTrue(TrialBalanceDAO.verify_balanced())
        report = TrialBalanceDAO.get_trial_balance()
        self.assertGreater(report["totals"]["total_debit"], 0.0)

    def test_23_profit_loss_still_works(self):
        batch = self._stock_tuple()
        self._sale(lines=[(batch, self.item_id, 1, 100.0, 0.0)])
        report = ProfitLossDAO.get_profit_loss()
        self.assertIn("totals", report)
        self.assertIsInstance(ProfitLossDAO.get_totals(), dict)

    def test_24_balance_sheet_still_works(self):
        batch = self._stock_tuple()
        self._sale(lines=[(batch, self.item_id, 1, 100.0, 0.0)])
        report = BalanceSheetDAO.get_balance_sheet()
        self.assertIn("totals", report)
        self.assertIsInstance(BalanceSheetDAO.get_totals(), dict)

    def test_25_stock_master_still_works(self):
        batch = self._stock_tuple(qty=50.0)
        self._sale(lines=[(batch, self.item_id, 5, 100.0, 0.0)])
        all_stock = StockDAO.get_all()
        self.assertEqual(len(all_stock), 1)
        self.assertEqual(all_stock[0]["stock_qty"], 45.0)

    def test_26_all_master_screens_still_work(self):
        self.assertGreater(len(CompanyDAO.get_all()), 0)
        self.assertGreater(len(UnitDAO.get_all()), 0)
        self.assertGreater(len(DrugDAO.get_all()), 0)
        self.assertGreater(len(SupplierDAO.get_all()), 0)
        self.assertGreater(len(CustomerDAO.get_all()), 0)
        self.assertGreater(len(DoctorDAO.get_all()), 0)
        self.assertGreater(len(ItemDAO.get_all()), 0)
        self.assertGreater(len(LedgerDAO.get_all_ledgers()), 0)


# ======================================================================
# 27: Persistence
# ======================================================================

class TestPersistence(_BaseTest):

    def test_27_persistence_after_restart(self):
        batch = self._stock_tuple()
        self._sale(bill_no="CS-PERSIST",
                   lines=[(batch, self.item_id, 2, 100.0, 0.0)])
        report = SalesReportDAO.get_sales_report()

        # Fresh connection reading committed state only
        fresh = sqlite3.connect(get_db_path())
        fresh.row_factory = sqlite3.Row
        try:
            row = fresh.execute(
                "SELECT COUNT(*) AS n FROM sales_invoice_items"
            ).fetchone()
        finally:
            fresh.close()

        self.assertEqual(row["n"], len(report["rows"]))
        again = SalesReportDAO.get_sales_report()
        self.assertEqual(again["summary"], report["summary"])
        self.assertEqual(again["rows"], report["rows"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
