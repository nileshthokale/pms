"""A6 Landscape (148 x 105 mm) Cash Memo Crystal Report Engine for Real Counter Sale Bills.

Loads reports/CounterSaleBill_A6.rpt at runtime and logs the full path.
Strictly read-only query on real sales tables (sales_invoices, sales_invoice_items, items, units, companies, firm master).

Features:
- Identical layout to Duplicate Sales Bill: A6 landscape (148 x 105 mm).
- Arial ONLY, ALL text BOLD.
- Header fixed at top: Shop name (11 pt), address (7 pt), patient/customer + address (8 pt), doctor (8 pt), Cash/Credit Memo # (8 pt), date (8 pt).
- No 'Counter Sale Bill' title, no 'DUPLICATE COPY' label, no internal debug text.
- Column widths (140 mm): QTY 8 | UNIT 15 | DESCRIPTION 38 | COMP. 12 | BATCH 28 | EXP. DT 19 | AMT 20.
- Item Area: Exactly 10 fixed rows of 4.0 mm (ITEM_ROWS = 10, 40 mm height), padded with blanks so footer never shifts.
- BATCH: Shrink-to-fit down to 6 pt, never cut characters, never '...'.
- DESCRIPTION: Cut at column width without dots, single line.
- Footer fixed at bottom: E & O E. Subject to AHMEDNAGAR Jurisdiction, licence wrapped on 2 lines, GSTIN, Net Amt as whole integer on last page only ('Continued...' on earlier pages).
- Multi-page indicator: 'Page X of Y' only when total_pages > 1.
- Canon LBP2900 feed rotation and integer 300 DPI rendering (shares calibration with duplicate bill).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from typing import Any

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from database.connection import get_connection
from database import duplicate_a6_cash_memo as memo_a6

# ── Report File Path ──────────────────────────────────────────────────
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_RPT_FILE_PATH = os.path.join(_PROJECT_ROOT, "reports", "CounterSaleBill_A6.rpt")


def log_loaded_report_path() -> str:
    """Log the loaded CounterSaleBill_A6.rpt full path to the app log and return it."""
    path = os.path.abspath(REAL_RPT_FILE_PATH)
    msg = f"[Crystal Reports] Loaded report: {path}"
    logging.info(msg)
    print(msg, file=sys.stderr)
    return path


def get_counter_sale_data(invoice_id: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Retrieve bill header and items from real sales tables (READ ONLY).

    Derives unit and comp short name from item master (read-only);
    does not alter any tables.
    """
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            SELECT si.*,
                   COALESCE(c.customer_name, '') AS customer_name,
                   COALESCE(c.address, '') AS customer_address,
                   COALESCE(d.doctor_name, '') AS doctor_name
            FROM sales_invoices si
            LEFT JOIN customers c ON c.id = si.customer_id
            LEFT JOIN doctors d ON d.id = si.doctor_id
            WHERE si.id = ?
            """,
            (invoice_id,),
        )
        head_row = cur.fetchone()
        if not head_row:
            raise ValueError(f"Sales bill #{invoice_id} was not found.")
        head = dict(head_row)

        # Build address: check customer address, then look up in patient_addresses
        addr = (head.get("customer_address") or "").strip()
        if not addr:
            pat_name = (head.get("patient_name") or "").strip()
            if pat_name and pat_name.upper() not in ("WALKIN", "WALKIN CUSTOMER"):
                pa_cur = conn.execute(
                    """
                    SELECT address FROM patient_addresses
                    WHERE UPPER(TRIM(patient_name)) = UPPER(TRIM(?))
                      AND address IS NOT NULL AND TRIM(address) <> ''
                    ORDER BY (customer_id = ?) DESC, updated_at DESC, id DESC LIMIT 1
                    """,
                    (pat_name, head.get("customer_id")),
                )
                pa_row = pa_cur.fetchone()
                if pa_row and pa_row[0]:
                    addr = str(pa_row[0]).strip()
            if not addr:
                pa_cur = conn.execute(
                    """
                    SELECT address FROM patient_addresses
                    WHERE UPPER(TRIM(patient_name)) IN ('WALKIN', 'WALKIN CUSTOMER')
                      AND address IS NOT NULL AND TRIM(address) <> ''
                    ORDER BY (customer_id = ?) DESC, updated_at DESC, id DESC LIMIT 1
                    """,
                    (head.get("customer_id"),),
                )
                pa_row = pa_cur.fetchone()
                if pa_row and pa_row[0]:
                    addr = str(pa_row[0]).strip()
        head["address"] = addr

        # Items query with read-only join on units and companies
        cur = conn.execute(
            """
            SELECT sii.*,
                   COALESCE(i.item_name, '') AS item_name,
                   COALESCE(u.unit_name, '') AS unit_name,
                   COALESCE(NULLIF(comp.short_name, ''), comp.company_name, '') AS comp_name
            FROM sales_invoice_items sii
            LEFT JOIN items i ON i.id = sii.item_id
            LEFT JOIN units u ON u.id = i.unit_id
            LEFT JOIN companies comp ON comp.id = i.company_id
            WHERE sii.sales_invoice_id = ?
            ORDER BY sii.id
            """,
            (invoice_id,),
        )
        item_rows = cur.fetchall()
        items = []
        for r in item_rows:
            d = dict(r)
            d["unit"] = str(d.get("unit_name") or d.get("pack_size") or "").strip()
            d["comp"] = str(d.get("comp_name") or d.get("location") or "").strip()
            d["sales_qty"] = d.get("sale_qty", 0.0)
            items.append(d)

        return head, items
    finally:
        conn.close()


def paginate_counter_sale_bill(invoice_id: int) -> list[dict[str, Any]]:
    """Paginate real counter sale bill into fixed-size A6 pages."""
    log_loaded_report_path()
    head, items = get_counter_sale_data(invoice_id)
    return memo_a6.paginate_items(
        head=head,
        items=items,
        show_duplicate=False,
        report_file=REAL_RPT_FILE_PATH,
        watermark=None,
    )


def generate_counter_sale_pdf(invoice_id: int, output_path: str | None = None) -> str:
    """Generate exact A6 Landscape PDF for Real Counter Sale Bill."""
    pages = paginate_counter_sale_bill(invoice_id)
    if not output_path:
        b_no = pages[0]["head"].get("bill_no") or invoice_id
        output_path = os.path.join(os.getcwd(), f"sales_bill_{b_no}.pdf")
    return memo_a6.generate_a6_cash_memo_pdf(pages, output_path)


def print_counter_sale_bill(
    invoice_id: int,
    parent=None,
    show_dialog: bool = True,
) -> bool:
    """Print Real Counter Sale Bill on A6 Landscape (Canon LBP2900)."""
    pages = paginate_counter_sale_bill(invoice_id)
    b_type = str(pages[0]["head"].get("sale_type") or "Cash").strip()
    memo_title = "Credit Memo" if b_type.lower() == "credit" else "Cash Memo"
    return memo_a6.print_a6_cash_memo(
        pages=pages,
        parent=parent,
        title=memo_title,
        show_dialog=show_dialog,
        rotate_for_feed=memo_a6.ROTATE_FOR_FEED,
        rotate_direction=memo_a6.ROTATE_DIRECTION,
    )


class CounterSaleBillA6PreviewDialog(QDialog):
    """Crystal-Report-Style Preview and Print Dialog for Real Counter Sale Bills.

    Features:
    - Viewer toolbar: Export (Save PDF), Print, Page navigation (First, Prev, Page box, Next, Last), Find, Zoom.
    - Status bar: Current Page No. | Total Page No. | Zoom Factor.
    - Central scroll area rendering exact A6 Landscape pages.
    - Print button and viewer print icon both trigger shared Canon LBP2900 print routine.
    """

    def __init__(self, invoice_id: int, parent: QWidget | None = None):
        super().__init__(parent)
        self._invoice_id = invoice_id
        self._pages = paginate_counter_sale_bill(invoice_id)
        self._current_page_idx = 0
        self._zoom_factor = 1.0  # default 100% zoom (150 DPI preview base)
        self._base_dpi = 150.0

        b_no = self._pages[0]["head"].get("bill_no") or invoice_id if self._pages else invoice_id
        self.setWindowTitle(f"Counter Sale Bill #{b_no} - A6 Cash Memo (148 x 105 mm)")
        self.resize(980, 720)
        self.setModal(True)

        self._build_ui()
        self._update_controls()
        self._display_current_page()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        # ── Toolbar ──────────────────────────────────────────────────
        tb = QFrame()
        tb.setFixedHeight(36)
        tb.setStyleSheet("QFrame { background-color: #E8EEF5; border: 1px solid #B0C4DE; border-radius: 2px; }")
        tl = QHBoxLayout(tb)
        tl.setContentsMargins(6, 2, 6, 2)
        tl.setSpacing(6)

        # Export Button (Save PDF)
        self.btn_export = QPushButton("📥 Export")
        self.btn_export.setFixedHeight(28)
        self.btn_export.setToolTip("Export report to PDF")
        self.btn_export.setStyleSheet("background-color: #0288d1; color: white; font-weight: bold; padding: 0 10px;")
        self.btn_export.clicked.connect(self._on_export_pdf)
        tl.addWidget(self.btn_export)

        # Print Button
        self.btn_print = QPushButton("🖨 Print")
        self.btn_print.setFixedHeight(28)
        self.btn_print.setToolTip("Print Cash Memo on A6 (Canon LBP2900)")
        self.btn_print.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold; padding: 0 12px;")
        self.btn_print.clicked.connect(self._on_print)
        tl.addWidget(self.btn_print)

        # Separator
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.VLine)
        sep1.setFrameShadow(QFrame.Sunken)
        tl.addWidget(sep1)

        # Page Navigation: First, Prev, Box, /Total, Next, Last
        self.btn_first = QPushButton("⏮")
        self.btn_first.setFixedSize(28, 26)
        self.btn_first.setToolTip("First Page")
        self.btn_first.clicked.connect(self._on_first_page)
        tl.addWidget(self.btn_first)

        self.btn_prev = QPushButton("◀")
        self.btn_prev.setFixedSize(28, 26)
        self.btn_prev.setToolTip("Previous Page")
        self.btn_prev.clicked.connect(self._on_prev_page)
        tl.addWidget(self.btn_prev)

        self.page_box = QLineEdit("1")
        self.page_box.setFixedSize(36, 26)
        self.page_box.setAlignment(Qt.AlignCenter)
        self.page_box.returnPressed.connect(self._on_page_box_entered)
        tl.addWidget(self.page_box)

        total = len(self._pages) if self._pages else 1
        self.page_total_lbl = QLabel(f"/ {total}")
        self.page_total_lbl.setStyleSheet("font-weight: bold; color: #333;")
        tl.addWidget(self.page_total_lbl)

        self.btn_next = QPushButton("▶")
        self.btn_next.setFixedSize(28, 26)
        self.btn_next.setToolTip("Next Page")
        self.btn_next.clicked.connect(self._on_next_page)
        tl.addWidget(self.btn_next)

        self.btn_last = QPushButton("⏭")
        self.btn_last.setFixedSize(28, 26)
        self.btn_last.setToolTip("Last Page")
        self.btn_last.clicked.connect(self._on_last_page)
        tl.addWidget(self.btn_last)

        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.VLine)
        sep2.setFrameShadow(QFrame.Sunken)
        tl.addWidget(sep2)

        # Find Button
        self.btn_find = QPushButton("🔍 Find")
        self.btn_find.setFixedHeight(26)
        self.btn_find.clicked.connect(self._on_find)
        tl.addWidget(self.btn_find)

        # Zoom Dropdown
        tl.addSpacing(6)
        tl.addWidget(QLabel("Zoom:"))
        self.zoom_combo = QComboBox()
        self.zoom_combo.setFixedHeight(26)
        self.zoom_combo.addItems(["50%", "75%", "100%", "125%", "150%", "Fit to Width", "Fit to Page"])
        self.zoom_combo.setCurrentText("100%")
        self.zoom_combo.currentTextChanged.connect(self._on_zoom_changed)
        tl.addWidget(self.zoom_combo)

        tl.addStretch()

        # Close Button
        self.btn_close = QPushButton("Close")
        self.btn_close.setFixedHeight(28)
        self.btn_close.setStyleSheet("font-weight: bold; padding: 0 12px;")
        self.btn_close.clicked.connect(self.reject)
        tl.addWidget(self.btn_close)

        root.addWidget(tb)

        # ── Scroll Area for A6 Canvas ────────────────────────────────
        self.scroll_area = QScrollArea()
        self.scroll_area.setStyleSheet("QScrollArea { background-color: #607d8b; border: 1px solid #B0C4DE; }")
        self.scroll_area.setAlignment(Qt.AlignCenter)

        self._page_label = QLabel()
        self._page_label.setAlignment(Qt.AlignCenter)
        self._page_label.setStyleSheet("QLabel { background: white; border: 1px solid #37474f; border-radius: 2px; }")
        self.scroll_area.setWidget(self._page_label)
        root.addWidget(self.scroll_area, 1)

        # ── Status Bar at Bottom ──────────────────────────────────────
        sb = QFrame()
        sb.setFixedHeight(24)
        sb.setStyleSheet(
            "QFrame { background-color: #E8EEF5; border-top: 1px solid #B0C4DE; }"
            "QLabel { color: #333333; font-size: 11px; padding: 0 8px; border-right: 1px solid #C0D0E0; }"
        )
        sb_layout = QHBoxLayout(sb)
        sb_layout.setContentsMargins(0, 0, 0, 0)
        sb_layout.setSpacing(0)

        self.lbl_stat_curr = QLabel("Current Page No.: 1")
        self.lbl_stat_total = QLabel(f"Total Page No.: {total}")
        self.lbl_stat_zoom = QLabel("Zoom Factor: 100%")
        self.lbl_stat_zoom.setStyleSheet("border-right: none;")

        sb_layout.addWidget(self.lbl_stat_curr)
        sb_layout.addWidget(self.lbl_stat_total)
        sb_layout.addWidget(self.lbl_stat_zoom)
        sb_layout.addStretch()
        root.addWidget(sb)

    def _display_current_page(self):
        if not self._pages or not (0 <= self._current_page_idx < len(self._pages)):
            return

        page_data = self._pages[self._current_page_idx]
        current_dpi = self._base_dpi * self._zoom_factor
        pixmap = memo_a6.render_a6_cash_memo_pixmap(page_data, dpi=current_dpi)

        self._page_label.setPixmap(pixmap)
        self._page_label.setFixedSize(pixmap.size())

        self.page_box.setText(str(self._current_page_idx + 1))
        self.lbl_stat_curr.setText(f"Current Page No.: {self._current_page_idx + 1}")
        self.lbl_stat_total.setText(f"Total Page No.: {len(self._pages)}")
        self.lbl_stat_zoom.setText(f"Zoom Factor: {int(round(self._zoom_factor * 100))}%")

    def _update_controls(self):
        total = len(self._pages) if self._pages else 1
        has_pages = bool(self._pages)

        self.btn_first.setEnabled(has_pages and self._current_page_idx > 0)
        self.btn_prev.setEnabled(has_pages and self._current_page_idx > 0)
        self.btn_next.setEnabled(has_pages and self._current_page_idx < total - 1)
        self.btn_last.setEnabled(has_pages and self._current_page_idx < total - 1)
        self.page_total_lbl.setText(f"/ {total}")

    def _on_first_page(self):
        if self._pages:
            self._current_page_idx = 0
            self._update_controls()
            self._display_current_page()

    def _on_prev_page(self):
        if self._pages and self._current_page_idx > 0:
            self._current_page_idx -= 1
            self._update_controls()
            self._display_current_page()

    def _on_next_page(self):
        if self._pages and self._current_page_idx < len(self._pages) - 1:
            self._current_page_idx += 1
            self._update_controls()
            self._display_current_page()

    def _on_last_page(self):
        if self._pages:
            self._current_page_idx = len(self._pages) - 1
            self._update_controls()
            self._display_current_page()

    def _on_page_box_entered(self):
        if not self._pages:
            return
        txt = self.page_box.text().strip()
        if txt.isdigit():
            idx = int(txt) - 1
            if 0 <= idx < len(self._pages):
                self._current_page_idx = idx
                self._update_controls()
                self._display_current_page()
            else:
                self.page_box.setText(str(self._current_page_idx + 1))
        else:
            self.page_box.setText(str(self._current_page_idx + 1))

    def _on_zoom_changed(self, text: str):
        if text == "Fit to Width":
            vw = self.scroll_area.viewport().width() - 40
            w_px = (memo_a6.PAGE_WIDTH_MM / 25.4) * self._base_dpi
            if w_px > 0 and vw > 0:
                self._zoom_factor = max(0.4, min(2.5, vw / w_px))
        elif text == "Fit to Page":
            vh = self.scroll_area.viewport().height() - 40
            h_px = (memo_a6.PAGE_HEIGHT_MM / 25.4) * self._base_dpi
            if h_px > 0 and vh > 0:
                self._zoom_factor = max(0.4, min(2.5, vh / h_px))
        else:
            val = text.replace("%", "").strip()
            try:
                self._zoom_factor = float(val) / 100.0
            except ValueError:
                pass
        self._display_current_page()

    def _on_find(self):
        if not self._pages:
            return
        from ui.crystal_report_viewer import QMessageBox_getText
        text, ok = QMessageBox_getText(self, "Find in Bill", "Search medicine or batch:")
        if ok and text:
            q = text.strip().lower()
            found_page = None
            for p_idx, p in enumerate(self._pages):
                for itm in p.get("items", []):
                    name = str(itm.get("item_name") or "").lower()
                    batch = str(itm.get("batch_no") or "").lower()
                    if q in name or q in batch:
                        found_page = p_idx
                        break
                if found_page is not None:
                    break
            if found_page is not None:
                self._current_page_idx = found_page
                self._update_controls()
                self._display_current_page()
                QMessageBox.information(self, "Find", f"Match found on Page {found_page + 1}.")
            else:
                QMessageBox.information(self, "Find", f"No matches found for '{text}'.")

    def _on_print(self):
        try:
            success = print_counter_sale_bill(self._invoice_id, parent=self, show_dialog=True)
            if success:
                self.accept()
        except Exception as exc:
            QMessageBox.critical(self, "Print Error", f"Failed to print A6 Cash Memo:\n{exc}")

    def _on_export_pdf(self):
        b_no = self._pages[0]["head"].get("bill_no") or self._invoice_id if self._pages else self._invoice_id
        default_name = f"sales_bill_A6_{b_no}.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Save A6 Sales Bill PDF", default_name, "PDF (*.pdf)")
        if not path:
            return
        try:
            out = generate_counter_sale_pdf(self._invoice_id, path)
            QMessageBox.information(self, "PDF Saved", f"A6 Cash Memo PDF saved to:\n{out}")
            # Automatically open the PDF file for user inspection if supported
            try:
                if sys.platform.startswith("win"):
                    os.startfile(out)
                elif sys.platform.startswith("darwin"):
                    subprocess.Popen(["open", out])
                else:
                    subprocess.Popen(["xdg-open", out])
            except Exception:
                pass
        except Exception as exc:
            QMessageBox.critical(self, "Export Error", f"Failed to save PDF:\n{exc}")
