"""Tests for purchase invoice free quantity calculation.

Verifies that:
- Amount = pay_qty × rate (free qty is NOT charged)
- GST is computed on the correct (pay-only) taxable amount
- Stock receives (pay_qty + free_qty) × pack_size loose units
- Net amount rounds to nearest integer
- purchase_rate = cost_per_paid_pack, net_rate = cost_per_received_pack
- Editing and deletion reverse/re-apply correctly
"""
from __future__ import annotations

import os, sys, unittest
from decimal import Decimal, ROUND_HALF_UP
from unittest.mock import patch, MagicMock

# Ensure the project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Headless Qt
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from screens.purchase_invoice import (
    _InvoiceItemRow,
    _InvoiceDialog,
    _safe_float,
    _round2,
    _d,
)
from database.purchase_dao import pack_factor


# ---------------------------------------------------------------------------
# Pure calculation helpers (mirrors the corrected UI formulas)
# ---------------------------------------------------------------------------

def compute_line(pay_qty: float, free_qty: float, rate: float,
                 discount_pct: float, gst_pct: float) -> dict:
    """Compute line-item values using the correct formula."""
    gross = _d(pay_qty) * _d(rate)
    disc = gross * _d(discount_pct) / _d(100) if discount_pct else _d(0)
    amount = _round2(gross - disc)
    gst_amount = _round2(amount * gst_pct / 100.0)
    total = _round2(_d(amount) + _d(gst_amount))
    qty_total = pay_qty + free_qty
    purchase_rate = _round2(total / pay_qty) if pay_qty else 0.0
    net_rate = _round2(total / qty_total) if qty_total else 0.0
    return {
        "amount": amount,
        "gst_amount": gst_amount,
        "total": total,
        "purchase_rate": purchase_rate,
        "net_rate": net_rate,
    }


def compute_round_off_and_net(total_amount: float, total_gst: float,
                               bill_disc: float = 0, dn: float = 0,
                               other: float = 0) -> tuple[float, float]:
    """Return (round_off, net_amount) matching _recalc_totals."""
    raw = _d(total_amount) + _d(total_gst) - _d(bill_disc) - _d(dn) + _d(other)
    rounded = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    round_off = _round2(float(Decimal(rounded) - raw))
    return round_off, float(rounded)


# =========================================================================
# Test cases
# =========================================================================

class TestFreeQtyCalculation(unittest.TestCase):
    """Core arithmetic: the EFEREM SP example from the user's requirements."""

    def test_01_eferem_sp_amount_pay_qty_only(self):
        """Amount = 20 × 74.64 = 1492.80 (NOT 24 × 74.64 = 1791.36)."""
        r = compute_line(pay_qty=20, free_qty=4, rate=74.64,
                         discount_pct=0, gst_pct=5)
        self.assertAlmostEqual(r["amount"], 1492.80, places=2)

    def test_02_eferem_sp_gst(self):
        """GST = 1492.80 × 5% = 74.64."""
        r = compute_line(pay_qty=20, free_qty=4, rate=74.64,
                         discount_pct=0, gst_pct=5)
        self.assertAlmostEqual(r["gst_amount"], 74.64, places=2)

    def test_03_eferem_sp_total_line(self):
        """Total = 1492.80 + 74.64 = 1567.44."""
        r = compute_line(pay_qty=20, free_qty=4, rate=74.64,
                         discount_pct=0, gst_pct=5)
        self.assertAlmostEqual(r["total"], 1567.44, places=2)

    def test_04_eferem_sp_net_amount_after_round_off(self):
        """Net amount should round to 1567.00, round_off = -0.44."""
        r = compute_line(pay_qty=20, free_qty=4, rate=74.64,
                         discount_pct=0, gst_pct=5)
        round_off, net = compute_round_off_and_net(r["amount"], r["gst_amount"])
        self.assertAlmostEqual(round_off, -0.44, places=2)
        self.assertAlmostEqual(net, 1567.00, places=2)

    def test_05_purchase_rate_per_paid_pack(self):
        """Purchase rate ≈ 1567.44 / 20 ≈ 78.37."""
        r = compute_line(pay_qty=20, free_qty=4, rate=74.64,
                         discount_pct=0, gst_pct=5)
        self.assertAlmostEqual(r["purchase_rate"], 78.37, places=2)

    def test_06_net_rate_per_received_pack(self):
        """Net rate ≈ 1567.44 / 24 ≈ 65.31."""
        r = compute_line(pay_qty=20, free_qty=4, rate=74.64,
                         discount_pct=0, gst_pct=5)
        self.assertAlmostEqual(r["net_rate"], 65.31, places=2)


