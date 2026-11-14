"""Integration tests verifying the Debit Note workflow across Screenshots 1, 2, and 3.

Screenshot 1: New Debit Note creation dialog (Type: Supplier, Item entry, 13 columns, Total Items, Total Amount, Amount Add to Supplier Ledger).
Screenshot 2: Purchase Invoice dialog with Net Payable section: Total Amount, Add GST Tax, Less Bill Discount, Less DN Amt + [Debit Note] button, Remarks, Add Other Amt, Paid Amount, Round off, Net Amount, alert banner, [Save], [Close].
Screenshot 3: Pending Debit Note(s) For [Supplier] dialog with VhType, VhNo, VhDate, VhAmount, UnSettled, DebitAmt, DiscAmt, [New Debit Note], [Done], [Close].
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from database.connection import get_connection, init_database
from database.purchase_dao import PurchaseDAO
from database.debit_note_dao import DebitNoteDAO
from database.item_dao import ItemDAO
from database.supplier_dao import SupplierDAO
from database.company_dao import CompanyDAO
from database.unit_dao import UnitDAO
from database.stock_dao import StockDAO
from database.account_roles import ensure_system_ledgers
from database import auth, financial_year

from screens.purchase_invoice import _InvoiceDialog
from screens.debit_note import _DebitNoteEntryDialog, PendingDebitNotesDialog


class TestDebitNoteWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls._db_fd, cls._db_path = tempfile.mkstemp(suffix="_dn_wf.db")
        os.close(cls._db_fd)
        os.environ["PHARMACY_DB"] = cls._db_path
        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin123")
        auth.session.login("admin", "admin123")

    @classmethod
    def tearDownClass(cls):
        try:
            os.remove(cls._db_path)
        except Exception:
            pass

    def setUp(self):
        conn = get_connection()
        for tbl in [
            "debit_note_settlements", "debit_note_items", "debit_notes",
            "purchase_invoice_items", "purchase_invoices", "stock_batches",
            "items", "suppliers", "companies", "units",
        ]:
            try:
                conn.execute(f"DELETE FROM {tbl}")
            except Exception:
                pass
        conn.commit()
        conn.close()

        ensure_system_ledgers()

        # Seed supplier, company, unit, item
        self.sup_id = SupplierDAO.insert("FRESHENIUS OCTA HEALTH SCI PVT LTD")
        self.comp_id = CompanyDAO.insert("Cipla Healthcare", "CIP")
        self.unit_id = UnitDAO.insert("STRIP")

        self.item_id = ItemDAO.insert(
            item_name="PROTONIX DSR CAPSULE",
            company_id=self.comp_id,
            unit_id=self.unit_id,
            pack_size="10",
            mrp=120.0,
            rate=91.42,
        )

        # Seed initial purchase to create stock batches
        self.init_inv_id = PurchaseDAO.insert_invoice(
            voucher_no="PI-001",
            voucher_date="2026-11-14",
            voucher_time="10:00 AM",
            purchase_type="Credit",
            supplier_id=self.sup_id,
            invoice_no="INV-100",
            invoice_date="2026-11-14",
            invoice_net_amount=7384.0,
            bill_discount=0.0,
            due_date="2026-12-14",
            total_amount=7384.0,
            gst_amount=369.2,
            debit_note_amount=0.0,
            other_amount=0.0,
            paid_amount=0.0,
            round_off=-0.2,
            net_amount=7753.0,
            remarks="Initial batch stock",
            items=[
                {
                    "item_id": self.item_id,
                    "pack_size": "10",
                    "pay_qty": 100.0,
                    "free_qty": 0.0,
                    "batch_no": "C-26056",
                    "expiry": "30-06-2028",
                    "rate": 91.42,
                    "mrp": 120.0,
                    "discount": 0.0,
                    "gst_percent": 5.0,
                    "gst_amount": 369.2,
                    "amount": 7384.0,
                    "purchase_rate": 73.84,
                    "net_rate": 73.84,
                    "pp": 25.01,
                }
            ],
        )

        batches = StockDAO.get_by_item(self.item_id)
        self.assertEqual(len(batches), 1)
        self.batch_id = batches[0]["id"]
        # 100 packs * 10 units = 1000 loose units
        self.assertEqual(batches[0]["stock_qty"], 1000.0)

    def test_debit_note_creation_and_pending_dialog(self):
        """Verify Screenshot 1 & 3: create debit note and verify it appears in PendingDebitNotesDialog."""
        dn_id = DebitNoteDAO.create_debit_note(
            header={
                "voucher_no": "DN-0001",
                "voucher_date": "2026-11-14",
                "voucher_time": "1:17 PM",
                "dn_date": "2026-11-14",
                "dn_type": "Supplier",
                "supplier_id": self.sup_id,
                "total_amount": 914.20,
                "added_to_ledger": "N",
                "remarks": "Return damaged goods",
            },
            items=[
                {
                    "item_id": self.item_id,
                    "stock_batch_id": self.batch_id,
                    "batch_no": "C-26056",
                    "expiry": "30-06-2028",
                    "pack_size": "10",
                    "rate": 91.42,
                    "mrp": 120.0,
                    "return_qty": 1.0,
                    "free_qty": 0.0,
                    "less_amount": 0.0,
                    "amount": 914.20,
                    "return_reason": "Purchase Return",
                    "price_factor": 1.0,
                    "is_pack_qty": True,
                }
            ],
        )
        self.assertIsNotNone(dn_id)

        # Stock deduction verified: 1 pack = 10 loose units returned
        batch_after = StockDAO.get_stock_batch_by_id(self.batch_id)
        self.assertEqual(batch_after["stock_qty"], 990.0)

        # Verify Screenshot 3: Pending Debit Note Dialog loads this note
        pending_notes = DebitNoteDAO.get_unsettled_by_supplier(self.sup_id)
        self.assertEqual(len(pending_notes), 1)
        self.assertEqual(pending_notes[0]["voucher_no"], "DN-0001")
        self.assertEqual(pending_notes[0]["unsettled_amount"], 914.20)
        self.assertEqual(pending_notes[0]["settlement_status"], "UNSETTLED")

        # Open PendingDebitNotesDialog
        dlg = PendingDebitNotesDialog(
            supplier_id=self.sup_id,
            supplier_name="FRESHENIUS OCTA HEALTH SCI PVT LTD",
            max_adjustment_needed=5000.0,
        )
        self.assertEqual(dlg.table.rowCount(), 1)
        self.assertEqual(dlg.table.item(0, 0).text(), "Debit Note")
        self.assertEqual(dlg.table.item(0, 1).text(), "DN-0001")
        self.assertEqual(dlg.table.item(0, 4).text(), "914.20")

        # By default auto-suggests up to max_needed
        debit_edit = dlg.table.cellWidget(0, 5)
        self.assertEqual(debit_edit.text(), "914.20")

        # Click done and verify result
        dlg._on_done()
        settlements = dlg.get_settlements()
        self.assertEqual(len(settlements), 1)
        self.assertEqual(settlements[0]["debit_note_id"], dn_id)
        self.assertEqual(settlements[0]["debit_amount"], 914.20)
        self.assertEqual(dlg.get_total_debit_applied(), 914.20)

    def test_purchase_invoice_footer_and_settlement_lifecycle(self):
        """Verify Screenshot 2: footer layout, Less DN Amt, Net Amount recalc, and atomic settlement."""
        # Create an unsettled Debit Note of 500.00
        dn_id = DebitNoteDAO.create_debit_note(
            header={
                "voucher_no": "DN-0002",
                "voucher_date": "2026-11-14",
                "supplier_id": self.sup_id,
                "total_amount": 500.0,
                "added_to_ledger": "N",
            },
            items=[
                {
                    "item_id": self.item_id,
                    "stock_batch_id": self.batch_id,
                    "batch_no": "C-26056",
                    "expiry": "30-06-2028",
                    "pack_size": "10",
                    "rate": 50.0,
                    "mrp": 120.0,
                    "return_qty": 1.0,
                    "free_qty": 0.0,
                    "amount": 500.0,
                    "is_pack_qty": True,
                }
            ],
        )

        inv_dlg = _InvoiceDialog()

        # Check footer components exist
        self.assertTrue(hasattr(inv_dlg, "_total_items_label"))
        self.assertTrue(hasattr(inv_dlg, "total_amount_label"))
        self.assertTrue(hasattr(inv_dlg, "gst_label"))
        self.assertTrue(hasattr(inv_dlg, "bill_disc_edit"))
        self.assertTrue(hasattr(inv_dlg, "dn_edit"))
        self.assertTrue(hasattr(inv_dlg, "dn_btn"))
        self.assertTrue(hasattr(inv_dlg, "other_edit"))
        self.assertTrue(hasattr(inv_dlg, "paid_edit"))
        self.assertTrue(hasattr(inv_dlg, "round_off_edit"))
        self.assertTrue(hasattr(inv_dlg, "net_amt_label"))
        self.assertTrue(hasattr(inv_dlg, "remarks_edit"))
        self.assertTrue(hasattr(inv_dlg, "info_banner"))
        self.assertTrue(hasattr(inv_dlg, "save_btn"))
        self.assertTrue(hasattr(inv_dlg, "cancel_btn"))

        # Verify buttons text
        self.assertEqual(inv_dlg.save_btn.text(), "Save")
        self.assertEqual(inv_dlg.cancel_btn.text(), "Close")

        # Select supplier
        idx = inv_dlg.supplier_combo.findData(self.sup_id)
        inv_dlg.supplier_combo.setCurrentIndex(idx)

        # Add 1 item row
        inv_dlg._entry_bar.item_combo.setCurrentIndex(inv_dlg._entry_bar.item_combo.findData(self.item_id))
        inv_dlg._entry_bar.batch_edit.setText("C-26056")
        inv_dlg._entry_bar.expiry_edit.setDate(QDate(2028, 6, 30))
        inv_dlg._entry_bar.pack_edit.setText("10")
        inv_dlg._entry_bar.pay_qty_edit.setText("100")
        inv_dlg._entry_bar.free_qty_edit.setText("30")
        inv_dlg._entry_bar.rate_edit.setText("91.42")
        inv_dlg._entry_bar.mrp_edit.setText("120")
        inv_dlg._entry_bar.discount_edit.setText("0")
        inv_dlg._entry_bar.gst_edit.setText("5")
        inv_dlg._on_add_item()

        # Verify Total Items display is 1
        self.assertEqual(inv_dlg._total_items_label.text(), "1")
        # Total Amount = 100 * 91.42 = 9142.00
        self.assertEqual(inv_dlg.total_amount_label.text(), "9142.00")
        # GST Tax = 5% of 9142 = 457.10
        self.assertEqual(inv_dlg.gst_label.text(), "457.10")

        # Apply Debit Note of 500
        inv_dlg._debit_note_settlements = [
            {"debit_note_id": dn_id, "voucher_no": "DN-0002", "debit_amount": 500.0, "discount_amount": 0.0}
        ]
        inv_dlg.dn_edit.setText("500.00")
        inv_dlg._recalc_totals()

        # 9142 + 457.10 - 500 = 9099.10 -> round off -0.10 -> Net Amount 9099
        self.assertEqual(inv_dlg.round_off_edit.text(), "-0.10")
        self.assertEqual(inv_dlg.net_amt_label.text(), "9099.00")

        inv_dlg.remarks_edit.setPlainText("Test purchase with DN settlement")

        # Mock out QMessageBox warnings/info and save
        with mock.patch.object(QMessageBox, "warning"), mock.patch.object(QMessageBox, "information"):
            inv_dlg._on_save()

        self.assertTrue(inv_dlg.was_saved)

        # Verify Debit Note is now SETTLED in DB
        dn_after = DebitNoteDAO.get_by_id(dn_id)
        self.assertEqual(dn_after["settled_amount"], 500.0)
        self.assertEqual(dn_after["settlement_status"], "SETTLED")

        # Verify settlement link exists
        cur_inv_id = PurchaseDAO.get_all()[0]["id"]
        settlements_in_db = DebitNoteDAO.get_settlements_for_invoice(cur_inv_id)
        self.assertEqual(len(settlements_in_db), 1)
        self.assertEqual(settlements_in_db[0]["debit_note_id"], dn_id)
        self.assertEqual(settlements_in_db[0]["settled_amount"], 500.0)

        # Deleting the purchase invoice reverses the settlement!
        PurchaseDAO.delete_invoice(cur_inv_id)

        dn_reverted = DebitNoteDAO.get_by_id(dn_id)
        self.assertEqual(dn_reverted["settled_amount"], 0.0)
        self.assertEqual(dn_reverted["settlement_status"], "UNSETTLED")

        inv_dlg.close()


if __name__ == "__main__":
    unittest.main()
