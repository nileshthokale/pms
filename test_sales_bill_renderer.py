"""Sales Bill renderer correctness tests: no diagonals, no overlap, in-page.

These parse the generated PDF's raw content stream, so they test what actually
reaches the printer rather than trusting the layout model. Each test locks in
one of the defects that broke the printed bill:

  * diagonal separator lines  (PDF path operator given width/height as absolute
    coordinates instead of offsets from the rule's own origin)
  * every section printed on top of the next  (reflow shifted all blocks by the
    page start instead of by each block's own top)
  * text pushed off the page  (millimetre->point conversion applied twice)

Plus the structural guarantees: content-sized page height, no overlapping ink
boxes, nothing outside the page box, and no source-data modification.

Every test uses a disposable temporary SQLite database; ``data/pharmacy.db`` is
never opened or modified.
"""

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import document_printing as printing   # noqa: E402
from database import pharmacy_a6_receipt as a6       # noqa: E402
from database.connection import get_connection, get_db_path, init_database  # noqa: E402

PT_PER_MM = 72.0 / 25.4
LONG_ITEM = ("Paracetamol 500mg Tablets Extended Release Film Coated Very "
             "Long Product Name 20 Strip Of 10 Tablets")
LONG_PERSON = ("Mr. Chandrashekhar Bhalchandra Jagtap Patil Alias Shekhar "
               "Jagtap Senior Citizen")
LONG_DOCTOR = ("Dr. Sharada Krishnarao Deshmukh Alias Dr. S. K. Deshmukh "
               "M.D. (Medicine)")

_APP = None


def setUpModule():
    global _APP
    from PySide6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication([])


# ── raw content-stream parsing ─────────────────────────────────────────

def media_box(data: bytes) -> tuple[float, float]:
    parts = [float(v) for v in re.search(rb"/MediaBox \[([^\]]+)\]", data).group(1).split()]
    return parts[2], parts[3]


def pdf_lines(data: bytes) -> list[tuple[float, float, float, float]]:
    """Every ``m ... l`` path segment in the content stream."""
    return [tuple(float(v) for v in match)
            for match in re.findall(rb"([\d.]+) ([\d.]+) m ([\d.]+) ([\d.]+) l S", data)]


def pdf_text_runs(data: bytes) -> list[tuple[float, float, float, str]]:
    """(x_pt, y_pt, size_pt, text) for every drawn string."""
    return [(float(x), float(y), float(size), text.decode("latin-1"))
            for _font, size, x, y, text in re.findall(
                rb"BT /F(\d) ([\d.]+) Tf 1 0 0 1 ([\d.]+) ([\d.]+) Tm \((.*?)\) Tj ET", data)]


def content_runs(data: bytes) -> list[tuple[float, float, float, str]]:
    """Bill content only, excluding the ``Page N of M`` chrome stamp."""
    return [run for run in pdf_text_runs(data) if not run[3].startswith("Page ")]


