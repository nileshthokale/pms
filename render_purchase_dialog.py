import sys, os
import pathlib
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)
app.setStyle("Fusion")

from ui.theme import theme_manager
from screens.purchase_invoice import _InvoiceDialog

ARTIFACT_DIR = pathlib.Path(r"C:\Users\Nilesh\.gemini\antigravity\brain\e3b761b3-55c7-40fb-98cd-6e0b36ed2722")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

def render_and_save(theme_name: str, filename: str):
    theme_manager.set_mode(theme_name)
    app.processEvents()
    dlg = _InvoiceDialog()
    dlg.refresh_theme()
    
    # Select real supplier ANAND PHARMA (158)
    sup_idx = dlg.supplier_combo.findData(158)
    if sup_idx >= 0:
        dlg.supplier_combo.setCurrentIndex(sup_idx)
    
    # Select EFEREM SP (1796)
    item_idx = dlg._entry_bar.item_combo.findData(1796)
    if item_idx >= 0:
        dlg._entry_bar.item_combo.setCurrentIndex(item_idx)
    
    dlg._entry_bar.pack_edit.setText("10")
    dlg._entry_bar.batch_edit.setText("EF2026B1")
    dlg._entry_bar.expiry_edit.setText("08/28")
    dlg._entry_bar.pay_qty_edit.setText("20")
    dlg._entry_bar.free_qty_edit.setText("4")
    dlg._entry_bar.rate_edit.setText("74.64")
    dlg._entry_bar.mrp_edit.setText("110.00")
    dlg._entry_bar.discount_edit.setText("0.00")
    dlg._entry_bar.gst_edit.setText("5.00")
    
    # Add to table
    dlg._on_add_item()
    
    # Fill entry bar with second item (ACCUZON 1GM, 1789)
    item2_idx = dlg._entry_bar.item_combo.findData(1789)
    if item2_idx >= 0:
        dlg._entry_bar.item_combo.setCurrentIndex(item2_idx)
    dlg._entry_bar.pack_edit.setText("10")
    dlg._entry_bar.batch_edit.setText("AUG9942")
    dlg._entry_bar.expiry_edit.setText("12/27")
    dlg._entry_bar.pay_qty_edit.setText("15")
    dlg._entry_bar.free_qty_edit.setText("2")
    dlg._entry_bar.rate_edit.setText("120.00")
    dlg._entry_bar.mrp_edit.setText("175.00")
    dlg._entry_bar.discount_edit.setText("5.00")
    dlg._entry_bar.gst_edit.setText("12.00")
    
    dlg.show()
    app.processEvents()
    pix = dlg.grab()
    target_path = ARTIFACT_DIR / filename
    pix.save(str(target_path), "PNG")
    print(f"Saved {theme_name} screenshot to {target_path}")
    dlg.close()

if __name__ == "__main__":
    render_and_save("dark", "purchase_invoice_dialog_night.png")
    render_and_save("light", "purchase_invoice_dialog_day.png")
