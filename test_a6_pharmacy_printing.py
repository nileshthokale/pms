"""Phase 6G A6 pharmacy receipt printing tests.

Covers the ``PHARMACY_A6`` profile, PDF media-box geometry, bill content, the
compact column model, long item names, pagination and printer discovery.

Every test uses a disposable temporary SQLite database; ``data/pharmacy.db`` is
never opened or modified.
"""

import inspect
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from database import document_printing as printing
from database import pharmacy_a6_receipt as a6
from database.connection import get_connection, init_database

PT_PER_MM = 72.0 / 25.4
LONG_NAME = ("Paracetamol 500mg Tablets Extended Release Film Coated Very Long "
             "Product Name 20 Strip Of 10 Tablets")


def media_boxes(data: bytes) -> list[tuple[float, float]]:
    """Page sizes in points parsed from the raw PDF media boxes."""
    found = []
    for box in re.findall(rb"/MediaBox \[([^\]]+)\]", data):
        parts = [float(value) for value in box.split()]
        found.append((parts[2], parts[3]))
    return found


def page_count(data: bytes) -> int:
    match = re.search(rb"/Type\s*/Pages.*?/Count\s+(\d+)", data, re.S)
    if match:
        return int(match.group(1))
    return len(re.findall(rb"/Type\s*/Page[^s]", data))


_APP = None


def setUpModule():
    """Qt page/printer queries need a live QApplication or the process aborts."""
    global _APP
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication([])


class A6GeometryTests(unittest.TestCase):
    """Paper size, orientation, margins and column widths."""

    def test_01_profile_exists(self):
        self.assertIn("PHARMACY_A6", a6.RECEIPT_PROFILES)

    def test_02_profile_is_105x148_mm(self):
        profile = a6.PHARMACY_A6
        self.assertEqual(profile.width_mm, 105.0)
        self.assertEqual(profile.height_mm, 148.0)

    def test_03_profile_is_portrait(self):
        self.assertEqual(a6.PHARMACY_A6.orientation, "Portrait")

    def test_04_profile_scale_is_100_percent(self):
        self.assertEqual(a6.PHARMACY_A6.scale_percent, 100)

    def test_05_profile_margins_are_small(self):
        profile = a6.PHARMACY_A6
        self.assertLessEqual(max(profile.margin_left_mm, profile.margin_right_mm), 6)
        self.assertLessEqual(max(profile.margin_top_mm, profile.margin_bottom_mm), 8)

    def test_06_margins_are_inside_the_page(self):
        profile = a6.PHARMACY_A6
        self.assertGreater(profile.content_width_mm, 0)
        self.assertGreater(profile.content_height_mm, 0)
        self.assertLess(profile.content_height_mm, profile.height_mm)

    def test_07_page_size_pt_matches_105x148_mm(self):
        width, height = a6.page_size_pt()
        self.assertAlmostEqual(width, 105.0 * PT_PER_MM, places=2)
        self.assertAlmostEqual(height, 148.0 * PT_PER_MM, places=2)

    def test_08_portrait_height_exceeds_width(self):
        width, height = a6.page_size_pt()
        self.assertGreater(height, width)

    def test_09_size_label_is_human_readable(self):
        self.assertEqual(a6.PHARMACY_A6.size_label, "A6 (105 \u00d7 148 mm)")

    def test_10_qt_page_size_is_valid_a6(self):
        page_size = a6.qt_page_size()
        if page_size is None:
            self.skipTest("Qt unavailable")
        self.assertTrue(page_size.isValid())
        from PySide6.QtGui import QPageSize
        millimetres = page_size.size(QPageSize.Millimeter)
        self.assertAlmostEqual(millimetres.width(), 105.0, places=1)
        self.assertAlmostEqual(millimetres.height(), 148.0, places=1)

    def test_11_qt_page_layout_is_portrait(self):
        layout = a6.qt_page_layout()
        if layout is None:
            self.skipTest("Qt unavailable")
        self.assertTrue(layout.isValid())
        from PySide6.QtGui import QPageLayout
        self.assertEqual(layout.orientation(), QPageLayout.Portrait)

    def test_12_profile_is_not_a4_or_letter(self):
        profile = a6.PHARMACY_A6
        self.assertNotEqual((profile.width_mm, profile.height_mm), (210.0, 297.0))
        self.assertNotEqual((profile.width_mm, profile.height_mm), (215.9, 279.4))

    def test_13_columns_use_the_required_headings(self):
        self.assertEqual([column.heading for column in a6.COLUMNS],
                         ["QTY", "UNIT", "DESCRIPTION", "COMP.", "BATCH", "EXP. DT", "AMT"])

    def test_14_columns_fit_the_105mm_width(self):
        self.assertLessEqual(a6.columns_width_mm(), a6.PHARMACY_A6.content_width_mm)

    def test_15_columns_have_no_empty_width(self):
        for column in a6.COLUMNS:
            self.assertGreater(column.width_mm, 0, column.heading)

    def test_16_column_x_offsets_are_monotonic(self):
        positions = [column.x_mm for column in a6.COLUMNS]
        self.assertEqual(positions, sorted(positions))

    def test_17_amount_column_right_aligned(self):
        amount = next(c for c in a6.COLUMNS if c.key == "amount")
        self.assertEqual(amount.align, "right")

    def test_18_description_wraps_to_two_lines(self):
        description = next(c for c in a6.COLUMNS if c.key == "description")
        self.assertTrue(description.wrap)
        self.assertEqual(description.max_lines, 2)

    def test_19_profile_serialises(self):
        data = a6.PHARMACY_A6.to_dict()
        self.assertEqual(data["name"], "PHARMACY_A6")
        self.assertEqual(data["size_pt"], (297.64, 419.53))
        self.assertEqual(data["margins_mm"]["left"], 4.0)


