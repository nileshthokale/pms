import os
import sys
import unittest
from unittest.mock import MagicMock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

app = QApplication.instance() or QApplication(sys.argv)

from database.customer_dao import CustomerDAO, PatientOption
from database.item_dao import ItemDAO
from screens.counter_sale import (
    _SalePanel,
    _ItemEntryBar,
    SalesBillReviewDialog,
    _POPUP_BODY_CHROME,
)


class TestSalesBillGlitchAndAddressAutofill(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure scratch directory exists
        os.makedirs("scratch", exist_ok=True)

    def setUp(self):
        self.source_panel = _SalePanel(popup_mode=False)

    def tearDown(self):
        if hasattr(self, "source_panel"):
            self.source_panel.deleteLater()

    # =========================================================================
    # 1. Entry Bar Layout & No Glitch / Overlap Verification
    # =========================================================================

    def test_sales_bill_dialog_min_width(self):
        """Verify MIN_WIDTH is configured to at least 1080px to prevent cramped controls."""
        self.assertGreaterEqual(SalesBillReviewDialog.MIN_WIDTH, 1080)
        target_w, target_h = SalesBillReviewDialog.target_size(800, 600)
        self.assertGreaterEqual(target_w, 1080)
        self.assertGreaterEqual(target_h, 600)

    def test_entry_bar_widgets_no_overlap_in_review_dialog(self):
        """SalesBillReviewDialog entry bar layout must not glitch or overlap.

        Every visible field and label in _entry_bar must have positive width
        and must not overlap horizontally with any subsequent widget.
        """
        dialog = SalesBillReviewDialog(self.source_panel)
        dialog.show()
        app.processEvents()

        bar = dialog._panel._entry_bar
        layout = bar.layout()
        self.assertIsNotNone(layout)

        visible_widgets = []
        for i in range(layout.count()):
            item = layout.itemAt(i)
            w = item.widget()
            if w is not None and not w.isHidden():
                geom = w.geometry()
                self.assertGreater(geom.width(), 0, f"Widget {w} has non-positive width {geom.width()}")
                self.assertGreater(geom.height(), 0, f"Widget {w} has non-positive height {geom.height()}")
                visible_widgets.append((w, geom.x(), geom.y(), geom.width(), geom.height()))

        # Sort by horizontal position
        visible_widgets.sort(key=lambda t: t[1])
        self.assertGreater(len(visible_widgets), 10, "Entry bar should contain at least 10 visible controls")

        # Check for overlaps between all consecutive widgets
        for i in range(len(visible_widgets) - 1):
            w1, x1, y1, width1, height1 = visible_widgets[i]
            w2, x2, y2, width2, height2 = visible_widgets[i + 1]

            w1_name = getattr(w1, "text", lambda: type(w1).__name__)()
            w2_name = getattr(w2, "text", lambda: type(w2).__name__)()
            w1_desc = f"{type(w1).__name__}('{w1_name}') at x={x1}..{x1+width1}"
            w2_desc = f"{type(w2).__name__}('{w2_name}') at x={x2}..{x2+width2}"

            # Ensure w1 ends before or at w2 start: no overlap
            self.assertLessEqual(
                x1 + width1,
                x2,
                f"Overlap detected in SalesBillReviewDialog entry bar between {w1_desc} and {w2_desc}!",
            )

        # Check key entry fields have usable widths (no 4-6px collapsed fields)
        self.assertGreaterEqual(bar.item_combo.width(), 80, "item_combo should be at least 80px")
        self.assertGreaterEqual(bar.batch_combo.width(), 50, "batch_combo should be at least 50px")
        self.assertGreaterEqual(bar.pack_edit.width(), 24, "pack_edit should be at least 24px")
        self.assertGreaterEqual(bar.location_edit.width(), 24, "location_edit should be at least 24px")
        self.assertGreaterEqual(bar.expiry_edit.width(), 28, "expiry_edit should be at least 28px")
        self.assertGreaterEqual(bar.mrp_edit.width(), 28, "mrp_edit should be at least 28px")
        self.assertGreaterEqual(bar.stock_edit.width(), 24, "stock_edit should be at least 24px")
        self.assertGreaterEqual(bar.qty_edit.width(), 24, "qty_edit should be at least 24px")
        self.assertGreaterEqual(bar.discount_edit.width(), 24, "discount_edit should be at least 24px")
        self.assertGreaterEqual(bar.amount_edit.width(), 30, "amount_edit should be at least 30px")
        self.assertGreaterEqual(bar.add_btn.width(), 40, "add_btn should be at least 40px")

        dialog.close()

    def test_entry_bar_no_overlap_at_various_dialog_widths(self):
        """Test entry bar layout stability at different window widths (1080, 1200, 1400, 1600)."""
        dialog = SalesBillReviewDialog(self.source_panel)
        # Allow expanding beyond offscreen screen default bounds
        dialog.setMaximumSize(2500, 2000)
        dialog.show()
        app.processEvents()

        for test_width in [1080, 1200, 1400, 1600]:
            dialog.resize(test_width, 700)
            app.processEvents()
            self.assertEqual(dialog.width(), test_width)

            bar = dialog._panel._entry_bar
            layout = bar.layout()
            visible_widgets = []
            for i in range(layout.count()):
                item = layout.itemAt(i)
                w = item.widget()
                if w is not None and not w.isHidden():
                    geom = w.geometry()
                    visible_widgets.append((w, geom.x(), geom.width()))

            visible_widgets.sort(key=lambda t: t[1])
            for i in range(len(visible_widgets) - 1):
                w1, x1, width1 = visible_widgets[i]
                w2, x2, width2 = visible_widgets[i + 1]
                self.assertLessEqual(
                    x1 + width1,
                    x2,
                    f"Overlap at width {test_width} between {w1} (x={x1}..{x1+width1}) and {w2} (x={x2})",
                )

        dialog.close()

    # =========================================================================
    # 2. Item Search Keystroke Performance Verification
    # =========================================================================

    def test_item_search_does_not_trigger_load_items_or_db_queries(self):
        """item_combo search text changes do not trigger expensive load_items() full database reloads during typing."""
        bar = _ItemEntryBar(two_row=False)
        bar.load_items = MagicMock()

        original_find = getattr(ItemDAO, "find_by_name", None)
        ItemDAO.find_by_name = MagicMock()

        try:
            # Simulate operator typing keystroke by keystroke
            for query in ["P", "PA", "PAR", "PARA", "PARACET", "PARACETAMOL"]:
                bar.item_combo.lineEdit().setText(query)
                bar._on_item_search_text_changed(query)

            self.assertEqual(
                bar.load_items.call_count,
                0,
                f"load_items() was called {bar.load_items.call_count} times during typing! Should be 0.",
            )
            self.assertEqual(
                ItemDAO.find_by_name.call_count,
                0,
                f"ItemDAO.find_by_name() was called {ItemDAO.find_by_name.call_count} times during typing! Should be 0.",
            )
            # Verify completer prefix was updated to the final typed text
            self.assertEqual(
                bar.item_combo.completer().completionPrefix(),
                "PARACETAMOL",
            )
        finally:
            if original_find is not None:
                ItemDAO.find_by_name = original_find

    # =========================================================================
    # 3. Patient Name Clean & Address Auto-fill Verification
    # =========================================================================

    def test_direct_set_patient_name_with_parenthesized_address(self):
        """Selecting or setting MR NILESH AGARE (MAISGAON) sets clean name and auto-fills Address."""
        panel = _SalePanel(popup_mode=True)
        panel.patient_name_edit.setText("MR NILESH AGARE (MAISGAON)")
        app.processEvents()

        self.assertEqual(panel.patient_name_edit.text(), "MR NILESH AGARE")
        self.assertEqual(panel.address_edit.text(), "MAISGAON")

    def test_patient_option_selection_sets_clean_name_and_autofills_address(self):
        """Selecting a PatientOption with duplicate disambiguation like 'NAME  (ADDRESS)' sets clean name & auto-fills."""
        panel = _SalePanel(popup_mode=True)
        opt = PatientOption("MR NILESH AGARE", "MAISGAON", is_duplicate=True)
        panel.patient_name_edit.addItem(opt.display_text, opt)

        # Trigger selection logic
        accepted = panel.patient_name_edit._apply_patient_selection(opt, opt.display_text)
        self.assertTrue(accepted)
        panel._on_patient_name_changed(panel.patient_name_edit.text())
        app.processEvents()

        self.assertEqual(panel.patient_name_edit.text(), "MR NILESH AGARE")
        self.assertEqual(panel.address_edit.text(), "MAISGAON")

    def test_sales_bill_review_dialog_patient_address_autofill(self):
        """SalesBillReviewDialog sets clean name and auto-fills address when typed or selected."""
        dialog = SalesBillReviewDialog(self.source_panel)
        dialog.show()
        app.processEvents()

        dialog._panel.patient_name_edit.setText("MR NILESH AGARE (MAISGAON)")
        app.processEvents()

        self.assertEqual(dialog._panel.patient_name_edit.text(), "MR NILESH AGARE")
        self.assertEqual(dialog._panel.address_edit.text(), "MAISGAON")
        dialog.close()

    def test_customer_dao_get_saved_addresses_and_mobile_strip_parentheses(self):
        """CustomerDAO helpers handle names with parenthesized addresses correctly."""
        addrs = CustomerDAO.get_saved_addresses_for_patient("MR NILESH AGARE (MAISGAON)")
        self.assertIn("MAISGAON", addrs)

        # Contact lookup should strip parenthesized address without SQLite errors
        mob = CustomerDAO.get_saved_mobile_for_patient("MR NILESH AGARE (MAISGAON)")
        self.assertIsInstance(mob, str)

    def test_user_edited_address_is_not_overwritten(self):
        """If user manually typed an address, changing patient name does not overwrite it."""
        panel = _SalePanel(popup_mode=True)
        panel.address_edit.setText("CUSTOM MANUAL ADDRESS")
        panel._user_edited_address = True

        panel.patient_name_edit.setText("MR NILESH AGARE (MAISGAON)")
        app.processEvents()

        self.assertEqual(panel.patient_name_edit.text(), "MR NILESH AGARE")
        self.assertEqual(panel.address_edit.text(), "CUSTOM MANUAL ADDRESS")

    # =========================================================================
    # 4. Offscreen Snapshot Rendering
    # =========================================================================

    def test_render_offscreen_snapshot(self):
        """Render offscreen snapshot of SalesBillReviewDialog to scratch/fixed_sales_bill_dialog.png."""
        dialog = SalesBillReviewDialog(self.source_panel)
        dialog.show()
        app.processEvents()

        pixmap = dialog.grab()
        self.assertFalse(pixmap.isNull())
        self.assertGreater(pixmap.width(), 0)
        self.assertGreater(pixmap.height(), 0)

        out_path = os.path.join("scratch", "fixed_sales_bill_dialog.png")
        saved = pixmap.save(out_path)
        self.assertTrue(saved, f"Failed to save snapshot to {out_path}")
        self.assertTrue(os.path.exists(out_path))
        self.assertGreater(os.path.getsize(out_path), 1000)

        # Also copy to artifact scratch directory if available
        art_dir = r"C:\Users\Nilesh\.gemini\antigravity\brain\e6c132a4-6a13-4729-81da-76f18327a2be\scratch"
        if os.path.exists(os.path.dirname(art_dir)):
            os.makedirs(art_dir, exist_ok=True)
            import shutil
            shutil.copyfile(out_path, os.path.join(art_dir, "fixed_sales_bill_dialog.png"))

        dialog.close()


if __name__ == "__main__":
    unittest.main()
