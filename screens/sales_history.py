from __future__ import annotations

import os
from PySide6.QtCore import QDate, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from database import document_printing, financial_year
from database.sales_dao import SalesDAO
from ui.components import FONT_FAMILY
from ui.crystal_report_viewer import (
    BlockKind,
    CrystalReportViewer,
    PAGE_HEIGHT_LANDSCAPE,
    PAGE_WIDTH_LANDSCAPE,
    ReportBlock,
    ReportHeaderData,
    ReportPage,
    get_default_store_identity,
    print_or_export_report_pages,
)
from ui.fy_view import view_year_bounds
from ui.input_rules import attach_uppercase
from ui.theme import (
    TYPE_BUTTON,
    TYPE_FORM_LABEL,
    TYPE_HINT,
    TYPE_INPUT,
    TYPE_PAGE_TITLE,
    TYPE_SECTION_HEADER,
    TYPE_TABLE_DATA,
    TYPE_TABLE_HEADER,
    TYPE_VALUE,
    TYPE_VALUE_EMPHASIS,
    date_subcontrols,
    palette,
)

_PAGE_SIZE_OPTIONS = [25, 50, 100]


def _fresh_edit_style(p: dict) -> str:
    return (
        f"QLineEdit {{"
        f"  background-color: {p['surface']}; color: {p['text']};"
        f"  border: 1px solid {p['border']}; border-radius: 2px;"
        f"  padding: 4px 6px; font-size: {TYPE_INPUT}px; font-family: {FONT_FAMILY};"
        f"}}"
        f"QLineEdit:focus {{ border: 1px solid {p['accent']}; }}"
    )


def _fresh_combo_style(p: dict) -> str:
    return (
        f"QComboBox {{"
        f"  background-color: {p['surface']}; color: {p['text']};"
        f"  border: 1px solid {p['border']}; border-radius: 2px;"
        f"  padding: 4px 6px; font-size: {TYPE_INPUT}px; font-family: {FONT_FAMILY};"
        f"}}"
        f"QComboBox:hover {{ border: 1px solid {p['accent']}; }}"
        f"QComboBox::drop-down {{ border: none; width: 20px; }}"
        f"QComboBox QAbstractItemView {{"
        f"  background-color: {p['bg']}; color: {p['text']};"
        f"  border: 1px solid {p['border']}; selection-background-color: {p['selected']};"
        f"  selection-color: {p['text']}; outline: 0;"
        f"  font-size: {TYPE_INPUT}px; font-family: {FONT_FAMILY};"
        f"}}"
    )


def _fresh_date_style(p: dict) -> str:
    return (
        f"QDateEdit {{"
        f"  background-color: {p['surface']}; color: {p['text']};"
        f"  border: 1px solid {p['border']}; border-radius: 2px;"
        f"  padding: 4px 6px; font-size: {TYPE_INPUT}px; font-family: {FONT_FAMILY};"
        f"}}"
        f"QDateEdit:focus {{ border: 1px solid {p['accent']}; }}"
        # Shared calendar chevron (ui.theme.date_subcontrols) — never
        # `image: none`, which hid the icon on every date field.
        + date_subcontrols(p, width=20)
    )


def _fresh_table_style(p: dict) -> str:
    return (
        f"QTableWidget {{"
        f"  background-color: {p['bg']}; color: {p['text']};"
        f"  border: 1px solid {p['border']}; gridline-color: {p['border']};"
        f"  font-size: {TYPE_TABLE_DATA}px; font-family: {FONT_FAMILY};"
        f"  selection-background-color: {p['accent']};"
        f"  selection-color: white;"
        f"}}"
        f"QTableWidget::item {{ padding: 3px 6px; }}"
    )


def _fresh_header_style(p: dict) -> str:
    return (
        f"QHeaderView::section {{"
        f"  background-color: {p['surface']}; color: {p['text']};"
        f"  border: none; border-bottom: 2px solid {p['accent']};"
        f"  padding: 4px 6px; font-weight: bold; font-size: {TYPE_TABLE_HEADER}px;"
        f"  font-family: {FONT_FAMILY};"
        f"}}"
    )


def _fresh_btn_style(p: dict, *, primary: bool = False, warning: bool = False) -> str:
    if primary:
        bg = p["accent"]
        hover = p["accent_hover"]
        fg = "white"
        edge = p["accent"]
    elif warning:
        bg = p["surface_alt"]
        hover = p["selected"]
        fg = p.get("warning", "#b26a00")
        edge = p.get("warning", "#b26a00")
    else:
        bg = p["surface_alt"]
        hover = p["selected"]
        fg = p["text"]
        edge = p["text_dim"]
    return (
        f"QPushButton {{"
        f"  background-color: {bg}; color: {fg};"
        f"  border: 1px solid {edge}; border-radius: 4px;"
        f"  padding: 5px 14px; font-weight: bold;"
        f"  font-size: {TYPE_BUTTON}px; font-family: {FONT_FAMILY};"
        f"}}"
        f"QPushButton:hover {{ background-color: {hover}; border: 1px solid {p['accent']}; }}"
        f"QPushButton:disabled {{"
        f"  background-color: {p['disabled_bg']}; color: {p['disabled_text']};"
        f"  border: 1px solid {p['border']};"
        f"}}"
    )


def _is_synthetic_fallback_bill(
    bill_no: str | None,
    remarks: str | None = None,
    invoice_id: int | None = None,
) -> bool:
    """Return True when ``bill_no`` is a synthetic fallback identifier.

    The legacy migrator (``database/legacy_migration.py``) generates a
    fallback ``bill_no`` of the form ``{FY}-{Vh}-{row}-S{legacy_id}`` only
    when the source legacy BillNo was missing, empty or zero, and records the
    provenance in ``remarks`` as ``Legacy salesvhheader ID …; BillNo {orig}``
    where {orig} is ``(missing)``, ``0``, or ``0.0``, and links the record in
    ``legacy_id_map`` (entity='sale', legacy_id, new_id).  Genuine bills
    record ``BillNo {actual}`` instead.

    Identification therefore relies strictly on migration provenance and the
    ``legacy_id_map`` audit trail — never on guessing from the shape of
    ``bill_no`` itself (hyphens, FY prefixes, or suffixes also occur in genuine
    historical numbers).  The stored ``bill_no``, source BillNo and
    ``legacy_id_map`` audit trail are left untouched; only the displayed
    value changes.
    """
    import re

    if not remarks and invoice_id is not None:
        try:
            from database.connection import get_connection
            conn = get_connection()
            try:
                row = conn.execute(
                    "SELECT remarks FROM sales_invoices WHERE id = ?",
                    (invoice_id,),
                ).fetchone()
                if row and row[0]:
                    remarks = row[0]
            finally:
                conn.close()
        except Exception:
            pass

    if not remarks:
        return False

    if "Legacy salesvhheader ID" not in remarks:
        return False

    # Extract original BillNo from provenance
    m = re.search(r"BillNo\s+([^\s;]+)", remarks)
    if not m:
        return False

    orig_bno = m.group(1).strip()
    if orig_bno in ("(missing)", "0", "0.0", "", "None"):
        if invoice_id is not None:
            try:
                from database.connection import get_connection
                conn = get_connection()
                try:
                    has_table = conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='legacy_id_map'"
                    ).fetchone()
                    if has_table:
                        mapped = conn.execute(
                            "SELECT legacy_id FROM legacy_id_map WHERE entity = 'sale' AND new_id = ?",
                            (invoice_id,),
                        ).fetchone()
                        if mapped:
                            return True
                finally:
                    conn.close()
            except Exception:
                pass
        return True

    return False


