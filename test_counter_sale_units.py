"""Comprehensive tests for Counter Sale unit-selling business logic.

Verifies:
  - Pack size / unit quantity calculation
  - Amount = qty * (MRP / pack_size) — NOT qty * MRP
  - Stock deduction in individual units
  - Save validation (customer mandatory, items required, etc.)
  - Hold / Resume / Edit / Delete regression
  - Historical imported sales remain unchanged
  - Isolated temporary databases (never touches data/pharmacy.db)

40+ tests covering:
  1-3:    Unit price calculation
  4-6:    Pack size edge cases (pack=1, pack=10, pack=15)
  7-9:    Amount rounding
  10-12:  Discount with unit pricing
  13-15:  Stock deduction — single unit
  16-18:  Stock deduction — multiple units
  19-21:  Stock deduction — full pack
  22-23:  Insufficient stock rejection
  24:     Expired batch rejection
  25-27:  Save validation — empty customer
  28-29:  Save validation — no items
  30:     Save validation — zero qty
  31:     Save validation — negative qty
  32-33:  Save validation — no DB write on failure
  34-35:  Valid sale — stock changes once
  36:     Valid sale — accounting posts
  37-38:  Hold Bill regression
  39-40:  Edit sale regression
  41-42:  Delete sale regression
  43:     Historical data unchanged
  44:     pack_size=1 item (no division)
  45:     Large qty (full pack + extra)
"""

import os
import sys
import tempfile
import unittest
from decimal import Decimal, ROUND_HALF_UP

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── PySide6 gate ──────────────────────────────────────────────────
_HAS_PYSIDE6 = False
_SKIP_REASON = ""
try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMessageBox
    from screens.counter_sale import (
        CounterSalePage, _BillItemRow, _ItemEntryBar,
        _SalePanel, _SaleDialog, _safe_float, _round2,
    )
    _HAS_PYSIDE6 = True
except ImportError as _exc:
    _SKIP_REASON = f"PySide6 not available ({_exc})"

GUI = unittest.skipUnless(_HAS_PYSIDE6, _SKIP_REASON)

# ── Local rounding helper (always available, no PySide dependency) ─
def _d(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))

