"""Comprehensive tests for TABLET-WISE vs STRIP-WISE stock quantity conversion.

Runs against an ISOLATED disposable test database (never live / production data).

Covers all 8 user requirements:
1. Pack size 10, stock 600 tablets, return 50 tablets -> remaining 550 tablets, correct unit rate.
2. Pack size 10, stock 600 tablets, return 600 tablets (500 pay + 100 free) -> remaining 0 tablets.
3. Attempt to return 601 tablets — reject with Insufficient Stock error.
4. Free quantity handling (deducts stock, excluded from return amount).
5. Multiple batches with different pack sizes (10, 15, 10x10).
6. Non-standard pack sizes ("1", "10'S", "10TAB", "1X10").
7. Stock after saving, reopening, updating, and deleting the transaction.
8. End-to-end integration: Purchase, Counter Sale, Credit Note, and Debit Note all maintain
   consistent tablet-wise loose units and financial amounts.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.connection import get_connection, init_database
from database.account_roles import ensure_system_ledgers
from database.company_dao import CompanyDAO
from database.unit_dao import UnitDAO
from database.supplier_dao import SupplierDAO
from database.customer_dao import CustomerDAO
from database.item_dao import ItemDAO
from database.stock_dao import StockDAO
from database.purchase_dao import PurchaseDAO, pack_factor
from database.sales_dao import SalesDAO
from database.credit_note_dao import CreditNoteDAO
from database.debit_note_dao import DebitNoteDAO


class TestStockQuantityConversion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmp_dir.name, "test_stock_conv.db")
        os.environ["PHARMACY_DB"] = cls.db_path
        init_database()
        ensure_system_ledgers()

    @classmethod
    def tearDownClass(cls):
        cls.tmp_dir.cleanup()

    def setUp(self):
        conn = get_connection()
        try:
            for tbl in [
                "debit_note_settlements", "debit_note_items", "debit_notes",
                "credit_note_items", "credit_notes",
                "sales_invoice_items", "sales_invoices",
                "purchase_invoice_items", "purchase_invoices",
                "ledger_transactions", "stock_batches", "items",
                "suppliers", "customers", "companies", "units",
            ]:
                conn.execute(f"DELETE FROM {tbl}")
            conn.commit()
        finally:
            conn.close()

        # Seed master data
        self.company_id = CompanyDAO.insert("WINNER PHARMA", "WP")
        self.unit_id = UnitDAO.insert("CAP")
        self.supplier_id = SupplierDAO.insert("SHRINIWAS AGENCIES")
        self.customer_id = CustomerDAO.insert("WALKIN")

        # Seed item matching screenshot: STABIZOL DSR (CAPSULE), pack size 10
        self.item_id = ItemDAO.insert(
            item_name="STABIZOL DSR (CAPSULE)",
            unit_id=self.unit_id,
            company_id=self.company_id,
            pack_size="10",
            reorder_stock_level=50,
        )

        # Purchase 60 packs of 10 = 600 loose units (capsules)
        # Rate: 92.20 per pack of 10, MRP: 121.00 per pack of 10
        PurchaseDAO.insert_invoice(
            voucher_no="PV-0001", voucher_date="2026-11-01", voucher_time="10:00 AM",
            purchase_type="Credit", supplier_id=self.supplier_id,
            invoice_no="INV-101", invoice_date="2026-11-01",
            invoice_net_amount=5532.0, bill_discount=0, due_date="2026-12-01",
            total_amount=5532.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=0, round_off=0, net_amount=5532.0,
            remarks="Initial Stock",
            items=[{
                "item_id": self.item_id,
                "pack_size": "10",
                "pay_qty": 60,  # 60 packs * 10 = 600 loose capsules
                "free_qty": 0,
                "batch_no": "AC2604005C",
                "expiry": "2028-03-31",
                "rate": 92.20,
                "mrp": 121.00,
                "discount": 0,
                "gst_percent": 0,
                "gst_amount": 0,
                "amount": 5532.0,
                "purchase_rate": 92.20,
                "net_rate": 92.20,
                "pp": 92.20,
            }],
        )

        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        self.assertEqual(len(batches), 1)
        self.batch_id = batches[0]["id"]
        # Verify initial database stock is 600 loose capsules
        self.assertEqual(batches[0]["stock_qty"], 600.0)

    # ──────────────────────────────────────────────────────────────────
    # Requirement 1: Pack size 10, stock 600 tablets, return 50 tablets
    # ──────────────────────────────────────────────────────────────────
    def test_01_return_50_tablets_from_600(self):
        """Pack size 10, stock 600, user returns 50 tablets.
        Should interpret as 50 loose units, price at 92.20 / 10 = 9.22 per unit,
        gross amount = 461.00, remaining stock = 550 tablets.
        """
        p_factor = pack_factor("10")
        self.assertEqual(p_factor, 10.0)

        unit_price = 92.20 / p_factor
        return_qty = 50.0
        expected_amount = round(return_qty * unit_price, 2)
        self.assertEqual(expected_amount, 461.00)

        header = {
            "voucher_date": "2026-11-15",
            "voucher_time": "11:00 AM",
            "dn_date": "2026-11-15",
            "dn_type": "Supplier",
            "supplier_id": self.supplier_id,
            "total_amount": expected_amount,
            "ledger_amount": 0.0,
            "add_to_ledger": False,
            "remarks": "Return 50 capsules",
        }
        items = [{
            "item_id": self.item_id,
            "stock_batch_id": self.batch_id,
            "batch_no": "AC2604005C",
            "expiry": "2028-03-31",
            "pack_size": "10",
            "rate": 92.20,
            "mrp": 121.00,
            "return_qty": return_qty,
            "free_qty": 0.0,
            "less_amount": 0.0,
            "amount": expected_amount,
            "return_reason": "Purchase Return",
            "price_factor": 1.0,
            "is_pack_qty": False,
        }]

        dn_id = DebitNoteDAO.insert_debit_note(header, items)
        self.assertGreater(dn_id, 0)

        # Verify stock_batches in DB
        batch = StockDAO.get_stock_batch_by_id(self.batch_id)
        self.assertEqual(batch["stock_qty"], 550.0, "Stock must decrease by exactly 50 loose tablets")

    # ──────────────────────────────────────────────────────────────────
    # Requirement 2: Pack size 10, stock 600 tablets, return 600 tablets
    # ──────────────────────────────────────────────────────────────────
    def test_02_return_all_600_tablets(self):
        """User returns all 600 tablets (500 return + 100 free) matching screenshot.
        Application must allow returning all 600 loose units, leaving remaining stock = 0.
        """
        p_factor = pack_factor("10")
        unit_price = 92.20 / p_factor
        ret_qty = 500.0
        free_qty = 100.0
        amount = round(ret_qty * unit_price, 2)  # 500 * 9.22 = 4610.00

        header = {
            "voucher_date": "2026-11-15",
            "voucher_time": "11:30 AM",
            "dn_date": "2026-11-15",
            "dn_type": "Supplier",
            "supplier_id": self.supplier_id,
            "total_amount": amount,
            "ledger_amount": 0.0,
            "add_to_ledger": False,
            "remarks": "Return all 600 capsules",
        }
        items = [{
            "item_id": self.item_id,
            "stock_batch_id": self.batch_id,
            "batch_no": "AC2604005C",
            "expiry": "2028-03-31",
            "pack_size": "10",
            "rate": 92.20,
            "mrp": 121.00,
            "return_qty": ret_qty,
            "free_qty": free_qty,
            "less_amount": 0.0,
            "amount": amount,
            "return_reason": "Purchase Return",
            "price_factor": 1.0,
            "is_pack_qty": False,
        }]

        dn_id = DebitNoteDAO.insert_debit_note(header, items)
        self.assertGreater(dn_id, 0)

        # Verify stock_batches in DB is exactly 0
        batch = StockDAO.get_stock_batch_by_id(self.batch_id)
        self.assertEqual(batch["stock_qty"], 0.0, "Stock must decrease by exactly 600 loose tablets to 0")

    # ──────────────────────────────────────────────────────────────────
    # Requirement 3: Attempt to return 601 tablets — reject
    # ──────────────────────────────────────────────────────────────────
    def test_03_reject_return_exceeding_stock(self):
        """Attempt to return 601 loose units when only 600 available.
        Must be rejected with Insufficient Stock ValueError. Stock must stay 600.
        """
        header = {
            "voucher_date": "2026-11-15",
            "voucher_time": "12:00 PM",
            "dn_date": "2026-11-15",
            "dn_type": "Supplier",
            "supplier_id": self.supplier_id,
            "total_amount": 5541.22,
            "ledger_amount": 0.0,
            "add_to_ledger": False,
            "remarks": "Exceeding return",
        }
        items = [{
            "item_id": self.item_id,
            "stock_batch_id": self.batch_id,
            "batch_no": "AC2604005C",
            "expiry": "2028-03-31",
            "pack_size": "10",
            "rate": 92.20,
            "mrp": 121.00,
            "return_qty": 601.0,
            "free_qty": 0.0,
            "less_amount": 0.0,
            "amount": 5541.22,
            "return_reason": "Purchase Return",
            "price_factor": 1.0,
            "is_pack_qty": False,
        }]

        with self.assertRaises(ValueError) as ctx:
            DebitNoteDAO.insert_debit_note(header, items)
        self.assertIn("Insufficient stock", str(ctx.exception))

        # Stock must remain unchanged at 600
        batch = StockDAO.get_stock_batch_by_id(self.batch_id)
        self.assertEqual(batch["stock_qty"], 600.0)

    # ──────────────────────────────────────────────────────────────────
    # Requirement 4: Free quantity handling
    # ──────────────────────────────────────────────────────────────────
    def test_04_free_quantity_handling(self):
        """Return 40 tablets + 10 free tablets.
        Total deduction from stock = 50 tablets (remaining: 550).
        Amount debited = only paid return_qty * unit_price = 40 * 9.22 = 368.80.
        """
        p_factor = pack_factor("10")
        unit_price = 92.20 / p_factor
        ret_qty = 40.0
        free_qty = 10.0
        amount = round(ret_qty * unit_price, 2)
        self.assertEqual(amount, 368.80)

        header = {
            "voucher_date": "2026-11-15",
            "voucher_time": "12:15 PM",
            "dn_date": "2026-11-15",
            "dn_type": "Supplier",
            "supplier_id": self.supplier_id,
            "total_amount": amount,
            "ledger_amount": 0.0,
            "add_to_ledger": False,
            "remarks": "Paid + Free return",
        }
        items = [{
            "item_id": self.item_id,
            "stock_batch_id": self.batch_id,
            "batch_no": "AC2604005C",
            "expiry": "2028-03-31",
            "pack_size": "10",
            "rate": 92.20,
            "mrp": 121.00,
            "return_qty": ret_qty,
            "free_qty": free_qty,
            "less_amount": 0.0,
            "amount": amount,
            "return_reason": "Purchase Return",
            "price_factor": 1.0,
            "is_pack_qty": False,
        }]

        dn_id = DebitNoteDAO.insert_debit_note(header, items)
        self.assertGreater(dn_id, 0)

        # Stock reduced by 40 + 10 = 50
        batch = StockDAO.get_stock_batch_by_id(self.batch_id)
        self.assertEqual(batch["stock_qty"], 550.0)

        # Line item details in DB
        saved_items = DebitNoteDAO.get_items(dn_id)
        self.assertEqual(len(saved_items), 1)
        self.assertEqual(saved_items[0]["return_qty"], 40.0)
        self.assertEqual(saved_items[0]["free_qty"], 10.0)
        self.assertEqual(saved_items[0]["amount"], 368.80)

    # ──────────────────────────────────────────────────────────────────
    # Requirement 5: Multiple batches with different pack sizes
    # ──────────────────────────────────────────────────────────────────
    def test_05_multiple_batches_different_pack_sizes(self):
        """Item 1: Pack size 10 (stock 600), return 20 tablets.
        Item 2: Pack size 15 (purchase 20 packs = 300 tablets), return 30 tablets.
        Item 3: Pack size 10x10=100 (purchase 5 packs = 500 tablets), return 50 tablets.
        All in one Debit Note transaction.
        """
        item2 = ItemDAO.insert(item_name="MED-15", unit_id=self.unit_id, company_id=self.company_id, pack_size="15", reorder_stock_level=10)
        item3 = ItemDAO.insert(item_name="MED-100", unit_id=self.unit_id, company_id=self.company_id, pack_size="10x10", reorder_stock_level=10)

        PurchaseDAO.insert_invoice(
            voucher_no="PV-0002", voucher_date="2026-11-01", voucher_time="10:00 AM",
            purchase_type="Credit", supplier_id=self.supplier_id,
            invoice_no="INV-102", invoice_date="2026-11-01",
            invoice_net_amount=5500.0, bill_discount=0, due_date="2026-12-01",
            total_amount=5500.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=0, round_off=0, net_amount=5500.0,
            remarks="",
            items=[
                {"item_id": item2, "pack_size": "15", "pay_qty": 20, "free_qty": 0, "batch_no": "B15", "expiry": "2027-12-31", "rate": 150.0, "mrp": 200.0, "discount": 0, "gst_percent": 0, "gst_amount": 0, "amount": 3000.0, "purchase_rate": 150.0, "net_rate": 150.0, "pp": 150.0},
                {"item_id": item3, "pack_size": "10x10", "pay_qty": 5, "free_qty": 0, "batch_no": "B100", "expiry": "2027-12-31", "rate": 500.0, "mrp": 600.0, "discount": 0, "gst_percent": 0, "gst_amount": 0, "amount": 2500.0, "purchase_rate": 500.0, "net_rate": 500.0, "pp": 500.0},
            ],
        )

        batch2_id = StockDAO.get_stock_batches_for_item(item2)[0]["id"]
        batch3_id = StockDAO.get_stock_batches_for_item(item3)[0]["id"]

        # Stock check: item2 has 20 * 15 = 300; item3 has 5 * 100 = 500
        self.assertEqual(StockDAO.get_stock_batch_by_id(batch2_id)["stock_qty"], 300.0)
        self.assertEqual(StockDAO.get_stock_batch_by_id(batch3_id)["stock_qty"], 500.0)

        # Line 1: 20 tablets of item 1 (pack 10, rate 92.20 -> unit 9.22 -> 184.40)
        # Line 2: 30 tablets of item 2 (pack 15, rate 150.00 -> unit 10.00 -> 300.00)
        # Line 3: 50 tablets of item 3 (pack 100, rate 500.00 -> unit 5.00 -> 250.00)
        amt1 = round(20 * (92.20 / 10), 2)   # 184.40
        amt2 = round(30 * (150.00 / 15), 2)  # 300.00
        amt3 = round(50 * (500.00 / 100), 2) # 250.00
        tot = round(amt1 + amt2 + amt3, 2)   # 734.40

        header = {
            "voucher_date": "2026-11-15",
            "voucher_time": "01:00 PM",
            "dn_date": "2026-11-15",
            "dn_type": "Supplier",
            "supplier_id": self.supplier_id,
            "total_amount": tot,
            "ledger_amount": 0.0,
            "add_to_ledger": False,
            "remarks": "Multi-batch return",
        }
        items = [
            {"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "AC2604005C", "expiry": "2028-03-31", "pack_size": "10", "rate": 92.20, "mrp": 121.00, "return_qty": 20.0, "free_qty": 0.0, "less_amount": 0.0, "amount": amt1, "return_reason": "Purchase Return", "price_factor": 1.0, "is_pack_qty": False},
            {"item_id": item2, "stock_batch_id": batch2_id, "batch_no": "B15", "expiry": "2027-12-31", "pack_size": "15", "rate": 150.0, "mrp": 200.0, "return_qty": 30.0, "free_qty": 0.0, "less_amount": 0.0, "amount": amt2, "return_reason": "Purchase Return", "price_factor": 1.0, "is_pack_qty": False},
            {"item_id": item3, "stock_batch_id": batch3_id, "batch_no": "B100", "expiry": "2027-12-31", "pack_size": "10x10", "rate": 500.0, "mrp": 600.0, "return_qty": 50.0, "free_qty": 0.0, "less_amount": 0.0, "amount": amt3, "return_reason": "Purchase Return", "price_factor": 1.0, "is_pack_qty": False},
        ]

        dn_id = DebitNoteDAO.insert_debit_note(header, items)
        self.assertGreater(dn_id, 0)

        # Check stock deduction for each batch:
        self.assertEqual(StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"], 580.0) # 600 - 20
        self.assertEqual(StockDAO.get_stock_batch_by_id(batch2_id)["stock_qty"], 270.0)     # 300 - 30
        self.assertEqual(StockDAO.get_stock_batch_by_id(batch3_id)["stock_qty"], 450.0)     # 500 - 50

    # ──────────────────────────────────────────────────────────────────
    # Requirement 6: Non-standard pack sizes ("1", "10'S", "10TAB", "1X10")
    # ──────────────────────────────────────────────────────────────────
    def test_06_non_standard_pack_sizes(self):
        """Verify pack_factor correctly parses various pack size formats."""
        self.assertEqual(pack_factor("1"), 1.0)
        self.assertEqual(pack_factor("10'S"), 10.0)
        self.assertEqual(pack_factor("10TAB"), 10.0)
        self.assertEqual(pack_factor("1X10"), 10.0)
        self.assertEqual(pack_factor("10*10"), 100.0)
        self.assertEqual(pack_factor("100ML"), 100.0)
        self.assertEqual(pack_factor(""), 1.0)
        self.assertEqual(pack_factor(None), 1.0)

    # ──────────────────────────────────────────────────────────────────
    # Requirement 7: Stock after saving, reopening, updating, deleting
    # ──────────────────────────────────────────────────────────────────
    def test_07_save_reopen_update_delete_stock_lifecycle(self):
        """Lifecycle test:
        1. Save Debit Note returning 50 tablets -> stock decreases 600 -> 550.
        2. Reopen / get_items -> verifies exact 50 return_qty loaded.
        3. Update Debit Note to return 80 tablets -> old reversed (600), new applied (600 - 80 = 520).
        4. Delete Debit Note -> stock restored back to original 600.
        """
        # 1. Insert DN (return 50 tablets)
        amt1 = round(50.0 * (92.20 / 10), 2)
        header = {
            "voucher_date": "2026-11-15", "voucher_time": "02:00 PM",
            "dn_date": "2026-11-15", "dn_type": "Supplier",
            "supplier_id": self.supplier_id, "total_amount": amt1,
            "ledger_amount": 0.0, "add_to_ledger": False, "remarks": "Initial return",
        }
        items = [{
            "item_id": self.item_id, "stock_batch_id": self.batch_id,
            "batch_no": "AC2604005C", "expiry": "2028-03-31", "pack_size": "10",
            "rate": 92.20, "mrp": 121.00, "return_qty": 50.0, "free_qty": 0.0,
            "less_amount": 0.0, "amount": amt1, "return_reason": "Purchase Return",
            "price_factor": 1.0, "is_pack_qty": False,
        }]
        dn_id = DebitNoteDAO.insert_debit_note(header, items)
        self.assertEqual(StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"], 550.0)

        # 2. Reopen / read items
        loaded_items = DebitNoteDAO.get_items(dn_id)
        self.assertEqual(len(loaded_items), 1)
        self.assertEqual(loaded_items[0]["return_qty"], 50.0)
        self.assertEqual(loaded_items[0]["is_pack_qty"], 0)

        # 3. Update DN (change return to 80 tablets)
        amt2 = round(80.0 * (92.20 / 10), 2)
        header["total_amount"] = amt2
        header["remarks"] = "Updated to 80 tablets"
        items[0]["return_qty"] = 80.0
        items[0]["amount"] = amt2

        DebitNoteDAO.update_debit_note(dn_id, header, items)
        self.assertEqual(StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"], 520.0, "600 - 80 = 520")

        # 4. Delete DN -> stock restored back to 600
        DebitNoteDAO.delete_debit_note(dn_id)
        self.assertEqual(StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"], 600.0, "Stock restored to 600")

    # ──────────────────────────────────────────────────────────────────
    # Requirement 8: Sales and Purchase workflows remain correct
    # ──────────────────────────────────────────────────────────────────
    def test_08_sales_and_purchase_calculations_remain_correct(self):
        """Verify Counter Sale and Credit Note remain consistent with tablet-wise stock:
        - Initial stock: 600 tablets.
        - Counter Sale of 15 tablets (1.5 packs equivalent):
          Sold in tablets: sale_qty = 15. Stock becomes 600 - 15 = 585 tablets.
          Price per tablet: 121.00 / 10 = 12.10. Gross = 15 * 12.10 = 181.50.
        - Credit Note (customer return) of 5 tablets:
          Restores 5 tablets: stock becomes 585 + 5 = 590 tablets.
          Refund amount: 5 * 12.10 = 60.50.
        - Debit Note (supplier return) of 90 tablets:
          Deducts 90 tablets: stock becomes 590 - 90 = 500 tablets.
          Supplier debit: 90 * 9.22 = 829.80.
        """
        initial_stock = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]
        self.assertEqual(initial_stock, 600.0)

        # 1. Counter Sale
        sale_id = SalesDAO.insert_invoice(
            bill_no=None,
            sale_date="2026-11-15",
            sale_time="02:30 PM",
            sale_type="Cash",
            customer_id=self.customer_id,
            patient_name="Test Patient",
            doctor_id=None,
            discount=0.0,
            paid_amount=181.50,
            total_amount=181.50,
            round_off=0.0,
            net_amount=181.50,
            remarks="",
            items=[{
                "item_id": self.item_id,
                "stock_batch_id": self.batch_id,
                "pack_size": "10",
                "location": "",
                "batch_no": "AC2604005C",
                "expiry": "2028-03-31",
                "mrp": 121.00,
                "sale_qty": 15.0,  # 15 tablets
                "discount_amount": 0.0,
                "amount": 181.50,
            }],
        )
        self.assertGreater(sale_id, 0)
        self.assertEqual(StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"], 585.0)

        # 2. Credit Note (Customer returns 5 tablets)
        cn_header = {
            "voucher_date": "2026-11-15", "customer_id": self.customer_id,
            "total_amount": 60.50, "add_to_ledger": False,
        }
        cn_items = [{
            "item_id": self.item_id, "stock_batch_id": self.batch_id,
            "batch_no": "AC2604005C", "expiry": "2028-03-31", "pack_size": "10",
            "rate": 92.20, "mrp": 121.00, "return_qty": 5.0, "less_amount": 0.0,
            "amount": 60.50, "return_reason": "Sales Return", "price_factor": 2.0, # MRP
        }]
        cn_id = CreditNoteDAO.insert_credit_note(cn_header, cn_items)
        self.assertGreater(cn_id, 0)
        self.assertEqual(StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"], 590.0)

        # 3. Debit Note (Supplier return 90 tablets)
        dn_header = {
            "voucher_date": "2026-11-15", "supplier_id": self.supplier_id,
            "total_amount": 829.80, "add_to_ledger": False,
        }
        dn_items = [{
            "item_id": self.item_id, "stock_batch_id": self.batch_id,
            "batch_no": "AC2604005C", "expiry": "2028-03-31", "pack_size": "10",
            "rate": 92.20, "mrp": 121.00, "return_qty": 90.0, "free_qty": 0.0,
            "less_amount": 0.0, "amount": 829.80, "return_reason": "Purchase Return",
            "price_factor": 1.0, "is_pack_qty": False,
        }]
        dn_id = DebitNoteDAO.insert_debit_note(dn_header, dn_items)
        self.assertGreater(dn_id, 0)
        self.assertEqual(StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"], 500.0)


if __name__ == "__main__":
    unittest.main()
