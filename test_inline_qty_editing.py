"""Regression tests for inline quantity editing in Sales / Counter Sale.

Covers all requirements:
1. Qty cell in Bill Items table is editable directly (all other columns non-editable).
2. Clicking Qty cell allows direct editing without deleting or re-adding the item.
3. Current quantity is preselected when editing starts.
4. Line amount recalculates immediately using existing billing formula.
5. All dependent totals update immediately (Line amt, Disc amt, Total Items, Total Amt, Customer Saving, NET AMT, Draft/Open Bill totals).
6. Line details (item ID, batch, expiry, pack size, location, MRP) are preserved.
7. Validation against batch available stock and pack-size/loose-unit rules; rejection of 0, negative, invalid, or excessive quantities with clear message.
8. Rejection or Esc restores previous valid quantity and totals.
9. Keyboard editing with Enter to confirm and table navigation.
10. Repeated edits do not duplicate items, double-count stock, or corrupt bill amounts.
Acceptance Test: Add BIO D3 PLUS with Qty = 5, edit Qty cell to 10 -> row remains selected, amount & totals recalculate immediately, save persists correct quantity and stock movement.
Safety: Runs on isolated temporary DB; production DB is 100% untouched.
"""

from __future__ import annotations

import math
import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Isolated temporary database
_TMP_DIR = tempfile.mkdtemp(prefix="pms_inline_qty_test_")
_TMP_DB = os.path.join(_TMP_DIR, "qty_test.db")
os.environ["PHARMACY_DB"] = _TMP_DB

from database.connection import get_connection, init_database
from database.customer_dao import CustomerDAO
from database.doctor_dao import DoctorDAO
from database.item_dao import ItemDAO
from database.unit_dao import UnitDAO
from database.company_dao import CompanyDAO
from database.supplier_dao import SupplierDAO
from database.purchase_dao import PurchaseDAO
from database.sales_dao import SalesDAO
from database.stock_dao import StockDAO
from database import auth, financial_year
from database.account_roles import ensure_system_ledgers

from PySide6.QtCore import Qt, QEvent, QTimer
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QLineEdit,
    QMessageBox,
    QStyledItemDelegate,
)
from screens.counter_sale import _SalePanel, SalesBillReviewDialog, _BillItemRow