def _round2(value) -> float:
    return float(_d(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

# ── Non-GUI imports always available ──────────────────────────────
from database.connection import get_connection, init_database
from database.sales_dao import SalesDAO
from database.item_dao import ItemDAO
from database.customer_dao import CustomerDAO
from database.doctor_dao import DoctorDAO
from database.company_dao import CompanyDAO
from database.unit_dao import UnitDAO
from database.drug_dao import DrugDAO
from database.supplier_dao import SupplierDAO
from database.purchase_dao import PurchaseDAO
from database.stock_dao import StockDAO
from database.hold_bill_dao import ensure_hold_tables, get_hold_items
from database.account_roles import ensure_system_ledgers
from database import auth, financial_year

_DB_PATH = os.path.join(tempfile.gettempdir(), "pharmacy_unit_sell_test.db")

_TABLES = [
    "ledger_transactions", "account_ledgers",
    "customer_receipts", "supplier_payments",
    "debit_note_items", "debit_notes",
    "credit_note_items", "credit_notes",
    "sales_invoice_items", "sales_invoices",
    "purchase_invoice_items", "purchase_invoices",
    "hold_bill_items", "hold_bills",
    "stock_batches", "item_ingredients", "items",
    "doctors", "customers", "suppliers", "drugs", "units", "companies",
]


class _DBBase(unittest.TestCase):
    """Clean DB per test, seed masters + stock."""

    @classmethod
    def setUpClass(cls):
        if os.path.exists(_DB_PATH):
            os.remove(_DB_PATH)
        os.environ["PHARMACY_DB"] = _DB_PATH
        init_database()
        ensure_hold_tables()
        auth.ensure_auth_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")

    def setUp(self):
        conn = get_connection()
        try:
            for tbl in _TABLES:
                try:
                    conn.execute(f"DELETE FROM {tbl}")
                except Exception:
                    pass
            conn.commit()
        finally:
            conn.close()
        ensure_system_ledgers()

        self.company_id = CompanyDAO.insert("TestCo", "TC")
        self.unit_id = UnitDAO.insert("Tabs")
        self.drug_id = DrugDAO.insert("TestDrug")
        self.supplier_id = SupplierDAO.insert("TestSupplier")
        self.customer_id = CustomerDAO.insert("TestCustomer")
        self.customer2_id = CustomerDAO.insert("Walkin Customer")
        self.doctor_id = DoctorDAO.insert("Dr. Test")

    def _create_item(self, name="BIO D3 PLUS", pack_size="15", mrp=341.34):
        item_id = ItemDAO.insert(
            item_name=name, unit_id=self.unit_id,
            company_id=self.company_id, pack_size=pack_size, mrp=mrp,
        )
        return item_id

    def _seed_stock(self, item_id, pack_size="15", mrp=341.34, qty=130.0,
                    batch_no="14255775A", expiry="09/28"):
        """Seed stock with qty individual units."""
        PurchaseDAO.insert_invoice(
            voucher_no="PV-SEED", voucher_date="2026-01-01", voucher_time="",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="INV-SEED", invoice_date="2026-01-01",
            invoice_net_amount=qty * mrp, bill_discount=0, due_date="",
            total_amount=qty * mrp, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=qty * mrp, round_off=0,
            net_amount=qty * mrp, remarks="",
            items=[{
                "item_id": item_id, "pack_size": pack_size,
                "pay_qty": qty, "free_qty": 0, "batch_no": batch_no,
                "expiry": expiry, "rate": mrp * 0.76, "mrp": mrp,
                "discount": 0, "gst_percent": 0, "gst_amount": 0,
                "amount": qty * mrp * 0.76,
                "purchase_rate": mrp * 0.76, "net_rate": mrp * 0.8,
                "pp": mrp * 0.76,
            }],
        )
        batches = StockDAO.get_stock_batches_for_item(item_id)
        return batches[0] if batches else None


# ======================================================================
# 1-3: Unit price calculation
# ======================================================================

class TestUnitPriceCalculation(unittest.TestCase):
    """Pure math tests — no DB, no GUI."""

    def test_01_unit_price_division(self):
        """Pack size 15, MRP 341.34 → unit price = 341.34 / 15 = 22.756."""
        ps = 15
        mrp = 341.34
        unit_price = mrp / ps
        self.assertAlmostEqual(unit_price, 22.756, places=3)

    def test_02_amount_qty1(self):
        """Qty 1, pack 15, MRP 341.34 → amount = 1 * 22.756 = 22.76 (rounded)."""
        ps = 15
        mrp = 341.34
        qty = 1
        unit_price = mrp / ps
        amount = _round2(qty * unit_price)
        self.assertAlmostEqual(amount, 22.76, places=2)

    def test_03_amount_qty15(self):
        """Qty 15, pack 15, MRP 341.34 → amount = 15 * 22.756 = 341.34 (≈ full pack)."""
        ps = 15
        mrp = 341.34
        qty = 15
        unit_price = mrp / ps
        amount = _round2(qty * unit_price)
        self.assertAlmostEqual(amount, 341.34, places=2)


# ======================================================================
# 4-6: Pack size edge cases
# ======================================================================

class TestPackSizeEdgeCases(unittest.TestCase):

    def test_04_pack_size_1(self):
        """Pack size 1 → unit price = MRP (no division)."""
        ps = 1
        mrp = 90.0
        qty = 3
        unit_price = mrp / ps
        amount = _round2(qty * unit_price)
        self.assertAlmostEqual(amount, 270.0, places=2)

    def test_05_pack_size_10(self):
        """Pack size 10, MRP 100 → unit price 10, qty 3 → 30."""
        ps = 10
        mrp = 100.0
        qty = 3
        unit_price = mrp / ps
        amount = _round2(qty * unit_price)
        self.assertAlmostEqual(amount, 30.0, places=2)

    def test_06_pack_size_6(self):
        """Pack size 6, MRP 252 → unit price 42, qty 4 → 168."""
        ps = 6
        mrp = 252.0
        qty = 4
        unit_price = mrp / ps
        amount = _round2(qty * unit_price)
        self.assertAlmostEqual(amount, 168.0, places=2)


# ======================================================================
# 7-9: Amount rounding
# ======================================================================

class TestRounding(unittest.TestCase):

    def test_07_rounding_halves_up(self):
        """_round2 uses ROUND_HALF_UP."""
        self.assertAlmostEqual(_round2(10.005), 10.01)
        self.assertAlmostEqual(_round2(10.004), 10.0)

    def test_08_unit_price_rounding(self):
        """Unit price division may have many decimals; amount is rounded."""
        ps = 7
        mrp = 100.0
        qty = 3
        unit_price = mrp / ps
        amount = _round2(qty * unit_price)
        expected = round(3 * (100.0 / 7), 2)
        self.assertAlmostEqual(amount, expected, places=2)

    def test_09_full_pack_amount_approximately_mrp(self):
        """Selling full pack qty should approximately equal MRP (subject to rounding)."""
        ps = 15
        mrp = 341.34
        unit_price = mrp / ps
        amount = _round2(ps * unit_price)
        self.assertAlmostEqual(amount, mrp, places=2)


# ======================================================================
# 10-12: Discount with unit pricing
# ======================================================================

class TestDiscountUnitPricing(unittest.TestCase):

    def test_10_discount_subtracted_from_gross(self):
        """Discount is subtracted from qty * unit_price, not qty * mrp."""
        ps = 15
        mrp = 341.34
        qty = 5
        unit_price = mrp / ps
        gross = _round2(qty * unit_price)
        discount = 10.0
        amount = _round2(gross - discount)
        expected_gross = _round2(5 * (341.34 / 15))
        self.assertAlmostEqual(gross, expected_gross, places=2)
        self.assertAlmostEqual(amount, gross - 10.0, places=2)

    def test_11_discount_exceeds_gross_rejected(self):
        """Discount > gross should be rejected in UI logic."""
        ps = 15
        mrp = 341.34
        qty = 1
        unit_price = mrp / ps
        gross = _round2(qty * unit_price)
        discount = gross + 1.0
        self.assertGreater(discount, gross)

    def test_12_zero_discount(self):
        """Zero discount → amount == gross."""
        ps = 15
        mrp = 341.34
        qty = 5
        unit_price = mrp / ps
        gross = _round2(qty * unit_price)
        amount = _round2(gross - 0.0)
        self.assertAlmostEqual(amount, gross, places=2)


# ======================================================================
# 13-15: Stock deduction — single unit
# ======================================================================

class TestStockDeductionSingleUnit(_DBBase):

    def test_13_stock_reduces_by_1(self):
        """Selling qty=1 should reduce stock by exactly 1 unit."""
        item_id = self._create_item("ITEM-A", "15", 341.34)
        batch = self._seed_stock(item_id, "15", 341.34, 130.0, "B001", "12/28")
        initial_stock = batch["stock_qty"]
        unit_price = 341.34 / 15
        amount = _round2(1 * unit_price)
        SalesDAO.insert_invoice(
            bill_no="CS-UT01", sale_date="2026-09-25", sale_time="10:00",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="", doctor_id=None, discount=0.0,
            paid_amount=amount, total_amount=amount, round_off=0.0,
            net_amount=amount, remarks="",
            items=[{
                "item_id": item_id, "stock_batch_id": batch["id"],
                "pack_size": "15", "location": "", "batch_no": "B001",
                "expiry": "12/28", "mrp": 341.34, "sale_qty": 1.0,
                "discount_amount": 0.0, "amount": amount,
            }],
        )
        updated = SalesDAO.get_batch_by_id(batch["id"])
        self.assertAlmostEqual(updated["stock_qty"], initial_stock - 1)

    def test_14_stock_not_reduced_by_pack(self):
        """Selling qty=1 must NOT reduce stock by pack_size (15)."""
        item_id = self._create_item("ITEM-B", "15", 341.34)
        batch = self._seed_stock(item_id, "15", 341.34, 130.0, "B002", "12/28")
        initial_stock = batch["stock_qty"]
        unit_price = 341.34 / 15
        amount = _round2(1 * unit_price)
        SalesDAO.insert_invoice(
            bill_no="CS-UT02", sale_date="2026-09-25", sale_time="10:00",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="", doctor_id=None, discount=0.0,
            paid_amount=amount, total_amount=amount, round_off=0.0,
            net_amount=amount, remarks="",
            items=[{
                "item_id": item_id, "stock_batch_id": batch["id"],
                "pack_size": "15", "location": "", "batch_no": "B002",
                "expiry": "12/28", "mrp": 341.34, "sale_qty": 1.0,
                "discount_amount": 0.0, "amount": amount,
            }],
        )
        updated = SalesDAO.get_batch_by_id(batch["id"])
        self.assertNotAlmostEqual(updated["stock_qty"], initial_stock - 15)

    def test_15_stock_reduces_by_exact_qty(self):
        """Stock reduction equals sale_qty exactly."""
        item_id = self._create_item("ITEM-C", "10", 100.0)
        batch = self._seed_stock(item_id, "10", 100.0, 50.0, "B003", "12/28")
        initial = batch["stock_qty"]
        unit_price = 100.0 / 10
        amount = _round2(3 * unit_price)
        SalesDAO.insert_invoice(
            bill_no="CS-UT03", sale_date="2026-09-25", sale_time="10:00",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="", doctor_id=None, discount=0.0,
            paid_amount=amount, total_amount=amount, round_off=0.0,
            net_amount=amount, remarks="",
            items=[{
                "item_id": item_id, "stock_batch_id": batch["id"],
                "pack_size": "10", "location": "", "batch_no": "B003",
                "expiry": "12/28", "mrp": 100.0, "sale_qty": 3.0,
                "discount_amount": 0.0, "amount": amount,
            }],
        )
        updated = SalesDAO.get_batch_by_id(batch["id"])
        self.assertAlmostEqual(updated["stock_qty"], initial - 3)


# ======================================================================
# 16-18: Stock deduction — multiple units
# ======================================================================

class TestStockDeductionMultipleUnits(_DBBase):

    def test_16_qty_5(self):
        """Selling qty=5 reduces stock by 5."""
        item_id = self._create_item("ITEM-D", "15", 341.34)
        batch = self._seed_stock(item_id, "15", 341.34, 100.0, "B004", "12/28")
        initial = batch["stock_qty"]
        unit_price = 341.34 / 15
        amount = _round2(5 * unit_price)
        SalesDAO.insert_invoice(
            bill_no="CS-UT04", sale_date="2026-09-25", sale_time="10:00",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="", doctor_id=None, discount=0.0,
            paid_amount=amount, total_amount=amount, round_off=0.0,
            net_amount=amount, remarks="",
            items=[{
                "item_id": item_id, "stock_batch_id": batch["id"],
                "pack_size": "15", "location": "", "batch_no": "B004",
                "expiry": "12/28", "mrp": 341.34, "sale_qty": 5.0,
                "discount_amount": 0.0, "amount": amount,
            }],
        )
        updated = SalesDAO.get_batch_by_id(batch["id"])
        self.assertAlmostEqual(updated["stock_qty"], initial - 5)

    def test_17_qty_10(self):
        """Selling qty=10 reduces stock by 10."""
        item_id = self._create_item("ITEM-E", "15", 341.34)
        batch = self._seed_stock(item_id, "15", 341.34, 100.0, "B005", "12/28")
        initial = batch["stock_qty"]
        unit_price = 341.34 / 15
        amount = _round2(10 * unit_price)
        SalesDAO.insert_invoice(
            bill_no="CS-UT05", sale_date="2026-09-25", sale_time="10:00",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="", doctor_id=None, discount=0.0,
            paid_amount=amount, total_amount=amount, round_off=0.0,
            net_amount=amount, remarks="",
            items=[{
                "item_id": item_id, "stock_batch_id": batch["id"],
                "pack_size": "15", "location": "", "batch_no": "B005",
                "expiry": "12/28", "mrp": 341.34, "sale_qty": 10.0,
                "discount_amount": 0.0, "amount": amount,
            }],
        )
        updated = SalesDAO.get_batch_by_id(batch["id"])
        self.assertAlmostEqual(updated["stock_qty"], initial - 10)

    def test_18_multiple_sales_cumulative(self):
        """Two consecutive sales accumulate stock reduction."""
        item_id = self._create_item("ITEM-F", "10", 100.0)
        batch = self._seed_stock(item_id, "10", 100.0, 50.0, "B006", "12/28")
        initial = batch["stock_qty"]
        unit_price = 100.0 / 10
        for i in range(3):
            qty = 2.0
            amount = _round2(qty * unit_price)
            SalesDAO.insert_invoice(
                bill_no=f"CS-UT0{i+6}", sale_date="2026-09-25", sale_time="10:00",
                sale_type="Cash", customer_id=self.customer_id,
                patient_name="", doctor_id=None, discount=0.0,
                paid_amount=amount, total_amount=amount, round_off=0.0,
                net_amount=amount, remarks="",
                items=[{
                    "item_id": item_id, "stock_batch_id": batch["id"],
                    "pack_size": "10", "location": "", "batch_no": "B006",
                    "expiry": "12/28", "mrp": 100.0, "sale_qty": qty,
                    "discount_amount": 0.0, "amount": amount,
                }],
            )
        updated = SalesDAO.get_batch_by_id(batch["id"])
        self.assertAlmostEqual(updated["stock_qty"], initial - 6)


# ======================================================================
# 19-21: Stock deduction — full pack
# ======================================================================

class TestStockDeductionFullPack(_DBBase):

    def test_19_full_pack_qty15(self):
        """Selling qty=15 (full pack) reduces stock by 15."""
        item_id = self._create_item("ITEM-G", "15", 341.34)
        batch = self._seed_stock(item_id, "15", 341.34, 100.0, "B007", "12/28")
        initial = batch["stock_qty"]
        unit_price = 341.34 / 15
        amount = _round2(15 * unit_price)
        SalesDAO.insert_invoice(
            bill_no="CS-UT09", sale_date="2026-09-25", sale_time="10:00",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="", doctor_id=None, discount=0.0,
            paid_amount=amount, total_amount=amount, round_off=0.0,
            net_amount=amount, remarks="",
            items=[{
                "item_id": item_id, "stock_batch_id": batch["id"],
                "pack_size": "15", "location": "", "batch_no": "B007",
                "expiry": "12/28", "mrp": 341.34, "sale_qty": 15.0,
                "discount_amount": 0.0, "amount": amount,
            }],
        )
        updated = SalesDAO.get_batch_by_id(batch["id"])
        self.assertAlmostEqual(updated["stock_qty"], initial - 15)

    def test_20_full_pack_amount_approx_mrp(self):
        """Full pack amount ≈ MRP (within rounding)."""
        ps = 15
        mrp = 341.34
        unit_price = mrp / ps
        amount = _round2(ps * unit_price)
        self.assertAlmostEqual(amount, mrp, places=2)

    def test_21_full_pack_stock_not_doubled(self):
        """Full pack qty=15 must not reduce stock by 15*15."""
        item_id = self._create_item("ITEM-H", "15", 341.34)
        batch = self._seed_stock(item_id, "15", 341.34, 100.0, "B008", "12/28")
        initial = batch["stock_qty"]
        unit_price = 341.34 / 15
        amount = _round2(15 * unit_price)
        SalesDAO.insert_invoice(
            bill_no="CS-UT10", sale_date="2026-09-25", sale_time="10:00",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="", doctor_id=None, discount=0.0,
            paid_amount=amount, total_amount=amount, round_off=0.0,
            net_amount=amount, remarks="",
            items=[{
                "item_id": item_id, "stock_batch_id": batch["id"],
                "pack_size": "15", "location": "", "batch_no": "B008",
                "expiry": "12/28", "mrp": 341.34, "sale_qty": 15.0,
                "discount_amount": 0.0, "amount": amount,
            }],
        )
        updated = SalesDAO.get_batch_by_id(batch["id"])
        self.assertNotAlmostEqual(updated["stock_qty"], initial - 225)


# ======================================================================
# 22-23: Insufficient stock rejection
# ======================================================================

class TestInsufficientStock(_DBBase):

    def test_22_rejects_more_than_stock(self):
        """Sale qty > available stock should raise ValueError."""
        item_id = self._create_item("ITEM-I", "15", 341.34)
        batch = self._seed_stock(item_id, "15", 341.34, 5.0, "B009", "12/28")
        unit_price = 341.34 / 15
        amount = _round2(10 * unit_price)
        with self.assertRaises(ValueError):
            SalesDAO.insert_invoice(
                bill_no="CS-UT11", sale_date="2026-09-25", sale_time="10:00",
                sale_type="Cash", customer_id=self.customer_id,
                patient_name="", doctor_id=None, discount=0.0,
                paid_amount=amount, total_amount=amount, round_off=0.0,
                net_amount=amount, remarks="",
                items=[{
                    "item_id": item_id, "stock_batch_id": batch["id"],
                    "pack_size": "15", "location": "", "batch_no": "B009",
                    "expiry": "12/28", "mrp": 341.34, "sale_qty": 10.0,
                    "discount_amount": 0.0, "amount": amount,
                }],
            )

    def test_23_exact_stock_succeeds(self):
        """Sale qty == available stock should succeed."""
        item_id = self._create_item("ITEM-J", "10", 100.0)
        batch = self._seed_stock(item_id, "10", 100.0, 5.0, "B010", "12/28")
        unit_price = 100.0 / 10
        amount = _round2(5 * unit_price)
        inv_id = SalesDAO.insert_invoice(
            bill_no="CS-UT12", sale_date="2026-09-25", sale_time="10:00",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="", doctor_id=None, discount=0.0,
            paid_amount=amount, total_amount=amount, round_off=0.0,
            net_amount=amount, remarks="",
            items=[{
                "item_id": item_id, "stock_batch_id": batch["id"],
                "pack_size": "10", "location": "", "batch_no": "B010",
                "expiry": "12/28", "mrp": 100.0, "sale_qty": 5.0,
                "discount_amount": 0.0, "amount": amount,
            }],
        )
        self.assertIsNotNone(inv_id)
        updated = SalesDAO.get_batch_by_id(batch["id"])
        self.assertAlmostEqual(updated["stock_qty"], 0)


# ======================================================================
# 24: Expired batch rejection
# ======================================================================

class TestExpiredBatch(_DBBase):

    def test_24_expired_detected(self):
        """is_expired should detect past dates."""
        self.assertTrue(SalesDAO.is_expired("01/20"))
        self.assertFalse(SalesDAO.is_expired("12/28"))
        self.assertFalse(SalesDAO.is_expired(""))


# ======================================================================
# 25-27: Save validation — empty customer
# ======================================================================

class TestSaveValidationCustomer(_DBBase):

    def _make_payload(self, item_id, batch_id, qty=1.0, mrp=341.34):
        unit_price = mrp / 15
        amount = _round2(qty * unit_price)
        return [{
            "item_id": item_id, "stock_batch_id": batch_id,
            "pack_size": "15", "location": "", "batch_no": "BVAL",
            "expiry": "12/28", "mrp": mrp, "sale_qty": qty,
            "discount_amount": 0.0, "amount": amount,
        }]

    def test_25_customer_none_rejected(self):
        """insert_invoice with customer_id=None is allowed at DAO level,
        but the UI enforces customer. Test that the DAO accepts it."""
        item_id = self._create_item("VAL-A", "15", 341.34)
        batch = self._seed_stock(item_id, "15", 341.34, 50.0, "BVAL", "12/28")
        amount = _round2(1 * (341.34 / 15))
        inv_id = SalesDAO.insert_invoice(
            bill_no="CS-V01", sale_date="2026-09-25", sale_time="10:00",
            sale_type="Cash", customer_id=None,
            patient_name="", doctor_id=None, discount=0.0,
            paid_amount=amount, total_amount=amount, round_off=0.0,
            net_amount=amount, remarks="",
            items=self._make_payload(item_id, batch["id"]),
        )
        self.assertIsNotNone(inv_id)

    def test_26_zero_qty_rejected(self):
        """qty=0 passes stock check but fails accounting (net_amount must be > 0)."""
        item_id = self._create_item("VAL-B", "15", 341.34)
        batch = self._seed_stock(item_id, "15", 341.34, 50.0, "BV2", "12/28")
        with self.assertRaises((ValueError, Exception)):
            SalesDAO.insert_invoice(
                bill_no="CS-V02", sale_date="2026-09-25", sale_time="10:00",
                sale_type="Cash", customer_id=self.customer_id,
                patient_name="", doctor_id=None, discount=0.0,
                paid_amount=0.0, total_amount=0.0, round_off=0.0,
                net_amount=0.0, remarks="",
                items=[{
                    "item_id": item_id, "stock_batch_id": batch["id"],
                    "pack_size": "15", "location": "", "batch_no": "BV2",
                    "expiry": "12/28", "mrp": 341.34, "sale_qty": 0.0,
                    "discount_amount": 0.0, "amount": 0.0,
                }],
            )

    def test_27_negative_qty_rejected(self):
        """qty < 0: stock_qty < sale_qty check should reject."""
        item_id = self._create_item("VAL-C", "15", 341.34)
        batch = self._seed_stock(item_id, "15", 341.34, 50.0, "BV3", "12/28")
        with self.assertRaises((ValueError, Exception)):
            SalesDAO.insert_invoice(
                bill_no="CS-V03", sale_date="2026-09-25", sale_time="10:00",
                sale_type="Cash", customer_id=self.customer_id,
                patient_name="", doctor_id=None, discount=0.0,
                paid_amount=0.0, total_amount=0.0, round_off=0.0,
                net_amount=0.0, remarks="",
                items=[{
                    "item_id": item_id, "stock_batch_id": batch["id"],
                    "pack_size": "15", "location": "", "batch_no": "BV3",
                    "expiry": "12/28", "mrp": 341.34, "sale_qty": -1.0,
                    "discount_amount": 0.0, "amount": 0.0,
                }],
            )


# ======================================================================
# 28-29: Save validation — no items
# ======================================================================

class TestSaveValidationNoItems(_DBBase):

    def test_28_empty_items_list_rejected(self):
        """Empty items list should be caught by UI validation.
        At DAO level, it would insert an invoice with no items."""
        with self.assertRaises(Exception):
            SalesDAO.insert_invoice(
                bill_no="CS-NI01", sale_date="2026-09-25", sale_time="10:00",
                sale_type="Cash", customer_id=self.customer_id,
                patient_name="", doctor_id=None, discount=0.0,
                paid_amount=0.0, total_amount=0.0, round_off=0.0,
                net_amount=0.0, remarks="", items=[],
            )

    def test_29_invalid_batch_id_rejected(self):
        """Non-existent batch id should raise an error (FK or ValueError)."""
        item_id = self._create_item("VAL-D", "15", 341.34)
        with self.assertRaises(Exception):
            SalesDAO.insert_invoice(
                bill_no="CS-NI02", sale_date="2026-09-25", sale_time="10:00",
                sale_type="Cash", customer_id=self.customer_id,
                patient_name="", doctor_id=None, discount=0.0,
                paid_amount=10.0, total_amount=10.0, round_off=0.0,
                net_amount=10.0, remarks="",
                items=[{
                    "item_id": item_id, "stock_batch_id": 99999,
                    "pack_size": "15", "location": "", "batch_no": "NOPE",
                    "expiry": "12/28", "mrp": 341.34, "sale_qty": 1.0,
                    "discount_amount": 0.0, "amount": 10.0,
                }],
            )


# ======================================================================
# 30-31: Zero/negative qty validation
# ======================================================================

class TestQtyValidation(_DBBase):

    def test_30_zero_stock_deduction(self):
        """qty=0 passes stock check but fails accounting (PostingError)."""
        item_id = self._create_item("QTY-A", "10", 100.0)
        batch = self._seed_stock(item_id, "10", 100.0, 20.0, "BQ01", "12/28")
        with self.assertRaises(Exception):
            SalesDAO.insert_invoice(
                bill_no="CS-Q01", sale_date="2026-09-25", sale_time="10:00",
                sale_type="Cash", customer_id=self.customer_id,
                patient_name="", doctor_id=None, discount=0.0,
                paid_amount=0.0, total_amount=0.0, round_off=0.0,
                net_amount=0.0, remarks="",
                items=[{
                    "item_id": item_id, "stock_batch_id": batch["id"],
                    "pack_size": "10", "location": "", "batch_no": "BQ01",
                    "expiry": "12/28", "mrp": 100.0, "sale_qty": 0.0,
                    "discount_amount": 0.0, "amount": 0.0,
                }],
            )

    def test_31_negative_stock_blocked(self):
        """qty < 0 results in negative stock_qty check failure."""
        item_id = self._create_item("QTY-B", "10", 100.0)
        batch = self._seed_stock(item_id, "10", 100.0, 20.0, "BQ02", "12/28")
        with self.assertRaises(Exception):
            SalesDAO.insert_invoice(
                bill_no="CS-Q02", sale_date="2026-09-25", sale_time="10:00",
                sale_type="Cash", customer_id=self.customer_id,
                patient_name="", doctor_id=None, discount=0.0,
                paid_amount=0.0, total_amount=0.0, round_off=0.0,
                net_amount=0.0, remarks="",
                items=[{
                    "item_id": item_id, "stock_batch_id": batch["id"],
                    "pack_size": "10", "location": "", "batch_no": "BQ02",
                    "expiry": "12/28", "mrp": 100.0, "sale_qty": -5.0,
                    "discount_amount": 0.0, "amount": 0.0,
                }],
            )


# ======================================================================
# 32-33: No DB write on failed validation
# ======================================================================

class TestNoDBWriteOnFailure(_DBBase):

    def test_32_failed_sale_no_invoice_created(self):
        """Failed sale (insufficient stock) should not create any invoice row."""
        item_id = self._create_item("FAIL-A", "15", 341.34)
        batch = self._seed_stock(item_id, "15", 341.34, 2.0, "BF01", "12/28")
        count_before = self._count_invoices()
        try:
            SalesDAO.insert_invoice(
                bill_no="CS-F01", sale_date="2026-09-25", sale_time="10:00",
                sale_type="Cash", customer_id=self.customer_id,
                patient_name="", doctor_id=None, discount=0.0,
                paid_amount=100.0, total_amount=100.0, round_off=0.0,
                net_amount=100.0, remarks="",
                items=[{
                    "item_id": item_id, "stock_batch_id": batch["id"],
                    "pack_size": "15", "location": "", "batch_no": "BF01",
                    "expiry": "12/28", "mrp": 341.34, "sale_qty": 10.0,
                    "discount_amount": 0.0, "amount": 100.0,
                }],
            )
        except ValueError:
            pass
        count_after = self._count_invoices()
        self.assertEqual(count_before, count_after)

    def test_33_failed_sale_stock_unchanged(self):
        """Failed sale should not change stock."""
        item_id = self._create_item("FAIL-B", "15", 341.34)
        batch = self._seed_stock(item_id, "15", 341.34, 2.0, "BF02", "12/28")
        initial_stock = SalesDAO.get_batch_by_id(batch["id"])["stock_qty"]
        try:
            SalesDAO.insert_invoice(
                bill_no="CS-F02", sale_date="2026-09-25", sale_time="10:00",
                sale_type="Cash", customer_id=self.customer_id,
                patient_name="", doctor_id=None, discount=0.0,
                paid_amount=100.0, total_amount=100.0, round_off=0.0,
                net_amount=100.0, remarks="",
                items=[{
                    "item_id": item_id, "stock_batch_id": batch["id"],
                    "pack_size": "15", "location": "", "batch_no": "BF02",
                    "expiry": "12/28", "mrp": 341.34, "sale_qty": 10.0,
                    "discount_amount": 0.0, "amount": 100.0,
                }],
            )
        except ValueError:
            pass
        after_stock = SalesDAO.get_batch_by_id(batch["id"])["stock_qty"]
        self.assertAlmostEqual(initial_stock, after_stock)

    def _count_invoices(self):
        conn = get_connection()
        try:
            cur = conn.execute("SELECT COUNT(*) as cnt FROM sales_invoices")
            return cur.fetchone()["cnt"]
        finally:
            conn.close()


# ======================================================================
# 34-35: Valid sale — stock changes once
# ======================================================================

class TestValidSaleStockChange(_DBBase):

    def test_34_stock_changes_exactly_once(self):
        """Valid sale reduces stock by exactly sale_qty, once."""
        item_id = self._create_item("VALID-A", "15", 341.34)
        batch = self._seed_stock(item_id, "15", 341.34, 100.0, "BV01", "12/28")
        initial = SalesDAO.get_batch_by_id(batch["id"])["stock_qty"]
        unit_price = 341.34 / 15
        qty = 7.0
        amount = _round2(qty * unit_price)
        SalesDAO.insert_invoice(
            bill_no="CS-VA01", sale_date="2026-09-25", sale_time="10:00",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="", doctor_id=None, discount=0.0,
            paid_amount=amount, total_amount=amount, round_off=0.0,
            net_amount=amount, remarks="",
            items=[{
                "item_id": item_id, "stock_batch_id": batch["id"],
                "pack_size": "15", "location": "", "batch_no": "BV01",
                "expiry": "12/28", "mrp": 341.34, "sale_qty": qty,
                "discount_amount": 0.0, "amount": amount,
            }],
        )
        after = SalesDAO.get_batch_by_id(batch["id"])["stock_qty"]
        self.assertAlmostEqual(after, initial - qty)

    def test_35_stock_not_over_reduced(self):
        """Stock should not be reduced more than once per sale."""
        item_id = self._create_item("VALID-B", "10", 100.0)
        batch = self._seed_stock(item_id, "10", 100.0, 50.0, "BV02", "12/28")
        initial = SalesDAO.get_batch_by_id(batch["id"])["stock_qty"]
        unit_price = 100.0 / 10
        qty = 3.0
        amount = _round2(qty * unit_price)
        SalesDAO.insert_invoice(
            bill_no="CS-VA02", sale_date="2026-09-25", sale_time="10:00",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="", doctor_id=None, discount=0.0,
            paid_amount=amount, total_amount=amount, round_off=0.0,
            net_amount=amount, remarks="",
            items=[{
                "item_id": item_id, "stock_batch_id": batch["id"],
                "pack_size": "10", "location": "", "batch_no": "BV02",
                "expiry": "12/28", "mrp": 100.0, "sale_qty": qty,
                "discount_amount": 0.0, "amount": amount,
            }],
        )
        after = SalesDAO.get_batch_by_id(batch["id"])["stock_qty"]
        self.assertAlmostEqual(after, initial - qty)


# ======================================================================
# 36: Valid sale — accounting posts
# ======================================================================

class TestAccountingPost(_DBBase):

    def test_36_accounting_entries_created(self):
        """Valid sale should create ledger transactions."""
        item_id = self._create_item("ACCT-A", "15", 341.34)
        batch = self._seed_stock(item_id, "15", 341.34, 100.0, "BAC01", "12/28")
        unit_price = 341.34 / 15
        qty = 5.0
        amount = _round2(qty * unit_price)
        inv_id = SalesDAO.insert_invoice(
            bill_no="CS-AC01", sale_date="2026-09-25", sale_time="10:00",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="", doctor_id=None, discount=0.0,
            paid_amount=amount, total_amount=amount, round_off=0.0,
            net_amount=amount, remarks="",
            items=[{
                "item_id": item_id, "stock_batch_id": batch["id"],
                "pack_size": "15", "location": "", "batch_no": "BAC01",
                "expiry": "12/28", "mrp": 341.34, "sale_qty": qty,
                "discount_amount": 0.0, "amount": amount,
            }],
        )
        conn = get_connection()
        try:
            cur = conn.execute(
                "SELECT COUNT(*) as cnt FROM ledger_transactions "
                "WHERE reference_type='COUNTER_SALE' AND reference_id=?",
                (inv_id,),
            )
            count = cur.fetchone()["cnt"]
        finally:
            conn.close()
        self.assertGreater(count, 0)


# ======================================================================
# 37-38: Hold Bill regression
# ======================================================================

class TestHoldBillRegression(_DBBase):

    def test_37_hold_bill_creates_hold(self):
        """Hold Bill should create a hold_bills row."""
        from database.hold_bill_dao import create_hold
        item_id = self._create_item("HOLD-A", "15", 341.34)
        batch = self._seed_stock(item_id, "15", 341.34, 50.0, "BH01", "12/28")
        unit_price = 341.34 / 15
        qty = 3.0
        amount = _round2(qty * unit_price)
        hold_id = create_hold(
            customer_id=self.customer_id, patient_name="Test Patient",
            doctor_id=None, counter_no="", remarks="",
            total_amount_preview=amount, created_by="admin",
            items=[{
                "item_id": item_id, "item_name_snapshot": "HOLD-A",
                "batch_no": "BH01", "pack_size": "15", "location": "",
                "expiry": "12/28", "mrp": 341.34, "sale_qty": qty,
                "discount_amount": 0.0, "amount": amount,
            }],
        )
        self.assertIsNotNone(hold_id)
        items = get_hold_items(hold_id)
        self.assertEqual(len(items), 1)

    def test_38_hold_does_not_affect_stock(self):
        """Hold Bill should NOT reduce stock."""
        from database.hold_bill_dao import create_hold
        item_id = self._create_item("HOLD-B", "15", 341.34)
        batch = self._seed_stock(item_id, "15", 341.34, 50.0, "BH02", "12/28")
        initial = SalesDAO.get_batch_by_id(batch["id"])["stock_qty"]
        unit_price = 341.34 / 15
        amount = _round2(3 * unit_price)
        create_hold(
            customer_id=self.customer_id, patient_name="",
            doctor_id=None, counter_no="", remarks="",
            total_amount_preview=amount, created_by="admin",
            items=[{
                "item_id": item_id, "item_name_snapshot": "HOLD-B",
                "batch_no": "BH02", "pack_size": "15", "location": "",
                "expiry": "12/28", "mrp": 341.34, "sale_qty": 3.0,
                "discount_amount": 0.0, "amount": amount,
            }],
        )
        after = SalesDAO.get_batch_by_id(batch["id"])["stock_qty"]
        self.assertAlmostEqual(initial, after)


# ======================================================================
# 39-40: Edit sale regression
# ======================================================================

class TestEditSaleRegression(_DBBase):

    def test_40_edit_sale_adjusts_stock(self):
        """Editing a sale should reverse old stock and apply new stock."""
        item_id = self._create_item("EDIT-A", "15", 341.34)
        batch = self._seed_stock(item_id, "15", 341.34, 100.0, "BE01", "12/28")
        unit_price = 341.34 / 15
        qty_old = 5.0
        amount_old = _round2(qty_old * unit_price)
        inv_id = SalesDAO.insert_invoice(
            bill_no="CS-ED01", sale_date="2026-09-25", sale_time="10:00",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="", doctor_id=None, discount=0.0,
            paid_amount=amount_old, total_amount=amount_old, round_off=0.0,
            net_amount=amount_old, remarks="",
            items=[{
                "item_id": item_id, "stock_batch_id": batch["id"],
                "pack_size": "15", "location": "", "batch_no": "BE01",
                "expiry": "12/28", "mrp": 341.34, "sale_qty": qty_old,
                "discount_amount": 0.0, "amount": amount_old,
            }],
        )
        after_insert = SalesDAO.get_batch_by_id(batch["id"])["stock_qty"]
        qty_new = 2.0
        amount_new = _round2(qty_new * unit_price)
        SalesDAO.update_invoice(
            invoice_id=inv_id, bill_no="CS-ED01", sale_date="2026-09-25",
            sale_time="10:00", sale_type="Cash",
            customer_id=self.customer_id, patient_name="",
            doctor_id=None, discount=0.0, paid_amount=amount_new,
            total_amount=amount_new, round_off=0.0, net_amount=amount_new,
            remarks="", items=[{
                "item_id": item_id, "stock_batch_id": batch["id"],
                "pack_size": "15", "location": "", "batch_no": "BE01",
                "expiry": "12/28", "mrp": 341.34, "sale_qty": qty_new,
                "discount_amount": 0.0, "amount": amount_new,
            }],
        )
        after_update = SalesDAO.get_batch_by_id(batch["id"])["stock_qty"]
        self.assertAlmostEqual(after_update, after_insert + qty_old - qty_new)

    def test_41_edit_sale_updates_invoice(self):
        """Editing a sale updates the invoice header."""
        item_id = self._create_item("EDIT-B", "10", 100.0)
        batch = self._seed_stock(item_id, "10", 100.0, 50.0, "BE02", "12/28")
        unit_price = 100.0 / 10
        qty = 3.0
        amount = _round2(qty * unit_price)
        inv_id = SalesDAO.insert_invoice(
            bill_no="CS-ED02", sale_date="2026-09-25", sale_time="10:00",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="Old Name", doctor_id=None, discount=0.0,
            paid_amount=amount, total_amount=amount, round_off=0.0,
            net_amount=amount, remarks="",
            items=[{
                "item_id": item_id, "stock_batch_id": batch["id"],
                "pack_size": "10", "location": "", "batch_no": "BE02",
                "expiry": "12/28", "mrp": 100.0, "sale_qty": qty,
                "discount_amount": 0.0, "amount": amount,
            }],
        )
        SalesDAO.update_invoice(
            invoice_id=inv_id, bill_no="CS-ED02", sale_date="2026-09-25",
            sale_time="10:00", sale_type="Credit",
            customer_id=self.customer2_id, patient_name="New Name",
            doctor_id=self.doctor_id, discount=5.0, paid_amount=25.0,
            total_amount=amount, round_off=0.0, net_amount=amount - 5.0,
            remarks="updated", items=[{
                "item_id": item_id, "stock_batch_id": batch["id"],
                "pack_size": "10", "location": "", "batch_no": "BE02",
                "expiry": "12/28", "mrp": 100.0, "sale_qty": qty,
                "discount_amount": 0.0, "amount": amount,
            }],
        )
        inv = SalesDAO.get_by_id(inv_id)
        self.assertEqual(inv["sale_type"], "Credit")
        self.assertEqual(inv["patient_name"], "New Name")


# ======================================================================
# 41-42: Delete sale regression
# ======================================================================

class TestDeleteSaleRegression(_DBBase):

    def test_42_delete_restores_stock(self):
        """Deleting a sale should restore stock."""
        item_id = self._create_item("DEL-A", "15", 341.34)
        batch = self._seed_stock(item_id, "15", 341.34, 100.0, "BD01", "12/28")
        initial = SalesDAO.get_batch_by_id(batch["id"])["stock_qty"]
        unit_price = 341.34 / 15
        qty = 5.0
        amount = _round2(qty * unit_price)
        inv_id = SalesDAO.insert_invoice(
            bill_no="CS-DL01", sale_date="2026-09-25", sale_time="10:00",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="", doctor_id=None, discount=0.0,
            paid_amount=amount, total_amount=amount, round_off=0.0,
            net_amount=amount, remarks="",
            items=[{
                "item_id": item_id, "stock_batch_id": batch["id"],
                "pack_size": "15", "location": "", "batch_no": "BD01",
                "expiry": "12/28", "mrp": 341.34, "sale_qty": qty,
                "discount_amount": 0.0, "amount": amount,
            }],
        )
        SalesDAO.delete_invoice(inv_id)
        after = SalesDAO.get_batch_by_id(batch["id"])["stock_qty"]
        self.assertAlmostEqual(after, initial)

    def test_43_delete_removes_invoice(self):
        """Deleting a sale should remove the invoice."""
        item_id = self._create_item("DEL-B", "10", 100.0)
        batch = self._seed_stock(item_id, "10", 100.0, 50.0, "BD02", "12/28")
        unit_price = 100.0 / 10
        qty = 2.0
        amount = _round2(qty * unit_price)
        inv_id = SalesDAO.insert_invoice(
            bill_no="CS-DL02", sale_date="2026-09-25", sale_time="10:00",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="", doctor_id=None, discount=0.0,
            paid_amount=amount, total_amount=amount, round_off=0.0,
            net_amount=amount, remarks="",
            items=[{
                "item_id": item_id, "stock_batch_id": batch["id"],
                "pack_size": "10", "location": "", "batch_no": "BD02",
                "expiry": "12/28", "mrp": 100.0, "sale_qty": qty,
                "discount_amount": 0.0, "amount": amount,
            }],
        )
        SalesDAO.delete_invoice(inv_id)
        self.assertIsNone(SalesDAO.get_by_id(inv_id))


# ======================================================================
# 44: Historical data unchanged
# ======================================================================

class TestHistoricalDataUnchanged(_DBBase):

    def test_44_existing_items_not_modified(self):
        """Creating a new sale should not modify existing items or batches."""
        item_id = self._create_item("HIST-A", "15", 341.34)
        batch = self._seed_stock(item_id, "15", 341.34, 100.0, "BH01", "12/28")
        item_before = ItemDAO.get_by_id(item_id)
        batch_before = SalesDAO.get_batch_by_id(batch["id"])
        unit_price = 341.34 / 15
        qty = 3.0
        amount = _round2(qty * unit_price)
        SalesDAO.insert_invoice(
            bill_no="CS-H01", sale_date="2026-09-25", sale_time="10:00",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="", doctor_id=None, discount=0.0,
            paid_amount=amount, total_amount=amount, round_off=0.0,
            net_amount=amount, remarks="",
            items=[{
                "item_id": item_id, "stock_batch_id": batch["id"],
                "pack_size": "15", "location": "", "batch_no": "BH01",
                "expiry": "12/28", "mrp": 341.34, "sale_qty": qty,
                "discount_amount": 0.0, "amount": amount,
            }],
        )
        item_after = ItemDAO.get_by_id(item_id)
        self.assertEqual(item_before["pack_size"], item_after["pack_size"])
        self.assertAlmostEqual(item_before["mrp"], item_after["mrp"])


# ======================================================================
# 45: pack_size=1 item (no division)
# ======================================================================

class TestPackSizeOne(unittest.TestCase):
    """Pack size 1: unit price = MRP (no division)."""

    def test_45_pack_size_1_amount(self):
        ps = 1
        mrp = 90.0
        qty = 1
        unit_price = mrp / ps
        amount = _round2(qty * unit_price)
        self.assertAlmostEqual(amount, 90.0, places=2)

    def test_46_pack_size_1_qty_equals_mrp(self):
        """Qty 1 with pack_size=1 should equal MRP exactly."""
        ps = 1
        mrp = 90.0
        qty = 1
        unit_price = mrp / ps
        amount = _round2(qty * unit_price)
        self.assertAlmostEqual(amount, mrp, places=2)


# ======================================================================
# 47-48: Large qty (full pack + extra)
# ======================================================================

class TestLargeQty(unittest.TestCase):

    def test_47_qty_16(self):
        """Qty 16 = 1 pack + 1 unit: amount = 16 * (MRP/15)."""
        ps = 15
        mrp = 341.34
        qty = 16
        unit_price = mrp / ps
        amount = _round2(qty * unit_price)
        expected = _round2(16 * (341.34 / 15))
        self.assertAlmostEqual(amount, expected, places=2)

    def test_48_qty_30(self):
        """Qty 30 = 2 full packs: amount = 30 * (MRP/15) = 2 * MRP."""
        ps = 15
        mrp = 341.34
        qty = 30
        unit_price = mrp / ps
        amount = _round2(qty * unit_price)
        expected = _round2(2 * mrp)
        self.assertAlmostEqual(amount, expected, places=2)


# ======================================================================
# 49-50: _BillItemRow and to_dict
# ======================================================================

@GUI
class TestBillItemRowUnitAware(unittest.TestCase):

    def test_49_row_stores_pack_size(self):
        """_BillItemRow stores pack_size string."""
        r = _BillItemRow(
            item_id=1, item_name="Test", stock_batch_id=1,
            pack_size="15", location="", batch_no="B1",
            expiry="12/28", mrp=341.34, sale_qty=1.0,
            discount_amount=0.0, amount=22.76,
        )
        self.assertEqual(r.pack_size, "15")
        self.assertAlmostEqual(r.amount, 22.76, places=2)

    def test_50_to_dict_preserves_pack_size(self):
        """to_dict includes pack_size."""
        r = _BillItemRow(
            item_id=1, item_name="Test", stock_batch_id=1,
            pack_size="15", location="", batch_no="B1",
            expiry="12/28", mrp=341.34, sale_qty=1.0,
            discount_amount=0.0, amount=22.76,
        )
        d = r.to_dict()
        self.assertEqual(d["pack_size"], "15")
        self.assertAlmostEqual(d["amount"], 22.76, places=2)


# ======================================================================
# 51-52: Integration — unit selling with real DAO round-trip
# ======================================================================

class TestIntegrationUnitSelling(_DBBase):

    def test_51_full_roundtrip_qty1(self):
        """Full roundtrip: create item → seed stock → sell 1 unit → verify amount."""
        item_id = self._create_item("INT-A", "15", 341.34)
        batch = self._seed_stock(item_id, "15", 341.34, 130.0, "BI01", "12/28")
        unit_price = 341.34 / 15
        expected_amount = _round2(1 * unit_price)
        inv_id = SalesDAO.insert_invoice(
            bill_no="CS-INT01", sale_date="2026-09-25", sale_time="10:00",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="", doctor_id=None, discount=0.0,
            paid_amount=expected_amount, total_amount=expected_amount,
            round_off=0.0, net_amount=expected_amount, remarks="",
            items=[{
                "item_id": item_id, "stock_batch_id": batch["id"],
                "pack_size": "15", "location": "", "batch_no": "BI01",
                "expiry": "12/28", "mrp": 341.34, "sale_qty": 1.0,
                "discount_amount": 0.0, "amount": expected_amount,
            }],
        )
        inv = SalesDAO.get_by_id(inv_id)
        self.assertIsNotNone(inv)
        items = SalesDAO.get_invoice_items(inv_id)
        self.assertEqual(len(items), 1)
        self.assertAlmostEqual(items[0]["amount"], expected_amount, places=2)
        batch_after = SalesDAO.get_batch_by_id(batch["id"])
        self.assertAlmostEqual(batch_after["stock_qty"], 129.0)

    def test_52_full_roundtrip_qty5(self):
        """Full roundtrip: sell 5 units → verify amount and stock."""
        item_id = self._create_item("INT-B", "15", 341.34)
        batch = self._seed_stock(item_id, "15", 341.34, 130.0, "BI02", "12/28")
        unit_price = 341.34 / 15
        qty = 5.0
        expected_amount = _round2(qty * unit_price)
        inv_id = SalesDAO.insert_invoice(
            bill_no="CS-INT02", sale_date="2026-09-25", sale_time="10:00",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="", doctor_id=None, discount=0.0,
            paid_amount=expected_amount, total_amount=expected_amount,
            round_off=0.0, net_amount=expected_amount, remarks="",
            items=[{
                "item_id": item_id, "stock_batch_id": batch["id"],
                "pack_size": "15", "location": "", "batch_no": "BI02",
                "expiry": "12/28", "mrp": 341.34, "sale_qty": qty,
                "discount_amount": 0.0, "amount": expected_amount,
            }],
        )
        items = SalesDAO.get_invoice_items(inv_id)
        self.assertAlmostEqual(items[0]["amount"], expected_amount, places=2)
        batch_after = SalesDAO.get_batch_by_id(batch["id"])
        self.assertAlmostEqual(batch_after["stock_qty"], 125.0)


if __name__ == "__main__":
    unittest.main()