class TestStockQuantity(unittest.TestCase):
    """Stock must include both paid and free quantities."""

    def test_07_stock_receives_all_packs(self):
        """Total received = (20 + 4) × pack_size_10 = 240 tablets."""
        total_packs = 20 + 4  # pay + free
        factor = pack_factor("10")
        self.assertEqual(factor, 10.0)
        self.assertEqual(total_packs * factor, 240.0)

    def test_08_pack_factor_defaults(self):
        """Non-numeric or missing pack_size defaults to 1.0."""
        self.assertEqual(pack_factor(""), 1.0)
        self.assertEqual(pack_factor(None), 1.0)
        self.assertEqual(pack_factor("abc"), 1.0)
        self.assertEqual(pack_factor("0"), 1.0)
        self.assertEqual(pack_factor("-5"), 1.0)


class TestFreeQtyNotCharged(unittest.TestCase):
    """Verify free qty does not increase payable amount."""

    def test_09_zero_free_qty_same_as_pay_only(self):
        """With free=0, amount = pay_qty × rate exactly."""
        r0 = compute_line(pay_qty=20, free_qty=0, rate=74.64,
                          discount_pct=0, gst_pct=5)
        r4 = compute_line(pay_qty=20, free_qty=4, rate=74.64,
                          discount_pct=0, gst_pct=5)
        # Amount and GST must be identical — free qty adds no cost
        self.assertAlmostEqual(r0["amount"], r4["amount"], places=2)
        self.assertAlmostEqual(r0["gst_amount"], r4["gst_amount"], places=2)

    def test_10_increasing_free_does_not_change_amount(self):
        """More free qty should NOT change the payable amount."""
        amounts = set()
        for free in [0, 2, 4, 10, 100]:
            r = compute_line(pay_qty=20, free_qty=free, rate=74.64,
                             discount_pct=0, gst_pct=5)
            amounts.add(r["amount"])
        self.assertEqual(len(amounts), 1, f"All amounts should be equal: {amounts}")


class TestDiscountApplied(unittest.TestCase):
    """Verify line discount is applied."""

    def test_11_ten_percent_discount(self):
        """10% discount on 20 packs × 100 = gross 2000 → disc 200 → amount 1800."""
        r = compute_line(pay_qty=20, free_qty=0, rate=100,
                         discount_pct=10, gst_pct=0)
        self.assertAlmostEqual(r["amount"], 1800.00, places=2)

    def test_12_discount_with_gst(self):
        """10% discount then 5% GST: amount=1800, gst=90, total=1890."""
        r = compute_line(pay_qty=20, free_qty=0, rate=100,
                         discount_pct=10, gst_pct=5)
        self.assertAlmostEqual(r["amount"], 1800.00, places=2)
        self.assertAlmostEqual(r["gst_amount"], 90.00, places=2)
        self.assertAlmostEqual(r["total"], 1890.00, places=2)