class A6TextTests(unittest.TestCase):
    """Text measurement, wrapping and clipping."""

    def test_20_text_width_scales_with_size(self):
        small = a6.text_width_mm("Item", 4.0)
        large = a6.text_width_mm("Item", 8.0)
        self.assertAlmostEqual(large / small, 2.0, places=3)

    def test_21_bold_is_wider_than_regular(self):
        self.assertGreater(a6.text_width_mm("Item", 6.0, bold=True),
                           a6.text_width_mm("Item", 6.0))

    def test_22_line_height_scales_with_size(self):
        self.assertGreater(a6.line_height_mm(9.0), a6.line_height_mm(5.0))

    def test_23_ellipsize_leaves_short_text_alone(self):
        self.assertEqual(a6.ellipsize("OK", 6.2, 27.0), "OK")

    def test_24_ellipsize_clips_long_text(self):
        clipped = a6.ellipsize(LONG_NAME, 6.2, 12.0)
        self.assertTrue(clipped.endswith("..."))
        self.assertLess(len(clipped), len(LONG_NAME))

    def test_25_ellipsize_never_exceeds_width(self):
        for column in a6.COLUMNS:
            clipped = a6.ellipsize(LONG_NAME, 6.2, column.width_mm)
            self.assertLessEqual(a6.text_width_mm(clipped, 6.2), column.width_mm + 0.01, column.heading)

    def test_26_ellipsize_is_latin1_safe(self):
        clipped = a6.ellipsize(LONG_NAME, 6.2, 12.0)
        clipped.encode("latin-1")

    def test_27_wrap_text_returns_one_line_when_it_fits(self):
        self.assertEqual(len(a6.wrap_text("Tablet", 6.2, 27.0, 2)), 1)

    def test_28_wrap_text_wraps_long_name_to_two_lines(self):
        lines = a6.wrap_text(LONG_NAME, 6.2, 27.0, 2)
        self.assertEqual(len(lines), 2)

    def test_29_wrap_text_respects_max_lines(self):
        self.assertLessEqual(len(a6.wrap_text(LONG_NAME, 6.2, 27.0, 2)), 2)

    def test_30_wrapped_lines_fit_the_column(self):
        for line in a6.wrap_text(LONG_NAME, 6.2, 27.0, 2):
            self.assertLessEqual(a6.text_width_mm(line, 6.2), 27.0 + 0.01)

    def test_31_wrap_text_handles_empty(self):
        self.assertEqual(a6.wrap_text("", 6.2, 27.0, 2), [""])

    def test_32_store_profile_declares_only_the_real_identity(self):
        profile = a6.store_profile()
        # The counter's identity is configured, so every declared key carries a
        # real value. Keys that were never supplied stay absent: an unset
        # GSTIN or pharmacist name is never invented.
        for key in ("name", "address", "jurisdiction", "licence"):
            self.assertTrue(str(profile.get(key, "")).strip(), key)
        for key in ("gstin", "pharmacist"):
            self.assertNotIn(key, profile, key)

    def test_33_business_identity_lives_only_in_store_profile(self):
        source = Path(a6.__file__).read_text(encoding="utf-8")
        identity = str(a6.store_profile().get("name") or "")
        self.assertTrue(identity)
        # The identity may be declared in exactly one place, and no printer or
        # business name may be scattered through the layout code.
        self.assertEqual(source.count(identity), 1, identity)
        declaration = inspect.getsource(a6.store_profile)
        remainder = source.replace(declaration, "")
        for marker in (identity, "Canon", "LBP2900", "AHMEDNAGAR"):
            self.assertNotIn(marker, remainder, marker)

    def test_34_module_has_no_mysql_reference(self):
        self.assertNotIn("mysql", Path(a6.__file__).read_text(encoding="utf-8").casefold())

    def test_35_module_does_not_modify_sales_dao(self):
        source = Path(a6.__file__).read_text(encoding="utf-8")
        for marker in ("INSERT INTO sales", "UPDATE sales", "DELETE FROM sales"):
            self.assertNotIn(marker, source.upper(), marker)


