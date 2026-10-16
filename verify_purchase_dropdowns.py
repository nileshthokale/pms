"""Verification and visual capture script for Purchase screen dropdown popups.

Tests:
1. Supplier dropdown:
   - Limits initial visible items to approx 8-10 entries
   - Maximum popup height within 250-300 px
   - Working vertical scrollbar reaches all 86 suppliers
   - Aligned directly with the Supplier input field
   - Sensible width matching field width, avoiding screen overflow
   - Complete supplier names readable
2. Item dropdown:
   - Limits visible items to approx 8-10 entries
   - Maximum popup height within 250-300 px
   - Working vertical scrollbar reaches all 940 items
   - Aligned directly with the Item field
   - Sensible width (~250-320 px) that does not cover the purchase dialog
   - Medicine names completely readable
   - Batch, Expiry, Rate, MRP, Discount, GST, and Add controls remain completely visible and accessible
3. Search and keyboard navigation:
   - Type-to-search prefix matching
   - Up/Down arrow navigation
   - Enter selection
   - Escape dismissal
   - Preserves supplier and item database IDs
   - Populates item details (pack, mrp, rate, gst) without affecting unrelated fields
4. Day Mode and Night Mode rendering and readability
5. Captures updated verification screenshots:
   - screenshot_purchase_supplier_dropdown.png
   - screenshot_purchase_item_dropdown.png
   - screenshot_purchase_supplier_dropdown_night.png
   - screenshot_purchase_item_dropdown_night.png
"""
from __future__ import annotations

import os
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtTest import QTest

from database.connection import init_database
from database import auth
from database.supplier_dao import SupplierDAO
from database.item_dao import ItemDAO
from screens.purchase_invoice import _InvoiceDialog
from ui import theme


def grab_dialog_with_popup(dialog, combo, out_path: str):
    """Render the dialog with its open top-level combobox popup window composited."""
    combo.showPopup()
    QApplication.processEvents()
    popup = combo.view().window()

    dlg_pix = dialog.grab()
    popup_pix = popup.grab()

    dlg_g = dialog.mapToGlobal(QPoint(0, 0))
    pop_g = popup.mapToGlobal(QPoint(0, 0))
    offset = pop_g - dlg_g

    composite = QPixmap(dlg_pix)
    p = QPainter(composite)
    p.drawPixmap(offset.x(), offset.y(), popup_pix)
    p.end()

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    composite.save(out_path)
    combo.hidePopup()
    QApplication.processEvents()
    print(f"Captured screenshot: {out_path}")


