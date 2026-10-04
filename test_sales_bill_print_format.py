"""Focused Sales Bill (cash-memo) print-format tests.

Covers the traditional pharmacy receipt output only:
  * header, store name/address hooks
  * Name / Doctor / Cash Memo / Date block
  * QTY UNIT DESCRIPTION COMP. BATCH EXP. DT AMT columns
  * real unit name, real company, stored batch and stored expiry
  * DD/MM/YYYY expiry re-formatting of stored values only
  * single Net Amt total from the stored net amount
  * footer: E & O E., configured GSTIN, store name, Pharmacist/Sign
  * multiple items, long item names, long company names, multiple bills
  * PDF validity, QPrinter print output, preview text
  * nothing in the source data is modified

Every test uses a disposable temporary SQLite database; ``data/pharmacy.db``
is never opened or modified.
"""

import inspect
import os
import re
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import document_printing as printing   # noqa: E402
from database import pharmacy_a6_receipt as a6       # noqa: E402
from database.connection import get_connection, get_db_path, init_database  # noqa: E402

PT_PER_MM = 72.0 / 25.4
LONG_ITEM = ("Paracetamol 500mg Tablets Extended Release Film Coated Very "
             "Long Product Name 20 Strip Of 10 Tablets")
LONG_COMPANY = "Very Long Manufacturer Company Name Limited Pharmaceuticals"

_APP = None


def setUpModule():
    """Qt printer/paper queries need a live QApplication or the process aborts."""
    global _APP
    from PySide6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication([])


def media_boxes(data: bytes) -> list[tuple[float, float]]:
    found = []
    for box in re.findall(rb"/MediaBox \[([^\]]+)\]", data):
        parts = [float(value) for value in box.split()]
        found.append((parts[2], parts[3]))
    return found


def dump(path: str) -> dict:
    """Full database snapshot, to prove printing changes nothing."""
    import sqlite3

    conn = sqlite3.connect(path)
    try:
        snapshot = {}
        for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ):
            snapshot[name] = conn.execute(f"SELECT * FROM {name}").fetchall()
        return snapshot
    finally:
        conn.close()