class A6PdfTests(unittest.TestCase):
    """PDF media-box geometry and bill content against a real stored sale."""

    @classmethod
    def setUpClass(cls):
        cls.db_path = os.path.join(tempfile.gettempdir(), "pharmacy_a6_receipt_test.db")
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)
        os.environ["PHARMACY_DB"] = cls.db_path
        init_database()
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        conn = get_connection()
        for table in ("ledger_transactions", "sales_invoice_items", "sales_invoices",
                      "stock_batches", "items", "customers", "doctors", "units", "companies"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("INSERT INTO customers (id, customer_name) VALUES (1,'Customer One')")
        conn.execute("INSERT INTO doctors (id, doctor_name) VALUES (1,'Dr Stored')")
        conn.execute("INSERT INTO units (id, unit_name) VALUES (1,'Box')")
        conn.execute("INSERT INTO companies (id, company_name, short_name) VALUES (1,'Company One','CO')")
        conn.execute("INSERT INTO items (id, item_name, unit_id, company_id, pack_size, mrp, rate)"
                     " VALUES (1,'Stored Tablet',1,1,'10x10',50,40)")
        conn.execute("INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp,"
                     " purchase_rate, stock_qty) VALUES (1,1,'B-001','12/27','10x10',50,40,20)")
        conn.execute(
            "INSERT INTO sales_invoices (id, bill_no, sale_date, sale_time, sale_type, customer_id,"
            " patient_name, doctor_id, discount, paid_amount, total_amount, round_off, net_amount, remarks)"
            " VALUES (1,'CS-0001','2026-09-16','10:30','Cash',1,'Patient One',1,2,48,50,0,48,'Sale remark')")
        conn.execute(
            "INSERT INTO sales_invoice_items (sales_invoice_id, item_id, stock_batch_id, pack_size,"
            " location, batch_no, expiry, mrp, sale_qty, discount_amount, amount)"
            " VALUES (1,1,1,'10x10','A-1','B-001','12/27',50,1,2,48)")
        conn.commit()
        conn.close()

    def bill(self, name: str, invoice_id: int = 1, title: str = "Sales Bill") -> bytes:
        path = Path(self.tmp.name) / name
        output = printing.generate_pharmacy_a6_bill(invoice_id, path, title)
        self.assertEqual(Path(output), path)
        return Path(output).read_bytes()

    def items(self, count: int) -> None:
        conn = get_connection()
        conn.execute("DELETE FROM sales_invoice_items")
        for index in range(1, count + 1):
            name = (LONG_NAME + f" {index}") if index % 3 == 0 else f"Item {index}"
            conn.execute("INSERT INTO items (id, item_name, unit_id, company_id, pack_size, mrp, rate)"
                         " VALUES (?,?,1,1,'10x10',50,40)", (100 + index, name))
            conn.execute("INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp,"
                         " purchase_rate, stock_qty) VALUES (?,?,?,'12/27','10x10',50,40,100)",
                         (100 + index, 100 + index, f"B-{index:03d}"))
            conn.execute(
                "INSERT INTO sales_invoice_items (sales_invoice_id, item_id, stock_batch_id, pack_size,"
                " location, batch_no, expiry, mrp, sale_qty, discount_amount, amount)"
                " VALUES (1,?,?,'10x10','A-1',?,'12/27',50,1,0,48)",
                (100 + index, 100 + index, f"B-{index:03d}"))
        conn.commit()
        conn.close()

    # â”€â”€ PDF validity and page size â”€â”€

    def test_36_pdf_is_valid(self):
        data = self.bill("a6.pdf")
        self.assertTrue(data.startswith(b"%PDF-1.4"))
        self.assertTrue(data.endswith(b"%%EOF\n"))
        self.assertGreater(len(data), 500)

    def test_37_pdf_page_is_the_receipt_width(self):
        boxes = media_boxes(self.bill("a6.pdf"))
        self.assertEqual(len(boxes), 1)
        width_mm = boxes[0][0] / PT_PER_MM
        height_mm = boxes[0][1] / PT_PER_MM
        # The page is sized to the bill: always the narrow receipt width, and a
        # height that follows the content instead of a fixed sheet.
        self.assertAlmostEqual(width_mm, 105.0, places=1)
        self.assertGreaterEqual(height_mm, a6.MIN_RECEIPT_HEIGHT_MM)
        self.assertLessEqual(height_mm, 148.0)

    def test_38_pdf_page_is_not_a4(self):
        width_mm, height_mm = (box / PT_PER_MM
                               for box in media_boxes(self.bill("a6.pdf"))[0])
        self.assertNotAlmostEqual(width_mm, 210.0, places=0)
        self.assertNotAlmostEqual(height_mm, 297.0, places=0)

    def test_39_every_page_is_the_receipt_width(self):
        self.items(30)
        for width, height in media_boxes(self.bill("a6_multi.pdf")):
            self.assertAlmostEqual(width / PT_PER_MM, 105.0, places=1)
            self.assertGreaterEqual(height / PT_PER_MM, a6.MIN_RECEIPT_HEIGHT_MM)
            # The profile's own page height round-trips through points, so a
            # full page measures a few thousandths of a millimetre over 148.
            self.assertLessEqual(height / PT_PER_MM, 148.0 + 0.01)

    # â”€â”€ Header, identifiers, party â”€â”€

    def test_40_title_present(self):
        self.assertIn(b"Sales Bill", self.bill("a6.pdf"))

    def test_41_counter_sale_title_present(self):
        self.assertIn(b"Counter Sale Bill", self.bill("a6.pdf", title="Counter Sale Bill"))

    def test_42_bill_number_present(self):
        self.assertIn(b"CS-0001", self.bill("a6.pdf"))

    def test_43_date_present(self):
        self.assertIn(b"2026-09-16", self.bill("a6.pdf"))

    def test_44_patient_present(self):
        self.assertIn(b"Name : Patient One", self.bill("a6.pdf"))

    def test_45_doctor_present(self):
        self.assertIn(b"Doctor : Dr Stored", self.bill("a6.pdf"))

    def test_46_customer_is_the_name_when_there_is_no_patient(self):
        """The single "Name" line falls back to the customer."""
        conn = get_connection()
        conn.execute("UPDATE sales_invoices SET patient_name = '' WHERE id = 1")
        conn.commit()
        conn.close()
        self.assertIn(b"Name : Customer One", self.bill("a6_nopatient.pdf"))
        conn = get_connection()
        conn.execute("UPDATE sales_invoices SET patient_name = 'Patient One' WHERE id = 1")
        conn.commit()
        conn.close()

    def test_47_configured_identity_is_printed_where_it_belongs(self):
        data = self.bill("a6.pdf")
        profile = a6.store_profile()
        name = str(profile["name"]).encode()
        address = str(profile["address"]).encode()
        licence = str(profile["licence"]).encode()
        # Shop name: big and bold at the top, and again in the right-hand
        # footer above the sign-off line. Address and licence print once each.
        self.assertEqual(data.count(name), 2)
        self.assertEqual(data.count(address), 1)
        self.assertEqual(data.count(licence), 1)
        self.assertLess(data.index(name), data.index(b"QTY"))
        self.assertGreater(data.rindex(name), data.index(b"Net Amt :"))
        # The shop name is the big bold line; the location prints small.
        self.assertIn(b"/F2 9.50 Tf", data)
        self.assertRegex(data, rb"/F1 6\.60 Tf 1 0 0 1 [\d.]+ [\d.]+ Tm \(GHORPADE HOSPITAL")
        # The jurisdiction is the configured one, and nothing else is invented.
        self.assertIn(b"E & O E. Subject to AHMEDNAGAR Jurisdiction", data)
        for marker in (b"GSTIN", b"Pharmacist:"):
            self.assertNotIn(marker, data, marker)

    # â”€â”€ Item table â”€â”€

    def test_48_column_headings_present(self):
        data = self.bill("a6.pdf")
        for heading in (b"QTY", b"UNIT", b"DESCRIPTION", b"COMP.", b"BATCH", b"EXP. DT", b"AMT"):
            self.assertIn(heading, data, heading)

    def test_49_item_name_present(self):
        self.assertIn(b"Stored Tablet", self.bill("a6.pdf"))

    def test_50_batch_present(self):
        self.assertIn(b"B-001", self.bill("a6.pdf"))

    def test_51_expiry_present(self):
        self.assertIn(b"12/2027", self.bill("a6.pdf"))

    def test_51b_expiry_iso_date_is_reformatted_to_dd_mm_yyyy(self):
        conn = get_connection()
        conn.execute("UPDATE sales_invoice_items SET expiry = '2028-01-31' WHERE sales_invoice_id = 1")
        conn.commit()
        conn.close()
        self.assertIn(b"31/01/2028", self.bill("a6_expiry.pdf"))

    def test_52_company_short_name_present(self):
        self.assertIn(b"CO", self.bill("a6.pdf"))

    def test_53_line_amount_present(self):
        self.assertIn(b"48.00", self.bill("a6.pdf"))

    def test_54_quantity_present(self):
        self.assertIn(b"QTY", self.bill("a6.pdf"))

    # â”€â”€ Totals and footer â”€â”€

    def test_55_net_amount_present(self):
        self.assertIn(b"Net Amt :", self.bill("a6.pdf"))

    def test_56_net_amount_value_present(self):
        self.assertIn(b"48.00", self.bill("a6.pdf"))

    def test_57_cash_memo_shows_the_bill_number(self):
        self.assertIn(b"Cash Memo : CS-0001", self.bill("a6.pdf"))

    def test_58_receipt_shows_only_the_net_total(self):
        """A cash memo carries a single Net Amt row, not an amount breakdown."""
        data = self.bill("a6.pdf")
        for absent in (b"Total Items", b"Total Amount", b"Bill Discount",
                       b"Round Off", b"Paid Amount"):
            self.assertNotIn(absent, data, absent)
        self.assertIn(b"Net Amt :", data)

    def test_59_remarks_present(self):
        self.assertIn(b"Sale remark", self.bill("a6.pdf"))

    def test_60_footer_error_and_omissions_present(self):
        self.assertIn(b"E & O E.", self.bill("a6.pdf"))

    def test_62_no_gst_value_is_invented_for_sales(self):
        data = self.bill("a6.pdf")
        for marker in (b"GST", b"CGST", b"SGST", b"IGST", b"GSTIN"):
            self.assertNotIn(marker, data, marker)

    def test_63_no_pharmacist_name_is_invented(self):
        self.assertNotIn(b"Pharmacist:", self.bill("a6.pdf"))

    # â”€â”€ Long names â”€â”€

    def test_64_long_item_name_is_wrapped_not_clipped_away(self):
        self.items(3)
        data = self.bill("a6_long.pdf")
        self.assertIn(b"Paracetamol 500mg", data)

    def test_65_long_name_never_overflows_its_column(self):
        self.items(3)
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        for page in pages:
            for block in page:
                for run in block.runs:
                    width = a6.text_width_mm(run.text, run.size_pt, bold=run.bold)
                    self.assertLessEqual(run.x_mm + width,
                                         a6.PHARMACY_A6.width_mm - a6.PHARMACY_A6.margin_right_mm + 0.01,
                                         run.text[:24])

    def test_66_content_stays_above_the_bottom_margin(self):
        self.items(30)
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        bottom = a6.PHARMACY_A6.height_mm - a6.PHARMACY_A6.margin_bottom_mm
        for page in pages:
            for block in page:
                for run in block.runs:
                    self.assertLessEqual(run.y_mm, bottom + 0.01, run.text[:24])

    def test_67_content_stays_right_of_the_left_margin(self):
        self.items(7)
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        for page in pages:
            for block in page:
                for run in block.runs:
                    self.assertGreaterEqual(run.x_mm, a6.PHARMACY_A6.margin_left_mm - 0.01)

    # â”€â”€ Pagination â”€â”€

    def test_68_single_item_is_one_page(self):
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        self.assertEqual(len(pages), 1)

    def test_69_seven_items_fit_one_page(self):
        self.items(7)
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        self.assertEqual(len(pages), 1)
        self.assertEqual(page_count(self.bill("a6_7.pdf")), 1)

    def test_70_large_sale_spans_multiple_pages(self):
        self.items(40)
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        self.assertGreater(len(pages), 1)
        self.assertGreater(page_count(self.bill("a6_40.pdf")), 1)

    def test_71_column_heading_repeats_on_every_page(self):
        self.items(40)
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        for page in pages:
            self.assertTrue(any("DESCRIPTION" in run.text for block in page for run in block.runs))

    def test_72_totals_appear_only_on_the_final_page(self):
        self.items(40)
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        for page in pages[:-1]:
            self.assertFalse(any(run.text == "Net Amt :" for block in page for run in block.runs))
        self.assertTrue(any(run.text == "Net Amt :" for block in pages[-1] for run in block.runs))

    def test_73_document_header_only_on_first_page(self):
        self.items(40)
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        self.assertTrue(any("CS-0001" in run.text for block in pages[0] for run in block.runs))
        for page in pages[1:]:
            self.assertFalse(any("CS-0001" in run.text for block in page for run in block.runs))

    def test_74_font_size_stays_readable(self):
        self.items(40)
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        sizes = [run.size_pt for page in pages for block in page for run in block.runs]
        self.assertGreaterEqual(min(sizes), 5.0)

    def test_75_body_font_is_not_microscopic(self):
        self.assertGreaterEqual(a6.BODY_PT, 6.0)

    # â”€â”€ Preview â”€â”€

    def test_76_preview_reflects_a6_layout(self):
        preview = printing.preview_pharmacy_a6_bill(1, "Sales Bill")
        self.assertIn("CS-0001", preview)
        self.assertIn("Net Amt", preview)
        self.assertIn("DESCRIPTION", preview)

    def test_77_legacy_preview_still_works(self):
        record = {"bill_no": "CS-0001", "sale_date": "2026-09-16", "net_amount": 48}
        self.assertIn("CS-0001", printing.preview_document("Sales Bill", record, []))

    # â”€â”€ Read-only guarantees â”€â”€

    def test_78_generation_does_not_change_stored_rows(self):
        tables = ("sales_invoices", "sales_invoice_items", "stock_batches", "items",
                  "ledger_transactions", "suppliers")
        conn = get_connection()
        before = tuple(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables)
        conn.close()
        self.bill("a6_readonly.pdf")
        conn = get_connection()
        after = tuple(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables)
        conn.close()
        self.assertEqual(before, after)

    def test_79_repeated_generation_is_stable(self):
        first = self.bill("a6_r1.pdf")
        second = self.bill("a6_r2.pdf")
        self.assertEqual(media_boxes(first), media_boxes(second))
        conn = get_connection()
        count = conn.execute("SELECT COUNT(*) FROM sales_invoices").fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)

    def test_80_missing_sale_raises_print_error(self):
        with self.assertRaises(printing.DocumentPrintError):
            printing.generate_pharmacy_a6_bill(999999, Path(self.tmp.name) / "missing.pdf")

    def test_81_extension_is_forced_to_pdf(self):
        output = printing.generate_pharmacy_a6_bill(1, Path(self.tmp.name) / "noext")
        self.assertEqual(Path(output).suffix, ".pdf")

    # â”€â”€ Printer discovery â”€â”€

    def test_82_printer_discovery_returns_list(self):
        printers = a6.available_printers()
        self.assertIsInstance(printers, list)
        for name in printers:
            self.assertIsInstance(name, str)

    def test_83_default_printer_is_not_hard_coded(self):
        name = a6.default_printer_name()
        self.assertNotIn("Canon", name)

    def test_84_no_printer_name_is_hard_coded(self):
        source = Path(a6.__file__).read_text(encoding="utf-8")
        self.assertNotIn("LBP2900", source)
        self.assertNotIn("Canon", source)

    def test_85_supported_page_sizes_are_queryable(self):
        for printer in a6.available_printers():
            sizes = a6.supported_page_size_mm(printer)
            self.assertIsInstance(sizes, list)

    def test_86_printing_uses_qt_page_setup_not_raw_coordinates(self):
        source = Path(a6.__file__).read_text(encoding="utf-8")
        self.assertIn("QPageSize", source)
        self.assertIn("QPageLayout", source)
        self.assertIn("QPrintDialog", source)

    def test_87_print_profile_is_reused_by_sales_and_counter_sale(self):
        source = Path(printing.__file__).read_text(encoding="utf-8")
        self.assertIn("generate_pharmacy_a6_bill", source)
        self.assertIn("print_pharmacy_a6_bill", source)

    def test_88_service_exposes_a6_helpers(self):
        for name in ("generate_pharmacy_a6_bill", "print_pharmacy_a6_bill",
                     "preview_pharmacy_a6_bill", "a6_profile"):
            self.assertTrue(hasattr(printing, name), name)

    def test_89_profile_label_is_a6(self):
        self.assertEqual(printing.a6_profile().size_label, "A6 (105 \u00d7 148 mm)")

    def test_90_other_documents_stay_on_a4(self):
        conn = get_connection()
        conn.execute("INSERT INTO suppliers (id, supplier_name) VALUES (1,'Supplier One')")
        conn.execute(
            "INSERT INTO purchase_invoices (id, voucher_no, voucher_date, purchase_type, supplier_id,"
            " invoice_no, total_amount, gst_amount, net_amount) VALUES (1,'PV-0001','2026-09-15','Credit',1,'INV-1',40,7.2,47.2)")
        conn.commit()
        conn.close()
        path = Path(self.tmp.name) / "purchase.pdf"
        printing.generate_purchase_invoice(1, path)
        width, height = media_boxes(path.read_bytes())[0]
        self.assertAlmostEqual(width, 595.0, places=1)
        self.assertAlmostEqual(height, 842.0, places=1)

    def test_91_real_database_is_never_used(self):
        self.assertTrue(os.environ["PHARMACY_DB"].startswith(tempfile.gettempdir()))
        self.assertNotIn("Pharmacy Management System", os.environ["PHARMACY_DB"])

    def test_92_receipt_engine_is_a_single_module(self):
        root = Path(__file__).parent
        modules = sorted(p.name for p in (root / "database").glob("*a6*.py"))
        self.assertEqual(modules, ["pharmacy_a6_receipt.py"])


