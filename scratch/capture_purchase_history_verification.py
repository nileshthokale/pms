import sys, os
import pathlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)
app.setStyle("Fusion")

from ui.theme import theme_manager
from screens.purchase_invoice import PurchaseInvoicePage, _InvoiceDialog

ARTIFACT_DIR = pathlib.Path(r"C:\Users\Nilesh\.gemini\antigravity\brain\ca104a78-f5b4-4642-b793-b52d601bddf3")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


def capture_all():
    for mode in ("dark", "light"):
        suffix = "night" if mode == "dark" else "day"
        theme_manager.set_mode(mode)
        app.processEvents()

        # 1. Purchase History Page
        page = PurchaseInvoicePage()
        page.resize(1280, 720)
        page.show()
        app.processEvents()

        # Grab full page
        pix_page = page.grab()
        path_page = ARTIFACT_DIR / f"purchase_history_{suffix}.png"
        pix_page.save(str(path_page), "PNG")
        print(f"Saved Purchase History {mode} -> {path_page}")

        # Crop table top rows (first 6 rows with headers)
        table_rect = page._hist_table.geometry()
        # header + ~6 rows = 56 + 6*32 = ~250px
        crop_h = min(280, page._hist_table.height())
        crop_w = min(1100, page._hist_table.width())
        pix_table_crop = page._hist_table.grab().copy(0, 0, crop_w, crop_h)
        path_table_crop = ARTIFACT_DIR / f"purchase_history_table_{suffix}.png"
        pix_table_crop.save(str(path_table_crop), "PNG")
        print(f"Saved Purchase History table crop {mode} -> {path_table_crop}")

        page.close()

        # 2. New Purchase Dialog
        dlg = _InvoiceDialog()
        dlg.resize(1180, 680)
        dlg.show()
        app.processEvents()

        pix_dlg = dlg.grab()
        path_dlg = ARTIFACT_DIR / f"purchase_invoice_dialog_{suffix}.png"
        pix_dlg.save(str(path_dlg), "PNG")
        print(f"Saved Purchase Dialog {mode} -> {path_dlg}")

        # Crop header showing Voucher No, Date, Time, Type
        pix_header_crop = dlg.grab().copy(10, 10, 620, 120)
        path_header_crop = ARTIFACT_DIR / f"purchase_header_crop_{suffix}.png"
        pix_header_crop.save(str(path_header_crop), "PNG")
        print(f"Saved Purchase Header crop {mode} -> {path_header_crop}")

        dlg.close()


if __name__ == "__main__":
    capture_all()
    print("All captures completed successfully.")