class SalesBillPrintFormatTests(unittest.TestCase):
    """The Sales Bill / Counter Sale cash-memo output."""

    @classmethod
    def setUpClass(cls):
        cls.db_path = os.path.join(tempfile.gettempdir(), "pharmacy_sales_bill_print.db")
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)
        os.environ["PHARMACY_DB"] = cls.db_path
        init_database()
        assert "data/pharmacy.db" not in get_db_path().replace("\\", "/"), get_db_path()
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        conn = get_connection()
        for table in ("sales_invoice_items", "sales_invoices", "stock_batches",
                      "items", "customers", "doctors", "units", "companies"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("INSERT INTO customers (id, customer_name) VALUES (1,'Customer One')")
        conn.execute("INSERT INTO doctors (id, doctor_name) VALUES (1,'Dr Smith')")
        conn.execute("INSERT INTO units (id, unit_name) VALUES (1,'TABLET')")
        conn.execute("INSERT INTO units (id, unit_name) VALUES (2,'BOTTLE')")
        conn.execute("INSERT INTO companies (id, company_name, short_name)"
                     " VALUES (1,'Cipla Limited','CIPLA')")
        conn.execute("INSERT INTO items (id, item_name, unit_id, company_id, pack_size, mrp, rate)"
                     " VALUES (1,'L-CIN 250',1,1,'10x10',25.7,20)")
        conn.execute("INSERT INTO items (id, item_name, unit_id, company_id, pack_size, mrp, rate)"
                     " VALUES (2,'Cough Syrup',2,1,'100ml',54.0,44)")
        conn.execute("INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp,"
                     " purchase_rate, stock_qty) VALUES (1,1,'JC00541','2028-01-31','10x10',25.7,20,50)")
        conn.execute("INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp,"
                     " purchase_rate, stock_qty) VALUES (2,2,'AZ90012','12/27','100ml',54.0,44,50)")
        conn.execute(
            "INSERT INTO sales_invoices (id, bill_no, sale_date, sale_time, sale_type, customer_id,"
            " patient_name, doctor_id, discount, paid_amount, total_amount, round_off, net_amount, remarks)"
            " VALUES (1,'CS-0001','2026-10-04','10:30','Cash',1,'Sunita Patil',1,0,79.7,79.7,0,79.7,'')")
        conn.execute(
            "INSERT INTO sales_invoice_items (sales_invoice_id, item_id, stock_batch_id, pack_size,"
            " location, batch_no, expiry, mrp, sale_qty, discount_amount, amount)"
            " VALUES (1,1,1,'10x10','','JC00541','2028-01-31',25.7,1,0,25.70)")
        conn.execute(
            "INSERT INTO sales_invoice_items (sales_invoice_id, item_id, stock_batch_id, pack_size,"
            " location, batch_no, expiry, mrp, sale_qty, discount_amount, amount)"
            " VALUES (1,2,2,'100ml','','AZ90012','12/27',54.0,1,0,54.00)")
        conn.commit()
        conn.close()

    # ── helpers ─────────────────────────────────────────────────────
    def pdf(self, name: str = "bill.pdf", invoice_id: int = 1,
            title: str = "Sales Bill") -> bytes:
        path = Path(self.tmp.name) / name
        output = printing.generate_pharmacy_a6_bill(invoice_id, path, title)
        self.assertEqual(Path(output), path)
        return Path(output).read_bytes()

    def preview(self, invoice_id: int = 1, title: str = "Sales Bill") -> str:
        return printing.preview_pharmacy_a6_bill(invoice_id, title)

    def add_item(self, *, name="Item X", unit=1, company=1, batch="B-9",
                 expiry="12/27", qty=1, amount=10.0, bill=1):
        conn = get_connection()
        item_id = conn.execute("SELECT COALESCE(MAX(id),0)+1 FROM items").fetchone()[0]
        batch_id = conn.execute("SELECT COALESCE(MAX(id),0)+1 FROM stock_batches").fetchone()[0]
        conn.execute("INSERT INTO items (id, item_name, unit_id, company_id, pack_size, mrp, rate)"
                     " VALUES (?,?,?,?,'10x10',50,40)", (item_id, name, unit, company))
        conn.execute("INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp,"
                     " purchase_rate, stock_qty) VALUES (?,?,?,?,'10x10',50,40,100)",
                     (batch_id, item_id, batch, expiry))
        conn.execute(
            "INSERT INTO sales_invoice_items (sales_invoice_id, item_id, stock_batch_id, pack_size,"
            " location, batch_no, expiry, mrp, sale_qty, discount_amount, amount)"
            " VALUES (?,?,?,'10x10','',?,?,50,?,0,?)", (bill, item_id, batch_id, batch, expiry, qty, amount))
        conn.commit()
        conn.close()

    # ── 1. page format ──────────────────────────────────────────────
    def test_01_receipt_page_is_narrow_not_a4(self):
        width, height = media_boxes(self.pdf())[0]
        # Narrow receipt width always; height follows the bill's own content.
        self.assertAlmostEqual(width / PT_PER_MM, 105.0, places=1)
        self.assertGreaterEqual(height / PT_PER_MM, a6.MIN_RECEIPT_HEIGHT_MM)
        self.assertLessEqual(height / PT_PER_MM, 148.0)
        self.assertNotAlmostEqual(width / PT_PER_MM, 210.0, places=0)
        self.assertNotAlmostEqual(height / PT_PER_MM, 297.0, places=0)

    def test_02_pdf_is_valid(self):
        data = self.pdf()
        self.assertTrue(data.startswith(b"%PDF-1.4"))
        self.assertTrue(data.endswith(b"%%EOF\n"))

    # ── 2. header ───────────────────────────────────────────────────
    def test_03_document_title_is_printed_when_no_store_name_exists(self):
        self.assertIn(b"Sales Bill", self.pdf())

    def test_04_configured_store_name_and_address_print_in_the_header(self):
        profile = {"name": "SHREE SAMARTH MEDICAL AND GEN STORE",
                   "address": "GHORPADE HOSPITAL, RAHURI"}
        with unittest.mock.patch.object(a6, "store_profile", lambda: profile):
            data = self.pdf("store.pdf")
        self.assertIn(b"SHREE SAMARTH MEDICAL AND GEN STORE", data)
        self.assertIn(b"GHORPADE HOSPITAL, RAHURI", data)

    def test_05_store_name_is_centred_and_bold_in_the_header(self):
        profile = {"name": "Test Pharmacy"}
        with unittest.mock.patch.object(a6, "store_profile", lambda: profile):
            pages, _record = a6.build_sale_pages(1, "Sales Bill")
        runs = [run for page in pages for block in page for run in block.runs
                if run.text == "Test Pharmacy"]
        # The shop name prints twice: big and bold and centred at the top, and
        # again above the sign-off line in the right-hand footer column.
        self.assertEqual(len(runs), 2)
        header = [run for run in runs if run.align == "center"]
        self.assertEqual(len(header), 1)
        self.assertTrue(header[0].bold)
        self.assertEqual(header[0].size_pt, a6.TITLE_PT)
        footer = [run for run in runs if run.align == "right"]
        self.assertEqual(len(footer), 1)
        self.assertTrue(footer[0].bold)
        self.assertGreater(footer[0].y_mm, header[0].y_mm)

    def test_06_business_identity_lives_only_in_store_profile(self):
        source = Path(a6.__file__).read_text(encoding="utf-8")
        identity = str(a6.store_profile().get("name") or "")
        self.assertTrue(identity)
        self.assertEqual(source.count(identity), 1, identity)
        remainder = source.replace(inspect.getsource(a6.store_profile), "")
        for marker in (identity, "AHMEDNAGAR", "Canon", "LBP2900"):
            self.assertNotIn(marker, remainder, marker)

    def test_07_only_the_configured_identity_is_printed(self):
        data = self.pdf()
        profile = a6.store_profile()
        # The shop name is printed at the top and again in the footer; the
        # location line is a header element only.
        self.assertEqual(data.count(str(profile["name"]).encode()), 2)
        self.assertEqual(data.count(str(profile["address"]).encode()), 1)
        self.assertEqual(data.count(str(profile["licence"]).encode()), 1)
        self.assertIn(b"E & O E. Subject to AHMEDNAGAR Jurisdiction", data)
        # Nothing outside the configured keys is invented.
        for marker in (b"GSTIN", b"Pharmacist:"):
            self.assertNotIn(marker, data, marker)

    # ── 3. customer / doctor / cash memo / date ─────────────────────
    def test_08_name_line_shows_the_patient(self):
        self.assertIn(b"Name : Sunita Patil", self.pdf())

    def test_09_name_line_falls_back_to_the_customer(self):
        conn = get_connection()
        conn.execute("UPDATE sales_invoices SET patient_name='' WHERE id=1")
        conn.commit()
        conn.close()
        self.assertIn(b"Name : Customer One", self.pdf("cust.pdf"))

    def test_10_doctor_line_is_printed(self):
        self.assertIn(b"Doctor : Dr Smith", self.pdf())

    def test_11_cash_memo_shows_the_stored_bill_number(self):
        self.assertIn(b"Cash Memo : CS-0001", self.pdf())

    def test_12_date_shows_the_stored_sale_date(self):
        self.assertIn(b"Date : 2026-10-04", self.pdf())

    def test_13_name_and_memo_share_one_row(self):
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        rows = {}
        for block in pages[0][:4]:
            for run in block.runs:
                rows.setdefault(round(run.y_mm, 2), []).append(run)
        shared = [y for y, runs in rows.items()
                  if any(r.text.startswith("Name :") for r in runs)
                  and any(r.text.startswith("Cash Memo :") for r in runs)]
        self.assertTrue(shared, "Name and Cash Memo must sit on one row")

    def test_14_memo_block_is_right_aligned(self):
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        memo_runs = [run for page in pages for block in page for run in block.runs
                     if run.text.startswith("Cash Memo :")]
        self.assertTrue(memo_runs)
        self.assertEqual(memo_runs[0].align, "right")

    # ── 4. item columns ─────────────────────────────────────────────
    def test_15_column_headings_are_the_cash_memo_columns(self):
        data = self.pdf()
        for heading in (b"QTY", b"UNIT", b"DESCRIPTION", b"COMP.",
                        b"BATCH", b"EXP. DT", b"AMT"):
            self.assertIn(heading, data, heading)

    def test_16_unit_comes_from_the_stored_unit_master(self):
        data = self.pdf()
        self.assertIn(b"TABLET", data)
        self.assertIn(b"BOTTLE", data)

    def test_17_unit_is_not_the_pack_size(self):
        self.assertNotIn(b"10x10", self.pdf())

    def test_18_description_is_the_stored_item_name(self):
        data = self.pdf()
        self.assertIn(b"L-CIN 250", data)
        self.assertIn(b"Cough Syrup", data)

    def test_19_company_is_the_stored_manufacturer_short_name(self):
        self.assertIn(b"CIPLA", self.pdf())

    def test_20_batch_is_the_stored_batch(self):
        data = self.pdf()
        self.assertIn(b"JC00541", data)
        self.assertIn(b"AZ90012", data)

    def test_21_iso_expiry_prints_as_dd_mm_yyyy(self):
        self.assertIn(b"31/01/2028", self.pdf())

    def test_22_month_year_expiry_expands_the_year_only(self):
        self.assertIn(b"12/2027", self.pdf())
        self.assertNotIn(b"12/27", self.pdf())

    def test_23_expiry_stored_value_is_not_rewritten(self):
        conn = get_connection()
        value = conn.execute(
            "SELECT expiry FROM sales_invoice_items WHERE batch_no='AZ90012'"
        ).fetchone()[0]
        conn.close()
        self.pdf()
        conn = get_connection()
        after = conn.execute(
            "SELECT expiry FROM sales_invoice_items WHERE batch_no='AZ90012'"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(value, after)

    def test_24_quantity_is_the_stored_sale_qty(self):
        self.assertIn(b"QTY", self.pdf())

    def test_25_line_amount_is_the_stored_line_amount(self):
        data = self.pdf()
        self.assertIn(b"25.70", data)
        self.assertIn(b"54.00", data)

    def test_26_net_amount_is_the_stored_net_amount(self):
        data = self.pdf()
        self.assertIn(b"Net Amt :", data)
        self.assertIn(b"79.70", data)

    def test_27_net_amount_is_not_recalculated(self):
        conn = get_connection()
        net = conn.execute("SELECT net_amount FROM sales_invoices WHERE id=1").fetchone()[0]
        conn.close()
        self.assertIn(f"{float(net):.2f}".encode(), self.pdf())

    # ── 5. totals ───────────────────────────────────────────────────
    def test_28_cash_memo_shows_a_single_net_total(self):
        data = self.pdf()
        for absent in (b"Total Items", b"Total Amount", b"Bill Discount",
                       b"Round Off", b"Paid Amount"):
            self.assertNotIn(absent, data, absent)

    def test_29_net_total_sits_on_the_final_page(self):
        self.add_item(name="Third Item")
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        self.assertTrue(any(run.text == "Net Amt :"
                            for block in pages[-1] for run in block.runs))

    # ── 6. footer ───────────────────────────────────────────────────
    def test_30_error_and_omissions_line_is_printed(self):
        self.assertIn(b"E & O E.", self.pdf())

    def test_31_no_gstin_is_invented_when_none_is_stored(self):
        data = self.pdf()
        for marker in (b"GSTIN", b"CGST", b"SGST", b"IGST"):
            self.assertNotIn(marker, data, marker)

    def test_32_configured_gstin_is_printed(self):
        profile = {"gstin": "27ABCDE1234F1Z5"}
        with unittest.mock.patch.object(a6, "store_profile", lambda: profile):
            self.assertIn(b"GSTIN: 27ABCDE1234F1Z5", self.pdf("gstin.pdf"))

    def test_33_configured_jurisdiction_is_appended_to_the_footer(self):
        profile = {"jurisdiction": "AHMEDNAGAR"}
        with unittest.mock.patch.object(a6, "store_profile", lambda: profile):
            self.assertIn(b"E & O E. Subject to AHMEDNAGAR Jurisdiction",
                          self.pdf("juris.pdf"))

    def test_34_only_the_configured_jurisdiction_is_printed(self):
        data = self.pdf()
        # The jurisdiction is configured, so it prints; a different place name
        # is never substituted for it.
        self.assertEqual(data.count(b"Jurisdiction"), 1)
        self.assertIn(b"E & O E. Subject to AHMEDNAGAR Jurisdiction", data)
        for marker in (b"PUNE", b"NASHIK", b"Jalgaon"):
            self.assertNotIn(marker, data, marker)

    def test_35_signature_line_is_printed(self):
        self.assertIn(b"Pharmacist/Sign", self.pdf())

    def test_36_signature_block_is_right_aligned(self):
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        runs = [run for page in pages for block in page for run in block.runs
                if run.text == "Pharmacist/Sign"]
        self.assertTrue(runs)
        self.assertEqual(runs[0].align, "right")

    def test_37_store_name_sits_above_the_sign_off_line(self):
        profile = {"name": "Test Pharmacy Store"}
        with unittest.mock.patch.object(a6, "store_profile", lambda: profile):
            pages, _record = a6.build_sale_pages(1, "Sales Bill")
        runs = [run for page in pages for block in page for run in block.runs
                if run.text in {"Test Pharmacy Store", "Pharmacist/Sign"}]
        name = [run for run in runs if run.text == "Test Pharmacy Store"]
        sign = [run for run in runs if run.text == "Pharmacist/Sign"]
        self.assertEqual(len(name), 2)
        self.assertEqual(len(sign), 1)
        # Both sit in the right-hand column, the name above the sign-off line.
        self.assertEqual(name[1].align, "right")
        self.assertEqual(sign[0].align, "right")
        self.assertEqual(round(name[1].x_mm, 2), round(sign[0].x_mm, 2))
        self.assertLess(name[1].y_mm, sign[0].y_mm)

    def test_39_licence_numbers_print_on_the_left_below_e_and_o_e(self):
        profile = {"licence": "20-MH-AHM-61069,21-MH-AHM-61070,20C-MH-AHM-610"}
        with unittest.mock.patch.object(a6, "store_profile", lambda: profile):
            pages, _record = a6.build_sale_pages(1, "Sales Bill")
        licence = [run for page in pages for block in page for run in block.runs
                   if run.text == profile["licence"]]
        self.assertEqual(len(licence), 1)
        self.assertEqual(licence[0].align, "left")
        # Unclipped: the whole licence string fits its line.
        self.assertNotIn(a6.ELLIPSIS, licence[0].text)

    def test_40_licence_line_never_collides_with_the_right_column(self):
        profile = {"name": "SHREE SAMARTH MEDICAL AND GEN STORE",
                   "licence": "20-MH-AHM-61069,21-MH-AHM-61070,20C-MH-AHM-610"}
        with unittest.mock.patch.object(a6, "store_profile", lambda: profile):
            pages, _record = a6.build_sale_pages(1, "Sales Bill")
        for number, page in enumerate(pages, 1):
            self.assertEqual(a6.overlapping_runs(page), [], f"page {number}")

    def test_41_unconfigured_gstin_is_never_printed(self):
        with unittest.mock.patch.object(a6, "store_profile", lambda: {}):
            self.assertNotIn(b"GSTIN", self.pdf("nogstin.pdf"))

    def test_38_no_invented_pharmacist_name(self):
        self.assertNotIn(b"Pharmacist:", self.pdf())

    # ── 7. multiple items / long values / multiple bills ────────────
    def test_39_every_item_row_is_printed(self):
        preview = self.preview()
        self.assertIn("L-CIN 250", preview)
        self.assertIn("Cough Syrup", preview)
        self.assertEqual(preview.count("QTY"), 1)

    def test_40_long_item_name_wraps_and_stays_inside_the_page(self):
        self.add_item(name=LONG_ITEM)
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        self.assertTrue(any("Paracetamol 500mg" in run.text
                            for page in pages for block in page for run in block.runs))
        limit = a6.PHARMACY_A6.width_mm - a6.PHARMACY_A6.margin_right_mm
        for page in pages:
            for block in page:
                for run in block.runs:
                    self.assertLessEqual(run.x_mm + a6.text_width_mm(
                        run.text, run.size_pt, bold=run.bold), limit + 0.01, run.text[:24])

    def test_41_long_company_name_is_clipped_not_overflowing(self):
        conn = get_connection()
        conn.execute("INSERT INTO companies (id, company_name, short_name) VALUES (9,?,?)",
                     (LONG_COMPANY, LONG_COMPANY))
        conn.execute("UPDATE items SET company_id=9 WHERE id=1")
        conn.commit()
        conn.close()
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        limit = a6.PHARMACY_A6.width_mm - a6.PHARMACY_A6.margin_right_mm
        for page in pages:
            for block in page:
                for run in block.runs:
                    self.assertLessEqual(run.x_mm + a6.text_width_mm(
                        run.text, run.size_pt, bold=run.bold), limit + 0.01, run.text[:24])

    def test_42_many_items_paginate_and_repeat_the_column_heading(self):
        for index in range(60):
            self.add_item(name=f"Item {index + 1}", batch=f"B-{index:03d}")
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        self.assertGreater(len(pages), 1)
        for page in pages:
            self.assertTrue(any("DESCRIPTION" in run.text
                                for block in page for run in block.runs))

    def test_43_items_are_never_duplicated(self):
        for index in range(5):
            self.add_item(name=f"Unique {index}", batch=f"BU-{index}")
        preview = self.preview()
        for index in range(5):
            self.assertEqual(preview.count(f"Unique {index}"), 1)

    def test_44_second_bill_prints_with_its_own_values(self):
        conn = get_connection()
        conn.execute(
            "INSERT INTO sales_invoices (id, bill_no, sale_date, sale_time, sale_type, customer_id,"
            " patient_name, doctor_id, discount, paid_amount, total_amount, round_off, net_amount, remarks)"
            " VALUES (2,'CS-0002','2026-10-05','11:00','Cash',1,'Amit Kulkarni',1,0,25.7,25.7,0,25.7,'')")
        conn.commit()
        conn.close()
        data = self.pdf("second.pdf", invoice_id=2)
        self.assertIn(b"Cash Memo : CS-0002", data)
        self.assertIn(b"Name : Amit Kulkarni", data)
        self.assertIn(b"25.70", data)
        self.assertNotIn(b"CS-0001", data)

    def test_45_counter_sale_uses_the_same_bill_layout(self):
        sale = self.pdf("sale.pdf", title="Sales Bill")
        counter = self.pdf("counter.pdf", title="Counter Sale Bill")
        self.assertIn(b"Counter Sale Bill", counter)
        for marker in (b"QTY", b"EXP. DT", b"Net Amt :", b"Pharmacist/Sign"):
            self.assertIn(marker, counter, marker)

    # ── 8. print output, preview and read-only guarantees ───────────
    def test_46_print_output_generates_a_real_pdf(self):
        from PySide6.QtGui import QPainter
        from PySide6.QtPrintSupport import QPrinter

        path = Path(self.tmp.name) / "printed.pdf"
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(str(path))
        painter = QPainter()
        self.assertTrue(painter.begin(printer))
        try:
            a6.draw_pages_on_painter(painter, pages, painter.viewport())
        finally:
            painter.end()
        self.assertTrue(path.exists())
        self.assertTrue(path.read_bytes().startswith(b"%PDF"))

    def test_47_preview_shows_the_cash_memo_structure(self):
        preview = self.preview()
        for fragment in ("Name :", "Doctor :", "Cash Memo :", "Date :",
                         "DESCRIPTION", "EXP. DT", "Net Amt :",
                         "E & O E.", "Pharmacist/Sign"):
            self.assertIn(fragment, preview, fragment)

    def test_48_legacy_preview_entry_point_still_works(self):
        record = {"bill_no": "CS-0001", "sale_date": "2026-10-04", "net_amount": 48}
        self.assertIn("CS-0001", printing.preview_document("Sales Bill", record, []))

    def test_49_printing_does_not_change_any_stored_row(self):
        before = dump(self.db_path)
        self.pdf("r1.pdf")
        self.pdf("r2.pdf", invoice_id=1, title="Counter Sale Bill")
        self.preview()
        self.assertEqual(dump(self.db_path), before)

    def test_50_printing_does_not_touch_stock_or_the_ledger(self):
        conn = get_connection()
        stock = conn.execute("SELECT id, stock_qty FROM stock_batches ORDER BY id").fetchall()
        ledger = conn.execute("SELECT * FROM ledger_transactions ORDER BY id").fetchall()
        conn.close()
        self.pdf()
        conn = get_connection()
        self.assertEqual(
            conn.execute("SELECT id, stock_qty FROM stock_batches ORDER BY id").fetchall(), stock)
        self.assertEqual(
            conn.execute("SELECT * FROM ledger_transactions ORDER BY id").fetchall(), ledger)
        conn.close()

    def test_51_repeated_generation_is_byte_stable(self):
        self.assertEqual(self.pdf("s1.pdf"), self.pdf("s2.pdf"))

    def test_52_real_database_is_never_used(self):
        self.assertTrue(os.environ["PHARMACY_DB"].startswith(tempfile.gettempdir()))
        self.assertNotIn("data/pharmacy.db", os.environ["PHARMACY_DB"])

    def test_53_sales_dao_is_not_modified_by_printing(self):
        source = Path(a6.__file__).read_text(encoding="utf-8").upper()
        for marker in ("INSERT INTO SALES", "UPDATE SALES", "DELETE FROM SALES"):
            self.assertNotIn(marker, source, marker)

    def test_54_expiry_reformatter_never_invents_a_day(self):
        self.assertEqual(a6._expiry(""), "")
        self.assertEqual(a6._expiry("2028-01-31"), "31/01/2028")
        self.assertEqual(a6._expiry("12/27"), "12/2027")
        self.assertEqual(a6._expiry("31/01/2028"), "31/01/2028")

    def test_55_missing_sale_raises_print_error(self):
        with self.assertRaises(printing.DocumentPrintError):
            printing.generate_pharmacy_a6_bill(999999, Path(self.tmp.name) / "missing.pdf")

    def test_56_other_document_formats_are_untouched(self):
        conn = get_connection()
        conn.execute("INSERT INTO suppliers (id, supplier_name) VALUES (1,'Supplier One')")
        conn.execute(
            "INSERT INTO purchase_invoices (id, voucher_no, voucher_date, purchase_type, supplier_id,"
            " invoice_no, total_amount, gst_amount, net_amount)"
            " VALUES (1,'PV-0001','2026-10-01','Credit',1,'INV-1',40,7.2,47.2)")
        conn.commit()
        conn.close()
        path = Path(self.tmp.name) / "purchase.pdf"
        printing.generate_purchase_invoice(1, path)
        width, height = media_boxes(path.read_bytes())[0]
        self.assertAlmostEqual(width, 595.0, places=1)
        self.assertAlmostEqual(height, 842.0, places=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)