class A6PainterBackendTests(unittest.TestCase):
    """The QPainter backend used for preview and for real Windows printing."""

    @classmethod
    def setUpClass(cls):
        cls.db_path = os.path.join(tempfile.gettempdir(), "pharmacy_a6_painter_test.db")
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)
        os.environ["PHARMACY_DB"] = cls.db_path
        init_database()
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        conn = get_connection()
        for table in ("ledger_transactions", "sales_invoice_items", "sales_invoices",
                      "stock_batches", "items", "customers", "doctors", "units", "companies"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("INSERT INTO customers (id, customer_name) VALUES (1,'Customer One')")
        conn.execute("INSERT INTO doctors (id, doctor_name) VALUES (1,'Dr Stored')")
        conn.execute("INSERT INTO units (id, unit_name) VALUES (1,'Box')")
        conn.execute("INSERT INTO companies (id, company_name, short_name) VALUES (1,'Company One','CO')")
        conn.execute(
            "INSERT INTO sales_invoices (id, bill_no, sale_date, sale_time, sale_type, customer_id,"
            " patient_name, doctor_id, discount, paid_amount, total_amount, round_off, net_amount, remarks)"
            " VALUES (1,'CS-0001','2026-09-16','10:30','Cash',1,'Patient One',1,2,48,50,0,48,'Sale remark')")
        for index in range(1, 41):
            conn.execute("INSERT INTO items (id, item_name, unit_id, company_id, pack_size, mrp, rate)"
                         " VALUES (?,?,1,1,'10x10',50,40)", (index, f"Item {index}"))
            conn.execute("INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp,"
                         " purchase_rate, stock_qty) VALUES (?,?,?,'12/27','10x10',50,40,100)",
                         (index, index, f"B-{index:03d}"))
        conn.commit()
        conn.close()

    def lines(self, count: int) -> None:
        conn = get_connection()
        conn.execute("DELETE FROM sales_invoice_items")
        for index in range(1, count + 1):
            conn.execute(
                "INSERT INTO sales_invoice_items (sales_invoice_id, item_id, stock_batch_id, pack_size,"
                " location, batch_no, expiry, mrp, sale_qty, discount_amount, amount)"
                " VALUES (1,?,?,'10x10','A-1',?,'12/27',50,1,0,48)", (index, index, f"B-{index:03d}"))
        conn.commit()
        conn.close()

    def test_93_qpdfwriter_receives_a6_page_size(self):
        from PySide6.QtGui import QPageSize, QPdfWriter

        path = Path(self.tmp.name) / "writer.pdf"
        writer = QPdfWriter(str(path))
        writer.setPageSize(a6.qt_page_size())
        millimetres = writer.pageLayout().pageSize().size(QPageSize.Millimeter)
        self.assertAlmostEqual(millimetres.width(), 105.0, places=1)
        self.assertAlmostEqual(millimetres.height(), 148.0, places=1)

    def test_94_rendered_pdf_is_valid_a6(self):
        from PySide6.QtGui import QPageSize, QPdfWriter, QPainter

        self.lines(7)
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        path = Path(self.tmp.name) / "rendered.pdf"
        writer = QPdfWriter(str(path))
        writer.setPageSize(QPageSize(QPageSize.A6))
        writer.setResolution(300)
        painter = QPainter()
        self.assertTrue(painter.begin(writer))
        try:
            a6.draw_pages_on_painter(painter, pages, painter.viewport())
        finally:
            painter.end()
        data = path.read_bytes()
        self.assertTrue(data.startswith(b"%PDF"))
        for width, height in media_boxes(data)[:1]:
            self.assertAlmostEqual(width / PT_PER_MM, 105.0, delta=1.0)
            self.assertAlmostEqual(height / PT_PER_MM, 148.0, delta=1.0)

    def test_95_rendered_pdf_contains_visible_content(self):
        from PySide6.QtGui import QPageSize, QPdfWriter, QPainter

        self.lines(7)
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        path = Path(self.tmp.name) / "visible.pdf"
        writer = QPdfWriter(str(path))
        writer.setPageSize(QPageSize(QPageSize.A6))
        painter = QPainter()
        painter.begin(writer)
        try:
            a6.draw_pages_on_painter(painter, pages, painter.viewport())
        finally:
            painter.end()
        self.assertGreater(path.stat().st_size, 500)
        # The same layout painted to a bitmap must actually put ink on the page.
        image = self._render_image(pages)
        self.assertTrue(self._ink(image), "nothing was drawn")

    @staticmethod
    def _render_image(pages, width: int = 297, height: int = 419):
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QImage, QPainter

        image = QImage(width, height, QImage.Format_RGB32)
        image.fill(0xFFFFFF)
        painter = QPainter(image)
        try:
            a6.draw_pages_on_painter(painter, pages, QRect(0, 0, width, height))
        finally:
            painter.end()
        return image

    @staticmethod
    def _ink(image) -> list:
        return [(x, y) for y in range(0, image.height(), 2) for x in range(0, image.width(), 2)
                if image.pixelColor(x, y).lightness() < 200]

    def test_96_multipage_render_creates_a_page_per_receipt_page(self):
        from PySide6.QtGui import QPageSize, QPdfWriter, QPainter

        self.lines(40)
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        self.assertGreater(len(pages), 1)
        path = Path(self.tmp.name) / "multi_render.pdf"
        writer = QPdfWriter(str(path))
        writer.setPageSize(QPageSize(QPageSize.A6))
        painter = QPainter()
        painter.begin(writer)
        try:
            a6.draw_pages_on_painter(painter, pages, painter.viewport())
        finally:
            painter.end()
        self.assertGreaterEqual(page_count(path.read_bytes()), len(pages))

    def test_97_qprinter_render_produces_a_printable_file(self):
        from PySide6.QtGui import QPainter
        from PySide6.QtPrintSupport import QPrinter

        self.lines(7)
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        path = Path(self.tmp.name) / "printer.pdf"
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

    def test_98_layout_is_letterboxed_into_a_smaller_rect(self):
        """A device smaller than the page must still receive all content."""
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QImage, QPainter

        self.lines(7)
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        image = QImage(150, 210, QImage.Format_RGB32)
        image.fill(0xFFFFFF)
        painter = QPainter(image)
        try:
            a6.draw_pages_on_painter(painter, pages, QRect(0, 0, 150, 210))
        finally:
            painter.end()
        self.assertTrue(self._ink(image), "nothing was drawn at the reduced size")
        self.assertEqual(image.width(), 150)

    def test_99_receipt_is_centred_on_the_page(self):
        """Left/right margins must be the receipt margins, and symmetric.

        Vertically the receipt is allowed to end early: a short bill should not
        be stretched to fill the sheet.
        """
        self.lines(7)
        pages, _record = a6.build_sale_pages(1, "Sales Bill")
        image = self._render_image(pages)
        ink = self._ink(image)
        self.assertTrue(ink, "no ink rendered")
        xs = [x for x, _ in ink]
        ys = [y for _, y in ink]
        expected_gap = a6.PHARMACY_A6.margin_left_mm / a6.PHARMACY_A6.width_mm * image.width()
        left_gap, right_gap = min(xs), image.width() - max(xs)
        # Right-aligned amounts stop short of the column edge, so the ink gap can
        # be slightly smaller than the paper margin; both must stay small.
        for gap in (left_gap, right_gap):
            self.assertGreaterEqual(gap, 0)
            self.assertLess(gap, expected_gap * 1.6, f"margin {gap} is too wide")
        self.assertLess(abs(left_gap - right_gap), expected_gap)
        self.assertGreater(min(ys), 0)
        self.assertLess(max(ys), image.height())

    def test_100_print_helper_uses_qt_page_layout(self):
        source = Path(a6.__file__).read_text(encoding="utf-8")
        self.assertIn("printer.setPageLayout", source)

    def test_101_print_path_does_not_force_a_printer_name(self):
        import inspect

        source = inspect.getsource(a6.print_pharmacy_a6_bill)
        self.assertNotIn("setPrinterName", source)
        self.assertNotIn("Canon", source)
        self.assertNotIn("LBP2900", source)

    def test_102_print_helper_can_run_without_a_dialog(self):
        signature = __import__("inspect").signature(a6.print_pharmacy_a6_bill)
        self.assertIn("show_dialog", signature.parameters)


if __name__ == "__main__":
    unittest.main()