def _fmt_bill_no(
    bill_no: str | None,
    remarks: str | None = None,
    invoice_id: int | None = None,
    patient_name: str | None = None,
) -> str:
    """Return the display value for a bill number using centralized formatting.

    If patient_name is provided and contains only whitespace or is empty,
    returns a blank string.
    """
    if patient_name is not None and not str(patient_name).strip():
        return ""
    from core.doc_formatter import format_document_number
    return format_document_number(bill_no, default="--")


def _fmt_patient_name(patient_name: str | None) -> str:
    """Return a display-friendly patient name.

    Missing, empty, whitespace-only, or placeholder ``--`` values are
    displayed as ``WALKIN`` so walk-in customers are obvious.  Real patient
    names are returned unchanged.
    """
    if not patient_name:
        return "WALKIN"
    name = patient_name.strip()
    if not name or name == "--":
        return "WALKIN"
    return patient_name


class SalesBillDetailsDialog(QDialog):
    """Modal dialog displaying original bill details, line items, and reprint options."""

    MIN_WIDTH = 880
    MIN_HEIGHT = 480
    DEFAULT_WIDTH = 990
    DEFAULT_HEIGHT = 540

    @classmethod
    def target_size(cls, available_w: int, available_h: int) -> tuple[int, int]:
        """Calculate balanced dialog size that stays compact and readable across displays."""
        try:
            aw = max(1, int(available_w or 0))
            ah = max(1, int(available_h or 0))
        except Exception:
            aw, ah = 1366, 768
        width = min(cls.DEFAULT_WIDTH, int(round(aw * 0.85)))
        height = min(cls.DEFAULT_HEIGHT, int(round(ah * 0.80)))
        width = max(min(cls.MIN_WIDTH, aw), min(width, aw))
        height = max(min(cls.MIN_HEIGHT, ah), min(height, ah))
        return width, height

    def __init__(self, invoice_id: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.invoice_id = invoice_id
        self.setWindowTitle("Sales Bill Details")
        self.setModal(True)

        self._invoice = SalesDAO.get_by_id(invoice_id)
        self._items = SalesDAO.get_invoice_items(invoice_id)
        self._customer_row_hidden = True

        self._build_ui()
        self._apply_screen_aware_size()
        self.refresh_theme()

    def _apply_screen_aware_size(self):
        """Size the dialog to a balanced, compact popup centered on screen and resizable."""
        try:
            screen = self.screen()
            if screen is None and self.parentWidget():
                screen = self.parentWidget().screen()
            if screen is None:
                screen = QGuiApplication.primaryScreen()

            geo = screen.availableGeometry() if screen is not None else QRect(0, 0, 1366, 768)
            aw = geo.width()
            ah = geo.height()

            # Offscreen / test host fallback where screen reports tiny bounds
            if self.parentWidget() and self.parentWidget().window():
                host = self.parentWidget().window()
                if host.width() > aw:
                    aw = host.width()
                if host.height() > ah:
                    ah = host.height()

            if aw < 1000:
                aw = 1366
            if ah < 600:
                ah = 768

            w, h = self.target_size(aw, ah)
            self.setMinimumSize(min(self.MIN_WIDTH, aw), min(self.MIN_HEIGHT, ah))
            self.setMaximumSize(aw, ah)
            self.resize(w, h)

            # Center on available screen
            x = geo.x() + max(0, (geo.width() - w) // 2)
            y = geo.y() + max(0, (geo.height() - h) // 2)
            self.move(x, y)
        except Exception:
            self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        # Title strip
        title_box = QHBoxLayout()
        self._title_lbl = QLabel("Sales Bill Details")
        self._title_lbl.setStyleSheet(f"font-size: {TYPE_PAGE_TITLE}px; font-weight: bold;")
        title_box.addWidget(self._title_lbl)
        title_box.addStretch()
        layout.addLayout(title_box)

        if not self._invoice:
            err_lbl = QLabel("Invoice details could not be loaded from database.")
            layout.addWidget(err_lbl)
            return

        # Header metadata frame (compact to preserve table space)
        self._meta_group = QGroupBox("Bill Information")
        grid = QGridLayout(self._meta_group)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(4)
        grid.setContentsMargins(10, 8, 10, 8)

        bill_no = self._invoice.get("bill_no") or "--"
        sale_date = self._invoice.get("sale_date") or "--"
        sale_time = self._invoice.get("sale_time") or ""
        dt_str = f"{sale_date} {sale_time}".strip()
        sale_type = self._invoice.get("sale_type") or "Cash"
        raw_pat = self._invoice.get("patient_name")
        pat_name = _fmt_patient_name(raw_pat)
        doc_name = self._invoice.get("doctor_name") or "--"
        remarks = self._invoice.get("remarks") or ""

        def _meta_row(row_idx, label1, val1, label2, val2, label3=None, val3=None):
            l1 = QLabel(f"<b>{label1}:</b>")
            v1 = QLabel(str(val1))
            grid.addWidget(l1, row_idx, 0)
            grid.addWidget(v1, row_idx, 1)

            l2 = QLabel(f"<b>{label2}:</b>")
            v2 = QLabel(str(val2))
            grid.addWidget(l2, row_idx, 2)
            grid.addWidget(v2, row_idx, 3)

            if label3 is not None:
                l3 = QLabel(f"<b>{label3}:</b>")
                v3 = QLabel(str(val3))
                grid.addWidget(l3, row_idx, 4)
                grid.addWidget(v3, row_idx, 5)

        _meta_row(
            0,
            "Bill / CNo",
            _fmt_bill_no(bill_no, remarks, self.invoice_id, patient_name=raw_pat),
            "Date & Time",
            dt_str,
            "Payment Type",
            sale_type,
        )
        _meta_row(1, "Patient", pat_name, "Doctor", doc_name)

        layout.addWidget(self._meta_group)

        # Line items table - given most of available space
        self._items_group = QGroupBox("Bill Items")
        items_layout = QVBoxLayout(self._items_group)
        items_layout.setContentsMargins(8, 8, 8, 8)

        self._table = QTableWidget()
        self._table.setColumnCount(9)
        self._table.setHorizontalHeaderLabels([
            "Item Name", "Pack", "Location", "Batch No", "Expiry", "Qty", "MRP", "Disc Amt", "Amount"
        ])
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, 9):
            header.setSectionResizeMode(c, QHeaderView.Interactive)

        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)

        self._table.setRowCount(len(self._items))
        for idx, item in enumerate(self._items):
            name_item = QTableWidgetItem(str(item.get("item_name") or ""))
            self._table.setItem(idx, 0, name_item)

            pack_item = QTableWidgetItem(str(item.get("pack_size") or ""))
            pack_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(idx, 1, pack_item)

            loc_item = QTableWidgetItem(str(item.get("location") or ""))
            loc_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(idx, 2, loc_item)

            batch_item = QTableWidgetItem(str(item.get("batch_no") or ""))
            batch_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(idx, 3, batch_item)

            exp_item = QTableWidgetItem(str(item.get("expiry") or ""))
            exp_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(idx, 4, exp_item)

            qty_item = QTableWidgetItem(f"{float(item.get('sale_qty') or 0.0):g}")
            qty_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(idx, 5, qty_item)

            mrp_item = QTableWidgetItem(f"{float(item.get('mrp') or 0.0):.2f}")
            mrp_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(idx, 6, mrp_item)

            disc_item = QTableWidgetItem(f"{float(item.get('discount_amount') or 0.0):.2f}")
            disc_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(idx, 7, disc_item)

            amt_item = QTableWidgetItem(f"{float(item.get('amount') or 0.0):.2f}")
            amt_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(idx, 8, amt_item)

        # Baseline widths tailored for pharmacy data
        self._table.setColumnWidth(1, 55)   # Pack
        self._table.setColumnWidth(2, 75)   # Location
        self._table.setColumnWidth(3, 125)  # Batch No
        self._table.setColumnWidth(4, 105)  # Expiry
        self._table.setColumnWidth(5, 52)   # Qty
        self._table.setColumnWidth(6, 78)   # MRP
        self._table.setColumnWidth(7, 78)   # Disc Amt
        self._table.setColumnWidth(8, 88)   # Amount

        # Content-aware expansion so long batches and dates are never truncated
        fm = self._table.fontMetrics()
        batch_w = 125
        exp_w = 105
        for it in self._items:
            b_txt = str(it.get("batch_no") or "")
            if b_txt:
                batch_w = max(batch_w, fm.horizontalAdvance(b_txt) + 16)
            e_txt = str(it.get("expiry") or "")
            if e_txt:
                exp_w = max(exp_w, fm.horizontalAdvance(e_txt) + 16)
        self._table.setColumnWidth(3, batch_w)
        self._table.setColumnWidth(4, exp_w)

        items_layout.addWidget(self._table)
        layout.addWidget(self._items_group, 1)

        # Totals footer (compact)
        totals_box = QHBoxLayout()
        totals_box.setSpacing(12)
        totals_box.setContentsMargins(0, 4, 0, 0)

        tot_amt = float(self._invoice.get("total_amount") or 0.0)
        tot_disc = float(self._invoice.get("discount") or 0.0)
        round_off = float(self._invoice.get("round_off") or 0.0)
        net_amt = float(self._invoice.get("net_amount") or 0.0)
        paid_amt = float(self._invoice.get("paid_amount") or 0.0)

        def _tot_card(caption: str, val: float, emphasize: bool = False):
            vbox = QVBoxLayout()
            vbox.setSpacing(2)
            c_lbl = QLabel(caption)
            c_lbl.setStyleSheet(f"font-size: {TYPE_HINT}px; font-weight: bold;")
            c_lbl.setAlignment(Qt.AlignCenter)
            vbox.addWidget(c_lbl)

            sz = TYPE_VALUE_EMPHASIS if emphasize else TYPE_VALUE
            v_lbl = QLabel(f"{val:.2f}")
            v_lbl.setStyleSheet(f"font-size: {sz}px; font-weight: bold;")
            v_lbl.setAlignment(Qt.AlignCenter)
            vbox.addWidget(v_lbl)
            totals_box.addLayout(vbox)

        _tot_card("Total Amount", tot_amt)
        _tot_card("Discount", tot_disc)
        _tot_card("Round Off", round_off)
        _tot_card("Net Amount", net_amt, emphasize=True)
        _tot_card("Paid Amount", paid_amt)

        totals_box.addStretch(1)

        # Actions
        self._direct_print_btn = QPushButton("Print / Direct Print")
        self._direct_print_btn.clicked.connect(self._on_direct_print)
        totals_box.addWidget(self._direct_print_btn)

        self._save_pdf_btn = QPushButton("Save PDF")
        self._save_pdf_btn.clicked.connect(self._on_save_pdf)
        totals_box.addWidget(self._save_pdf_btn)

        self._close_btn = QPushButton("Close")
        self._close_btn.clicked.connect(self.accept)
        totals_box.addWidget(self._close_btn)

        layout.addLayout(totals_box)

    def _on_direct_print(self):
        try:
            document_printing.print_pharmacy_a6_bill(self.invoice_id, self, "Counter Sale Bill")
        except document_printing.DocumentPrintError as exc:
            QMessageBox.warning(self, "Print Bill", str(exc))

    def _on_save_pdf(self):
        bill_no = (self._invoice.get("bill_no") or f"bill_{self.invoice_id}").replace("/", "_")
        default_name = f"sale_bill_{bill_no}.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Save Bill PDF", default_name, "PDF (*.pdf)")
        if not path:
            return
        try:
            output = document_printing.generate_counter_sale_bill(self.invoice_id, path)
            QMessageBox.information(self, "PDF Saved", f"Bill saved to:\n{output}")
        except document_printing.DocumentPrintError as exc:
            QMessageBox.warning(self, "Save PDF", str(exc))

    def refresh_theme(self):
        p = palette()
        self.setStyleSheet(f"background-color: {p['bg']}; color: {p['text']}; font-family: {FONT_FAMILY};")
        self._table.setStyleSheet(_fresh_table_style(p))
        self._table.horizontalHeader().setStyleSheet(_fresh_header_style(p))
        self._direct_print_btn.setStyleSheet(_fresh_btn_style(p, primary=True))
        self._save_pdf_btn.setStyleSheet(_fresh_btn_style(p))
        self._close_btn.setStyleSheet(_fresh_btn_style(p))


