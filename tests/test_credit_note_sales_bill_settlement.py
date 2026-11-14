"""Integration tests verifying the Credit Note workflow across Screenshots 1, 2, and 3.

Screenshot 1: New Credit Note entry dialog.
Screenshot 2: Sales Bill review dialog with 'Less CN Amt' and '[ Credit Note ]' button.
Screenshot 3: Pending Credit Note(s) dialog with VhType, VhNo, VhDate, VhAmount,
              UnSettled, CreditAmt, DiscAmt, [New Credit Note], [Done], [Close].
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from database.connection import get_connection, init_database
from database.sales_dao import SalesDAO
from database.item_dao import ItemDAO
from database.customer_dao import CustomerDAO
from database.doctor_dao import DoctorDAO
from database.supplier_dao import SupplierDAO
from database.company_dao import CompanyDAO
from database.unit_dao import UnitDAO
from database.purchase_dao import PurchaseDAO
from database.stock_dao import StockDAO
from database.credit_note_dao import CreditNoteDAO
from database.account_roles import ensure_system_ledgers
from database import auth, financial_year

from screens.counter_sale import CounterSalePage, SalesBillReviewDialog
from screens.credit_note import _CreditNoteEntryDialog, PendingCreditNotesDialog


class TestCreditNoteWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls._db_fd, cls._db_path = tempfile.mkstemp(suffix="_cn_wf.db")
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
        self._msg = mock.patch.multiple(
            QMessageBox, warning=mock.DEFAULT, information=mock.DEFAULT,
            critical=mock.DEFAULT, question=mock.DEFAULT,
        )
        self._msg.start()
        self.addCleanup(self._msg.stop)

        conn = get_connection()
        try:
            for tbl in [
                "credit_note_settlements", "credit_note_items", "credit_notes",
                "sales_invoice_items", "sales_invoices", "stock_batches",
                "items", "customers", "doctors", "companies", "units",
            ]:
                try:
                    conn.execute(f"DELETE FROM {tbl}")
                except Exception:
                    pass
            conn.commit()
        finally:
            conn.close()

        ensure_system_ledgers()
        self.comp_id = CompanyDAO.insert("Cipla", "CIP")
        self.unit_id = UnitDAO.insert("Tab")
        self.cust_id = CustomerDAO.insert("WALKIN")
        self.doc_id = DoctorDAO.insert("DR.K.N.GHORPADE")
        self.item_id = ItemDAO.insert(
            item_name="MGMIX TABLET",
            unit_id=self.unit_id,
            company_id=self.comp_id,
            pack_size="10",
            mrp=285.0,
        )
        self.supp_id = SupplierDAO.insert("Cipla Supplier")
        PurchaseDAO.insert_invoice(
            voucher_no="PV-001",
            voucher_date="2026-11-14",
            voucher_time="10:00 AM",
            purchase_type="Cash",
            supplier_id=self.supp_id,
            invoice_no="PINV-001",
            invoice_date="2026-11-14",
            invoice_net_amount=500.0,
            bill_discount=0,
            due_date="",
            total_amount=500.0,
            gst_amount=0,
            debit_note_amount=0,
            other_amount=0,
            paid_amount=500.0,
            round_off=0,
            net_amount=500.0,
            remarks="",
            items=[{
                "item_id": self.item_id,
                "pack_size": "10",
                "pay_qty": 50,
                "free_qty": 0,
                "batch_no": "NPT2029",
                "expiry": "30-06-2028",
                "rate": 200.0,
                "mrp": 285.0,
                "discount": 0,
                "gst_percent": 0,
                "gst_amount": 0,
                "amount": 10000.0,
                "purchase_rate": 200.0,
                "net_rate": 200.0,
                "pp": 200.0,
            }],
        )
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        self.batch_id = batches[0]["id"]

    def test_full_credit_note_issue_and_settlement_workflow(self):
        # 1. Screenshot 1: Create a Credit Note for WALKIN (Amount = 50.00)
        cn_header = {
            "voucher_no": "CN-0001",
            "voucher_date": "2026-11-14",
            "voucher_time": "1:14 PM",
            "cn_date": "2026-11-14",
            "cn_type": "Customer",
            "customer_id": self.cust_id,
            "total_amount": 50.0,
            "ledger_amount": 0.0,
            "add_to_ledger": False,
            "remarks": "Test credit note return",
        }
        cn_items = [{
            "item_id": self.item_id,
            "stock_batch_id": self.batch_id,
            "batch_no": "NPT2029",
            "expiry": "30-06-2028",
            "pack_size": "10",
            "rate": 20.0,
            "mrp": 28.5,
            "return_qty": 2.0,
            "less_amount": 7.0,
            "amount": 50.0,
            "return_reason": "Sales Return",
            "price_factor": "MRP",
            "price_factor_num": 1.0,
        }]
        cn_id = CreditNoteDAO.insert_credit_note(cn_header, cn_items)
        self.assertGreater(cn_id, 0)

        # Verify it appears in unsettled credit notes for WALKIN (Screenshot 3)
        pending = CreditNoteDAO.get_unsettled_by_customer(self.cust_id, "WALKIN")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["id"], cn_id)
        self.assertEqual(pending[0]["total_amount"], 50.0)
        self.assertEqual(pending[0]["unsettled_amount"], 50.0)

        # 2. Screenshot 3 Dialog Verification
        pending_dlg = PendingCreditNotesDialog(
            None,
            customer_id=self.cust_id,
            customer_name="WALKIN",
            max_adjustment_needed=142.50,
        )
        self.assertEqual(pending_dlg.table.rowCount(), 1)
        self.assertEqual(pending_dlg.table.item(0, 1).text(), "CN-0001")
        self.assertEqual(pending_dlg.table.item(0, 4).text(), "50.00")
        # Check auto-suggested or edited credit amount
        self.assertEqual(pending_dlg._row_edits[0]["credit_edit"].text(), "50.00")
        pending_dlg._on_done()
        self.assertEqual(pending_dlg.get_total_credit_applied(), 50.0)
        settlements = pending_dlg.get_settlements()
        self.assertEqual(len(settlements), 1)
        self.assertEqual(settlements[0]["credit_note_id"], cn_id)
        self.assertEqual(settlements[0]["credit_amount"], 50.0)

        # 3. Screenshot 2: Sales Bill Review Dialog with 'Less CN Amt' + Credit Note Button
        page = CounterSalePage()
        panel = page._sale_panel
        panel.customer_combo.setCurrentIndex(panel.customer_combo.findData(self.cust_id))
        panel.doctor_combo.setCurrentIndex(panel.doctor_combo.findData(self.doc_id))
        panel.patient_name_edit.setText("WALKIN")
        panel._entry_bar.item_combo.setCurrentIndex(panel._entry_bar.item_combo.findData(self.item_id))
        panel._entry_bar.batch_combo.setCurrentIndex(panel._entry_bar.batch_combo.findData(self.batch_id))
        panel._entry_bar.qty_edit.setText("5")
        panel._entry_bar.discount_edit.setText("0.00")
        panel._on_add_item()
        self.assertEqual(len(panel._item_rows), 1)

        # Total amount = 5 * 28.5 = 142.50
        self.assertEqual(panel.total_amount_label.text(), "142.50")

        # Open Sales Bill Review Dialog
        dialog = SalesBillReviewDialog(panel, None)
        self.assertEqual(dialog._total_items_label.text(), "1")
        self.assertEqual(dialog._footer_total_amount.text(), "142.50")
        self.assertTrue(hasattr(dialog, "_credit_note_btn"))
        self.assertTrue(hasattr(dialog, "_cn_amt_edit"))
        self.assertTrue(hasattr(dialog, "_dr_amt_edit"))

        # Apply credit note settlement of 50.00
        dialog._panel._cn_amount = 50.0
        dialog._panel._applied_cn_settlements = settlements
        dialog._cn_amt_edit.setText("50.00")
        dialog._panel._recalc_totals()
        dialog._update_footer_totals()

        # Net amount should now be 142.50 - 50.00 = 92.50 -> rounded to 93 (or 92.50 + 0.50)
        self.assertEqual(dialog._footer_net_amount.text(), "93.00")
        self.assertEqual(dialog._footer_round_off.text(), "+0.50")

        # Commit bill
        dialog._on_final_save()
        self.assertTrue(dialog._panel.was_saved)

        # 4. Verify Database Persistence & Credit Note Settlement
        invoices = SalesDAO.get_all()
        self.assertEqual(len(invoices), 1)
        saved_inv = invoices[0]
        self.assertEqual(saved_inv["cn_amount"], 50.0)
        self.assertEqual(saved_inv["net_amount"], 93.0)

        # Verify Credit Note is now fully settled!
        cn_after = CreditNoteDAO.get_by_id(cn_id)
        self.assertEqual(cn_after["settled_amount"], 50.0)
        self.assertEqual(cn_after["settlement_status"], "SETTLED")

        # Verify settlements table records the link
        saved_settlements = CreditNoteDAO.get_settlements_for_invoice(saved_inv["id"])
        self.assertEqual(len(saved_settlements), 1)
        self.assertEqual(saved_settlements[0]["credit_note_id"], cn_id)
        self.assertEqual(saved_settlements[0]["settled_amount"], 50.0)

        # Verify no more pending credit notes for WALKIN
        pending_after = CreditNoteDAO.get_unsettled_by_customer(self.cust_id, "WALKIN")
        self.assertEqual(len(pending_after), 0)

        # 5. Verify Reversal when Invoice is Deleted
        SalesDAO.delete_invoice(saved_inv["id"])
        cn_reverted = CreditNoteDAO.get_by_id(cn_id)
        self.assertEqual(cn_reverted["settled_amount"], 0.0)
        self.assertEqual(cn_reverted["settlement_status"], "UNSETTLED")

        # Now pending credit notes for WALKIN has the 50.00 available again!
        pending_reverted = CreditNoteDAO.get_unsettled_by_customer(self.cust_id, "WALKIN")
        self.assertEqual(len(pending_reverted), 1)
        self.assertEqual(pending_reverted[0]["unsettled_amount"], 50.0)


if __name__ == "__main__":
    unittest.main()
