"""Legacy tax-code flag display tests (Phase 1 tax correction).

Owner decision "flag all, convert none": stored legacy codes stay verbatim,
no code is converted to GST, no VAT option is introduced, and the user
never sees a bare number or a guessed GST name — only the explicit
"Legacy Tax Code N — Mapping Required" flag.

Every test runs against a disposable temporary database.
``data/pharmacy.db`` is never used.
"""

import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HAS_PYSIDE6 = False
_PYSIDE_SKIP_REASON = "PySide6 not available"
try:
    from PySide6.QtWidgets import QApplication, QMessageBox

    HAS_PYSIDE6 = True
except ImportError:  # pragma: no cover - environment dependent
    pass


ALL_LEGACY_CODES = ("1", "2", "4", "6", "7", "11", "12", "13", "14", "15")

EXPECTED_OPTIONS = (
    ("GST @ 5% (CGST-2.5% & SGST-2.5%)", "5"),
    ("GST @ 12% (CGST-6% & SGST-6%)", "12"),
    ("GST @ 18% (CGST-9% & SGST-9%)", "18"),
    ("GST @ 28% (CGST-14% & SGST-14%)", "28"),
    ("ZERO GST", "0"),
)


def _fresh_db(tag: str) -> str:
    db_path = os.path.join(tempfile.gettempdir(), f"pharmacy_taxflag_{tag}.db")
    for suffix in ("", "-wal", "-shm"):
        stale = db_path + suffix
        if os.path.exists(stale):
            os.remove(stale)
    os.environ["PHARMACY_DB"] = db_path
    return db_path


class LegacyFlagDisplayTests(unittest.TestCase):
    def test_01_raw_codes_never_shown_as_gst_names(self):
        from database.tax_structures import display_for
        for code in ALL_LEGACY_CODES:
            with self.subTest(code=code):
                label = display_for(code)
                self.assertNotIn("GST @", label)
                self.assertNotEqual(label, code, "bare numbers must never display")

    def test_02_flag_format_is_explicit(self):
        from database.tax_structures import display_for, legacy_display, legacy_flag_label
        for code in ("6", "11", "12"):
            with self.subTest(code=code):
                expected = f"Legacy Tax Code {code} \u2014 Mapping Required"
                self.assertEqual(display_for(code), expected)
                self.assertEqual(legacy_display(code), expected)
                self.assertEqual(legacy_flag_label(code), expected)

    def test_03_five_gst_options_exact(self):
        from database.tax_structures import GST_TAX_STRUCTURES, VALID_TAX_VALUES
        self.assertEqual(GST_TAX_STRUCTURES, EXPECTED_OPTIONS)
        self.assertEqual(VALID_TAX_VALUES, ("5", "12", "18", "28", "0"))

    def test_04_no_vat_option_introduced(self):
        from database.tax_structures import (
            GST_TAX_STRUCTURES, VALID_TAX_VALUES, is_gst_rate, rate_percent,
        )
        for text, _ in GST_TAX_STRUCTURES:
            self.assertNotIn("VAT", text)
        for probe in ("VAT @ 12.50%", "VAT @ 5.00%", "12.50", "13.50", "5.5", "6"):
            with self.subTest(probe=probe):
                self.assertFalse(is_gst_rate(probe))
                self.assertIsNone(rate_percent(probe))

    def test_05_ambiguous_codes_remain_flagged(self):
        from database.tax_structures import LEGACY_TAX_ID_MAPPING, resolve_tax_display
        ambiguous = [k for k, v in LEGACY_TAX_ID_MAPPING.items()
                     if v["status"] in ("AMBIGUOUS", "UNKNOWN")]
        self.assertTrue(ambiguous)
        for code in ambiguous:
            with self.subTest(code=code):
                self.assertIn("Mapping Required", resolve_tax_display(code))

    def test_06_verified_mapping_mechanism_shows_gst_name(self):
        from database.tax_structures import resolve_tax_display
        mapping = {"99": {"new": "18", "status": "VERIFIED", "reason": "test"}}
        self.assertEqual(
            resolve_tax_display("99", mapping=mapping), "GST @ 18% (CGST-9% & SGST-9%)")
        self.assertIn("Mapping Required",
                      resolve_tax_display("98", mapping={"98": {"new": None, "status": "UNKNOWN",
                                                       "reason": "test"}}))

    def test_07_mapping_covers_all_known_codes(self):
        from database.tax_structures import LEGACY_TAX_ID_MAPPING
        for code in ALL_LEGACY_CODES:
            with self.subTest(code=code):
                entry = LEGACY_TAX_ID_MAPPING.get(code)
                self.assertIsNotNone(entry, f"code {code} missing from mapping")
                self.assertIsNone(entry["new"], "no GST may be assigned without owner verification")
                self.assertIn(entry["status"], ("AMBIGUOUS", "UNKNOWN", "VERIFIED"))
                self.assertTrue(entry["reason"])

    def test_08_legacy_value_stays_traceable_and_fields_untouched(self):
        _fresh_db("trace")
        from database.connection import init_database
        from database.item_dao import ItemDAO
        from database import auth

        init_database()
        auth.ensure_auth_schema()
        from database.unit_dao import UnitDAO
        from database.company_dao import CompanyDAO

        unit = UnitDAO.insert("TABLET")
        company = CompanyDAO.insert("Acme Corp", "ACM")
        item_id = ItemDAO.insert(
            item_name="POWERGESIC", unit_id=unit, company_id=company,
            pack_size="10", tax_structure="6", discount=1.0, mrp=100.0,
            rate=80.0, reorder_stock_level=5, scheduled="1",
            location="A1", pathy="ALLOPATHIC MEDICINES", dpco="N")
        row = ItemDAO.get_by_id(item_id)
        self.assertEqual(row["tax_structure"], "6")
        self.assertEqual(
            (row["item_name"], row["unit_id"], row["company_id"], row["pack_size"],
             row["discount"], row["mrp"], row["rate"], row["reorder_stock_level"],
             row["scheduled"], row["location"], row["pathy"], row["dpco"]),
            ("POWERGESIC", unit, company, "10", 1.0, 100.0, 80.0, 5,
             "1", "A1", "ALLOPATHIC MEDICINES", "N"))
        # Same name under another unit keeps its own traceable code.
        gel = UnitDAO.insert("GEL")
        other = ItemDAO.insert(item_name="POWERGESIC", unit_id=gel, tax_structure="6")
        self.assertNotEqual(item_id, other)
        self.assertEqual(ItemDAO.get_by_id(other)["tax_structure"], "6")


