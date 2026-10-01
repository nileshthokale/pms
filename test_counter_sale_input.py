"""Focused tests for Counter Sale input workflow (Phase 6E fix).

Verifies the complete Item -> Batch -> Qty -> Add -> Save pipeline
and all supporting controls.  GUI tests skip when PySide6 is unavailable.

55 tests covering:
  1-3:    Utility helpers (_safe_float, _round2)
  4-5:    _BillItemRow data class
  6-9:    SalesDAO wiring (batch loading, expiry, bill no)
 10-12:   SalesDAO stock / expiry / bill-no helpers
 13-14:   SalesDAO insert + stock deduction round-trip
 15-16:   Business-logic payload integrity
 17-21:   _ItemEntryBar loads items into combo
 22-24:   Item selection triggers batch population
 25-27:   Batch selection populates stock/expiry/MRP
 28-31:   Add button workflow
 32-33:   Bill totals update
 34-35:   Customer / doctor combos
 36-37:   New Sale reset + focus
 38-39:   Save Sale validation
 40:      Hold Bill validation
 41-43:   Architecture invariants
 44-45:   Region B stays fixed after adding items
 46-48:   Full end-to-end add flow
 49-50:   Edge cases (zero qty, discount > gross)
 51-52:   Clear / reset
 53:      Edit loads invoice
 54-55:   Hold & resume
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── PySide6 gate ──────────────────────────────────────────────────
_HAS_PYSIDE6 = False
_SKIP_REASON = ""
try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QPushButton, QMessageBox
    from screens.counter_sale import (
        CounterSalePage, _BillItemRow, _ItemEntryBar,
        _SalePanel, _SaleDialog, _safe_float, _round2,
    )
    _HAS_PYSIDE6 = True
except ImportError as _exc:
    _SKIP_REASON = f"PySide6 not available ({_exc})"

GUI = unittest.skipUnless(_HAS_PYSIDE6, _SKIP_REASON)

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
from database.hold_bill_dao import ensure_hold_tables
from database.account_roles import ensure_system_ledgers
from database import auth, financial_year

_DB_PATH = os.path.join(tempfile.gettempdir(), "pharmacy_counter_sale_input_test.db")

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


# ======================================================================
# Base class
# ======================================================================

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
        self.unit_id = UnitDAO.insert("Pcs")
        self.drug_id = DrugDAO.insert("Paracetamol")
        self.supplier_id = SupplierDAO.insert("TestSupplier")
        self.customer_id = CustomerDAO.insert("TestCustomer")
        self.customer2_id = CustomerDAO.insert("Walkin Customer")
        self.doctor_id = DoctorDAO.insert("Dr. Test")
        self.item_id = ItemDAO.insert(
            item_name="TestItem", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="10x10", mrp=50.0,
        )
        self._seed_stock()

    def _seed_stock(self, qty=100.0, rate=40.0, mrp=50.0):
        PurchaseDAO.insert_invoice(
            voucher_no="PV-0001", voucher_date="2026-01-01", voucher_time="",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="INV-001", invoice_date="2026-01-01",
            invoice_net_amount=qty * rate, bill_discount=0, due_date="",
            total_amount=qty * rate, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=qty * rate, round_off=0,
            net_amount=qty * rate, remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": qty, "free_qty": 0, "batch_no": "BATCH-A",
                "expiry": "12/27", "rate": 40.0, "mrp": 50.0, "discount": 0,
                "gst_percent": 0, "gst_amount": 0, "amount": qty * 40.0,
                "purchase_rate": 40.0, "net_rate": 40.0, "pp": 40.0,
            }],
        )
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        self.batch_id = batches[0]["id"]
        self.batch_info = batches[0]

    def _items_payload(self, qty=5.0, mrp=50.0):
        return [{
            "item_id": self.item_id, "stock_batch_id": self.batch_id,
            "pack_size": "10x10", "location": "", "batch_no": "BATCH-A",
            "expiry": "12/27", "mrp": mrp, "sale_qty": qty,
            "discount_amount": 0.0, "amount": round(qty * mrp, 2),
        }]


if _HAS_PYSIDE6:
    def _make_bill_row(idx=1):
        return _BillItemRow(
            item_id=idx, item_name=f"Item{idx}", stock_batch_id=idx,
            pack_size="10x10", location="", batch_no=f"B{idx}",
            expiry="12/27", mrp=50.0, sale_qty=2.0,
            discount_amount=0.0, amount=100.0,
        )
else:
    _make_bill_row = None  # type: ignore[assignment]


# ======================================================================
# 1-3: Utility helpers (no DB, no GUI)
# ======================================================================

@GUI
class TestHelpers(unittest.TestCase):
    def test_01_safe_float_valid(self):
        self.assertAlmostEqual(_safe_float("12.50"), 12.5)

    def test_02_safe_float_empty(self):
        self.assertAlmostEqual(_safe_float(""), 0.0)
        self.assertAlmostEqual(_safe_float("abc", 7.0), 7.0)

    def test_03_round2(self):
        self.assertAlmostEqual(_round2(10.005), 10.01)
        self.assertAlmostEqual(_round2(10.004), 10.0)


# ======================================================================
# 4-5: _BillItemRow
# ======================================================================

@GUI
class TestBillItemRow(unittest.TestCase):
    def test_04_creation(self):
        r = _make_bill_row(1)
        self.assertEqual(r.item_id, 1)
        self.assertEqual(r.amount, 100.0)

    def test_05_to_dict(self):
        r = _make_bill_row(5)
        d = r.to_dict()
        self.assertEqual(d["item_id"], 5)
        self.assertEqual(d["stock_batch_id"], 5)
        self.assertNotIn("item_name", d)


# ======================================================================
# 6-14: SalesDAO wiring
# ======================================================================

class TestSalesDAO(_DBBase):
    def test_06_get_stock_batches(self):
        batches = SalesDAO.get_stock_batches_for_item(self.item_id)
        self.assertGreater(len(batches), 0)
        self.assertEqual(batches[0]["batch_no"], "BATCH-A")

    def test_07_excludes_zero_stock(self):
        conn = get_connection()
        try:
            conn.execute("UPDATE stock_batches SET stock_qty=0 WHERE id=?", (self.batch_id,))
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(len(SalesDAO.get_stock_batches_for_item(self.item_id)), 0)

    def test_08_get_batch_by_id(self):
        b = SalesDAO.get_batch_by_id(self.batch_id)
        self.assertIsNotNone(b)
        self.assertEqual(b["batch_no"], "BATCH-A")

    def test_09_get_batch_by_item_and_batch_no(self):
        b = SalesDAO.get_batch_by_item_and_batch_no(self.item_id, "BATCH-A")
        self.assertIsNotNone(b)
        self.assertEqual(b["id"], self.batch_id)

    def test_10_expired(self):
        self.assertTrue(SalesDAO.is_expired("01/20"))

    def test_iso_expiry_date_is_expired(self):
        self.assertTrue(SalesDAO.is_expired("2014-04-30"))

    def test_iso_expiry_date_in_future_is_not_expired(self):
        self.assertFalse(SalesDAO.is_expired("2028-07-31"))

    def test_11_not_expired(self):
        self.assertFalse(SalesDAO.is_expired("12/27"))
        self.assertFalse(SalesDAO.is_expired(""))

    def test_12_bill_no(self):
        self.assertTrue(SalesDAO.generate_next_bill_no().startswith("CS-"))

    def test_13_insert_get(self):
        inv_id = SalesDAO.insert_invoice(
            bill_no="CS-1001", sale_date="2026-01-25", sale_time="10:00",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="P1", doctor_id=None, discount=0.0,
            paid_amount=250.0, total_amount=250.0, round_off=0.0,
            net_amount=250.0, remarks="", items=self._items_payload(5),
        )
        self.assertIsNotNone(SalesDAO.get_by_id(inv_id))
        self.assertEqual(len(SalesDAO.get_invoice_items(inv_id)), 1)

    def test_14_stock_reduced(self):
        before = self.batch_info["stock_qty"]
        SalesDAO.insert_invoice(
            bill_no="CS-1002", sale_date="2026-01-25", sale_time="10:00",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="", doctor_id=None, discount=0.0,
            paid_amount=100.0, total_amount=100.0, round_off=0.0,
            net_amount=100.0, remarks="", items=self._items_payload(2),
        )
        batch = SalesDAO.get_batch_by_id(self.batch_id)
        self.assertAlmostEqual(batch["stock_qty"], before - 2)


# ======================================================================
# 15-16: Payload integrity
# ======================================================================

class TestPayloadIntegrity(_DBBase):
    def test_15_insert_payload_keys(self):
        recorded = {}
        orig = SalesDAO.insert_invoice

        def capture(**kw):
            recorded.update(kw)
            return orig(**kw)

        with mock.patch.object(SalesDAO, "insert_invoice", side_effect=capture):
            SalesDAO.insert_invoice(
                bill_no="CS-2001", sale_date="2026-01-25", sale_time="10:00",
                sale_type="Cash", customer_id=self.customer_id,
                patient_name="", doctor_id=None, discount=0.0,
                paid_amount=100.0, total_amount=100.0, round_off=0.0,
                net_amount=100.0, remarks="", items=self._items_payload(2),
            )
        for k in ("bill_no", "sale_date", "sale_time", "sale_type",
                   "customer_id", "patient_name", "doctor_id", "discount",
                   "paid_amount", "total_amount", "round_off", "net_amount",
                   "remarks", "items"):
            self.assertIn(k, recorded)
        self.assertEqual(recorded["customer_id"], self.customer_id)

    def test_16_item_dict_shape(self):
        items = self._items_payload(3)
        for k in ("item_id", "stock_batch_id", "pack_size", "location",
                   "batch_no", "expiry", "mrp", "sale_qty",
                   "discount_amount", "amount"):
            self.assertIn(k, items[0])
        self.assertEqual(items[0]["sale_qty"], 3.0)


# ======================================================================
# 17-55: GUI tests — all skip when PySide6 is missing
# ======================================================================

@GUI
class TestItemEntryBarLoadItems(_DBBase):
    """17-21: ItemEntryBar loads items on construction."""

    def setUp(self):
        super().setUp()
        self._app = QApplication.instance() or QApplication([])
        self._msg = mock.patch.multiple(
            QMessageBox, warning=mock.DEFAULT, information=mock.DEFAULT,
            critical=mock.DEFAULT, question=mock.DEFAULT,
        )
        self._msg.start()
        self.addCleanup(self._msg.stop)

    def _bar(self):
        bar = _ItemEntryBar()
        bar.load_items()
        QApplication.processEvents()
        return bar

    def test_17_combo_populated(self):
        self.assertGreaterEqual(self._bar().item_combo.count(), 2)

    def test_18_placeholder_first(self):
        bar = self._bar()
        self.assertEqual(bar.item_combo.itemText(0), "-- Select --")
        self.assertIsNone(bar.item_combo.itemData(0))

    def test_19_combo_has_test_item(self):
        bar = self._bar()
        ids = [bar.item_combo.itemData(i) for i in range(bar.item_combo.count())]
        self.assertIn(self.item_id, ids)

    def test_20_load_blocks_signals(self):
        bar = _ItemEntryBar()
        h = mock.MagicMock()
        bar.item_combo.currentIndexChanged.connect(h)
        bar.load_items()
        QApplication.processEvents()
        h.assert_not_called()

    def test_21_set_cno(self):
        bar = self._bar()
        bar.set_cno("CS-9999")
        self.assertEqual(bar.cno_label.text(), "CS-9999")


@GUI
class TestItemSelectionBatches(_DBBase):
    """22-24: Selecting item populates batches."""

    def setUp(self):
        super().setUp()
        self._app = QApplication.instance() or QApplication([])
        self._msg = mock.patch.multiple(
            QMessageBox, warning=mock.DEFAULT, information=mock.DEFAULT,
            critical=mock.DEFAULT,
        )
        self._msg.start()
        self.addCleanup(self._msg.stop)

    def _bar(self):
        bar = _ItemEntryBar()
        bar.load_items()
        QApplication.processEvents()
        return bar

    def test_22_batches_populated(self):
        bar = self._bar()
        bar.item_combo.setCurrentIndex(bar.item_combo.findData(self.item_id))
        QApplication.processEvents()
        self.assertGreaterEqual(bar.batch_combo.count(), 2)

    def test_23_batch_placeholder(self):
        bar = self._bar()
        bar.item_combo.setCurrentIndex(bar.item_combo.findData(self.item_id))
        QApplication.processEvents()
        self.assertEqual(bar.batch_combo.itemText(0), "-- Select Batch --")

    def test_24_placeholder_clears(self):
        bar = self._bar()
        bar.item_combo.setCurrentIndex(bar.item_combo.findData(self.item_id))
        QApplication.processEvents()
        self.assertGreater(bar.batch_combo.count(), 1)
        bar.item_combo.setCurrentIndex(0)
        QApplication.processEvents()
        self.assertEqual(bar.batch_combo.count(), 0)


@GUI
class TestBatchDetails(_DBBase):
    """25-27: Batch selection fills MRP/expiry/stock."""

    def setUp(self):
        super().setUp()
        self._app = QApplication.instance() or QApplication([])
        self._msg = mock.patch.multiple(
            QMessageBox, warning=mock.DEFAULT, information=mock.DEFAULT,
            critical=mock.DEFAULT,
        )
        self._msg.start()
        self.addCleanup(self._msg.stop)

    def _bar(self):
        bar = _ItemEntryBar()
        bar.load_items()
        QApplication.processEvents()
        bar.item_combo.setCurrentIndex(bar.item_combo.findData(self.item_id))
        QApplication.processEvents()
        return bar

    def test_25_mrp(self):
        bar = self._bar()
        bar.batch_combo.setCurrentIndex(1)
        QApplication.processEvents()
        self.assertNotEqual(bar.mrp_edit.text(), "")
        self.assertNotEqual(bar.mrp_edit.text(), "0.00")

    def test_26_expiry(self):
        bar = self._bar()
        bar.batch_combo.setCurrentIndex(1)
        QApplication.processEvents()
        self.assertEqual(bar.expiry_edit.text(), "12/27")

    def test_27_stock(self):
        bar = self._bar()
        bar.batch_combo.setCurrentIndex(1)
        QApplication.processEvents()
        self.assertNotEqual(bar.stock_edit.text(), "0")


@GUI
class TestAddWorkflow(_DBBase):
    """28-31: Add button creates bill rows."""

    def setUp(self):
        super().setUp()
        self._app = QApplication.instance() or QApplication([])
        self._msg = mock.patch.multiple(
            QMessageBox, warning=mock.DEFAULT, information=mock.DEFAULT,
            critical=mock.DEFAULT,
        )
        self._msg.start()
        self.addCleanup(self._msg.stop)
        self.page = CounterSalePage()
        self.page.resize(1366, 708)
        self.page.show()
        QApplication.processEvents()
        self.panel = self.page._sale_panel
        self.entry = self.panel._entry_bar

    def tearDown(self):
        self.page.hide()
        self.page.deleteLater()
        QApplication.processEvents()

    def _add_btn(self):
        return [b for b in self.entry.findChildren(QPushButton) if b.text() == "+ Add"][0]

    def _select_item_batch(self):
        self.entry.item_combo.setCurrentIndex(
            self.entry.item_combo.findData(self.item_id))
        QApplication.processEvents()
        self.entry.batch_combo.setCurrentIndex(1)
        QApplication.processEvents()

    def test_28_add_button_exists(self):
        texts = [b.text() for b in self.entry.findChildren(QPushButton)]
        self.assertIn("+ Add", texts)

    def test_29_no_selection_warning(self):
        self._add_btn().click()
        QApplication.processEvents()
        self.assertEqual(self.panel._table.rowCount(), 0)

    def test_30_add_creates_row(self):
        self._select_item_batch()
        self.entry.qty_edit.setText("5")
        self.entry.discount_edit.setText("0.00")
        self._add_btn().click()
        QApplication.processEvents()
        self.assertEqual(self.panel._table.rowCount(), 1)
        self.assertEqual(len(self.panel._item_rows), 1)

    def test_31_correct_amount(self):
        self._select_item_batch()
        self.entry.qty_edit.setText("5")
        self.entry.discount_edit.setText("0.00")
        self._add_btn().click()
        QApplication.processEvents()
        self.assertAlmostEqual(self.panel._item_rows[0].amount, 250.0)


@GUI
class TestBillTotals(_DBBase):
    """32-33: Totals recalculate."""

    def setUp(self):
        super().setUp()
        self._app = QApplication.instance() or QApplication([])
        self._msg = mock.patch.multiple(
            QMessageBox, warning=mock.DEFAULT, information=mock.DEFAULT,
            critical=mock.DEFAULT,
        )
        self._msg.start()
        self.addCleanup(self._msg.stop)
        self.panel = _SalePanel()
        QApplication.processEvents()

    def tearDown(self):
        self.panel.deleteLater()
        QApplication.processEvents()

    def test_32_total_updates(self):
        self.panel._item_rows.append(_make_bill_row(1))
        self.panel._refresh_table()
        self.panel._recalc_totals()
        QApplication.processEvents()
        self.assertEqual(self.panel.total_amount_label.text(), "100.00")

    def test_33_discount_reduces_net(self):
        self.panel._item_rows.append(_make_bill_row(1))
        self.panel._refresh_table()
        self.panel.bill_disc_edit.setText("10.00")
        QApplication.processEvents()
        self.assertEqual(self.panel.net_amt_label.text(), "90.00")


@GUI
class TestCustomerDoctor(_DBBase):
    """34-35: Combos populated."""

    def setUp(self):
        super().setUp()
        self._app = QApplication.instance() or QApplication([])
        self._msg = mock.patch.multiple(
            QMessageBox, warning=mock.DEFAULT, information=mock.DEFAULT,
            critical=mock.DEFAULT,
        )
        self._msg.start()
        self.addCleanup(self._msg.stop)
        self.panel = _SalePanel()
        QApplication.processEvents()

    def tearDown(self):
        self.panel.deleteLater()
        QApplication.processEvents()

    def test_34_customer_combo(self):
        self.assertGreaterEqual(self.panel.customer_combo.count(), 2)

    def test_35_doctor_combo(self):
        self.assertGreaterEqual(self.panel.doctor_combo.count(), 2)


@GUI
class TestNewSaleReset(_DBBase):
    """36-37: Reset + focus."""

    def setUp(self):
        super().setUp()
        self._app = QApplication.instance() or QApplication([])
        self._msg = mock.patch.multiple(
            QMessageBox, warning=mock.DEFAULT, information=mock.DEFAULT,
            critical=mock.DEFAULT, question=mock.DEFAULT,
        )
        self._msg.start()
        self.addCleanup(self._msg.stop)
        self.page = CounterSalePage()
        self.page.resize(1366, 708)
        self.page.show()
        QApplication.processEvents()
        self.panel = self.page._sale_panel

    def tearDown(self):
        self.page.hide()
        self.page.deleteLater()
        QApplication.processEvents()

    def test_36_clears_table(self):
        self.panel._item_rows.append(_make_bill_row(1))
        self.panel._refresh_table()
        self.page._on_new()
        QApplication.processEvents()
        self.assertEqual(self.panel._table.rowCount(), 0)

    def test_37_focuses_item(self):
        self.page._on_new()
        QApplication.processEvents()
        self.assertTrue(
            QApplication.focusWidget() is self.panel._entry_bar.item_combo)


@GUI
class TestSaveValidation(_DBBase):
    """38-39: Save validates customer + items."""

    def setUp(self):
        super().setUp()
        self._app = QApplication.instance() or QApplication([])
        self._msg = mock.patch.multiple(
            QMessageBox, warning=mock.DEFAULT, information=mock.DEFAULT,
            critical=mock.DEFAULT,
        )
        self._msg.start()
        self.addCleanup(self._msg.stop)
        self.panel = _SalePanel()
        QApplication.processEvents()

    def tearDown(self):
        self.panel.deleteLater()
        QApplication.processEvents()

    def test_38_needs_customer(self):
        self.panel.customer_combo.setCurrentIndex(0)
        self.panel._item_rows.append(_make_bill_row(1))
        self.panel._refresh_table()
        self.panel._on_save()
        QApplication.processEvents()
        QMessageBox.warning.assert_called()

    def test_39_needs_items(self):
        self.panel.customer_combo.setCurrentIndex(1)
        self.panel._on_save()
        QApplication.processEvents()
        QMessageBox.warning.assert_called()


@GUI
class TestHoldValidation(_DBBase):
    """40: Hold validates items exist."""

    def setUp(self):
        super().setUp()
        self._app = QApplication.instance() or QApplication([])
        self._msg = mock.patch.multiple(
            QMessageBox, warning=mock.DEFAULT, information=mock.DEFAULT,
            critical=mock.DEFAULT,
        )
        self._msg.start()
        self.addCleanup(self._msg.stop)
        self.panel = _SalePanel()
        QApplication.processEvents()

    def tearDown(self):
        self.panel.deleteLater()
        QApplication.processEvents()

    def test_40_hold_needs_items(self):
        self.panel._on_hold()
        QApplication.processEvents()
        QMessageBox.warning.assert_called()


@GUI
class TestArchitecture(_DBBase):
    """41-43: Architecture invariants."""

    def setUp(self):
        super().setUp()
        self._app = QApplication.instance() or QApplication([])

    def test_41_panel_has_entry_bar(self):
        p = _SalePanel()
        QApplication.processEvents()
        self.assertIsInstance(p, _SalePanel)
        self.assertIsInstance(p._entry_bar, _ItemEntryBar)
        p.deleteLater()
        QApplication.processEvents()

    def test_42_load_items_called(self):
        p = _SalePanel()
        QApplication.processEvents()
        self.assertGreaterEqual(p._entry_bar.item_combo.count(), 2)
        p.deleteLater()
        QApplication.processEvents()

    def test_43_dialog_wraps_panel(self):
        d = _SaleDialog()
        QApplication.processEvents()
        self.assertIsInstance(d._panel, _SalePanel)
        d.deleteLater()
        QApplication.processEvents()


@GUI
class TestRegionBStability(_DBBase):
    """44-45: Region B stays fixed."""

    def setUp(self):
        super().setUp()
        self._app = QApplication.instance() or QApplication([])
        self._msg = mock.patch.multiple(
            QMessageBox, warning=mock.DEFAULT, information=mock.DEFAULT,
            critical=mock.DEFAULT,
        )
        self._msg.start()
        self.addCleanup(self._msg.stop)
        self.page = CounterSalePage()
        self.page.resize(1366, 708)
        self.page.show()
        QApplication.processEvents()
        self.page._apply_history_height()
        QApplication.processEvents()

    def tearDown(self):
        self.page.hide()
        self.page.deleteLater()
        QApplication.processEvents()

    def _entry_y(self):
        e = self.page._sale_panel._entry_bar
        return e.mapTo(self.page, e.rect().topLeft()).y()

    def test_44_stable_after_one_add(self):
        before = self._entry_y()
        self.page._sale_panel._item_rows.append(_make_bill_row(1))
        self.page._sale_panel._refresh_table()
        QApplication.processEvents()
        self.assertEqual(self._entry_y(), before)

    def test_45_stable_after_two_adds(self):
        before = self._entry_y()
        for i in range(2):
            self.page._sale_panel._item_rows.append(_make_bill_row(i))
        self.page._sale_panel._refresh_table()
        QApplication.processEvents()
        self.assertEqual(self._entry_y(), before)


@GUI
class TestEndToEndFlow(_DBBase):
    """46-48: Full Item -> Batch -> Qty -> Add flow."""

    def setUp(self):
        super().setUp()
        self._app = QApplication.instance() or QApplication([])
        self._msg = mock.patch.multiple(
            QMessageBox, warning=mock.DEFAULT, information=mock.DEFAULT,
            critical=mock.DEFAULT,
        )
        self._msg.start()
        self.addCleanup(self._msg.stop)
        self.page = CounterSalePage()
        self.page.resize(1366, 708)
        self.page.show()
        QApplication.processEvents()
        self.entry = self.page._sale_panel._entry_bar

    def tearDown(self):
        self.page.hide()
        self.page.deleteLater()
        QApplication.processEvents()

    def _add(self, qty="3"):
        self.entry.item_combo.setCurrentIndex(
            self.entry.item_combo.findData(self.item_id))
        QApplication.processEvents()
        self.entry.batch_combo.setCurrentIndex(1)
        QApplication.processEvents()
        self.entry.qty_edit.setText(qty)
        self.entry.discount_edit.setText("0.00")
        [b for b in self.entry.findChildren(QPushButton)
         if b.text() == "+ Add"][0].click()
        QApplication.processEvents()

    def test_46_full_flow(self):
        self._add("3")
        self.assertEqual(self.page._sale_panel._table.rowCount(), 1)
        self.assertAlmostEqual(self.page._sale_panel._item_rows[0].amount, 150.0)

    def test_47_same_item_batch_merges(self):
        self._add("2")
        self._add("2")
        self.assertEqual(self.page._sale_panel._table.rowCount(), 1)
        self.assertEqual(self.page._sale_panel._item_rows[0].sale_qty, 4)
        self.assertEqual(self.page._sale_panel.total_amount_label.text(), "200.00")

    def test_48_add_then_delete(self):
        self._add("1")
        self.assertEqual(self.page._sale_panel._table.rowCount(), 1)
        self.page._sale_panel._delete_item(0)
        QApplication.processEvents()
        self.assertEqual(self.page._sale_panel._table.rowCount(), 0)


@GUI
class TestEdgeCases(_DBBase):
    """49-50: Validation edge cases."""

    def setUp(self):
        super().setUp()
        self._app = QApplication.instance() or QApplication([])
        self._msg = mock.patch.multiple(
            QMessageBox, warning=mock.DEFAULT, information=mock.DEFAULT,
            critical=mock.DEFAULT,
        )
        self._msg.start()
        self.addCleanup(self._msg.stop)
        self.panel = _SalePanel()
        QApplication.processEvents()

    def tearDown(self):
        self.panel.deleteLater()
        QApplication.processEvents()

    def test_49_zero_qty(self):
        self.panel._entry_bar.get_current_data = mock.MagicMock(return_value={
            "item_id": 1, "item_name": "X", "stock_batch_id": 1,
            "pack_size": "", "location": "", "batch_no": "B1",
            "expiry": "12/27", "mrp": 50.0, "sale_qty": 0.0,
            "discount_amount": 0.0, "batch_stock": 100.0,
        })
        self.panel._on_add_item()
        QApplication.processEvents()
        self.assertEqual(len(self.panel._item_rows), 0)

    def test_50_discount_exceeds_gross(self):
        self.panel._entry_bar.get_current_data = mock.MagicMock(return_value={
            "item_id": 1, "item_name": "X", "stock_batch_id": 1,
            "pack_size": "", "location": "", "batch_no": "B1",
            "expiry": "12/27", "mrp": 50.0, "sale_qty": 2.0,
            "discount_amount": 200.0, "batch_stock": 100.0,
        })
        self.panel._on_add_item()
        QApplication.processEvents()
        self.assertEqual(len(self.panel._item_rows), 0)


@GUI
class TestClearReset(_DBBase):
    """51-52: Clear / reset."""

    def setUp(self):
        super().setUp()
        self._app = QApplication.instance() or QApplication([])
        self._msg = mock.patch.multiple(
            QMessageBox, warning=mock.DEFAULT, information=mock.DEFAULT,
            critical=mock.DEFAULT,
        )
        self._msg.start()
        self.addCleanup(self._msg.stop)
        self.panel = _SalePanel()
        QApplication.processEvents()

    def tearDown(self):
        self.panel.deleteLater()
        QApplication.processEvents()

    def test_51_clear_resets(self):
        e = self.panel._entry_bar
        e.item_combo.setCurrentIndex(e.item_combo.findData(self.item_id))
        QApplication.processEvents()
        e.batch_combo.setCurrentIndex(1)
        QApplication.processEvents()
        e.clear()
        QApplication.processEvents()
        self.assertEqual(e.item_combo.currentIndex(), 0)
        self.assertEqual(e.qty_edit.text(), "1")

    def test_52_reset_clears_rows(self):
        self.panel._item_rows.append(_make_bill_row(1))
        self.panel._refresh_table()
        self.assertEqual(self.panel._table.rowCount(), 1)
        self.panel.reset_for_new()
        QApplication.processEvents()
        self.assertEqual(self.panel._table.rowCount(), 0)
        self.assertEqual(self.panel._entry_bar.item_combo.currentIndex(), 0)


@GUI
class TestEditInvoice(_DBBase):
    """53: Edit loads existing invoice."""

    def setUp(self):
        super().setUp()
        self._app = QApplication.instance() or QApplication([])
        self._msg = mock.patch.multiple(
            QMessageBox, warning=mock.DEFAULT, information=mock.DEFAULT,
            critical=mock.DEFAULT,
        )
        self._msg.start()
        self.addCleanup(self._msg.stop)
        self.inv_id = SalesDAO.insert_invoice(
            bill_no="CS-3001", sale_date="2026-01-25", sale_time="10:00",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="P1", doctor_id=self.doctor_id,
            discount=5.0, paid_amount=245.0, total_amount=250.0,
            round_off=0.0, net_amount=245.0, remarks="",
            items=self._items_payload(5),
        )
        self.panel = _SalePanel()
        QApplication.processEvents()

    def tearDown(self):
        self.panel.deleteLater()
        QApplication.processEvents()

    def test_53_load_invoice(self):
        inv = SalesDAO.get_by_id(self.inv_id)
        self.panel.load_invoice(inv)
        QApplication.processEvents()
        self.assertEqual(self.panel._table.rowCount(), 1)
        self.assertEqual(self.panel.bill_no_edit.text(), "CS-3001")


@GUI
class TestHoldResume(_DBBase):
    """54-55: Hold & resume."""

    def setUp(self):
        super().setUp()
        self._app = QApplication.instance() or QApplication([])
        self._msg = mock.patch.multiple(
            QMessageBox, warning=mock.DEFAULT, information=mock.DEFAULT,
            critical=mock.DEFAULT,
        )
        self._msg.start()
        self.addCleanup(self._msg.stop)
        self.page = CounterSalePage()
        self.page.resize(1366, 708)
        self.page.show()
        QApplication.processEvents()

    def tearDown(self):
        self.page.hide()
        self.page.deleteLater()
        QApplication.processEvents()

    def test_54_hold_works(self):
        p = self.page._sale_panel
        p._item_rows.append(_make_bill_row(1))
        p._refresh_table()
        p._on_hold()
        QApplication.processEvents()
        QMessageBox.information.assert_called()

    def test_55_resume_loads(self):
        from database.hold_bill_dao import create_hold, get_by_id
        hid = create_hold(
            patient_name="ResumedP", total_amount_preview=100.0,
            created_by="admin", items=[],
        )
        hold = get_by_id(hid)
        self.page.open_sale_dialog_with_hold({"hold": hold, "items": []})
        QApplication.processEvents()
        self.assertEqual(self.page._sale_panel._hold_bill_id, hid)
        self.assertEqual(
            self.page._sale_panel.patient_name_edit.text(), "ResumedP")


if __name__ == "__main__":
    unittest.main(verbosity=2)