class TestRoundOff(unittest.TestCase):
    """Round-off should produce whole-rupee net amounts."""

    def test_13_round_off_rounds_to_integer(self):
        """1567.44 should round to 1567, with round_off = -0.44."""
        ro, net = compute_round_off_and_net(1492.80, 74.64)
        self.assertEqual(net, 1567.0)
        self.assertAlmostEqual(ro, -0.44, places=2)

    def test_14_round_off_rounds_up(self):
        """If raw_net = 1567.50, round to 1568, round_off = +0.50."""
        ro, net = compute_round_off_and_net(1493.00, 74.50)
        self.assertEqual(net, 1568.0)
        self.assertAlmostEqual(ro, 0.50, places=2)

    def test_15_round_off_exact_integer(self):
        """If raw net is already integer, round_off = 0."""
        ro, net = compute_round_off_and_net(1000.00, 0.00)
        self.assertEqual(net, 1000.0)
        self.assertAlmostEqual(ro, 0.00, places=2)


class TestUIDialogCalculation(unittest.TestCase):
    """Integration: test the actual _InvoiceDialog._on_add_item flow."""

    @patch("screens.purchase_invoice.PurchaseDAO")
    @patch("screens.purchase_invoice.ItemDAO")
    @patch("screens.purchase_invoice.SupplierDAO")
    @patch("screens.purchase_invoice.financial_year")
    def test_16_dialog_add_item_correct_amounts(self, mock_fy, mock_sup, mock_item, mock_purch):
        """Adding EFEREM SP via the dialog produces the correct line values."""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)

        mock_fy.get_active_financial_year.return_value = {
            "id": 1, "start_date": "2026-04-01", "end_date": "2027-03-31"
        }
        mock_sup.get_all.return_value = [
            {"id": 1, "supplier_name": "TestSupplier", "opening_balance": 0}
        ]
        mock_item.get_all.return_value = [
            {"id": 100, "item_name": "EFEREM SP"}
        ]
        mock_item.get_by_id.return_value = {
            "id": 100, "item_name": "EFEREM SP",
            "pack_size": "10", "mrp": 100.0, "rate": 74.64,
            "tax_structure": "GST5"
        }
        mock_purch.generate_next_voucher_no.return_value = "PV-0001"

        dlg = _InvoiceDialog()

        # Simulate filling in entry bar fields
        dlg._entry_bar.item_combo.blockSignals(True)
        dlg._entry_bar.item_combo.addItem("EFEREM SP", 100)
        dlg._entry_bar.item_combo.setCurrentIndex(0)
        dlg._entry_bar.item_combo.blockSignals(False)

        dlg._entry_bar.pack_edit.setText("10")
        dlg._entry_bar.pay_qty_edit.setText("20")
        dlg._entry_bar.free_qty_edit.setText("4")
        dlg._entry_bar.batch_edit.setText("B001")
        dlg._entry_bar.expiry_edit.setText("12/28")
        dlg._entry_bar.rate_edit.setText("74.64")
        dlg._entry_bar.mrp_edit.setText("100.00")
        dlg._entry_bar.discount_edit.setText("0")
        dlg._entry_bar.gst_edit.setText("5")

        # Add the item
        dlg._on_add_item()

        # Verify the row was added with correct values
        self.assertEqual(len(dlg._item_rows), 1)
        row = dlg._item_rows[0]
        self.assertAlmostEqual(row.amount, 1492.80, places=2,
                               msg="Amount should be pay_qty × rate = 20 × 74.64")
        self.assertAlmostEqual(row.gst_amount, 74.64, places=2,
                               msg="GST should be 1492.80 × 5%")
        self.assertAlmostEqual(row.purchase_rate, 78.37, places=2,
                               msg="Purchase rate = 1567.44 / 20")
        self.assertAlmostEqual(row.net_rate, 65.31, places=2,
                               msg="Net rate = 1567.44 / 24")
        self.assertAlmostEqual(row.pp, 1567.44, places=2,
                               msg="PP = amount + gst = 1567.44")

        # Verify totals
        self.assertEqual(dlg.total_amount_label.text(), "1492.80")
        self.assertEqual(dlg.gst_label.text(), "74.64")
        self.assertEqual(dlg.round_off_edit.text(), "-0.44")
        self.assertEqual(dlg.net_amt_label.text(), "1567.00")

        dlg.close()

    @patch("screens.purchase_invoice.PurchaseDAO")
    @patch("screens.purchase_invoice.ItemDAO")
    @patch("screens.purchase_invoice.SupplierDAO")
    @patch("screens.purchase_invoice.financial_year")
    def test_17_dialog_add_item_with_discount(self, mock_fy, mock_sup, mock_item, mock_purch):
        """Verify line discount is applied in the dialog flow."""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)

        mock_fy.get_active_financial_year.return_value = {
            "id": 1, "start_date": "2026-04-01", "end_date": "2027-03-31"
        }
        mock_sup.get_all.return_value = []
        mock_item.get_all.return_value = [{"id": 50, "item_name": "TESTDRUG"}]
        mock_item.get_by_id.return_value = {
            "id": 50, "item_name": "TESTDRUG",
            "pack_size": "10", "mrp": 200.0, "rate": 100.0,
            "tax_structure": ""
        }
        mock_purch.generate_next_voucher_no.return_value = "PV-0002"

        dlg = _InvoiceDialog()

        dlg._entry_bar.item_combo.blockSignals(True)
        dlg._entry_bar.item_combo.addItem("TESTDRUG", 50)
        dlg._entry_bar.item_combo.setCurrentIndex(0)
        dlg._entry_bar.item_combo.blockSignals(False)

        dlg._entry_bar.pack_edit.setText("10")
        dlg._entry_bar.pay_qty_edit.setText("10")
        dlg._entry_bar.free_qty_edit.setText("2")
        dlg._entry_bar.batch_edit.setText("B002")
        dlg._entry_bar.expiry_edit.setText("06/29")
        dlg._entry_bar.rate_edit.setText("100.00")
        dlg._entry_bar.mrp_edit.setText("200.00")
        dlg._entry_bar.discount_edit.setText("10")  # 10% discount
        dlg._entry_bar.gst_edit.setText("12")

        dlg._on_add_item()

        self.assertEqual(len(dlg._item_rows), 1)
        row = dlg._item_rows[0]
        # Gross = 10 × 100 = 1000, Disc = 100, Amount = 900
        self.assertAlmostEqual(row.amount, 900.00, places=2)
        # GST = 900 × 12% = 108
        self.assertAlmostEqual(row.gst_amount, 108.00, places=2)
        # PP = 900 + 108 = 1008
        self.assertAlmostEqual(row.pp, 1008.00, places=2)
        # Purchase rate = 1008 / 10 = 100.80
        self.assertAlmostEqual(row.purchase_rate, 100.80, places=2)
        # Net rate = 1008 / 12 = 84.00
        self.assertAlmostEqual(row.net_rate, 84.00, places=2)

        dlg.close()