class PatientSearchEdit(QLineEdit):
    """Patient search input with dynamic database autocomplete dropdown."""

    # Emitted when an available patient name is picked from the dropdown
    # or confirmed with Enter.
    picked = Signal()

    def __init__(self, placeholder: str = "Search patient name...", parent: QWidget | None = None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        attach_uppercase(self)

        self._popup = QListWidget()
        self._popup.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
        self._popup.setFocusPolicy(Qt.NoFocus)
        self._popup.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._popup.itemClicked.connect(self._on_item_clicked)

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(120)
        self._debounce_timer.timeout.connect(self._fetch_suggestions)

        self.textEdited.connect(self._on_text_edited)
        self.textChanged.connect(self._on_text_changed)
        self.destroyed.connect(self._cleanup_popup)
        self.refresh_theme()

    def _cleanup_popup(self):
        if hasattr(self, "_popup") and self._popup:
            self._popup.deleteLater()

    def refresh_theme(self):
        p = palette()
        self.setStyleSheet(_fresh_edit_style(p))
        self._popup.setStyleSheet(
            f"QListWidget {{"
            f"  background-color: {p['surface']}; color: {p['text']};"
            f"  border: 1px solid {p['accent']}; border-radius: 2px;"
            f"  font-size: {TYPE_INPUT}px; font-family: {FONT_FAMILY}; font-weight: bold;"
            f"  outline: 0;"
            f"}}"
            f"QListWidget::item {{"
            f"  padding: 4px 8px; min-height: 24px;"
            f"}}"
            f"QListWidget::item:selected {{"
            f"  background-color: {p['accent']}; color: #ffffff;"
            f"}}"
            f"QListWidget::item:hover {{"
            f"  background-color: {p['accent']}; color: #ffffff;"
            f"}}"
        )

    def _on_text_edited(self, text: str):
        clean = text.strip()
        if not clean:
            self.hide_suggestions()
            return
        self._debounce_timer.start(120)

    def _on_text_changed(self, text: str):
        if not text.strip():
            self._debounce_timer.stop()
            self.hide_suggestions()

    def _fetch_suggestions(self):
        text = self.text().strip()
        if not text:
            self._popup.hide()
            return
        names = SalesDAO.get_matching_patient_names(text, limit=15)
        if not names:
            self._popup.hide()
            return
        self._popup.clear()
        for name in names:
            self._popup.addItem(name)

        try:
            global_pos = self.mapToGlobal(QPoint(0, self.height()))
            popup_w = max(self.width(), 340)
            item_h = 28
            popup_h = min(len(names) * item_h + 4, 250)
            self._popup.setGeometry(global_pos.x(), global_pos.y() + 1, popup_w, popup_h)
        except Exception:
            pass

        self._popup.setCurrentRow(-1)
        self._popup.show()

    def _on_item_clicked(self, item):
        self.setText(item.text())
        self._popup.hide()
        self.picked.emit()

    def hide_suggestions(self):
        if hasattr(self, "_popup"):
            try:
                self._popup.hide()
            except RuntimeError:
                pass

    def clear_filter(self):
        self.clear()
        self.hide_suggestions()

    def set_options(self, *args, **kwargs):
        pass

    def keyPressEvent(self, event):
        key = event.key()
        if self._popup.isVisible():
            if key == Qt.Key_Down:
                row = self._popup.currentRow()
                new_row = 0 if row < 0 else min(row + 1, self._popup.count() - 1)
                self._popup.setCurrentRow(new_row)
                item = self._popup.item(new_row)
                if item:
                    self._popup.scrollToItem(item)
                return
            elif key == Qt.Key_Up:
                row = self._popup.currentRow()
                new_row = max(row - 1, 0)
                self._popup.setCurrentRow(new_row)
                item = self._popup.item(new_row)
                if item:
                    self._popup.scrollToItem(item)
                return
            elif key in (Qt.Key_Return, Qt.Key_Enter):
                current = self._popup.currentItem()
                if current and self._popup.currentRow() >= 0:
                    self.setText(current.text())
                self._popup.hide()
                self.picked.emit()
                return
            elif key == Qt.Key_Escape:
                self._popup.hide()
                return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        # Hide dropdown shortly after losing focus
        QTimer.singleShot(150, self._popup.hide)
        super().focusOutEvent(event)

    def hideEvent(self, event):
        self.hide_suggestions()
        super().hideEvent(event)


# ══════════════════════════════════════════════════════════════════════
# Sales History Crystal Report & Dialog
# ══════════════════════════════════════════════════════════════════════

_MAX_LANDSCAPE_BODY_HEIGHT = 635.0


def _paginate_sales_history_blocks(
    header: ReportHeaderData,
    blocks: list[ReportBlock],
    table_header_block: ReportBlock,
) -> list[ReportPage]:
    """Split report blocks across A4 landscape pages, repeating header row."""
    if not blocks:
        return [
            ReportPage(
                page_num=1,
                total_pages=1,
                header=header,
                blocks=[],
                orientation="landscape",
                page_width=PAGE_WIDTH_LANDSCAPE,
                page_height=PAGE_HEIGHT_LANDSCAPE,
            )
        ]

    pages: list[ReportPage] = []
    current_blocks: list[ReportBlock] = []
    current_h = 0.0

    for block in blocks:
        if current_blocks and current_h + block.height > _MAX_LANDSCAPE_BODY_HEIGHT:
            pages.append(
                ReportPage(
                    page_num=len(pages) + 1,
                    total_pages=0,
                    header=header,
                    blocks=current_blocks,
                    orientation="landscape",
                    page_width=PAGE_WIDTH_LANDSCAPE,
                    page_height=PAGE_HEIGHT_LANDSCAPE,
                )
            )
            current_blocks = []
            current_h = 0.0
            if block.kind != BlockKind.TABLE_HEADER:
                current_blocks.append(table_header_block)
                current_h += table_header_block.height

        current_blocks.append(block)
        current_h += block.height

    if current_blocks:
        pages.append(
            ReportPage(
                page_num=len(pages) + 1,
                total_pages=0,
                header=header,
                blocks=current_blocks,
                orientation="landscape",
                page_width=PAGE_WIDTH_LANDSCAPE,
                page_height=PAGE_HEIGHT_LANDSCAPE,
            )
        )

    total = len(pages)
    for p in pages:
        p.total_pages = total

    return pages


def build_sales_history_report_pages(
    rows: list[dict],
    from_date: str = "",
    to_date: str = "",
    patient_filter: str = "",
) -> list[ReportPage]:
    """Generate A4 landscape Crystal Report pages for historical sales."""
    store_name, store_address = get_default_store_identity()

    period_parts = []
    if from_date and to_date:
        period_parts.append(f"Period : {from_date}  To  {to_date}")
    elif from_date:
        period_parts.append(f"From : {from_date}")
    elif to_date:
        period_parts.append(f"Up To : {to_date}")
    else:
        period_parts.append("All Records")

    header_line_2 = " | ".join(period_parts)
    header_line_3 = f"Patient : {patient_filter}" if patient_filter else ""

    header = ReportHeaderData(
        store_name=store_name,
        store_address=store_address,
        header_line_1="SALES HISTORY REPORT",
        header_line_2=header_line_2,
        header_line_3=header_line_3,
    )

    columns = [
        "Bill No",
        "Date & Time",
        "Patient Name",
        "Doctor",
        "Bill Total",
        "Discount",
        "Paid Amount",
        "Net Amount",
        "Pay Type",
    ]
    widths = [85.0, 120.0, 198.0, 170.0, 100.0, 90.0, 100.0, 100.0, 90.0]
    aligns = [
        "center",
        "center",
        "left",
        "left",
        "right",
        "right",
        "right",
        "right",
        "center",
    ]

    table_header_block = ReportBlock(
        kind=BlockKind.TABLE_HEADER,
        height=22.0,
        data={"columns": columns, "widths": widths, "aligns": aligns},
    )

    if not rows:
        return [
            ReportPage(
                page_num=1,
                total_pages=1,
                header=header,
                blocks=[table_header_block],
                orientation="landscape",
                page_width=PAGE_WIDTH_LANDSCAPE,
                page_height=PAGE_HEIGHT_LANDSCAPE,
            )
        ]

    blocks: list[ReportBlock] = [table_header_block]

    tot_total = 0.0
    tot_disc = 0.0
    tot_paid = 0.0
    tot_net = 0.0

    for idx, row in enumerate(rows):
        bno = _fmt_bill_no(
            row.get("bill_no") or "--",
            row.get("remarks"),
            row.get("id"),
            patient_name=row.get("patient_name"),
        )
        s_date = row.get("sale_date") or ""
        s_time = row.get("sale_time") or ""
        dt_str = f"{s_date} {s_time}".strip()
        p_name = _fmt_patient_name(row.get("patient_name"))
        d_name = row.get("doctor_name") or "--"

        amt_total = float(row.get("total_amount") or 0.0)
        amt_disc = float(row.get("discount") or 0.0)
        amt_paid = float(row.get("paid_amount") or 0.0)
        amt_net = float(row.get("net_amount") or 0.0)
        stype = row.get("sale_type") or "Cash"

        tot_total += amt_total
        tot_disc += amt_disc
        tot_paid += amt_paid
        tot_net += amt_net

        cells = [
            bno,
            dt_str,
            p_name,
            d_name,
            f"{amt_total:.2f}",
            f"{amt_disc:.2f}",
            f"{amt_paid:.2f}",
            f"{amt_net:.2f}",
            stype,
        ]

        bg = "#F9FBFC" if idx % 2 == 1 else None

        blocks.append(
            ReportBlock(
                kind=BlockKind.DATA_ROW,
                height=18.0,
                data={
                    "cells": cells,
                    "widths": widths,
                    "aligns": aligns,
                    "bg": bg,
                },
            )
        )

    # Multi-column Grand Total matching table columns
    prefix_w = widths[0] + widths[1] + widths[2] + widths[3]  # 573.0
    custom_cells = [
        {"width": prefix_w, "text": f"Grand Total ({len(rows)} Bills) :", "align": "right"},
        {"width": widths[4], "text": f"{tot_total:.2f}", "align": "right"},
        {"width": widths[5], "text": f"{tot_disc:.2f}", "align": "right"},
        {"width": widths[6], "text": f"{tot_paid:.2f}", "align": "right"},
        {"width": widths[7], "text": f"{tot_net:.2f}", "align": "right"},
        {"width": widths[8], "text": "", "align": "center"},
    ]

    blocks.append(
        ReportBlock(
            kind=BlockKind.GRAND_TOTAL,
            height=22.0,
            data={"custom_cells": custom_cells, "widths": widths},
        )
    )

    return _paginate_sales_history_blocks(header, blocks, table_header_block)


class SalesHistoryReportDialog(QDialog):
    """Crystal Reports preview and print dialog for Sales History."""

    def __init__(
        self,
        pages: list[ReportPage],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._pages = list(pages)
        self._export_name = "sales_history_report.pdf"

        self.setWindowTitle("Sales History - Crystal Report")
        self.resize(1180, 820)
        self.setMinimumSize(900, 600)
        self.setModal(False)
        self.setAttribute(Qt.WA_DeleteOnClose, True)

        p = palette()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Viewer with full toolbar: Export, Print, Copy, Navigation, Zoom, Find
        self.viewer = CrystalReportViewer(self)
        self.viewer.print_requested.connect(self._on_print)
        self.viewer.export_requested.connect(self._on_export)
        layout.addWidget(self.viewer, 1)
        self.viewer.set_pages(self._pages)

        # Bottom action bar for convenient printing and exporting
        bottom_frame = QFrame()
        bottom_frame.setStyleSheet(
            f"QFrame {{ background-color: {p['surface']}; border-top: 1px solid {p['border']}; padding: 6px; }}"
        )
        bottom_layout = QHBoxLayout(bottom_frame)
        bottom_layout.setContentsMargins(10, 6, 10, 6)
        bottom_layout.setSpacing(10)

        count_lbl = QLabel(f"Total Pages: {len(self._pages)}")
        count_lbl.setStyleSheet(f"color: {p['text']}; font-weight: bold; font-size: {TYPE_FORM_LABEL}px;")
        bottom_layout.addWidget(count_lbl)

        bottom_layout.addStretch()

        self.btn_print = QPushButton("Print Report")
        self.btn_print.setStyleSheet(_fresh_btn_style(p, primary=True))
        self.btn_print.clicked.connect(self._on_print)
        bottom_layout.addWidget(self.btn_print)

        self.btn_export = QPushButton("Export PDF")
        self.btn_export.setStyleSheet(_fresh_btn_style(p))
        self.btn_export.clicked.connect(self._on_export)
        bottom_layout.addWidget(self.btn_export)

        self.btn_close = QPushButton("Close")
        self.btn_close.setStyleSheet(_fresh_btn_style(p))
        self.btn_close.clicked.connect(self.close)
        bottom_layout.addWidget(self.btn_close)

        layout.addWidget(bottom_frame)

    def _on_print(self):
        if self._pages:
            print_or_export_report_pages(self._pages, parent=self)

    def _on_export(self):
        if not self._pages:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Sales History Report",
            self._export_name,
            "PDF Files (*.pdf)",
        )
        if not path:
            return
        if not path.casefold().endswith(".pdf"):
            path += ".pdf"
        if print_or_export_report_pages(
            self._pages, parent=self, output_pdf_path=path
        ):
            QMessageBox.information(
                self, "Export", f"Sales History Report saved as PDF:\n{path}"
            )


class SalesHistoryPage(QWidget):
    """Dedicated Sales History screen (Sales → Sales History).

    Provides comprehensive searching, filtering across financial years,
    invoice details viewing, and safe reprinting without modifying any database
    or stock state.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("SalesHistoryPage")
        self._current_page = 1
        self._page_size = 50
        self._total_records = 0
        self._history_financial_year: dict | None = None

        self._build_ui()
        self._load_master_data()
        self._set_default_dates()
        self.refresh_theme()
        self._perform_search()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # ── 1. Page Title Header ─────────────────────────────────────
        title_box = QHBoxLayout()
        self._title_lbl = QLabel("Patient Bill History")
        self._title_lbl.setStyleSheet(f"font-size: {TYPE_PAGE_TITLE}px; font-weight: bold;")
        title_box.addWidget(self._title_lbl)

        self._stats_lbl = QLabel("")
        self._stats_lbl.setStyleSheet(
            f"color: {palette()['text_dim']}; font-size: {TYPE_HINT}px;"
        )
        title_box.addWidget(self._stats_lbl)
        title_box.addStretch()

        layout.addLayout(title_box)

        # ── 2. Search & Filter Bar ───────────────────────────────────
        self._filter_box = QGroupBox("Search Patient Bill History")
        filter_layout = QVBoxLayout(self._filter_box)
        filter_layout.setContentsMargins(8, 12, 8, 8)
        filter_layout.setSpacing(6)

        # Single-row filter bar: Patient | Financial Year | Search | Reset.
        row = QHBoxLayout()
        row.setSpacing(10)

        # Patient search edit with dynamic dropdown
        p_box = QHBoxLayout()
        p_box.setSpacing(6)
        p_lbl = QLabel("Patient:")
        p_lbl.setStyleSheet(f"font-size: {TYPE_FORM_LABEL}px; font-weight: bold;")
        p_box.addWidget(p_lbl)
        self._patient_edit = PatientSearchEdit("Search patient name...")
        self._patient_edit.returnPressed.connect(self._on_search_clicked)
        self._patient_edit.picked.connect(self._on_search_clicked)
        p_box.addWidget(self._patient_edit)
        row.addLayout(p_box, 1)

        # From Date
        from_box = QHBoxLayout()
        from_box.setSpacing(6)
        self._from_lbl = QLabel("From:")
        self._from_lbl.setStyleSheet(f"font-size: {TYPE_FORM_LABEL}px; font-weight: bold;")
        from_box.addWidget(self._from_lbl)
        self._from_date = QDateEdit()
        self._from_date.setCalendarPopup(True)
        self._from_date.setDisplayFormat("dd/MM/yyyy")
        self._from_date.setDate(QDate.currentDate())
        self._from_date.setFixedWidth(115)
        from_box.addWidget(self._from_date)
        row.addLayout(from_box)

        # To Date
        to_box = QHBoxLayout()
        to_box.setSpacing(6)
        self._to_lbl = QLabel("To:")
        self._to_lbl.setStyleSheet(f"font-size: {TYPE_FORM_LABEL}px; font-weight: bold;")
        to_box.addWidget(self._to_lbl)
        self._to_date = QDateEdit()
        self._to_date.setCalendarPopup(True)
        self._to_date.setDisplayFormat("dd/MM/yyyy")
        self._to_date.setDate(QDate.currentDate())
        self._to_date.setFixedWidth(115)
        to_box.addWidget(self._to_date)
        row.addLayout(to_box)

        # Search & Reset buttons
        self._search_btn = QPushButton("Search")
        self._search_btn.clicked.connect(self._on_search_clicked)
        row.addWidget(self._search_btn)

        self._reset_btn = QPushButton("Reset")
        self._reset_btn.clicked.connect(self._on_reset_clicked)
        row.addWidget(self._reset_btn)

        self._report_btn = QPushButton("Print Report")
        self._report_btn.setToolTip("Preview and Print Patient Bill History Report")
        self._report_btn.clicked.connect(self._on_open_report)
        row.addWidget(self._report_btn)

        filter_layout.addLayout(row)
        layout.addWidget(self._filter_box)

        # Retained as internal attributes for backwards compatibility
        self._date_check = QCheckBox("Filter by Date:")
        self._date_check.setChecked(False)
        self._fy_combo = QComboBox()
        self._fy_combo.addItem("All Financial Years", userData=None)
        self._fy_combo.currentIndexChanged.connect(self._on_fy_changed)

        # ── 3. Results Table ─────────────────────────────────────────
        self._table = QTableWidget()
        self._table.setColumnCount(9)
        self._table.setHorizontalHeaderLabels([
            "Bill No / CNo",
            "Sale Date & Time",
            "Patient",
            "Doctor",
            "Bill Total",
            "Discount",
            "Paid Amount",
            "Net Amount",
            "Payment Type",
        ])
        header = self._table.horizontalHeader()
        # Bill No / CNo and Sale Date & Time size to their content so long
        # legacy bill numbers are never clipped; Patient and Doctor absorb
        # the recovered space from the removed Customer column.
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(8, QHeaderView.ResizeToContents)

        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.doubleClicked.connect(self._on_view_details)
        self._table.itemSelectionChanged.connect(self._update_action_state)

        layout.addWidget(self._table, 1)

        # ── 4. Action Bar & Pagination Footer ────────────────────────
        footer_layout = QHBoxLayout()
        footer_layout.setSpacing(10)

        # Action buttons
        self._view_details_btn = QPushButton("View Details")
        self._view_details_btn.setEnabled(False)
        self._view_details_btn.clicked.connect(self._on_view_details)
        footer_layout.addWidget(self._view_details_btn)

        # Retained as hidden attributes for backwards compatibility
        self._print_btn = QPushButton("Print / Direct Print")
        self._print_btn.setVisible(False)
        self._save_pdf_btn = QPushButton("Save PDF")
        self._save_pdf_btn.setVisible(False)
        self._footer_report_btn = QPushButton("Print Report")
        self._footer_report_btn.setVisible(False)

        footer_layout.addStretch(1)

        # Pagination controls
        self._prev_btn = QPushButton("« Prev")
        self._prev_btn.setEnabled(False)
        self._prev_btn.clicked.connect(self._on_prev_page)
        footer_layout.addWidget(self._prev_btn)

        self._page_lbl = QLabel("Page 1 of 1")
        self._page_lbl.setStyleSheet(f"font-size: {TYPE_VALUE}px; font-weight: bold;")
        footer_layout.addWidget(self._page_lbl)

        self._next_btn = QPushButton("Next »")
        self._next_btn.setEnabled(False)
        self._next_btn.clicked.connect(self._on_next_page)
        footer_layout.addWidget(self._next_btn)

        page_sz_lbl = QLabel("Rows:")
        footer_layout.addWidget(page_sz_lbl)
        self._page_size_combo = QComboBox()
        for sz in _PAGE_SIZE_OPTIONS:
            self._page_size_combo.addItem(str(sz), userData=sz)
        self._page_size_combo.setCurrentText(str(self._page_size))
        self._page_size_combo.currentIndexChanged.connect(self._on_page_size_changed)
        footer_layout.addWidget(self._page_size_combo)

        layout.addLayout(footer_layout)

    def _on_patient_text_changed(self, _text: str = ""):
        """Preserved for compatibility."""
        pass

    def _load_master_data(self):
        """Populate financial year candidates."""
        self._fy_combo.blockSignals(True)
        try:
            self._fy_combo.clear()
            self._fy_combo.addItem("All Financial Years", userData=None)
            all_years = financial_year.get_financial_years()
            for y in all_years:
                self._fy_combo.addItem(f"FY {y['name']}", userData=y)
        finally:
            self._fy_combo.blockSignals(False)

    def _set_default_dates(self):
        self._from_date.setDate(QDate.currentDate())
        self._to_date.setDate(QDate.currentDate())

    def set_history_financial_year(self, year: dict | None) -> None:
        """Called by the main-window navigation bar when viewing a different FY."""
        self._history_financial_year = dict(year) if year else None
        if not year:
            self._date_check.setChecked(False)
            self._set_default_dates()
            if hasattr(self, "_fy_combo"):
                self._fy_combo.setCurrentIndex(0)
            self._current_page = 1
            self._perform_search()
            return

        start_iso = year.get("start_date") or ""
        end_iso = year.get("end_date") or ""
        if start_iso and end_iso:
            start_qd = QDate.fromString(start_iso, "yyyy-MM-dd")
            end_qd = QDate.fromString(end_iso, "yyyy-MM-dd")
            if start_qd.isValid():
                self._from_date.setDate(start_qd)
            if end_qd.isValid():
                self._to_date.setDate(end_qd)
            self._date_check.setChecked(True)

        if hasattr(self, "_fy_combo"):
            for idx in range(1, self._fy_combo.count()):
                y = self._fy_combo.itemData(idx)
                if y and y.get("name") == year.get("name"):
                    self._fy_combo.setCurrentIndex(idx)
                    break
        self._current_page = 1
        self._perform_search()

    def _on_fy_changed(self, index: int):
        self._current_page = 1
        self._perform_search()

    def _on_date_check_toggled(self, checked: bool):
        self._from_date.setEnabled(checked)
        self._to_date.setEnabled(checked)

    def _on_search_clicked(self):
        self._patient_edit.hide_suggestions()
        self._current_page = 1
        self._perform_search()

    def _on_reset_clicked(self):
        self._patient_edit.clear_filter()
        if hasattr(self, "_fy_combo"):
            self._fy_combo.setCurrentIndex(0)
        self._date_check.setChecked(False)
        self._set_default_dates()
        self._current_page = 1
        self._perform_search()

    def _on_open_report(self):
        """Build and display the Sales History Crystal Report."""
        patient_name = self._patient_edit.text().strip()

        start_date = ""
        end_date = ""
        if self._date_check.isChecked():
            if self._from_date.date() > self._to_date.date():
                QMessageBox.warning(
                    self,
                    "Sales History",
                    "From Date cannot be later than To Date.",
                )
                return
            start_date = self._from_date.date().toString("yyyy-MM-dd")
            end_date = self._to_date.date().toString("yyyy-MM-dd")

        try:
            rows, total = SalesDAO.search_sales_history(
                patient_name=patient_name,
                start_date=start_date,
                end_date=end_date,
                limit=10000,
                offset=0,
            )
        except Exception as exc:
            QMessageBox.warning(
                self, "Report Error", f"Failed to generate report:\n{exc}"
            )
            return

        if not rows:
            QMessageBox.information(
                self,
                "Sales History Report",
                "No sales records found for the selected period.",
            )
            return

        from_str = self._from_date.date().toString("dd/MM/yyyy") if start_date else ""
        to_str = self._to_date.date().toString("dd/MM/yyyy") if end_date else ""

        pages = build_sales_history_report_pages(
            rows=rows,
            from_date=from_str,
            to_date=to_str,
            patient_filter=patient_name,
        )

        dlg = SalesHistoryReportDialog(pages, self)
        self._report_dialog = dlg
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _on_prev_page(self):
        if self._current_page > 1:
            self._current_page -= 1
            self._perform_search()

    def _on_next_page(self):
        max_page = max(1, (self._total_records + self._page_size - 1) // self._page_size)
        if self._current_page < max_page:
            self._current_page += 1
            self._perform_search()

    def _on_page_size_changed(self):
        sz = self._page_size_combo.currentData()
        if sz and sz != self._page_size:
            self._page_size = sz
            self._current_page = 1
            self._perform_search()

    def _selected_invoice_id(self) -> int | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        item = self._table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def _update_action_state(self):
        has_sel = self._selected_invoice_id() is not None
        self._view_details_btn.setEnabled(has_sel)
        self._print_btn.setEnabled(has_sel)
        self._save_pdf_btn.setEnabled(has_sel)

    def _on_view_details(self):
        inv_id = self._selected_invoice_id()
        if not inv_id:
            return
        dlg = SalesBillDetailsDialog(inv_id, self)
        dlg.exec()

    def _on_direct_print(self):
        inv_id = self._selected_invoice_id()
        if not inv_id:
            return
        try:
            document_printing.print_pharmacy_a6_bill(inv_id, self, "Counter Sale Bill")
        except document_printing.DocumentPrintError as exc:
            QMessageBox.warning(self, "Print Bill", str(exc))

    def _on_save_pdf(self):
        inv_id = self._selected_invoice_id()
        if not inv_id:
            return
        inv = SalesDAO.get_by_id(inv_id) or {}
        bill_no = (inv.get("bill_no") or f"bill_{inv_id}").replace("/", "_")
        default_name = f"sale_bill_{bill_no}.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Save Bill PDF", default_name, "PDF (*.pdf)")
        if not path:
            return
        try:
            output = document_printing.generate_counter_sale_bill(inv_id, path)
            QMessageBox.information(self, "PDF Saved", f"Bill saved to:\n{output}")
        except document_printing.DocumentPrintError as exc:
            QMessageBox.warning(self, "Save PDF", str(exc))

    def _perform_search(self):
        """Execute database query with filters and populate the results table."""
        patient_name = self._patient_edit.text().strip()

        start_date = ""
        end_date = ""
        fy = self._fy_combo.currentData() if hasattr(self, "_fy_combo") else None
        if fy:
            start_date = fy.get("start_date") or ""
            end_date = fy.get("end_date") or ""
        elif self._date_check.isChecked():
            if self._from_date.date() > self._to_date.date():
                QMessageBox.warning(
                    self,
                    "Sales History",
                    "From Date cannot be later than To Date.",
                )
                return
            start_date = self._from_date.date().toString("yyyy-MM-dd")
            end_date = self._to_date.date().toString("yyyy-MM-dd")

        offset = (self._current_page - 1) * self._page_size

        try:
            rows, total = SalesDAO.search_sales_history(
                patient_name=patient_name,
                start_date=start_date,
                end_date=end_date,
                limit=self._page_size,
                offset=offset,
            )
        except Exception as exc:
            rows, total = [], 0
            QMessageBox.warning(self, "Search Error", f"Failed to search sales:\n{exc}")

        self._total_records = total
        self._populate_table(rows)

        # Update pagination info
        max_page = max(1, (self._total_records + self._page_size - 1) // self._page_size)
        self._page_lbl.setText(f"Page {self._current_page} of {max_page} ({self._total_records} bills)")
        self._prev_btn.setEnabled(self._current_page > 1)
        self._next_btn.setEnabled(self._current_page < max_page)
        self._stats_lbl.setText(f"Showing {len(rows)} of {self._total_records} records")
        self._update_action_state()

    def _populate_table(self, rows: list[dict]):
        self._table.setRowCount(len(rows))
        for r_idx, row in enumerate(rows):
            # 0: Bill No (numeric sequence displayed when patient present, blank when empty)
            raw_bno = row.get("bill_no") or "--"
            bno_item = QTableWidgetItem(
                _fmt_bill_no(
                    raw_bno,
                    row.get("remarks"),
                    row.get("id"),
                    patient_name=row.get("patient_name"),
                )
            )
            bno_item.setData(Qt.UserRole, row.get("id"))
            bno_item.setTextAlignment(Qt.AlignCenter)
            bno_item.setToolTip(f"Full Bill No: {raw_bno}")
            self._table.setItem(r_idx, 0, bno_item)

            # 1: Date & Time
            s_date = row.get("sale_date") or ""
            s_time = row.get("sale_time") or ""
            dt_item = QTableWidgetItem(f"{s_date} {s_time}".strip())
            dt_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(r_idx, 1, dt_item)

            # 2: Patient (WALKIN fallback for missing names)
            p_name = _fmt_patient_name(row.get("patient_name"))
            self._table.setItem(r_idx, 2, QTableWidgetItem(p_name))

            # 3: Doctor
            d_name = row.get("doctor_name") or "--"
            self._table.setItem(r_idx, 3, QTableWidgetItem(d_name))

            # 4: Bill Total
            tot = float(row.get("total_amount") or 0.0)
            tot_item = QTableWidgetItem(f"{tot:.2f}")
            tot_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(r_idx, 4, tot_item)

            # 5: Discount
            disc = float(row.get("discount") or 0.0)
            disc_item = QTableWidgetItem(f"{disc:.2f}")
            disc_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(r_idx, 5, disc_item)

            # 6: Paid Amount
            paid = float(row.get("paid_amount") or 0.0)
            paid_item = QTableWidgetItem(f"{paid:.2f}")
            paid_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(r_idx, 6, paid_item)

            # 7: Net Amount
            net = float(row.get("net_amount") or 0.0)
            net_item = QTableWidgetItem(f"{net:.2f}")
            net_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(r_idx, 7, net_item)

            # 8: Payment Type
            stype = row.get("sale_type") or "Cash"
            st_item = QTableWidgetItem(stype)
            st_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(r_idx, 8, st_item)

    def refresh_theme(self):
        p = palette()
        self.setStyleSheet(f"background-color: {p['bg']}; color: {p['text']}; font-family: {FONT_FAMILY};")

        # Tables and headers
        self._table.setStyleSheet(_fresh_table_style(p))
        self._table.horizontalHeader().setStyleSheet(_fresh_header_style(p))

        # Inputs
        self._patient_edit.refresh_theme()
        if hasattr(self, "_fy_combo"):
            self._fy_combo.setStyleSheet(_fresh_combo_style(p))
        self._page_size_combo.setStyleSheet(_fresh_combo_style(p))
        self._from_date.setStyleSheet(_fresh_date_style(p))
        self._to_date.setStyleSheet(_fresh_date_style(p))

        # Labels
        if hasattr(self, "_from_lbl"):
            self._from_lbl.setStyleSheet(f"color: {p['text']}; font-size: {TYPE_FORM_LABEL}px; font-weight: bold;")
        if hasattr(self, "_to_lbl"):
            self._to_lbl.setStyleSheet(f"color: {p['text']}; font-size: {TYPE_FORM_LABEL}px; font-weight: bold;")

        # Buttons
        self._search_btn.setStyleSheet(_fresh_btn_style(p, primary=True))
        self._reset_btn.setStyleSheet(_fresh_btn_style(p))
        if hasattr(self, "_report_btn"):
            self._report_btn.setStyleSheet(_fresh_btn_style(p))
        if hasattr(self, "_footer_report_btn"):
            self._footer_report_btn.setStyleSheet(_fresh_btn_style(p))
        self._view_details_btn.setStyleSheet(_fresh_btn_style(p, primary=True))
        self._print_btn.setStyleSheet(_fresh_btn_style(p))
        self._save_pdf_btn.setStyleSheet(_fresh_btn_style(p))
        self._prev_btn.setStyleSheet(_fresh_btn_style(p))
        self._next_btn.setStyleSheet(_fresh_btn_style(p))

        # Group box
        self._filter_box.setStyleSheet(
            f"QGroupBox {{"
            f"  background-color: {p['bg']}; color: {p['text']};"
            f"  font-weight: bold; font-size: {TYPE_SECTION_HEADER}px;"
            f"  border: 1px solid {p['border']}; border-radius: 2px;"
            f"  margin-top: 10px; padding-top: 14px;"
            f"}}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 6px;"
            f"  color: {p['text']}; background-color: {p['bg']}; }}"
        )

