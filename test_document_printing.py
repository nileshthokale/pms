"""Phase 5H document output tests using isolated temporary SQLite data."""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from database.connection import get_connection, init_database
from database import document_printing as printing


class DocumentPrintingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = os.path.join(tempfile.gettempdir(), "pharmacy_document_printing_test.db")
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)
        os.environ["PHARMACY_DB"] = cls.db_path
        init_database()

    def setUp(self):
        conn = get_connection()
        for table in (
            "ledger_transactions", "sales_invoice_items", "purchase_invoice_items",
            "credit_note_items", "debit_note_items", "sales_invoices", "purchase_invoices",
            "credit_notes", "debit_notes", "customer_receipts", "supplier_payments",
            "stock_batches", "items", "customers", "suppliers", "doctors", "units", "companies",
        ):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("INSERT INTO customers (id, customer_name) VALUES (1, 'Customer One')")
        conn.execute("INSERT INTO suppliers (id, supplier_name) VALUES (1, 'Supplier One')")
        conn.execute("INSERT INTO doctors (id, doctor_name) VALUES (1, 'Dr Stored')")
        conn.execute("INSERT INTO units (id, unit_name) VALUES (1, 'Box')")
        conn.execute("INSERT INTO companies (id, company_name, short_name) VALUES (1, 'Company One', 'CO')")
        conn.execute("INSERT INTO items (id, item_name, unit_id, company_id, pack_size, mrp, rate) VALUES (1, 'Stored Tablet', 1, 1, '10x10', 50, 40)")
        conn.execute("INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp, purchase_rate, stock_qty) VALUES (1, 1, 'B-001', '12/27', '10x10', 50, 40, 20)")
        conn.execute("""INSERT INTO sales_invoices
            (id, bill_no, sale_date, sale_time, sale_type, customer_id, patient_name, doctor_id,
             discount, paid_amount, total_amount, round_off, net_amount, remarks)
            VALUES (1, 'CS-0001', '2026-09-16', '10:30', 'Cash', 1, 'Patient One', 1,
                    2, 48, 50, 0, 48, 'Sale remark')""")
        conn.execute("""INSERT INTO sales_invoice_items
            (sales_invoice_id, item_id, stock_batch_id, pack_size, location, batch_no, expiry,
             mrp, sale_qty, discount_amount, amount)
            VALUES (1, 1, 1, '10x10', 'A-1', 'B-001', '12/27', 50, 1, 2, 48)""")
        conn.execute("""INSERT INTO purchase_invoices
            (id, voucher_no, voucher_date, voucher_time, purchase_type, supplier_id, invoice_no,
             invoice_date, invoice_net_amount, bill_discount, due_date, total_amount, gst_amount,
             debit_note_amount, other_amount, paid_amount, round_off, net_amount, remarks)
            VALUES (1, 'PV-0001', '2026-09-15', '09:15', 'Credit', 1, 'INV-1', '2026-09-14',
                    46.2, 1, '', 40, 7.2, 0, 0, 0, 0, 47.2, 'Purchase remark')""")
        conn.execute("""INSERT INTO purchase_invoice_items
            (purchase_invoice_id, item_id, pack_size, pay_qty, free_qty, batch_no, expiry, rate,
             mrp, discount, gst_percent, gst_amount, amount, purchase_rate, net_rate, pp)
            VALUES (1, 1, '10x10', 2, 1, 'B-001', '12/27', 20, 50, 1, 18, 7.2, 40, 20, 20, 47.2)""")
        conn.execute("""INSERT INTO credit_notes
            (id, voucher_no, voucher_date, voucher_time, cn_date, cn_type, customer_id,
             total_amount, ledger_amount, remarks)
            VALUES (1, 'CN-0001', '2026-09-13', '11:00', '2026-09-13', 'Customer', 1, 38, 38, 'Credit reason')""")
        conn.execute("""INSERT INTO credit_note_items
            (credit_note_id, item_id, stock_batch_id, batch_no, expiry, pack_size, rate, mrp,
             return_qty, less_amount, amount, return_reason, price_factor)
            VALUES (1, 1, 1, 'B-001', '12/27', '10x10', 40, 50, 1, 2, 38, 'Damaged', 1)""")
        conn.execute("""INSERT INTO debit_notes
            (id, voucher_no, voucher_date, voucher_time, dn_date, dn_type, supplier_id,
             total_amount, ledger_amount, remarks)
            VALUES (1, 'DN-0001', '2026-09-12', '12:00', '2026-09-12', 'Supplier', 1, 38, 38, 'Debit reason')""")
        conn.execute("""INSERT INTO debit_note_items
            (debit_note_id, item_id, stock_batch_id, batch_no, expiry, pack_size, rate, mrp,
             return_qty, less_amount, amount, return_reason, price_factor)
            VALUES (1, 1, 1, 'B-001', '12/27', '10x10', 40, 50, 1, 2, 38, 'Expired', 1)""")
        conn.execute("""INSERT INTO customer_receipts
            (id, voucher_no, receipt_date, receipt_time, customer_id, receipt_mode, amount,
             reference_no, remarks)
            VALUES (1, 'CR-0001', '2026-09-11', '13:00', 1, 'UPI', 25, 'REF-C', 'Receipt remark')""")
        conn.execute("""INSERT INTO supplier_payments
            (id, voucher_no, payment_date, payment_time, supplier_id, payment_mode, amount,
             reference_no, remarks)
            VALUES (1, 'SP-0001', '2026-09-10', '14:00', 1, 'Bank', 30, 'REF-S', 'Payment remark')""")
        conn.commit(); conn.close()
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)

    def pdf(self, generator, name):
        path = Path(self.tmp.name) / name
        output = generator(1, path)
        self.assertEqual(Path(output), path)
        data = path.read_bytes()
        self.assertTrue(data.startswith(b"%PDF-1.4")); self.assertTrue(data.endswith(b"%%EOF\n")); self.assertGreater(len(data), 500)
        return data

    def counts(self):
        conn = get_connection()
        tables = ("sales_invoices", "sales_invoice_items", "purchase_invoices", "purchase_invoice_items", "credit_notes", "debit_notes", "customer_receipts", "supplier_payments", "stock_batches", "ledger_transactions")
        values = tuple(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables); conn.close(); return values

    def test_01_service_import(self): self.assertTrue(hasattr(printing, "generate_sales_bill"))
    def test_02_sales_pdf_exists(self): self.pdf(printing.generate_sales_bill, "sales.pdf")
    def test_03_counter_pdf_exists(self): self.pdf(printing.generate_counter_sale_bill, "counter.pdf")
    def test_04_purchase_pdf_exists(self): self.pdf(printing.generate_purchase_invoice, "purchase.pdf")
    def test_05_credit_pdf_exists(self): self.pdf(printing.generate_credit_note, "credit.pdf")
    def test_06_debit_pdf_exists(self): self.pdf(printing.generate_debit_note, "debit.pdf")
    def test_07_receipt_pdf_exists(self): self.pdf(printing.generate_customer_receipt, "receipt.pdf")
    def test_08_payment_pdf_exists(self): self.pdf(printing.generate_supplier_payment, "payment.pdf")
    def test_09_output_extension(self): self.assertTrue(Path(printing.generate_sales_bill(1, Path(self.tmp.name) / "named")).suffix == ".pdf")
    def test_10_default_output(self):
        output = printing.generate_sales_bill(1); self.assertTrue(output.endswith(".pdf")); Path(output).unlink(missing_ok=True)
    def test_11_missing_sales(self):
        with self.assertRaises(printing.DocumentPrintError): printing.generate_sales_bill(999, Path(self.tmp.name) / "x.pdf")
    def test_12_missing_purchase(self):
        with self.assertRaises(printing.DocumentPrintError): printing.generate_purchase_invoice(999, Path(self.tmp.name) / "x.pdf")
    def test_13_missing_credit(self):
        with self.assertRaises(printing.DocumentPrintError): printing.generate_credit_note(999, Path(self.tmp.name) / "x.pdf")
    def test_14_missing_debit(self):
        with self.assertRaises(printing.DocumentPrintError): printing.generate_debit_note(999, Path(self.tmp.name) / "x.pdf")
    def test_15_missing_receipt(self):
        with self.assertRaises(printing.DocumentPrintError): printing.generate_customer_receipt(999, Path(self.tmp.name) / "x.pdf")
    def test_16_missing_payment(self):
        with self.assertRaises(printing.DocumentPrintError): printing.generate_supplier_payment(999, Path(self.tmp.name) / "x.pdf")
    def test_17_sales_title(self): self.assertIn(b"Sales Bill", self.pdf(printing.generate_sales_bill, "sales.pdf"))
    def test_18_counter_title(self): self.assertIn(b"Counter Sale Bill", self.pdf(printing.generate_counter_sale_bill, "counter.pdf"))
    def test_19_purchase_title(self): self.assertIn(b"Purchase Invoice", self.pdf(printing.generate_purchase_invoice, "purchase.pdf"))
    def test_20_credit_title(self): self.assertIn(b"Credit Note", self.pdf(printing.generate_credit_note, "credit.pdf"))
    def test_21_debit_title(self): self.assertIn(b"Debit Note", self.pdf(printing.generate_debit_note, "debit.pdf"))
    def test_22_receipt_title(self): self.assertIn(b"Customer Receipt", self.pdf(printing.generate_customer_receipt, "receipt.pdf"))
    def test_23_payment_title(self): self.assertIn(b"Supplier Payment", self.pdf(printing.generate_supplier_payment, "payment.pdf"))
    def test_24_sales_number(self): self.assertIn(b"CS-0001", self.pdf(printing.generate_sales_bill, "sales.pdf"))
    def test_25_purchase_number(self): self.assertIn(b"PV-0001", self.pdf(printing.generate_purchase_invoice, "purchase.pdf"))
    def test_26_credit_number(self): self.assertIn(b"CN-0001", self.pdf(printing.generate_credit_note, "credit.pdf"))
    def test_27_debit_number(self): self.assertIn(b"DN-0001", self.pdf(printing.generate_debit_note, "debit.pdf"))
    def test_28_receipt_number(self): self.assertIn(b"CR-0001", self.pdf(printing.generate_customer_receipt, "receipt.pdf"))
    def test_29_payment_number(self): self.assertIn(b"SP-0001", self.pdf(printing.generate_supplier_payment, "payment.pdf"))
    def test_30_sales_values(self):
        data = self.pdf(printing.generate_sales_bill, "sales.pdf"); self.assertIn(b"Stored Tablet", data); self.assertIn(b"B-001", data); self.assertIn(b"Patient One", data)
    def test_31_sales_expiry(self): self.assertIn(b"12/2027", self.pdf(printing.generate_sales_bill, "sales.pdf"))
    def test_32_sales_net_amount(self): self.assertIn(b"Net Amt :", self.pdf(printing.generate_sales_bill, "sales.pdf"))
    def test_33_sales_no_breakdown_rows(self):
        # The cash memo carries a single Net Amt total, so the amount
        # breakdown lines are intentionally absent.
        data = self.pdf(printing.generate_sales_bill, "sales.pdf")
        for absent in (b"Round Off", b"Bill Discount", b"Paid Amount", b"Total Items"):
            self.assertNotIn(absent, data, absent)
    def test_34_sales_remarks(self): self.assertIn(b"Sale remark", self.pdf(printing.generate_sales_bill, "sales.pdf"))
    def test_35_sales_party(self): self.assertIn(b"Name : Patient One", self.pdf(printing.generate_sales_bill, "sales.pdf"))
    def test_36_sales_doctor(self): self.assertIn(b"Doctor : Dr Stored", self.pdf(printing.generate_sales_bill, "sales.pdf"))
    def test_37_counter_stored_values(self): self.assertIn(b"CS-0001", self.pdf(printing.generate_counter_sale_bill, "counter.pdf"))
    def test_38_counter_repeated(self):
        self.pdf(printing.generate_counter_sale_bill, "a.pdf"); self.pdf(printing.generate_counter_sale_bill, "b.pdf"); self.assertEqual(self.counts()[0], 1)
    def test_39_purchase_supplier(self): self.assertIn(b"Supplier One", self.pdf(printing.generate_purchase_invoice, "purchase.pdf"))
    def test_40_purchase_invoice_no(self): self.assertIn(b"INV-1", self.pdf(printing.generate_purchase_invoice, "purchase.pdf"))
    def test_41_purchase_quantities(self):
        data = self.pdf(printing.generate_purchase_invoice, "purchase.pdf"); self.assertIn(b"2", data); self.assertIn(b"1", data)
    def test_42_purchase_batch(self): self.assertIn(b"B-001", self.pdf(printing.generate_purchase_invoice, "purchase.pdf"))
    def test_43_purchase_gst_percent(self): self.assertIn(b"18.00", self.pdf(printing.generate_purchase_invoice, "purchase.pdf"))
    def test_44_purchase_gst_amount(self): self.assertIn(b"7.20", self.pdf(printing.generate_purchase_invoice, "purchase.pdf"))
    def test_45_purchase_discount(self): self.assertIn(b"1.00", self.pdf(printing.generate_purchase_invoice, "purchase.pdf"))
    def test_46_purchase_totals(self): self.assertIn(b"47.20", self.pdf(printing.generate_purchase_invoice, "purchase.pdf"))
    def test_47_purchase_remarks(self): self.assertIn(b"Purchase remark", self.pdf(printing.generate_purchase_invoice, "purchase.pdf"))
    def test_48_credit_reason(self): self.assertIn(b"Damaged", self.pdf(printing.generate_credit_note, "credit.pdf"))
    def test_49_credit_quantity(self): self.assertIn(b"Return Qty", self.pdf(printing.generate_credit_note, "credit.pdf"))
    def test_50_credit_amount(self): self.assertIn(b"38.00", self.pdf(printing.generate_credit_note, "credit.pdf"))
    def test_51_credit_remarks(self): self.assertIn(b"Credit reason", self.pdf(printing.generate_credit_note, "credit.pdf"))
    def test_52_debit_reason(self): self.assertIn(b"Expired", self.pdf(printing.generate_debit_note, "debit.pdf"))
    def test_53_debit_quantity(self): self.assertIn(b"Return Qty", self.pdf(printing.generate_debit_note, "debit.pdf"))
    def test_54_debit_amount(self): self.assertIn(b"38.00", self.pdf(printing.generate_debit_note, "debit.pdf"))
    def test_55_debit_remarks(self): self.assertIn(b"Debit reason", self.pdf(printing.generate_debit_note, "debit.pdf"))
    def test_56_receipt_customer(self): self.assertIn(b"Customer One", self.pdf(printing.generate_customer_receipt, "receipt.pdf"))
    def test_57_receipt_mode(self): self.assertIn(b"UPI", self.pdf(printing.generate_customer_receipt, "receipt.pdf"))
    def test_58_receipt_amount(self): self.assertIn(b"25.00", self.pdf(printing.generate_customer_receipt, "receipt.pdf"))
    def test_59_receipt_reference(self): self.assertIn(b"REF-C", self.pdf(printing.generate_customer_receipt, "receipt.pdf"))
    def test_60_receipt_remarks(self): self.assertIn(b"Receipt remark", self.pdf(printing.generate_customer_receipt, "receipt.pdf"))
    def test_61_payment_supplier(self): self.assertIn(b"Supplier One", self.pdf(printing.generate_supplier_payment, "payment.pdf"))
    def test_62_payment_mode(self): self.assertIn(b"Bank", self.pdf(printing.generate_supplier_payment, "payment.pdf"))
    def test_63_payment_amount(self): self.assertIn(b"30.00", self.pdf(printing.generate_supplier_payment, "payment.pdf"))
    def test_64_payment_reference(self): self.assertIn(b"REF-S", self.pdf(printing.generate_supplier_payment, "payment.pdf"))
    def test_65_payment_remarks(self): self.assertIn(b"Payment remark", self.pdf(printing.generate_supplier_payment, "payment.pdf"))
    def test_66_read_only_sales(self):
        before = self.counts(); self.pdf(printing.generate_sales_bill, "sales.pdf"); self.assertEqual(before, self.counts())
    def test_67_read_only_purchase(self):
        before = self.counts(); self.pdf(printing.generate_purchase_invoice, "purchase.pdf"); self.assertEqual(before, self.counts())
    def test_68_read_only_notes(self):
        before = self.counts(); self.pdf(printing.generate_credit_note, "credit.pdf"); self.pdf(printing.generate_debit_note, "debit.pdf"); self.assertEqual(before, self.counts())
    def test_69_read_only_receipts(self):
        before = self.counts(); self.pdf(printing.generate_customer_receipt, "receipt.pdf"); self.pdf(printing.generate_supplier_payment, "payment.pdf"); self.assertEqual(before, self.counts())
    def test_70_repeated_generation_no_rows(self):
        before = self.counts()
        for generator, name in ((printing.generate_sales_bill, "s"), (printing.generate_purchase_invoice, "p"), (printing.generate_credit_note, "c"), (printing.generate_debit_note, "d"), (printing.generate_customer_receipt, "r"), (printing.generate_supplier_payment, "sp")):
            self.pdf(generator, name + ".pdf"); self.pdf(generator, name + "2.pdf")
        self.assertEqual(before, self.counts())
    def test_71_large_document_paginates(self):
        conn = get_connection()
        for index in range(2, 80):
            conn.execute("INSERT INTO sales_invoice_items (sales_invoices_id) VALUES (?)", (1,)) if False else conn.execute("""INSERT INTO sales_invoice_items
                (sales_invoice_id, item_id, stock_batch_id, pack_size, location, batch_no, expiry, mrp, sale_qty, discount_amount, amount)
                VALUES (1, 1, 1, '10x10', 'A-1', ?, '12/27', 50, 1, 0, 50)""", (f"B-{index:03d}",))
        conn.commit(); conn.close()
        data = self.pdf(printing.generate_sales_bill, "large.pdf"); self.assertGreater(data.count(b"/Type /Page"), 1)
    def test_72_plain_preview(self):
        record = {"bill_no": "CS-0001", "sale_date": "2026-09-16", "net_amount": 48}
        self.assertIn("CS-0001", printing.preview_document("Sales Bill", record, []))
    def test_73_printer_unavailable_error(self):
        with self.assertRaises(printing.DocumentPrintError): printing.print_pdf("missing.pdf")
    def test_74_no_mysql_reference(self): self.assertNotIn("mysql", Path(printing.__file__).read_text(encoding="utf-8").casefold())
    def test_75_real_database_not_targeted(self): self.assertNotEqual(Path(self.db_path).resolve(), (Path(__file__).parent / "data" / "pharmacy.db").resolve())


if __name__ == "__main__": unittest.main()