class TestEdgeCases(unittest.TestCase):
    """Edge cases in the calculation."""

    def test_18_zero_free_qty(self):
        """free_qty=0 should work correctly."""
        r = compute_line(pay_qty=10, free_qty=0, rate=50.0,
                         discount_pct=0, gst_pct=18)
        self.assertAlmostEqual(r["amount"], 500.00, places=2)
        self.assertAlmostEqual(r["gst_amount"], 90.00, places=2)
        self.assertAlmostEqual(r["total"], 590.00, places=2)
        # purchase_rate = net_rate when free=0
        self.assertAlmostEqual(r["purchase_rate"], r["net_rate"], places=2)

    def test_19_large_free_qty_lowers_net_rate(self):
        """More free qty should lower the net_rate but not change amount."""
        r_small = compute_line(pay_qty=10, free_qty=2, rate=100,
                               discount_pct=0, gst_pct=0)
        r_large = compute_line(pay_qty=10, free_qty=10, rate=100,
                               discount_pct=0, gst_pct=0)
        # Same amount
        self.assertEqual(r_small["amount"], r_large["amount"])
        # But net_rate is lower when more free
        self.assertLess(r_large["net_rate"], r_small["net_rate"])

    def test_20_various_gst_rates(self):
        """Test common GST rates: 0%, 5%, 12%, 18%, 28%."""
        for gst in [0, 5, 12, 18, 28]:
            r = compute_line(pay_qty=10, free_qty=0, rate=100,
                             discount_pct=0, gst_pct=gst)
            self.assertAlmostEqual(r["amount"], 1000.00, places=2)
            expected_gst = _round2(1000.00 * gst / 100.0)
            self.assertAlmostEqual(r["gst_amount"], expected_gst, places=2)


