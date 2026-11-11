import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

sys.path.insert(0, os.getcwd())

from PySide6.QtWidgets import QApplication, QMessageBox
_app = QApplication.instance() or QApplication([])

from database.connection import init_database, get_connection
from database import auth, financial_year
from database.company_dao import CompanyDAO
from database.unit_dao import UnitDAO
from database.supplier_dao import SupplierDAO
from database.customer_dao import CustomerDAO
from database.item_dao import ItemDAO
from database.purchase_dao import PurchaseDAO, pack_factor
from database.sales_dao import SalesDAO
from database.credit_note_dao import CreditNoteDAO
from database.debit_note_dao import DebitNoteDAO
from database.stock_dao import StockDAO
from database.stock_adjustment_dao import StockAdjustmentDAO, StockAdjustmentError
from screens.stock_adjustment_dialog import StockAdjustmentDialog


class TestStockQuantityCalculationAndReconciliation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fd, cls._db_path = tempfile.mkstemp(prefix="pharmacy_stock_calc_test_", suffix=".db")
        os.close(fd)
        cls._previous_db = os.environ.get("PHARMACY_DB")
        os.environ["PHARMACY_DB"] = cls._db_path

        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_financial_year_schema()
        financial_year.ensure_default_financial_year()
        from database.account_roles import ensure_system_ledgers
        ensure_system_ledgers()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")

    @classmethod
    def tearDownClass(cls):
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(cls._db_path + suffix)
            except FileNotFoundError:
                pass
        if cls._previous_db is None:
            os.environ.pop("PHARMACY_DB", None)
        else:
            os.environ["PHARMACY_DB"] = cls._previous_db

    def setUp(self):
        conn = get_connection()
        try:
            for table in (
                "stock_adjustments", "credit_note_items", "credit_notes",
                "debit_note_items", "debit_notes", "sales_invoice_items",
                "sales_invoices", "purchase_invoice_items", "purchase_invoices",
                "stock_batches", "items", "customers", "suppliers", "units", "companies",
            ):
                try:
                    conn.execute(f"DELETE FROM {table}")
                except Exception:
                    pass
            conn.commit()
        finally:
            conn.close()

        self.company_id = CompanyDAO.insert("Stabizol Laboratories", "SL")
        self.unit_id = UnitDAO.insert("Tablets")
        self.supplier_id = SupplierDAO.insert("Med Distributors")
        self.customer_id = CustomerDAO.insert("WALKIN", "9999999999")

        # Mock standard modal message boxes
        self._patches = [
            mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "information", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "critical", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
        ]
        for patch in self._patches:
            patch.start()
            self.addCleanup(patch.stop)

    def _pump(self):
        _app.processEvents()

    def _insert_purchase(self, item_id, pay_qty, free_qty, batch_no="B1", expiry="2028-12-31", rate=50.0, mrp=100.0, pack_size="10"):
        amount = pay_qty * rate
        return PurchaseDAO.insert_invoice(
            voucher_no=f"PV-{batch_no}",
            voucher_date="2026-10-01",
            voucher_time="10:00:00",
            purchase_type="Cash",
            supplier_id=self.supplier_id,
            invoice_no=f"INV-{batch_no}",
            invoice_date="2026-10-01",
            invoice_net_amount=amount,
            bill_discount=0.0,
            due_date="2026-11-01",
            total_amount=amount,
            gst_amount=0.0,
            debit_note_amount=0.0,
            other_amount=0.0,
            paid_amount=amount,
            round_off=0.0,
            net_amount=amount,
            remarks="",
            items=[{
                "item_id": item_id,
                "pack_size": str(pack_size),
                "pay_qty": float(pay_qty),
                "free_qty": float(free_qty),
                "batch_no": batch_no,
                "expiry": expiry,
                "rate": rate,
                "mrp": mrp,
                "discount": 0.0,
                "gst_percent": 0.0,
                "gst_amount": 0.0,
                "amount": amount,
                "purchase_rate": rate,
                "net_rate": rate,
                "pp": 25.0,
            }],
        )

    def test_01_pack_size_conventions_packs_vs_loose_units(self):
        """1. Pack size 10: purchases recorded in packs, stock_batches stores loose units."""
        item_id = ItemDAO.insert(
            item_name="STABIZOL DSR", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="10",
            rate=92.20, mrp=121.0, tax_structure="GST @ 5%",
        )

        # Purchase 5 packs pay_qty + 1 pack free_qty = 6 packs
        self._insert_purchase(item_id, pay_qty=5.0, free_qty=1.0, batch_no="BATCH-P10", rate=92.20, mrp=121.0)

        batches = StockDAO.get_stock_batches_for_item(item_id)
        self.assertEqual(len(batches), 1)
        # 6 packs * 10 = 60 loose tablets in stock_batches.stock_qty
        self.assertEqual(batches[0]["stock_qty"], 60.0)

        # purchase_invoice_items must preserve original pack quantities
        conn = get_connection()
        try:
            pi_item = conn.execute("SELECT pay_qty, free_qty, pack_size FROM purchase_invoice_items WHERE item_id = ?", (item_id,)).fetchone()
            self.assertEqual(pi_item["pay_qty"], 5.0)
            self.assertEqual(pi_item["free_qty"], 1.0)
            self.assertEqual(str(pi_item["pack_size"]), "10")
        finally:
            conn.close()

    def test_02_free_quantities_correctly_increase_loose_stock(self):
        """2. Free quantities are added to loose stock as (pay_qty + free_qty) * pack_size."""
        item_id = ItemDAO.insert(
            item_name="AMOX-500", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="10",
            rate=50.0, mrp=100.0, tax_structure="GST @ 5%",
        )

        # 10 pay_qty + 2 free_qty = 12 packs * 10 = 120 loose tablets
        self._insert_purchase(item_id, pay_qty=10.0, free_qty=2.0, batch_no="AMOX-B1")

        summary = StockDAO.get_item_stock_summary(item_id)
        self.assertEqual(summary["eligible_stock"], 120.0)
        self.assertEqual(summary["total_book_stock"], 120.0)

    def test_03_multiple_batches_same_item_and_smart_sorting(self):
        """3. Multiple batches: active batches prioritized, 0-stock and expired at bottom, auto-selects primary active."""
        item_id = ItemDAO.insert(
            item_name="MULTI-BATCH ITEM", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="10",
            rate=92.20, mrp=121.0, tax_structure="GST @ 5%",
        )

        future_exp1 = (date.today() + timedelta(days=300)).isoformat()
        future_exp2 = (date.today() + timedelta(days=500)).isoformat()
        past_exp = (date.today() - timedelta(days=500)).isoformat()

        conn = get_connection()
        try:
            # Batch 1: Expired, positive stock 450
            conn.execute(
                "INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty) "
                "VALUES (?, 'OLD-EXP', ?, '10', 90.0, 64.0, 60.0, 450.0)",
                (item_id, past_exp),
            )
            # Batch 2: Active, stock 13
            conn.execute(
                "INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty) "
                "VALUES (?, 'ACTIVE-SMALL', ?, '10', 121.0, 92.2, 80.68, 13.0)",
                (item_id, future_exp1),
            )
            # Batch 3: Active, stock 218 (largest active stock)
            conn.execute(
                "INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty) "
                "VALUES (?, 'ACTIVE-LARGE', ?, '10', 121.0, 92.2, 80.68, 218.0)",
                (item_id, future_exp2),
            )
            # Batch 4: Zero stock
            conn.execute(
                "INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty) "
                "VALUES (?, 'ZERO-STK', ?, '10', 121.0, 92.2, 80.68, 0.0)",
                (item_id, future_exp1),
            )
            conn.commit()
        finally:
            conn.close()

        # Stock summary calculation
        summary = StockDAO.get_item_stock_summary(item_id)
        # Eligible = 13 + 218 = 231
        self.assertEqual(summary["eligible_stock"], 231.0)
        # Expired = 450
        self.assertEqual(summary["expired_stock"], 450.0)
        # Total book = 231 + 450 = 681
        self.assertEqual(summary["total_book_stock"], 681.0)

        # Batch order check: active batches first, then expired, then zero-stock
        ordered_batches = summary["batches"]
        ordered_nos = [b["batch_no"] for b in ordered_batches]
        self.assertIn(ordered_nos[0], ["ACTIVE-SMALL", "ACTIVE-LARGE"])
        self.assertIn(ordered_nos[1], ["ACTIVE-SMALL", "ACTIVE-LARGE"])
        self.assertEqual(ordered_nos[2], "OLD-EXP")
        self.assertEqual(ordered_nos[3], "ZERO-STK")

        # Open StockAdjustmentDialog and verify no auto-selection under new requirement
        dlg = StockAdjustmentDialog()
        self._pump()
        dlg.item_combo.set_selected_id(item_id)
        self._pump()

        # Item Stock must show 231 (eligible stock), NOT 681
        self.assertEqual(dlg.item_stock_edit.text(), "231")
        # Under new requirement: selecting medicine does NOT auto-select any batch.
        self.assertIsNone(dlg.batch_combo.currentData())
        self.assertEqual(dlg.batch_stock_edit.text(), "")

        # When user explicitly selects the active batch, batch stock shows 218
        active_b_id = next(b["id"] for b in ordered_batches if b["batch_no"] == "ACTIVE-LARGE")
        dlg._select_batch_by_id(active_b_id)
        self._pump()
        self.assertEqual(dlg.batch_stock_edit.text(), "218")
        self.assertIn("ACTIVE-LARGE", dlg.batch_combo.currentText())
        dlg.close()

    def test_04_sales_movements_deduct_loose_units(self):
        """4. Sales movements deduct loose units directly from stock_batches.stock_qty."""
        item_id = ItemDAO.insert(
            item_name="PARACETAMOL 650", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="10",
            rate=15.0, mrp=30.0, tax_structure="GST @ 5%",
        )
        # Initial purchase: 10 packs = 100 loose tablets
        self._insert_purchase(item_id, pay_qty=10.0, free_qty=0.0, batch_no="PARA-B1", rate=15.0, mrp=30.0)
        batch = StockDAO.get_stock_batches_for_item(item_id)[0]
        self.assertEqual(batch["stock_qty"], 100.0)

        # Sell 14 loose tablets (1 full strip of 10 + 4 loose)
        SalesDAO.insert_invoice(
            bill_no="BILL-001", sale_date="2026-10-05", sale_time="10:00:00",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="TEST PATIENT", doctor_id=None,
            discount=0.0, paid_amount=42.0, total_amount=42.0,
            round_off=0.0, net_amount=42.0, remarks="",
            items=[{
                "item_id": item_id, "stock_batch_id": batch["id"],
                "batch_no": "PARA-B1", "pack_size": "10",
                "expiry": "2028-12-31", "mrp": 30.0,
                "sale_qty": 14.0, "discount_amount": 0.0, "amount": 42.0,
            }],
        )

        reloaded_batch = StockDAO.get_stock_batch_by_id(batch["id"])
        # 100 - 14 = 86 loose tablets
        self.assertEqual(reloaded_batch["stock_qty"], 86.0)

    def test_05_purchase_returns_sales_returns_and_authoritative_ledger(self):
        """5. Complete movement ledger: purchases, sales, sales returns, purchase returns, and adjustments."""
        item_id = ItemDAO.insert(
            item_name="AZITHRO 500", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="10",
            rate=100.0, mrp=150.0, tax_structure="GST @ 5%",
        )
        # 1. Purchase: 20 packs = 200 loose units
        self._insert_purchase(item_id, pay_qty=20.0, free_qty=0.0, batch_no="AZ-B1", rate=100.0, mrp=150.0)
        batch = StockDAO.get_stock_batches_for_item(item_id)[0]
        batch_id = batch["id"]

        # 2. Sale: 50 loose units
        SalesDAO.insert_invoice(
            bill_no="BILL-AZ-1", sale_date="2026-10-02", sale_time="10:00:00",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="PATIENT 1", doctor_id=None,
            discount=0.0, paid_amount=750.0, total_amount=750.0,
            round_off=0.0, net_amount=750.0, remarks="",
            items=[{
                "item_id": item_id, "stock_batch_id": batch_id,
                "batch_no": "AZ-B1", "pack_size": "10",
                "expiry": "2028-12-31", "mrp": 150.0,
                "sale_qty": 50.0, "discount_amount": 0.0, "amount": 750.0,
            }],
        )

        # 3. Sales Return (Credit Note): Customer returns 5 loose tablets
        CreditNoteDAO.insert_credit_note(
            {
                "voucher_date": "2026-10-03", "customer_id": self.customer_id,
                "total_amount": 75.0, "less_amount": 0.0, "net_amount": 75.0,
                "remarks": "Return 5 tablets",
            },
            [{
                "item_id": item_id, "stock_batch_id": batch_id,
                "batch_no": "AZ-B1", "pack_size": "10",
                "expiry": "2028-12-31", "rate": 100.0, "mrp": 150.0,
                "return_qty": 5.0, "less_amount": 0.0, "amount": 75.0,
            }],
        )

        # 4. Purchase Return (Debit Note): Return 2 packs (20 loose units) to supplier
        DebitNoteDAO.insert_debit_note(
            {
                "voucher_date": "2026-10-04", "supplier_id": self.supplier_id,
                "total_amount": 200.0, "gst_amount": 10.0, "net_amount": 210.0,
                "remarks": "Return 2 packs",
            },
            [{
                "item_id": item_id, "stock_batch_id": batch_id,
                "batch_no": "AZ-B1", "pack_size": "10",
                "expiry": "2028-12-31", "rate": 100.0, "mrp": 150.0,
                "return_qty": 2.0, "is_pack_qty": True, "gst_percent": 5.0, "gst_amount": 10.0,
                "amount": 200.0,
            }],
        )

        # 5. Stock Adjustment: +10 loose units
        StockAdjustmentDAO.record_adjustment(item_id, batch_id, adjusted_qty=10.0, reason="Found stock")

        # Theoretical math:
        # Pur (200) - Sale (50) + CN (5) - DN (20) + Adj (10) = 145 loose units
        movement = StockDAO.get_batch_ledger_movement(item_id, batch_id)
        self.assertEqual(movement["purchased_loose"], 200.0)
        self.assertEqual(movement["sold_loose"], 50.0)
        self.assertEqual(movement["sales_returns_loose"], 5.0)
        self.assertEqual(movement["purchase_returns_loose"], 20.0)
        self.assertEqual(movement["adjustments_loose"], 10.0)
        self.assertEqual(movement["calculated_book_stock"], 145.0)
        self.assertEqual(movement["stored_stock"], 145.0)
        self.assertEqual(movement["variance"], 0.0)

    def test_06_safe_physical_reconciliation_workflow(self):
        """6. Reconciling physical count: calculates variance transparently, records audit adjustment."""
        item_id = ItemDAO.insert(
            item_name="RECONCILE TEST MED", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="10",
            rate=92.20, mrp=121.0, tax_structure="GST @ 5%",
        )
        conn = get_connection()
        try:
            cur = conn.cursor()
            # Batch 1 (Active): 218 units
            cur.execute(
                "INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty) "
                "VALUES (?, 'ACT-218', '2028-03-31', '10', 121.0, 92.2, 80.68, 218.0)",
                (item_id,),
            )
            b1_id = cur.lastrowid
            # Batch 2 (Active): 15 units (Total active = 233)
            cur.execute(
                "INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty) "
                "VALUES (?, 'ACT-15', '2028-04-30', '10', 121.0, 92.2, 80.68, 15.0)",
                (item_id,),
            )
            # Batch 3 (Expired): 450 units (Expired book = 450, total book = 683)
            cur.execute(
                "INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty) "
                "VALUES (?, 'EXP-450', '2017-04-30', '10', 90.0, 64.0, 60.0, 450.0)",
                (item_id,),
            )
            b3_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()

        dlg = StockAdjustmentDialog()
        self._pump()
        dlg.item_combo.set_selected_id(item_id)
        self._pump()

        # Item Stock must show 233 (active eligible stock)
        self.assertEqual(dlg.item_stock_edit.text(), "233")
        # Batch combo remains unselected initially until explicitly chosen
        self.assertIsNone(dlg.batch_combo.currentData())
        dlg._select_batch_by_id(b1_id)
        self._pump()
        # Batch ACT-218 explicitly selected with Batch Stock = 218
        self.assertEqual(dlg.batch_stock_edit.text(), "218")

        # User enters reported physical count = 230
        dlg.phys_count_edit.setText("230")
        self._pump()
        # Status shows physical count vs active book (230 vs 233 = -3 variance)
        self.assertIn("Var: -3", dlg.reconcile_status_lbl.text())
        self.assertIn("450 expired", dlg.reconcile_status_lbl.text())

        # Click Reconcile Difference
        dlg._on_apply_physical_reconciliation()
        self._pump()
        # Qty (+/-) is set to -3
        self.assertEqual(dlg.qty_edit.text(), "-3")
        self.assertIn("Physical count reconciliation", dlg.reason_edit.text())

        # Save adjustment
        dlg._on_save()
        self._pump()

        # Stock batch 1 must now be 218 - 3 = 215
        reloaded_b1 = StockDAO.get_stock_batch_by_id(b1_id)
        self.assertEqual(reloaded_b1["stock_qty"], 215.0)

        # Audit record created in stock_adjustments
        adjs = StockAdjustmentDAO.get_adjustments_for_item(item_id)
        self.assertEqual(len(adjs), 1)
        self.assertEqual(adjs[0]["adjusted_qty"], -3.0)
        self.assertEqual(adjs[0]["resulting_qty"], 215.0)

        # Now test write-off on expired batch EXP-450
        dlg2 = StockAdjustmentDialog()
        self._pump()
        dlg2.item_combo.set_selected_id(item_id)
        self._pump()
        dlg2.batch_combo.set_selected_id(b3_id)
        self._pump()

        self.assertEqual(dlg2.batch_stock_edit.text(), "450")
        dlg2._on_write_off_batch()
        self._pump()
        self.assertEqual(dlg2.qty_edit.text(), "-450")
        self.assertIn("Expired stock write-off", dlg2.reason_edit.text())
        dlg2._on_save()
        self._pump()

        # Expired batch stock is now 0
        reloaded_b3 = StockDAO.get_stock_batch_by_id(b3_id)
        self.assertEqual(reloaded_b3["stock_qty"], 0.0)

        # Total item stock is now 215 + 15 = 230
        summary_after = StockDAO.get_item_stock_summary(item_id)
        self.assertEqual(summary_after["eligible_stock"], 230.0)
        self.assertEqual(summary_after["total_book_stock"], 230.0)

    def test_07_historical_records_never_silently_modified(self):
        """7. Adjustments and reconciliation never modify or delete historical purchase or sales rows."""
        item_id = ItemDAO.insert(
            item_name="AUDIT SAFETY ITEM", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="10",
            rate=50.0, mrp=100.0, tax_structure="GST @ 5%",
        )
        pur_id = self._insert_purchase(item_id, pay_qty=5.0, free_qty=0.0, batch_no="SAFE-B1", rate=50.0, mrp=100.0)
        batch = StockDAO.get_stock_batches_for_item(item_id)[0]

        sale_id = SalesDAO.insert_invoice(
            bill_no="BILL-SAFE-1", sale_date="2026-10-02", sale_time="10:00:00",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="PATIENT SAFE", doctor_id=None,
            discount=0.0, paid_amount=100.0, total_amount=100.0,
            round_off=0.0, net_amount=100.0, remarks="",
            items=[{
                "item_id": item_id, "stock_batch_id": batch["id"],
                "batch_no": "SAFE-B1", "pack_size": "10",
                "expiry": "2028-12-31", "mrp": 100.0,
                "sale_qty": 10.0, "discount_amount": 0.0, "amount": 100.0,
            }],
        )

        # Snapshot purchase and sale rows
        conn = get_connection()
        try:
            pur_row_before = dict(conn.execute("SELECT * FROM purchase_invoices WHERE id = ?", (pur_id,)).fetchone())
            pur_item_before = dict(conn.execute("SELECT * FROM purchase_invoice_items WHERE purchase_invoice_id = ?", (pur_id,)).fetchone())
            sale_row_before = dict(conn.execute("SELECT * FROM sales_invoices WHERE id = ?", (sale_id,)).fetchone())
            sale_item_before = dict(conn.execute("SELECT * FROM sales_invoice_items WHERE sales_invoice_id = ?", (sale_id,)).fetchone())
        finally:
            conn.close()

        # Perform stock adjustments
        StockAdjustmentDAO.record_adjustment(item_id, batch["id"], adjusted_qty=5.0, reason="Test safety 1")
        StockAdjustmentDAO.record_adjustment(item_id, batch["id"], adjusted_qty=-2.0, reason="Test safety 2")

        # Snapshot after adjustments
        conn = get_connection()
        try:
            pur_row_after = dict(conn.execute("SELECT * FROM purchase_invoices WHERE id = ?", (pur_id,)).fetchone())
            pur_item_after = dict(conn.execute("SELECT * FROM purchase_invoice_items WHERE purchase_invoice_id = ?", (pur_id,)).fetchone())
            sale_row_after = dict(conn.execute("SELECT * FROM sales_invoices WHERE id = ?", (sale_id,)).fetchone())
            sale_item_after = dict(conn.execute("SELECT * FROM sales_invoice_items WHERE sales_invoice_id = ?", (sale_id,)).fetchone())
        finally:
            conn.close()

        self.assertEqual(pur_row_before, pur_row_after)
        self.assertEqual(pur_item_before, pur_item_after)
        self.assertEqual(sale_row_before, sale_row_after)
        self.assertEqual(sale_item_before, sale_item_after)

    def test_08_negative_stock_rejection_on_adjustment(self):
        """8. Negative stock is rejected with clear error message without mutating database."""
        item_id = ItemDAO.insert(
            item_name="NEGATIVE TEST MED", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="10",
            rate=50.0, mrp=100.0, tax_structure="GST @ 5%",
        )
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty) "
                "VALUES (?, 'NEG-B1', '2028-12-31', '10', 100.0, 50.0, 50.0, 5.0)",
                (item_id,),
            )
            b_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()

        with self.assertRaises(StockAdjustmentError):
            StockAdjustmentDAO.record_adjustment(item_id, b_id, adjusted_qty=-10.0, reason="Too much decrease")

        # Stock must remain 5.0
        reloaded = StockDAO.get_stock_batch_by_id(b_id)
        self.assertEqual(reloaded["stock_qty"], 5.0)


if __name__ == "__main__":
    unittest.main()