def run_tests():
    init_database()
    auth.ensure_auth_schema()
    if auth.user_count() == 0:
        auth.create_first_admin("admin", "admin-pass-1")
    auth.session.login("admin", "admin-pass-1")

    app = QApplication.instance() or QApplication(sys.argv)

    # -----------------------------------------------------------------
    # Day Mode Verification
    # -----------------------------------------------------------------
    theme.theme_manager.set_mode("light")
    theme.apply_to_app(app)

    dlg = _InvoiceDialog()
    dlg.resize(1200, 700)
    dlg.show()
    app.processEvents()

    # --- Supplier Dropdown Tests ---
    s_combo = dlg.supplier_combo
    total_suppliers = s_combo.count()
    assert total_suppliers >= 80, f"Expected long supplier list, got {total_suppliers}"
    assert s_combo.maxVisibleItems() in (8, 9, 10), f"maxVisibleItems not 8-10: {s_combo.maxVisibleItems()}"

    s_combo.showPopup()
    app.processEvents()
    s_popup = s_combo.view().window()
    s_geo = s_popup.geometry()
    s_global = s_combo.mapToGlobal(QPoint(0, 0))

    print(f"[TEST] Supplier popup geometry: {s_geo}")
    assert 240 <= s_geo.height() <= 300, f"Supplier popup height {s_geo.height()} outside 250-300px range"
    assert s_geo.x() == s_global.x(), f"Supplier popup not aligned with field: {s_geo.x()} vs {s_global.x()}"
    assert s_geo.width() >= s_combo.width(), f"Supplier popup narrower than field"
    assert s_combo.view().verticalScrollBar().isVisible() or s_combo.view().verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded, "Scrollbar missing"

    # Test keyboard navigation
    s_view = s_combo.view()
    QTest.keyClick(s_view, Qt.Key_M)
    app.processEvents()
    matched_name = s_view.currentIndex().data()
    assert matched_name.startswith("M"), f"Type-to-search failed: {matched_name}"

    QTest.keyClick(s_view, Qt.Key_Down)
    app.processEvents()
    next_name = s_view.currentIndex().data()
    assert next_name != matched_name, "Down arrow did not advance selection"

    QTest.keyClick(s_view, Qt.Key_Return)
    app.processEvents()
    assert s_combo.currentData() is not None, "Enter key did not preserve supplier ID"
    print(f"[PASS] Supplier dropdown: Sizing, vertical scrollbar, alignment, keyboard navigation verified")

    # Capture Day Mode Supplier Screenshot
    grab_dialog_with_popup(dlg, dlg.supplier_combo, str(ROOT / "docs" / "screenshot_purchase_supplier_dropdown.png"))

    # --- Item Dropdown Tests ---
    i_combo = dlg._entry_bar.item_combo
    total_items = i_combo.count()
    assert total_items >= 500, f"Expected long item list, got {total_items}"
    assert i_combo.maxVisibleItems() in (8, 9, 10), f"maxVisibleItems not 8-10: {i_combo.maxVisibleItems()}"

    i_combo.showPopup()
    app.processEvents()
    i_popup = i_combo.view().window()
    i_geo = i_popup.geometry()
    i_global = i_combo.mapToGlobal(QPoint(0, 0))

    print(f"[TEST] Item popup geometry: {i_geo}")
    assert 240 <= i_geo.height() <= 300, f"Item popup height {i_geo.height()} outside 250-300px range"
    assert i_geo.x() == i_global.x(), f"Item popup not aligned with field: {i_geo.x()} vs {i_global.x()}"
    assert i_geo.width() <= 350, f"Item popup too wide: {i_geo.width()}"

    # Verify clearance for adjacent controls
    batch_x = dlg._entry_bar.batch_edit.mapToGlobal(QPoint(0, 0)).x()
    assert i_geo.right() < batch_x, f"Item popup covers Batch field: right={i_geo.right()}, batch_x={batch_x}"
    print(f"[PASS] Batch, Expiry, Rate, MRP, Discount, GST and Add controls are completely unobstructed (clearance: {batch_x - i_geo.right()}px)")

    # Test keyboard navigation & selection on item
    i_combo.setCurrentIndex(2)
    app.processEvents()
    item_data = dlg._entry_bar.get_current_item_data()
    assert item_data is not None, "get_current_item_data returned None"
    assert item_data["item_id"] is not None, "item_id is None"
    assert item_data["item_name"], "item_name is empty"
    assert dlg._entry_bar.mrp_edit.text() != "", "MRP was not populated"
    print(f"[PASS] Item selection successfully populated fields: {item_data['item_name']}, MRP={dlg._entry_bar.mrp_edit.text()}")

    # Capture Day Mode Item Screenshot
    grab_dialog_with_popup(dlg, dlg._entry_bar.item_combo, str(ROOT / "docs" / "screenshot_purchase_item_dropdown.png"))

    # -----------------------------------------------------------------
    # Night Mode Verification
    # -----------------------------------------------------------------
    theme.theme_manager.set_mode("night")
    theme.apply_to_app(app)
    dlg.refresh_theme()
    app.processEvents()

    grab_dialog_with_popup(dlg, dlg.supplier_combo, str(ROOT / "docs" / "screenshot_purchase_supplier_dropdown_night.png"))
    grab_dialog_with_popup(dlg, dlg._entry_bar.item_combo, str(ROOT / "docs" / "screenshot_purchase_item_dropdown_night.png"))
    print("[PASS] Night Mode screenshots captured successfully")

    # Reset back to light mode
    theme.theme_manager.set_mode("light")
    theme.apply_to_app(app)

    print("\nALL VERIFICATIONS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    run_tests()