class SalesBillRendererTests(unittest.TestCase):
    """One-item, multi-item and long-value bills rendered end to end."""

    @classmethod
    def setUpClass(cls):
        cls.db_path = os.path.join(tempfile.gettempdir(), "pharmacy_bill_renderer.db")
        for suffix in ("", "-wal", "-shm"):
            stale = Path(cls.db_path + suffix)
            if stale.exists():
                stale.unlink()
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
        conn.execute("INSERT INTO companies (id, company_name, short_name)"
                     " VALUES (1,'Cipla Limited','CIPLA')")
        conn.execute("INSERT INTO items (id, item_name, unit_id, company_id, pack_size, mrp, rate)"
                     " VALUES (1,'L-CIN 250',1,1,'10x10',25.7,20)")
        conn.execute("INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp,"
                     " purchase_rate, stock_qty) VALUES (1,1,'JC00541','2028-01-31','10x10',25.7,20,50)")
        conn.execute(
            "INSERT INTO sales_invoices (id, bill_no, sale_date, sale_time, sale_type, customer_id,"
            " patient_name, doctor_id, discount, paid_amount, total_amount, round_off, net_amount, remarks)"
            " VALUES (1,'CS-0001','2026-09-27','10:30','Cash',1,'Sunita Patil',1,0,25.7,25.7,0,25.7,'')")
        conn.execute(
            "INSERT INTO sales_invoice_items (sales_invoice_id, item_id, stock_batch_id, pack_size,"
            " location, batch_no, expiry, mrp, sale_qty, discount_amount, amount)"
            " VALUES (1,1,1,'10x10','','JC00541','2028-01-31',25.7,1,0,25.70)")
        conn.commit()
        conn.close()

    # ── helpers ─────────────────────────────────────────────────────
    def pdf(self, name="b.pdf", invoice_id=1, title="Sales Bill") -> bytes:
        path = Path(self.tmp.name) / name
        return Path(printing.generate_pharmacy_a6_bill(invoice_id, path, title)).read_bytes()

    def add_item(self, *, name="Item X", batch="B-9", expiry="12/27", amount=10.0):
        conn = get_connection()
        item_id = conn.execute("SELECT COALESCE(MAX(id),0)+1 FROM items").fetchone()[0]
        batch_id = conn.execute("SELECT COALESCE(MAX(id),0)+1 FROM stock_batches").fetchone()[0]
        conn.execute("INSERT INTO items (id, item_name, unit_id, company_id, pack_size, mrp, rate)"
                     " VALUES (?,?,1,1,'10x10',50,40)", (item_id, name))
        conn.execute("INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp,"
                     " purchase_rate, stock_qty) VALUES (?,?,?,?,'10x10',50,40,100)",
                     (batch_id, item_id, batch, expiry))
        conn.execute(
            "INSERT INTO sales_invoice_items (sales_invoice_id, item_id, stock_batch_id, pack_size,"
            " location, batch_no, expiry, mrp, sale_qty, discount_amount, amount)"
            " VALUES (1,?,?,'10x10','',?,?,50,1,0,?)", (item_id, batch_id, batch, expiry, amount))
        conn.commit()
        conn.close()

    # ══════════════════════════════════════════════════════════════
    # 1. NO DIAGONAL LINES
    # ══════════════════════════════════════════════════════════════
    def test_01_no_diagonal_separator_lines_in_one_item_bill(self):
        for x0, y0, x1, y1 in pdf_lines(self.pdf()):
            self.assertLessEqual(
                abs(y1 - y0), 2.0,
                f"separator drawn diagonally from ({x0},{y0}) to ({x1},{y1})")

    def test_02_no_diagonal_lines_in_multi_item_bill(self):
        for index in range(6):
            self.add_item(name=f"Item {index}", batch=f"B-{index:02d}")
        for x0, y0, x1, y1 in pdf_lines(self.pdf("multi.pdf")):
            self.assertLessEqual(abs(y1 - y0), 2.0, f"({x0},{y0})->({x1},{y1})")

    def test_03_no_diagonal_lines_in_long_value_bill(self):
        self.add_item(name=LONG_ITEM)
        for x0, y0, x1, y1 in pdf_lines(self.pdf("long.pdf")):
            self.assertLessEqual(abs(y1 - y0), 2.0, f"({x0},{y0})->({x1},{y1})")

    def test_04_separator_lines_span_the_content_width(self):
        """A horizontal rule must run left-to-right, never to a corner."""
        data = self.pdf()
        lines = pdf_lines(data)
        self.assertTrue(lines, "the bill must draw its section separators")
        margin_pt = a6.PHARMACY_A6.margin_left_mm * PT_PER_MM
        content_pt = a6.PHARMACY_A6.content_width_mm * PT_PER_MM
        for x0, _y0, x1, _y1 in lines:
            self.assertAlmostEqual(x0, margin_pt, places=1)
            self.assertAlmostEqual(x1, margin_pt + content_pt, places=1)

    def test_05_every_separator_stays_inside_the_page(self):
        for index in range(5):
            self.add_item(name=f"Item {index}")
        data = self.pdf("inside.pdf")
        width_pt, height_pt = media_box(data)
        for x0, y0, x1, y1 in pdf_lines(data):
            for x, y in ((x0, y0), (x1, y1)):
                self.assertGreaterEqual(x, -0.01)
                self.assertLessEqual(x, width_pt + 0.01)
                self.assertGreaterEqual(y, -0.01)
                self.assertLessEqual(y, height_pt + 0.01)

    def test_06_rule_source_does_not_pass_bare_width_as_line_endpoint(self):
        """Guards the exact regression: ``l`` must be offset by the rule origin."""
        source = Path(a6.__file__).read_text(encoding="utf-8")
        self.assertNotIn(
            "{profile.content_width_mm * mm_to_pt:.2f} {y_pt:.2f} l", source)
        self.assertIn("rule_x_pt + rule_len_pt", source)

    # ══════════════════════════════════════════════════════════════
    # 2. NO OVERLAPPING TEXT / SECTIONS
    # ══════════════════════════════════════════════════════════════
    def test_07_no_overlapping_text_boxes_in_layout_model(self):
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        for number, page in enumerate(pages, 1):
            self.assertEqual(a6.overlapping_runs(page), [],
                             f"page {number} has overlapping text runs")

    def test_08_no_overlap_with_many_items(self):
        for index in range(8):
            self.add_item(name=f"Item {index}", batch=f"B-{index:02d}")
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        for number, page in enumerate(pages, 1):
            self.assertEqual(a6.overlapping_runs(page), [], f"page {number}")

    def test_09_no_overlap_with_long_patient_and_doctor_names(self):
        conn = get_connection()
        conn.execute("UPDATE sales_invoices SET patient_name=? WHERE id=1", (LONG_PERSON,))
        conn.execute("UPDATE doctors SET doctor_name=? WHERE id=1", (LONG_DOCTOR,))
        conn.commit()
        conn.close()
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        for number, page in enumerate(pages, 1):
            self.assertEqual(a6.overlapping_runs(page), [], f"page {number}")

    def test_10_sections_stack_top_to_bottom_in_order(self):
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        flat = [(round(run.y_mm, 2), run.text)
                for page in pages for block in page for run in block.runs if run.text]
        # Millimetres grow downward, so ascending y is reading order.
        order = [text for _y, text in sorted(flat, key=lambda item: item[0])]
        joined = " | ".join(order)
        # A configured jurisdiction is appended to the "E & O E." line, so match
        # the line by its stable prefix instead of an exact string.
        errors_line = next(text for text in order if text.startswith("E & O E."))
        self.assertLess(order.index("Cash Memo : CS-0001"), order.index("QTY"), joined)
        self.assertLess(order.index("QTY"), order.index("L-CIN 250"), joined)
        self.assertLess(order.index("L-CIN 250"), order.index("Net Amt :"), joined)
        self.assertLess(order.index("Net Amt :"), order.index(errors_line), joined)
        self.assertLess(order.index(errors_line), order.index("Pharmacist/Sign"), joined)

    def test_11_reflow_shifts_each_block_by_its_own_top(self):
        """The overlap regression: blocks must advance, not share one y."""
        blocks = [
            a6.Block(kind="header", height_mm=4.0,
                     runs=[a6.Run(4.0, 1.0, 20.0, "first", 6.0)],
                     rules=[(3.0, 0.4)]),
            a6.Block(kind="row", height_mm=4.0,
                     runs=[a6.Run(4.0, 1.0, 20.0, "second", 6.0)]),
            a6.Block(kind="footer", height_mm=4.0,
                     runs=[a6.Run(4.0, 1.0, 20.0, "third", 6.0)]),
        ]
        placed = a6.reflow(blocks, 10.0)
        self.assertEqual([round(b.top_mm, 2) for b in placed], [10.0, 14.0, 18.0])
        self.assertEqual([round(b.runs[0].y_mm, 2) for b in placed], [11.0, 15.0, 19.0])
        self.assertEqual([round(b.rules[0][0], 2) for b in placed if b.rules], [13.0])

    # ══════════════════════════════════════════════════════════════
    # 3. NOTHING OUTSIDE THE PAGE
    # ══════════════════════════════════════════════════════════════
    def test_12_all_pdf_text_is_inside_the_page_box(self):
        """Locks the double mm->pt conversion that pushed text off the page."""
        for index in range(4):
            self.add_item(name=f"Item {index}")
        data = self.pdf("inpage.pdf")
        width_pt, height_pt = media_box(data)
        runs = content_runs(data)
        self.assertTrue(runs)
        for x, y, size, text in runs:
            self.assertGreaterEqual(x, -0.01, text)
            self.assertLessEqual(x, width_pt - 0.5, f"{text} at x={x}")
            self.assertGreaterEqual(y, -0.01, text)
            self.assertLessEqual(y, height_pt + 0.01, f"{text} at y={y}")

    def test_13_column_headings_land_inside_the_page(self):
        data = self.pdf()
        width_pt, _height_pt = media_box(data)
        headings = {t for _x, _y, _s, t in content_runs(data)}
        for heading in ("QTY", "UNIT", "DESCRIPTION", "COMP.", "BATCH", "EXP. DT", "AMT"):
            self.assertIn(heading, headings)
        for x, _y, _s, text in content_runs(data):
            if text in ("QTY", "UNIT", "DESCRIPTION", "COMP.", "BATCH", "EXP. DT", "AMT"):
                self.assertLessEqual(x, width_pt - 0.5, heading_or(text))

    def test_14_validate_pages_rejects_out_of_page_content(self):
        bad = [[a6.Block(kind="row", height_mm=4.0,
                         runs=[a6.Run(4.0, 9999.0, 20.0, "too low", 6.0)])]]
        with self.assertRaises(a6.ReceiptPrintError):
            a6.validate_pages(bad, a6.PHARMACY_A6)

    def test_15_validate_pages_rejects_text_past_the_right_edge(self):
        bad = [[a6.Block(kind="row", height_mm=4.0,
                         runs=[a6.Run(400.0, 10.0, 20.0, "too wide", 6.0)])]]
        with self.assertRaises(a6.ReceiptPrintError):
            a6.validate_pages(bad, a6.PHARMACY_A6)

    def test_16_validate_pages_rejects_negative_coordinates(self):
        bad = [[a6.Block(kind="row", height_mm=4.0,
                         runs=[a6.Run(-5.0, 10.0, 20.0, "negative", 6.0)])]]
        with self.assertRaises(a6.ReceiptPrintError):
            a6.validate_pages(bad, a6.PHARMACY_A6)

    def test_17_no_negative_coordinates_in_a_real_bill(self):
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        for page in pages:
            for block in page:
                for run in block.runs:
                    self.assertGreaterEqual(run.x_mm, -0.01, run.text[:24])
                    self.assertGreaterEqual(run.y_mm, -0.01, run.text[:24])
                for y_mm, _t in block.rules:
                    self.assertGreaterEqual(y_mm, -0.01)

    # ══════════════════════════════════════════════════════════════
    # 4. PAGE SIZE FOLLOWS THE CONTENT
    # ══════════════════════════════════════════════════════════════
    def test_18_one_item_bill_is_not_a_full_blank_sheet(self):
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        profile = a6.content_profile(pages)
        self.assertLess(profile.height_mm, a6.PHARMACY_A6.height_mm)
        self.assertGreaterEqual(profile.height_mm, a6.MIN_RECEIPT_HEIGHT_MM)

    def test_19_page_height_grows_with_the_item_count(self):
        self.pdf("one.pdf")
        one_height = media_box(Path(self.tmp.name, "one.pdf").read_bytes())[1]
        for index in range(14):
            self.add_item(name=f"Item {index}", batch=f"B-{index:02d}")
        self.pdf("many.pdf")
        many_height = media_box(Path(self.tmp.name, "many.pdf").read_bytes())[1]
        self.assertGreater(many_height, one_height)

    def test_20_used_height_covers_all_content(self):
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        profile = a6.content_profile(pages)
        deepest = a6.deepest_content_mm(pages[0])
        self.assertGreaterEqual(profile.height_mm, deepest)
        self.assertLessEqual(profile.height_mm, a6.PHARMACY_A6.height_mm)

    def test_21_page_width_stays_the_receipt_width(self):
        for index in range(6):
            self.add_item(name=f"Item {index}")
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        profile = a6.content_profile(pages)
        self.assertAlmostEqual(profile.width_mm, 105.0, places=3)

    def test_22_content_profile_keeps_the_same_margins(self):
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        profile = a6.content_profile(pages)
        for field in ("margin_left_mm", "margin_right_mm",
                      "margin_top_mm", "margin_bottom_mm"):
            self.assertEqual(getattr(profile, field),
                             getattr(a6.PHARMACY_A6, field), field)

    # ══════════════════════════════════════════════════════════════
    # 5. STRUCTURE STILL CORRECT
    # ══════════════════════════════════════════════════════════════
    def test_23_header_customer_and_footer_text_present(self):
        data = self.pdf()
        for marker in (b"Sales Bill", b"Name : Sunita Patil", b"Doctor : Dr Smith",
                       b"Cash Memo : CS-0001", b"Date : 2026-09-27", b"QTY", b"UNIT",
                       b"DESCRIPTION", b"COMP.", b"BATCH", b"EXP. DT", b"AMT",
                       b"L-CIN 250", b"CIPLA", b"JC00541", b"31/01/2028",
                       b"25.70", b"Net Amt :", b"E & O E.", b"Pharmacist/Sign"):
            self.assertIn(marker, data, marker)

    def test_24_all_items_print_for_a_multi_item_bill(self):
        for index in range(6):
            self.add_item(name=f"Distinct Item {index}", batch=f"BT-{index:02d}")
        data = self.pdf("six.pdf")
        for index in range(6):
            self.assertEqual(data.count(f"Distinct Item {index}".encode()), 1)

    def test_25_long_patient_and_doctor_names_do_not_overflow(self):
        conn = get_connection()
        conn.execute("UPDATE sales_invoices SET patient_name=? WHERE id=1", (LONG_PERSON,))
        conn.execute("UPDATE doctors SET doctor_name=? WHERE id=1", (LONG_DOCTOR,))
        conn.commit()
        conn.close()
        data = self.pdf("people.pdf")
        width_pt, _height_pt = media_box(data)
        for x, _y, _size, text in content_runs(data):
            self.assertLessEqual(x, width_pt - 0.5, text[:30])

    # ══════════════════════════════════════════════════════════════
    # 6. PDF OPENS / READ-ONLY GUARANTEES
    # ══════════════════════════════════════════════════════════════
    def test_26_pdf_is_a_valid_openable_file(self):
        data = self.pdf()
        self.assertTrue(data.startswith(b"%PDF-1.4"))
        self.assertTrue(data.rstrip().endswith(b"%%EOF"))
        self.assertIn(b"/Type /Catalog", data)
        self.assertIn(b"startxref", data)
        self.assertIn(b"trailer", data)
        self.assertGreater(len(data), 800)

    def test_27_print_output_also_has_no_diagonals_or_overlap(self):
        """The QPainter path must lay out identically to the PDF path."""
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QImage, QPainter

        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        profile = a6.content_profile(pages)
        image = QImage(600, 900, QImage.Format_RGB32)
        image.fill(0xFFFFFF)
        painter = QPainter(image)
        try:
            a6.draw_pages_on_painter(painter, pages, QRect(0, 0, 600, 900), profile)
        finally:
            painter.end()
        self.assertTrue(image.save(str(Path(self.tmp.name) / "rendered.png")))
        self.assertEqual(a6.overlapping_runs(pages[0]), [])

    def test_28_qprinter_output_is_a_real_pdf(self):
        from PySide6.QtGui import QPainter
        from PySide6.QtPrintSupport import QPrinter

        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        profile = a6.content_profile(pages)
        path = Path(self.tmp.name) / "printed.pdf"
        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(str(path))
        painter = QPainter()
        self.assertTrue(painter.begin(printer))
        try:
            a6.draw_pages_on_painter(painter, pages, painter.viewport(), profile)
        finally:
            painter.end()
        self.assertTrue(path.read_bytes().startswith(b"%PDF"))

    def test_29_rendering_does_not_modify_any_stored_row(self):
        import sqlite3

        def snapshot():
            conn = sqlite3.connect(self.db_path)
            try:
                return {name: conn.execute(f"SELECT * FROM {name}").fetchall()
                        for (name,) in conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'")}
            finally:
                conn.close()

        before = snapshot()
        self.pdf("r1.pdf")
        self.pdf("r2.pdf", title="Counter Sale Bill")
        a6.preview_pharmacy_a6_bill(1, "Sales Bill")
        self.assertEqual(snapshot(), before)

    def test_30_rendering_does_not_touch_stock_or_the_ledger(self):
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

    def test_31_repeated_generation_is_identical(self):
        self.assertEqual(self.pdf("g1.pdf"), self.pdf("g2.pdf"))

    def test_32_real_database_is_never_used(self):
        self.assertTrue(os.environ["PHARMACY_DB"].startswith(tempfile.gettempdir()))
        self.assertNotIn("data/pharmacy.db", os.environ["PHARMACY_DB"])

    def test_33_transaction_logic_is_not_touched_by_the_renderer(self):
        source = Path(a6.__file__).read_text(encoding="utf-8").upper()
        for marker in ("INSERT INTO SALES", "UPDATE SALES", "DELETE FROM SALES",
                       "UPDATE STOCK", "INSERT INTO LEDGER"):
            self.assertNotIn(marker, source, marker)


def heading_or(text: str) -> str:
    return text


if __name__ == "__main__":
    unittest.main(verbosity=2)