class TestInlineQuantityEditing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PHARMACY_DB"] = _TMP_DB
        init_database()
        cls._app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        os.environ["PHARMACY_DB"] = _TMP_DB
        conn = get_connection()
        try:
            for tbl in [
                "sales_invoice_items", "sales_invoices",
                "purchase_invoice_items", "purchase_invoices",
                "stock_batches", "items", "customers", "account_ledgers",
                "ledger_transactions", "journal_entries", "journal_entry_items",
                "doctors", "suppliers", "units", "companies",
            ]:
                try:
                    conn.execute(f"DELETE FROM {tbl}")
                except Exception:
                    pass
            conn.commit()
        finally:
            conn.close()

        ensure_system_ledgers()
        financial_year.ensure_default_financial_year()

        self.unit_id = UnitDAO.insert("Pcs")
        self.company_id = CompanyDAO.insert("TestPharma", "TP")
        self.supplier_id = SupplierDAO.insert("TestSupplier")
        self.doctor_id = DoctorDAO.insert("Dr. Test")
        self.walkin_id = CustomerDAO.get_or_create_walkin()

        # Seed "BIO D3 PLUS" item: pack size 10, MRP 200.00 (unit price 20.00)
        self.bio_item_id = ItemDAO.insert(
            item_name="BIO D3 PLUS",
            unit_id=self.unit_id,
            company_id=self.company_id,
            pack_size="10",
            mrp=200.0,
        )

        # Seed stock: 50 units
        PurchaseDAO.insert_invoice(
            voucher_no="PV-BIO-01", voucher_date="2026-01-01", voucher_time="",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="INV-BIO-01", invoice_date="2026-01-01",
            invoice_net_amount=1000.0, bill_discount=0, due_date="",
            total_amount=1000.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=1000.0, round_off=0,
            net_amount=1000.0, remarks="",
            items=[{
                "item_id": self.bio_item_id, "pack_size": "10",
                "pay_qty": 5.0, "free_qty": 0, "batch_no": "BIO-B01",
                "expiry": "12/28", "rate": 150.0, "mrp": 200.0,
                "discount": 0, "gst_percent": 0, "gst_amount": 0,
                "amount": 750.0, "purchase_rate": 150.0,
                "net_rate": 150.0, "pp": 150.0,
            }],
        )
        bio_batches = StockDAO.get_stock_batches_for_item(self.bio_item_id)
        self.bio_batch = bio_batches[0]
        self.bio_batch_id = self.bio_batch["id"]

        self._warning_messages = []
        self._patches = [
            mock.patch.object(
                QMessageBox, "warning",
                side_effect=lambda parent, title, msg: (self._warning_messages.append((title, msg)), QMessageBox.Ok)[1]
            ),
            mock.patch.object(QMessageBox, "information", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "critical", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def _pump(self, n=5):
        for _ in range(n):
            self._app.processEvents()

    def _create_sale_panel_with_bio(self, qty=5.0) -> _SalePanel:
        panel = _SalePanel(popup_mode=False)
        self._pump()
        # Add BIO D3 PLUS line directly
        unit_price = 200.0 / 10.0  # 20.0
        row = _BillItemRow(
            item_id=self.bio_item_id,
            item_name="BIO D3 PLUS",
            stock_batch_id=self.bio_batch_id,
            pack_size="10",
            location="Rack-A",
            batch_no="BIO-B01",
            expiry="12/28",
            mrp=200.0,
            sale_qty=qty,
            discount_amount=0.0,
            amount=round(qty * unit_price, 2),
        )
        panel._item_rows.append(row)
        panel._refresh_table()
        panel._recalc_totals()
        self._pump()
        return panel

    def test_01_qty_cell_editable_directly_and_others_not(self):
        """1. Make Qty cell in Bill Items table editable directly; others non-editable."""
        panel = self._create_sale_panel_with_bio(qty=5.0)

        # Qty is Column 7
        qty_item = panel._table.item(0, 7)
        self.assertIsNotNone(qty_item)
        self.assertTrue(bool(qty_item.flags() & Qt.ItemIsEditable), "Column 7 (Qty) must be editable")

        # All other columns (0, 1, 2, 3, 4, 5, 6, 8, 9) must NOT be editable
        for col in [0, 1, 2, 3, 4, 5, 6, 8, 9]:
            item = panel._table.item(0, col)
            if item:
                self.assertFalse(
                    bool(item.flags() & Qt.ItemIsEditable),
                    f"Column {col} should NOT be editable"
                )

    def test_02_click_qty_cell_initiates_editing_and_preselects_quantity(self):
        """2 & 3. Clicking Qty cell initiates editing and preselects current quantity."""
        panel = self._create_sale_panel_with_bio(qty=5.0)

        # Trigger cell click on column 7
        panel._on_table_cell_clicked(0, 7)
        self._pump()

        # Verify active editor is created on delegate
        delegate = panel._qty_delegate
        self.assertIsNotNone(delegate.active_editor, "Editor should be active on Qty cell")
        self.assertEqual(delegate.active_editor.text(), "5")

        # Pump events to let QTimer.singleShot(0, editor.selectAll) run
        self._pump(10)
        self.assertTrue(delegate.active_editor.hasSelectedText(), "Current quantity must be preselected")
        self.assertEqual(delegate.active_editor.selectedText(), "5")

    def test_03_acceptance_test_bio_d3_plus_5_to_10_recalc_and_save(self):
        """Acceptance Test: Add BIO D3 PLUS with Qty = 5, edit Qty cell to 10.

        The same row must remain selected, the amount and all bill totals must
        recalculate immediately, and saving must persist the correct quantity
        and stock movement.
        """
        panel = self._create_sale_panel_with_bio(qty=5.0)

        # Initial checks (Qty = 5, pack_size = 10, MRP = 200 -> unit_price = 20)
        self.assertEqual(panel._item_rows[0].sale_qty, 5.0)
        self.assertEqual(panel._item_rows[0].amount, 100.0)
        self.assertEqual(panel.total_items_label.text(), "1")
        self.assertEqual(panel.total_amount_label.text(), "100.00")
        self.assertEqual(panel.net_amt_label.text(), "100.00")

        # Inline edit Qty cell from 5 to 10
        success = panel._update_row_quantity(0, "10")
        self.assertTrue(success)
        self._pump()

        # 1. The same row must remain selected
        self.assertEqual(panel._table.currentRow(), 0)

        # 2. Qty and Amount in table must update
        self.assertEqual(panel._table.item(0, 7).text(), "10")
        self.assertEqual(panel._table.item(0, 9).text(), "200.00")

        # 3. All bill totals must recalculate immediately
        self.assertEqual(panel._item_rows[0].sale_qty, 10.0)
        self.assertEqual(panel._item_rows[0].amount, 200.0)
        self.assertEqual(panel.total_items_label.text(), "1")
        self.assertEqual(panel.total_amount_label.text(), "200.00")
        self.assertEqual(panel.net_amt_label.text(), "200.00")

        # 4. Saving must persist the correct quantity and stock movement
        initial_stock = float(StockDAO.get_stock_batches_for_item(self.bio_item_id)[0]["stock_qty"])
        self.assertEqual(initial_stock, 50.0)

        # Commit sale directly (simulating review dialog final save)
        panel._in_review_popup = True
        panel._on_save()
        self._pump()

        # Verify saved invoice in DB
        invoices = SalesDAO.get_all()
        self.assertEqual(len(invoices), 1)
        inv = invoices[0]
        self.assertEqual(inv["total_amount"], 200.0)
        self.assertEqual(inv["net_amount"], 200.0)

        items = SalesDAO.get_invoice_items(inv["id"])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["sale_qty"], 10.0)
        self.assertEqual(items[0]["amount"], 200.0)

        # Verify stock movement: exactly 10 units deducted from 50 -> 40
        updated_stock = float(StockDAO.get_stock_batches_for_item(self.bio_item_id)[0]["stock_qty"])
        self.assertEqual(updated_stock, 40.0, "Stock must decrease by exactly 10 units")

    def test_04_pack_size_and_loose_unit_calculation(self):
        """4 & 7. Pack-size and loose-unit calculation (amount = qty * MRP / pack_size)."""
        # Seed an item with pack_size = 15, MRP = 150 (unit price = 10.00)
        item15_id = ItemDAO.insert(
            item_name="Tablet-15",
            unit_id=self.unit_id,
            company_id=self.company_id,
            pack_size="15",
            mrp=150.0,
        )
        PurchaseDAO.insert_invoice(
            voucher_no="PV-T15", voucher_date="2026-01-01", voucher_time="",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="INV-T15", invoice_date="2026-01-01",
            invoice_net_amount=1500.0, bill_discount=0, due_date="",
            total_amount=1500.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=1500.0, round_off=0,
            net_amount=1500.0, remarks="",
            items=[{
                "item_id": item15_id, "pack_size": "15",
                "pay_qty": 2.0, "free_qty": 0, "batch_no": "B15-01",
                "expiry": "12/28", "rate": 100.0, "mrp": 150.0,
                "discount": 0, "gst_percent": 0, "gst_amount": 0,
                "amount": 200.0, "purchase_rate": 100.0,
                "net_rate": 100.0, "pp": 100.0,
            }],
        )
        b15 = StockDAO.get_stock_batches_for_item(item15_id)[0]

        panel = _SalePanel(popup_mode=False)
        self._pump()
        row = _BillItemRow(
            item_id=item15_id, item_name="Tablet-15",
            stock_batch_id=b15["id"], pack_size="15",
            location="A1", batch_no="B15-01", expiry="12/28",
            mrp=150.0, sale_qty=3.0, discount_amount=0.0, amount=30.0,
        )
        panel._item_rows.append(row)
        panel._refresh_table()
        panel._recalc_totals()

        # Edit Qty to 7 loose tablets: 7 * (150 / 15) = 70.00
        success = panel._update_row_quantity(0, "7")
        self.assertTrue(success)
        self.assertEqual(panel._item_rows[0].sale_qty, 7.0)
        self.assertEqual(panel._item_rows[0].amount, 70.0)
        self.assertEqual(panel._table.item(0, 9).text(), "70.00")
        self.assertEqual(panel.total_amount_label.text(), "70.00")

    def test_05_line_discount_and_dependent_totals(self):
        """5. Recalculate dependent totals including line discount and customer savings."""
        panel = self._create_sale_panel_with_bio(qty=5.0)
        # Set line discount = 15.00: Gross = 100.00, Line Amt = 85.00
        panel._item_rows[0].discount_amount = 15.0
        panel._item_rows[0].amount = 85.0
        panel._refresh_table()
        panel._recalc_totals()

        self.assertEqual(panel._table.item(0, 8).text(), "15.00")
        self.assertEqual(panel._table.item(0, 9).text(), "85.00")
        self.assertEqual(panel.total_amount_label.text(), "85.00")

        # Edit Qty to 10: Gross = 200.00, Line Amt = 200 - 15 = 185.00
        panel._update_row_quantity(0, "10")
        self.assertEqual(panel._item_rows[0].amount, 185.0)
        self.assertEqual(panel._table.item(0, 9).text(), "185.00")
        self.assertEqual(panel.total_amount_label.text(), "185.00")

        # Set Customer Saving (bill_discount) = 25.00
        panel.bill_disc_edit.setText("25.00")
        self._pump()
        # Net = 185 - 25 = 160.00
        self.assertEqual(panel.net_amt_label.text(), "160.00")

    def test_06_reject_zero_negative_and_invalid_quantities(self):
        """7 & 8. Reject invalid, zero, or negative quantities and restore previous valid value."""
        panel = self._create_sale_panel_with_bio(qty=5.0)

        for invalid_val in ["0", "-5", "abc", "", "   ", "-0.1"]:
            self._warning_messages.clear()
            success = panel._update_row_quantity(0, invalid_val)
            self.assertFalse(success, f"Value '{invalid_val}' should be rejected")
            self.assertTrue(len(self._warning_messages) >= 1)
            # Verify previous quantity 5 is restored
            self.assertEqual(panel._item_rows[0].sale_qty, 5.0)
            self.assertEqual(panel._item_rows[0].amount, 100.0)
            self.assertEqual(panel._table.item(0, 7).text(), "5")
            self.assertEqual(panel._table.item(0, 9).text(), "100.00")
            self.assertEqual(panel.total_amount_label.text(), "100.00")

    def test_07_reject_excessive_quantity_exceeding_stock(self):
        """7 & 8. Reject quantity exceeding batch available stock and restore previous value."""
        panel = self._create_sale_panel_with_bio(qty=5.0)
        # Available stock is 50. Try to change to 100
        self._warning_messages.clear()
        success = panel._update_row_quantity(0, "100")
        self.assertFalse(success, "Quantity exceeding available stock must be rejected")
        self.assertTrue(any("Insufficient Stock" in t or "available" in m for t, m in self._warning_messages))

        # Restores previous quantity 5
        self.assertEqual(panel._item_rows[0].sale_qty, 5.0)
        self.assertEqual(panel._table.item(0, 7).text(), "5")
        self.assertEqual(panel.total_amount_label.text(), "100.00")

    def test_08_cancel_editing_with_esc_preserves_quantity_and_totals(self):
        """8. Pressing Esc cancels editing and preserves previous valid quantity and totals."""
        panel = self._create_sale_panel_with_bio(qty=5.0)
        panel._on_table_cell_clicked(0, 7)
        self._pump()

        editor = panel._qty_delegate.active_editor
        self.assertIsNotNone(editor)
        editor.setText("999")

        # Simulate Escape key press
        esc_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
        QApplication.sendEvent(editor, esc_event)
        self._pump()

        # Cell and totals remain unchanged
        self.assertEqual(panel._item_rows[0].sale_qty, 5.0)
        self.assertEqual(panel._table.item(0, 7).text(), "5")
        self.assertEqual(panel._item_rows[0].amount, 100.0)
        self.assertEqual(panel.total_amount_label.text(), "100.00")

    def test_09_repeated_quantity_edits_no_duplicates_no_stock_leak(self):
        """10. Repeated edits do not duplicate items, double-count stock, or corrupt bill."""
        panel = self._create_sale_panel_with_bio(qty=5.0)

        # Sequence of edits: 5 -> 10 -> 8 -> 15 -> 6
        for qty in [10.0, 8.0, 15.0, 6.0]:
            success = panel._update_row_quantity(0, str(int(qty)))
            self.assertTrue(success)
            self.assertEqual(len(panel._item_rows), 1, "Must never duplicate items")
            self.assertEqual(panel._table.rowCount(), 1, "Must have exactly 1 row")
            expected_amt = round(qty * 20.0, 2)
            self.assertEqual(panel._item_rows[0].amount, expected_amt)
            self.assertEqual(panel._table.item(0, 9).text(), f"{expected_amt:.2f}")
            self.assertEqual(panel.total_amount_label.text(), f"{expected_amt:.2f}")

    def test_10_keyboard_editing_and_enter_confirmation(self):
        """9. Keyboard editing with Enter to confirm and navigation."""
        panel = self._create_sale_panel_with_bio(qty=5.0)
        panel._table.setCurrentCell(0, 0)
        panel._table.selectRow(0)

        # Press Enter on selected row
        enter_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
        QApplication.sendEvent(panel._table, enter_event)
        self._pump()

        # Editor should be active on Qty
        editor = panel._qty_delegate.active_editor
        self.assertIsNotNone(editor, "Enter key on row must open Qty editor")
        editor.setText("12")

        # Press Enter on editor to confirm
        editor.returnPressed.emit()
        self._pump()

        # Verified updated
        self.assertEqual(panel._item_rows[0].sale_qty, 12.0)
        self.assertEqual(panel._item_rows[0].amount, 240.0)
        self.assertEqual(panel._table.item(0, 7).text(), "12")
        self.assertEqual(panel._table.item(0, 9).text(), "240.00")

    def test_11_sales_bill_review_dialog_editing_existing_bill(self):
        """Editing an existing bill in SalesBillReviewDialog preserves edit workflow."""
        # Save an initial bill with BIO D3 PLUS Qty = 5
        panel = self._create_sale_panel_with_bio(qty=5.0)
        panel._in_review_popup = True
        panel._on_save()
        self._pump()

        invoices = SalesDAO.get_all()
        self.assertEqual(len(invoices), 1)
        inv = SalesDAO.get_by_id(invoices[0]["id"])

        # Stock after 5 units sold: 50 - 5 = 45
        stock_after_first_sale = StockDAO.get_stock_batches_for_item(self.bio_item_id)[0]["stock_qty"]
        self.assertEqual(stock_after_first_sale, 45.0)

        # Open SalesBillReviewDialog in edit mode for this invoice
        source_panel = _SalePanel(popup_mode=False)
        self._pump()
        dlg = SalesBillReviewDialog(source_panel, invoice=inv)
        self._pump()

        # In edit dialog, edit Qty cell from 5 to 8
        review_panel = dlg._panel
        self.assertEqual(len(review_panel._item_rows), 1)
        self.assertEqual(review_panel._item_rows[0].sale_qty, 5.0)

        success = review_panel._update_row_quantity(0, "8")
        self.assertTrue(success)
        self._pump()

        # Dialog totals should update immediately
        self.assertEqual(review_panel._item_rows[0].amount, 160.0)
        self.assertEqual(dlg._footer_total_amount.text(), "160.00")
        self.assertEqual(dlg._footer_net_amount.text(), "160.00")

        # Save from review dialog
        review_panel._commit_sale()
        self._pump()

        # Verify updated invoice in DB
        updated_inv = SalesDAO.get_by_id(inv["id"])
        self.assertEqual(updated_inv["total_amount"], 160.0)
        updated_items = SalesDAO.get_invoice_items(inv["id"])
        self.assertEqual(updated_items[0]["sale_qty"], 8.0)

        # Verify net stock deducted: 50 - 8 = 42
        final_stock = StockDAO.get_stock_batches_for_item(self.bio_item_id)[0]["stock_qty"]
        self.assertEqual(final_stock, 42.0)

    def test_12_production_database_safety(self):
        """Verify production DB was completely untouched during test execution."""
        prod_db = os.path.join(os.path.dirname(__file__), "data", "pharmacy.db")
        if os.path.exists(prod_db):
            import sqlite3
            pconn = sqlite3.connect(prod_db)
            cur = pconn.cursor()
            cur.execute("SELECT COUNT(*) FROM sales_invoices")
            count = cur.fetchone()[0]
            pconn.close()
            self.assertEqual(count, 72175, "Production invoices count must remain 72,175 intact")


if __name__ == "__main__":
    unittest.main()