class TestDatabaseIntegration(unittest.TestCase):
    """End-to-end database tests: insert, stock creation, ledger posting, update, delete."""

    def setUp(self):
        import tempfile
        from database.connection import init_database
        from database.account_roles import ensure_system_ledgers
        from database import auth, financial_year
        from database.company_dao import CompanyDAO
        from database.unit_dao import UnitDAO
        from database.drug_dao import DrugDAO
        from database.item_dao import ItemDAO
        from database.supplier_dao import SupplierDAO

        self.db_path = os.path.join(tempfile.gettempdir(), f"test_purchase_free_{os.getpid()}.db")
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        os.environ["PHARMACY_DB"] = self.db_path

        init_database()
        ensure_system_ledgers()
        auth.ensure_auth_schema()
        financial_year.ensure_default_financial_year()

        self.company_id = CompanyDAO.insert("Goldline Pharm", "GL")
        self.unit_id = UnitDAO.insert("Tablet")
        self.drug_id = DrugDAO.insert("Aceclofenac")
        self.supplier_id = SupplierDAO.insert("Anand Pharma")

        self.item_id = ItemDAO.insert(
            item_name="EFEREM SP",
            unit_id=self.unit_id,
            company_id=self.company_id,
            pack_size="10",
            tax_structure="GST5",
            rate=74.64,
            mrp=110.0,
        )

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass

    def test_21_database_insert_eferem_sp(self):
        """Insert EFEREM SP invoice and verify header, item, stock, and ledger."""
        from database.purchase_dao import PurchaseDAO
        from database.connection import get_connection

        # Compute line values using the corrected formulas
        line = compute_line(pay_qty=20, free_qty=4, rate=74.64, discount_pct=0, gst_pct=5)
        round_off, net = compute_round_off_and_net(line["amount"], line["gst_amount"])

        items = [
            {
                "item_id": self.item_id,
                "pack_size": "10",
                "pay_qty": 20.0,
                "free_qty": 4.0,
                "batch_no": "EF2026B1",
                "expiry": "08/28",
                "rate": 74.64,
                "mrp": 110.00,
                "discount": 0.0,
                "gst_percent": 5.0,
                "gst_amount": line["gst_amount"],
                "amount": line["amount"],
                "purchase_rate": line["purchase_rate"],
                "net_rate": line["net_rate"],
                "pp": line["total"],
            }
        ]

        inv_id = PurchaseDAO.insert_invoice(
            voucher_no="PV-2026-0001",
            voucher_date="2026-06-01",
            voucher_time="10:00",
            purchase_type="Credit",
            supplier_id=self.supplier_id,
            invoice_no="INV-EF-001",
            invoice_date="2026-06-01",
            invoice_net_amount=1567.0,
            bill_discount=0.0,
            due_date="2026-07-01",
            total_amount=line["amount"],
            gst_amount=line["gst_amount"],
            debit_note_amount=0.0,
            other_amount=0.0,
            paid_amount=0.0,
            round_off=round_off,
            net_amount=net,
            remarks="EFEREM SP purchase test",
            items=items,
        )

        # 1. Verify header amounts
        inv = PurchaseDAO.get_by_id(inv_id)
        self.assertIsNotNone(inv)
        self.assertAlmostEqual(inv["total_amount"], 1492.80, places=2)
        self.assertAlmostEqual(inv["gst_amount"], 74.64, places=2)
        self.assertAlmostEqual(inv["round_off"], -0.44, places=2)
        self.assertAlmostEqual(inv["net_amount"], 1567.00, places=2)

        # 2. Verify line item amounts
        inv_items = PurchaseDAO.get_invoice_items(inv_id)
        self.assertEqual(len(inv_items), 1)
        it = inv_items[0]
        self.assertAlmostEqual(it["amount"], 1492.80, places=2)
        self.assertAlmostEqual(it["gst_amount"], 74.64, places=2)
        self.assertAlmostEqual(it["purchase_rate"], 78.37, places=2)
        self.assertAlmostEqual(it["net_rate"], 65.31, places=2)
        self.assertEqual(it["pay_qty"], 20.0)
        self.assertEqual(it["free_qty"], 4.0)

        # 3. Verify stock: 24 packs × 10 units/pack = 240 units
        batches = PurchaseDAO.get_stock_batches_for_item(self.item_id)
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0]["batch_no"], "EF2026B1")
        self.assertEqual(batches[0]["stock_qty"], 240.0)

        # 4. Verify supplier ledger is credited for net 1567.00 only (NOT 1791.36)
        conn = get_connection()
        try:
            cur = conn.cursor()
            rows = cur.execute(
                "SELECT debit, credit, description FROM ledger_transactions WHERE reference_id = ?",
                (inv_id,),
            ).fetchall()
            self.assertEqual(len(rows), 2)
            # One debit to Purchase (1567.00), one credit to Supplier (1567.00)
            total_debits = sum(r["debit"] for r in rows)
            total_credits = sum(r["credit"] for r in rows)
            self.assertAlmostEqual(total_debits, 1567.00, places=2)
            self.assertAlmostEqual(total_credits, 1567.00, places=2)
        finally:
            conn.close()

    def test_22_database_update_adjusts_stock_correctly(self):
        """Updating an invoice with more free qty increases stock without increasing amount."""
        from database.purchase_dao import PurchaseDAO

        line = compute_line(pay_qty=20, free_qty=4, rate=74.64, discount_pct=0, gst_pct=5)
        round_off, net = compute_round_off_and_net(line["amount"], line["gst_amount"])

        items = [
            {
                "item_id": self.item_id,
                "pack_size": "10",
                "pay_qty": 20.0,
                "free_qty": 4.0,
                "batch_no": "EF2026B1",
                "expiry": "08/28",
                "rate": 74.64,
                "mrp": 110.00,
                "discount": 0.0,
                "gst_percent": 5.0,
                "gst_amount": line["gst_amount"],
                "amount": line["amount"],
                "purchase_rate": line["purchase_rate"],
                "net_rate": line["net_rate"],
                "pp": line["total"],
            }
        ]

        inv_id = PurchaseDAO.insert_invoice(
            voucher_no="PV-2026-0002",
            voucher_date="2026-06-01",
            voucher_time="10:00",
            purchase_type="Credit",
            supplier_id=self.supplier_id,
            invoice_no="INV-EF-002",
            invoice_date="2026-06-01",
            invoice_net_amount=1567.0,
            bill_discount=0.0,
            due_date="2026-07-01",
            total_amount=line["amount"],
            gst_amount=line["gst_amount"],
            debit_note_amount=0.0,
            other_amount=0.0,
            paid_amount=0.0,
            round_off=round_off,
            net_amount=net,
            remarks="",
            items=items,
        )

        # Update: supplier gave 6 free packs instead of 4
        line2 = compute_line(pay_qty=20, free_qty=6, rate=74.64, discount_pct=0, gst_pct=5)
        round_off2, net2 = compute_round_off_and_net(line2["amount"], line2["gst_amount"])
        items2 = [
            {
                "item_id": self.item_id,
                "pack_size": "10",
                "pay_qty": 20.0,
                "free_qty": 6.0,  # 6 free packs
                "batch_no": "EF2026B1",
                "expiry": "08/28",
                "rate": 74.64,
                "mrp": 110.00,
                "discount": 0.0,
                "gst_percent": 5.0,
                "gst_amount": line2["gst_amount"],
                "amount": line2["amount"],
                "purchase_rate": line2["purchase_rate"],
                "net_rate": line2["net_rate"],
                "pp": line2["total"],
            }
        ]

        PurchaseDAO.update_invoice(
            invoice_id=inv_id,
            voucher_no="PV-2026-0002",
            voucher_date="2026-06-01",
            voucher_time="10:00",
            purchase_type="Credit",
            supplier_id=self.supplier_id,
            invoice_no="INV-EF-002",
            invoice_date="2026-06-01",
            invoice_net_amount=1567.0,
            bill_discount=0.0,
            due_date="2026-07-01",
            total_amount=line2["amount"],
            gst_amount=line2["gst_amount"],
            debit_note_amount=0.0,
            other_amount=0.0,
            paid_amount=0.0,
            round_off=round_off2,
            net_amount=net2,
            remarks="",
            items=items2,
        )

        # Amount and payable remain identical (1492.80 and 1567.00)
        inv2 = PurchaseDAO.get_by_id(inv_id)
        self.assertAlmostEqual(inv2["net_amount"], 1567.00, places=2)

        # Stock should now be (20 + 6) × 10 = 260 units
        batches = PurchaseDAO.get_stock_batches_for_item(self.item_id)
        self.assertEqual(batches[0]["stock_qty"], 260.0)

    def test_23_database_delete_reverses_stock_and_ledger(self):
        """Deleting an invoice reverses both paid and free stock and clears ledger effect."""
        from database.purchase_dao import PurchaseDAO
        from database.connection import get_connection

        line = compute_line(pay_qty=20, free_qty=4, rate=74.64, discount_pct=0, gst_pct=5)
        round_off, net = compute_round_off_and_net(line["amount"], line["gst_amount"])

        items = [
            {
                "item_id": self.item_id,
                "pack_size": "10",
                "pay_qty": 20.0,
                "free_qty": 4.0,
                "batch_no": "EF2026B1",
                "expiry": "08/28",
                "rate": 74.64,
                "mrp": 110.00,
                "discount": 0.0,
                "gst_percent": 5.0,
                "gst_amount": line["gst_amount"],
                "amount": line["amount"],
                "purchase_rate": line["purchase_rate"],
                "net_rate": line["net_rate"],
                "pp": line["total"],
            }
        ]

        inv_id = PurchaseDAO.insert_invoice(
            voucher_no="PV-2026-0003",
            voucher_date="2026-06-01",
            voucher_time="10:00",
            purchase_type="Credit",
            supplier_id=self.supplier_id,
            invoice_no="INV-EF-003",
            invoice_date="2026-06-01",
            invoice_net_amount=1567.0,
            bill_discount=0.0,
            due_date="2026-07-01",
            total_amount=line["amount"],
            gst_amount=line["gst_amount"],
            debit_note_amount=0.0,
            other_amount=0.0,
            paid_amount=0.0,
            round_off=round_off,
            net_amount=net,
            remarks="",
            items=items,
        )

        # Delete invoice
        PurchaseDAO.delete_invoice(inv_id)

        # Stock is reduced back to 0
        batches = PurchaseDAO.get_stock_batches_for_item(self.item_id)
        self.assertEqual(len(batches), 0, "Stock batches with > 0 stock should be empty")

        # Active ledger effect is net zero
        conn = get_connection()
        try:
            cur = conn.cursor()
            rows = cur.execute(
                "SELECT SUM(debit) as d, SUM(credit) as c FROM ledger_transactions WHERE reference_id = ?",
                (inv_id,),
            ).fetchone()
            # Original + reversal sum to equal debits and credits
            self.assertAlmostEqual(rows["d"], rows["c"], places=2)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