@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class LegacyFlagDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _fresh_db("dialog")
        from database.connection import init_database
        from database import auth

        init_database()
        auth.ensure_auth_schema()
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        patches = mock.patch.multiple(
            QMessageBox, warning=mock.DEFAULT, information=mock.DEFAULT,
            critical=mock.DEFAULT,
        )
        patches.start()
        self.addCleanup(patches.stop)
        from database.connection import get_connection

        conn = get_connection()
        conn.execute("DELETE FROM items")
        conn.commit()
        conn.close()

    def test_20_dialog_flags_legacy_code_in_dropdown(self):
        from database.item_dao import ItemDAO
        from screens.item_master import _ItemDialog

        item_id = ItemDAO.insert(item_name="Flagged Item", tax_structure="11",
                                 legacy_tax_id=11)
        dialog = _ItemDialog(item=ItemDAO.get_by_id(item_id))
        self.addCleanup(dialog.deleteLater)
        texts = [dialog._tax_structure_combo.itemText(i)
                 for i in range(dialog._tax_structure_combo.count())]
        self.assertIn("Legacy Tax Code 11 \u2014 Mapping Required", texts)
        for text in texts:
            self.assertNotEqual(text.strip(), "12")

    def test_21_dialog_grid_flag_for_migrated_row(self):
        from database.item_dao import ItemDAO
        from screens.item_master import ItemMasterPage

        ItemDAO.insert(item_name="Grid Flagged", tax_structure="6")
        page = ItemMasterPage()
        self.addCleanup(page.deleteLater)
        page.show()
        QApplication.processEvents()
        page._refresh()
        QApplication.processEvents()
        cells = {page._table.item(r, 1).text(): page._table.item(r, 7).text()
                 for r in range(page._table.rowCount())}
        self.assertEqual(cells["Grid Flagged"], "Legacy Tax Code 6 \u2014 Mapping Required")


if __name__ == "__main__":
    unittest.main(verbosity=2)
