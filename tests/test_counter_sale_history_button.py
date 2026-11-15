import os
import sys
import unittest
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication(sys.argv)

from database.connection import get_connection
from database.company_dao import CompanyDAO
from database.unit_dao import UnitDAO
from database.item_dao import ItemDAO
from database.supplier_dao import SupplierDAO
from database.purchase_dao import PurchaseDAO
from database.stock_dao import StockDAO
from screens.counter_sale import _ItemEntryBar
from screens.purchase_invoice import _ItemPurchaseHistoryDialog


class TestCounterSaleHistoryButton(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        conn = get_connection()
        conn.execute("PRAGMA foreign_keys = OFF;")
        conn.close()

    def setUp(self):
        import uuid
        uid = uuid.uuid4().hex[:6].upper()
        # Find or create unit
        conn = get_connection()
        cur = conn.execute("SELECT id FROM units WHERE unit_name = 'STRIP'")
        row = cur.fetchone()
        if row:
            self.u_id = row[0]
        else:
            self.u_id = UnitDAO.insert(f"U_{uid}")

        cur = conn.execute("SELECT id FROM companies WHERE company_name LIKE 'Sun Pharma%'")
        row = cur.fetchone()
        if row:
            self.c_id = row[0]
        else:
            self.c_id = CompanyDAO.insert(f"Comp_{uid}", f"C{uid[:3]}")

        cur = conn.execute("SELECT id FROM suppliers WHERE supplier_name = 'SHRINIWAS AGENCIES'")
        row = cur.fetchone()
        if row:
            self.s_id = row[0]
        else:
            self.s_id = SupplierDAO.insert(f"SUPP_{uid}", contact_no="9876543210")
        conn.close()

        self.item_id = ItemDAO.insert(
            item_name=f"STAFLEX 3 D CAPSULE {uid}",
            unit_id=self.u_id,
            company_id=self.c_id,
            pack_size="10",
            mrp=683.0,
            rate=520.38,
        )

    def test_item_entry_bar_controls(self):
        bar = _ItemEntryBar(two_row=True)
        self.assertTrue(hasattr(bar, "hist_btn"))
        self.assertEqual(bar.hist_btn.text(), "Hist.")
        self.assertEqual(bar.hist_btn.toolTip(), "View item purchase history")
        self.assertEqual(bar.hist_btn.focusPolicy(), Qt.NoFocus)
        self.assertFalse(hasattr(bar, "adjusted_btn"))
        self.assertFalse(hasattr(bar, "purchase_btn"))

    def test_history_dialog_columns_and_data(self):
        import uuid
        test_vno = f"2026-2027-Credit-{uuid.uuid4().hex[:5].upper()}"
        # Insert a purchase invoice with purchase item for this item
        inv_id = PurchaseDAO.insert_invoice(
            voucher_no=test_vno,
            voucher_date="2026-10-06",
            voucher_time="10:00",
            purchase_type="Credit",
            supplier_id=self.s_id,
            invoice_no=f"INV-{uuid.uuid4().hex[:4].upper()}",
            invoice_date="2026-10-06",
            invoice_net_amount=5203.80,
            bill_discount=0.0,
            due_date="2026-11-06",
            total_amount=5203.80,
            gst_amount=0.0,
            debit_note_amount=0.0,
            other_amount=0.0,
            paid_amount=0.0,
            round_off=0.0,
            net_amount=5203.80,
            remarks="Test",
            items=[{
                "item_id": self.item_id,
                "batch_no": "26SFC02",
                "expiry": "2028-10-31",
                "pack_size": "10",
                "pay_qty": 10.0,
                "free_qty": 2.0,
                "rate": 520.38,
                "mrp": 683.0,
                "discount": 0.0,
                "gst_percent": 0.0,
                "gst_amount": 0.0,
                "amount": 5203.80,
                "purchase_rate": 520.38,
                "net_rate": 520.38,
                "pp": 520.38,
            }],
        )

        rows = PurchaseDAO.get_item_purchase_history(self.item_id)
        self.assertGreaterEqual(len(rows), 1)
        self.assertEqual(rows[0]["batch_no"], "26SFC02")
        self.assertTrue("SHRINIWAS" in rows[0]["supplier_name"] or "SUPP_" in rows[0]["supplier_name"])

        dlg = _ItemPurchaseHistoryDialog(item_id=self.item_id, item_name="STAFLEX 3 D CAPSULE")
        self.assertEqual(dlg.windowTitle(), "Item Purchase History [ STAFLEX 3 D CAPSULE ]")
        self.assertEqual(dlg.table.columnCount(), 10)

        expected_headers = [
            "Tran.No", "Tran.Date", "Tran.Type", "BatchNo", "PayQty", "FreeQty",
            "MRP", "Rate", "DiscAmt", "Supplier"
        ]
        actual_headers = [dlg.table.horizontalHeaderItem(i).text() for i in range(10)]
        self.assertEqual(actual_headers, expected_headers)
        self.assertEqual(dlg.table.rowCount(), len(rows))

        # Check row 0 contents
        from core.doc_formatter import format_purchase_voucher_number
        self.assertEqual(dlg.table.item(0, 0).text(), format_purchase_voucher_number(test_vno))
        self.assertEqual(dlg.table.item(0, 1).text(), "06-10-2026")
        self.assertEqual(dlg.table.item(0, 3).text(), "26SFC02")
        self.assertEqual(dlg.table.item(0, 4).text(), "10")
        self.assertEqual(dlg.table.item(0, 5).text(), "2")
        self.assertEqual(dlg.table.item(0, 6).text(), "683.00")
        self.assertEqual(dlg.table.item(0, 7).text(), "520.38")

        # Test selecting row and clicking ok
        dlg.table.selectRow(0)
        dlg._on_ok_clicked()
        self.assertIsNotNone(dlg.selected_batch)
        self.assertEqual(dlg.selected_batch.get("batch_no"), "26SFC02")


if __name__ == "__main__":
    unittest.main()
