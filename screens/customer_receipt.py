from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from database.customer_dao import CustomerDAO
from database.customer_receipt_dao import CustomerReceiptDAO
from database import auth
from database import financial_year
from database.document_printing import DocumentPrintError, generate_customer_receipt

from ui.theme import palette
_p = palette()
_DARK_BG = _p["bg"]
_SURFACE = _p["surface"]
_BORDER = _p["border"]
_ACCENT = _p["accent"]
_ACCENT_HOVER = _p["accent_hover"]
_TEXT = _p["text"]
_TEXT_DIM = _p["text_dim"]
_ERROR = "#c0392b"

_COMBO_STYLE = (
    f"QComboBox {{"
    f"  background-color: {_SURFACE}; color: {_TEXT};"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  padding: 6px; font-size: 12px; font-family: 'Segoe UI';"
    f"}}"
    f"QComboBox:hover {{ border: 1px solid {_ACCENT}; }}"
    f"QComboBox::drop-down {{ border: none; width: 24px; }}"
    f"QComboBox::down-arrow {{ image: none; border: none; }}"
    f"QComboBox QAbstractItemView {{"
    f"  background-color: {_SURFACE}; color: {_TEXT};"
    f"  border: 1px solid {_BORDER}; selection-background-color: {_ACCENT};"
    f"  font-size: 12px; font-family: 'Segoe UI';"
    f"}}"
)

_EDIT_STYLE = (
    f"QLineEdit {{"
    f"  background-color: {_SURFACE}; color: {_TEXT};"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  padding: 5px; font-size: 12px; font-family: 'Segoe UI';"
    f"}}"
    f"QLineEdit:focus {{ border: 1px solid {_ACCENT}; }}"
)

_DATE_STYLE = (
    f"QDateEdit {{"
    f"  background-color: {_SURFACE}; color: {_TEXT};"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  padding: 5px; font-size: 12px; font-family: 'Segoe UI';"
    f"}}"
    f"QDateEdit:focus {{ border: 1px solid {_ACCENT}; }}"
    f"QDateEdit::drop-down {{ border: none; width: 24px; }}"
    f"QDateEdit::down-arrow {{ image: none; border: none; }}"
)

_BTN_SAVE = (
    f"QPushButton {{ background-color: {_ACCENT}; color: white;"
    f"  border: none; border-radius: 2px; padding: 8px 20px;"
    f"  font-weight: bold; font-size: 13px; font-family: 'Segoe UI'; }}"
    f"QPushButton:hover {{ background-color: {_ACCENT_HOVER}; }}"
)

_BTN_SECONDARY = (
    f"QPushButton {{ background-color: {_BORDER}; color: {_TEXT};"
    f"  border: none; border-radius: 2px; padding: 8px 20px;"
    f"  font-size: 13px; font-family: 'Segoe UI'; }}"
    f"QPushButton:hover {{ background-color: #7d93a8; }}"
)

_BTN_DANGER = (
    f"QPushButton {{ background-color: {_ERROR}; color: white;"
    f"  border: none; border-radius: 3px; padding: 4px 8px;"
    f"  font-weight: bold; font-size: 12px; font-family: 'Segoe UI'; }}"
    f"QPushButton:hover {{ background-color: #d32f2f; }}"
)

_BTN_GREEN_SM = (
    f"QPushButton {{ background-color: {_ACCENT}; color: white;"
    f"  border: none; border-radius: 2px; padding: 6px 14px;"
    f"  font-weight: bold; font-size: 12px; font-family: 'Segoe UI'; }}"
    f"QPushButton:hover {{ background-color: {_ACCENT_HOVER}; }}"
)

_LABEL_STYLE = f"color: {_TEXT}; font-size: 12px; font-family: 'Segoe UI'; background: transparent;"
_LABEL_DIM = f"color: {_TEXT}; font-size: 12px; font-weight: bold; font-family: 'Segoe UI'; background: transparent;"
_HEADER_LABEL = f"color: {_TEXT}; font-size: 12px; font-family: 'Segoe UI'; background: transparent; font-weight: bold;"

_GROUP_BOX = (
    f"QGroupBox {{"
    f"  color: {_TEXT}; font-weight: bold; font-size: 12px;"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  margin-top: 10px; padding-top: 14px;"
    f"}}"
    f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 6px; }}"
)


def _safe_float(text: str, default: float = 0.0) -> float:
    try:
        return float(text.strip()) if text.strip() else default
    except ValueError:
        return default


def _make_edit(placeholder: str = "", width: int | None = None) -> QLineEdit:
    e = QLineEdit()
    e.setPlaceholderText(placeholder)
    e.setStyleSheet(_EDIT_STYLE)
    from PySide6.QtGui import QFont
    e.setFont(QFont("Segoe UI", 12))
    if width:
        e.setMaximumWidth(width)
    return e


def _make_combo() -> QComboBox:
    c = QComboBox()
    c.setStyleSheet(_COMBO_STYLE)
    return c


def _make_date() -> QDateEdit:
    d = QDateEdit()
    d.setCalendarPopup(True)
    d.setStyleSheet(_DATE_STYLE)
    return d


# ======================================================================
# Customer Receipt Entry Dialog
# ======================================================================

class _CustomerReceiptEntryDialog(QDialog):
    """Modal dialog for creating / editing a customer receipt."""

    def __init__(self, parent: QWidget | None = None, *, receipt: dict | None = None):
        super().__init__(parent)
        self._receipt = receipt
        self._saved = False

        self.setWindowTitle("Customer Receipt Voucher")
        self.setMinimumWidth(700)
        self.setMinimumHeight(420)
        self.setModal(True)
        self.setStyleSheet(
            f"QDialog {{ background-color: {_DARK_BG}; }}"
            f"QLabel {{ {_LABEL_STYLE} }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # -- Balance display --
        self._build_balance(root)

        # -- Header group --
        self._build_header(root)

        # -- Button bar --
        btn_bar = QHBoxLayout()
        btn_bar.addStretch()

        save_btn = QPushButton("Save Receipt")
        save_btn.setStyleSheet(_BTN_SAVE)
        save_btn.clicked.connect(self._on_save)
        btn_bar.addWidget(save_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(_BTN_SECONDARY)
        cancel_btn.clicked.connect(self.reject)
        btn_bar.addWidget(cancel_btn)

        root.addLayout(btn_bar)

        self._set_voucher_no()
        self._set_current_datetime()

        if receipt:
            self._populate_receipt(receipt)

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    def _build_header(self, root_layout: QVBoxLayout):
        grp = QGroupBox("Receipt Details")
        grp.setStyleSheet(_GROUP_BOX)
        grid = QGridLayout(grp)
        grid.setSpacing(8)
        grid.setContentsMargins(12, 20, 12, 10)

        row = 0
        grid.addWidget(self._lbl("Voucher No"), row, 0)
        self.voucher_no_edit = _make_edit()
        self.voucher_no_edit.setReadOnly(True)
        grid.addWidget(self.voucher_no_edit, row, 1)

        grid.addWidget(self._lbl("Date *"), row, 2)
        self.receipt_date = _make_date()
        self.receipt_date.setMaximumWidth(140)
        grid.addWidget(self.receipt_date, row, 3)

        row = 1
        grid.addWidget(self._lbl("Time"), row, 0)
        self.receipt_time_edit = _make_edit()
        self.receipt_time_edit.setMaximumWidth(80)
        grid.addWidget(self.receipt_time_edit, row, 1)

        grid.addWidget(self._lbl("Receipt Mode *"), row, 2)
        self.receipt_mode_combo = _make_combo()
        self.receipt_mode_combo.addItems(["Cash", "Bank", "Cheque", "UPI"])
        self.receipt_mode_combo.setMaximumWidth(140)
        grid.addWidget(self.receipt_mode_combo, row, 3)

        row = 2
        grid.addWidget(self._lbl("Customer *"), row, 0)
        self.customer_combo = _make_combo()
        self.customer_combo.setMinimumWidth(250)
        self.customer_combo.currentIndexChanged.connect(self._on_customer_changed)
        grid.addWidget(self.customer_combo, row, 1)

        grid.addWidget(self._lbl("Amount *"), row, 2)
        self.amount_edit = _make_edit("0.00")
        self.amount_edit.setMaximumWidth(140)
        grid.addWidget(self.amount_edit, row, 3)

        row = 3
        grid.addWidget(self._lbl("Reference No"), row, 0)
        self.reference_no_edit = _make_edit("Cheque/UPI/Ref no")
        grid.addWidget(self.reference_no_edit, row, 1)

        grid.addWidget(self._lbl("Remarks"), row, 2)
        self.remarks_edit = _make_edit()
        grid.addWidget(self.remarks_edit, row, 3)

        root_layout.addWidget(grp)
        self._load_customers()

    def _build_balance(self, root_layout: QVBoxLayout):
        self._balance_widget = QWidget()
        bal_layout = QHBoxLayout(self._balance_widget)
        bal_layout.setContentsMargins(12, 0, 12, 0)
        bal_layout.setSpacing(8)

        lbl = QLabel("Customer Outstanding Balance:")
        lbl.setStyleSheet(_HEADER_LABEL)
        bal_layout.addWidget(lbl)

        self._balance_value = QLabel("Select a customer")
        self._balance_value.setStyleSheet(
            f"color: {_TEXT_DIM}; font-size: 13px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        bal_layout.addWidget(self._balance_value)
        bal_layout.addStretch()

        root_layout.addWidget(self._balance_widget)

    def _load_customers(self):
        customers = CustomerDAO.get_all()
        self.customer_combo.addItem("-- Select Customer --", None)
        for c in customers:
            self.customer_combo.addItem(c["customer_name"], c["id"])

    def _on_customer_changed(self, idx: int):
        cid = self.customer_combo.currentData()
        if cid is None:
            self._balance_value.setText("Select a customer")
            self._balance_value.setStyleSheet(
                f"color: {_TEXT_DIM}; font-size: 13px; font-weight: bold;"
                f"background: transparent; font-family: 'Segoe UI';"
            )
            return
        balance = CustomerReceiptDAO.get_customer_balance(cid)
        if balance == 0:
            self._balance_value.setText("No outstanding balance")
            self._balance_value.setStyleSheet(
                f"color: {_ACCENT}; font-size: 13px; font-weight: bold;"
                f"background: transparent; font-family: 'Segoe UI';"
            )
        else:
            self._balance_value.setText(f"{balance:,.2f}")
            self._balance_value.setStyleSheet(
                f"color: {_ERROR}; font-size: 13px; font-weight: bold;"
                f"background: transparent; font-family: 'Segoe UI';"
            )

    def _set_voucher_no(self):
        if not self._receipt:
            conn = None
            try:
                from database.connection import get_connection
                conn = get_connection()
                self.voucher_no_edit.setText(
                    CustomerReceiptDAO.generate_next_voucher_no(conn)
                )
            finally:
                if conn:
                    conn.close()

    def _set_current_datetime(self):
        from PySide6.QtCore import QDate
        now = datetime.now()
        qdate = QDate(now.year, now.month, now.day)
        self.receipt_date.setDate(qdate)
        self.receipt_time_edit.setText(now.strftime("%H:%M"))

    # ------------------------------------------------------------------
    # Populate for edit
    # ------------------------------------------------------------------

    def _populate_receipt(self, rec: dict):
        self.voucher_no_edit.setText(rec.get("voucher_no", ""))

        from PySide6.QtCore import QDate
        rd = rec.get("receipt_date", "")
        if rd:
            try:
                parts = rd.split("-")
                self.receipt_date.setDate(QDate(int(parts[0]), int(parts[1]), int(parts[2])))
            except Exception:
                pass

        self.receipt_time_edit.setText(rec.get("receipt_time", ""))

        idx = self.receipt_mode_combo.findText(rec.get("receipt_mode", "Cash"))
        if idx >= 0:
            self.receipt_mode_combo.setCurrentIndex(idx)

        cid = rec.get("customer_id")
        if cid:
            idx = self.customer_combo.findData(cid)
            if idx >= 0:
                self.customer_combo.setCurrentIndex(idx)

        self.amount_edit.setText(f"{rec.get('amount', 0.0):.2f}")
        self.reference_no_edit.setText(rec.get("reference_no", ""))
        self.remarks_edit.setText(rec.get("remarks", ""))

    @staticmethod
    def _lbl(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_HEADER_LABEL)
        return lbl

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _on_save(self):
        try:
            financial_year.validate_transaction_date(self.receipt_date.date().toString("yyyy-MM-dd"))
        except financial_year.FinancialYearError as exc:
            QMessageBox.warning(self, "Financial Year", str(exc)); return
        cid = self.customer_combo.currentData()
        if not cid:
            QMessageBox.warning(self, "Validation", "Customer is required.")
            return

        amount = _safe_float(self.amount_edit.text(), 0.0)
        if amount <= 0:
            QMessageBox.warning(self, "Validation", "Amount must be greater than 0.")
            return

        receipt_date = self.receipt_date.date().toString("yyyy-MM-dd")
        receipt_time = self.receipt_time_edit.text().strip()
        receipt_mode = self.receipt_mode_combo.currentText()
        reference_no = self.reference_no_edit.text().strip()
        remarks = self.remarks_edit.text().strip()

        header = {
            "receipt_date": receipt_date,
            "receipt_time": receipt_time,
            "customer_id": cid,
            "receipt_mode": receipt_mode,
            "amount": amount,
            "reference_no": reference_no,
            "remarks": remarks,
        }

        try:
            if self._receipt:
                CustomerReceiptDAO.update_receipt(self._receipt["id"], header)
            else:
                CustomerReceiptDAO.insert_receipt(header)
            self._saved = True
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save receipt:\n{e}")

    @property
    def was_saved(self) -> bool:
        return self._saved


# ======================================================================
# Customer Receipt PAGE
# ======================================================================

class CustomerReceiptPage(QWidget):
    """Customer Receipt screen with history list and entry dialog."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {_DARK_BG};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._stack = QStackedWidget()
        root.addWidget(self._stack)

        self._history_page = self._build_history_page()
        self._stack.addWidget(self._history_page)

        self._placeholder = QWidget()
        ph_layout = QVBoxLayout(self._placeholder)
        ph_layout.setAlignment(Qt.AlignCenter)
        lbl = QLabel("Customer receipt entry opens via dialog.")
        lbl.setStyleSheet(f"color: {_TEXT}; font-size: 16px; font-family: 'Segoe UI';")
        lbl.setAlignment(Qt.AlignCenter)
        ph_layout.addWidget(lbl)
        self._stack.addWidget(self._placeholder)

        self._refresh_history()

    # ------------------------------------------------------------------
    # History page
    # ------------------------------------------------------------------

    def _build_history_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QWidget()
        header.setFixedHeight(56)
        header.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)

        title = QLabel("Customer Receipt Voucher - History")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 18px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        hl.addWidget(title)
        hl.addStretch()

        new_btn = QPushButton("New Receipt")
        new_btn.setFixedWidth(130)
        new_btn.setStyleSheet(_BTN_SAVE)
        new_btn.clicked.connect(self._on_new)
        hl.addWidget(new_btn)

        edit_btn = QPushButton("Edit")
        edit_btn.setFixedWidth(90)
        edit_btn.setStyleSheet(_BTN_SECONDARY)
        edit_btn.clicked.connect(self._on_edit)
        hl.addWidget(edit_btn)

        print_btn = QPushButton("Print / PDF")
        print_btn.setFixedWidth(110)
        print_btn.setStyleSheet(_BTN_SECONDARY)
        print_btn.clicked.connect(self._on_print)
        hl.addWidget(print_btn)

        del_btn = QPushButton("Delete")
        del_btn.setFixedWidth(90)
        del_btn.setStyleSheet(_BTN_DANGER)
        del_btn.clicked.connect(self._on_delete)
        hl.addWidget(del_btn)

        layout.addWidget(header)

        # Filter bar
        filter_bar = QWidget()
        filter_bar.setFixedHeight(48)
        filter_bar.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        fl = QHBoxLayout(filter_bar)
        fl.setContentsMargins(16, 0, 16, 0)
        fl.setSpacing(8)

        fl.addWidget(self._flbl("From"))
        self._filter_from = _make_date()
        self._filter_from.setMaximumWidth(120)
        fl.addWidget(self._filter_from)

        fl.addWidget(self._flbl("To"))
        self._filter_to = _make_date()
        self._filter_to.setMaximumWidth(120)
        fl.addWidget(self._filter_to)

        fl.addWidget(self._flbl("Customer"))
        self._filter_customer = _make_combo()
        self._filter_customer.setMinimumWidth(160)
        self._filter_customer.addItem("All Customers", None)
        for c in CustomerDAO.get_all():
            self._filter_customer.addItem(c["customer_name"], c["id"])
        fl.addWidget(self._filter_customer)

        filter_btn = QPushButton("Filter")
        filter_btn.setFixedWidth(70)
        filter_btn.setStyleSheet(_BTN_GREEN_SM)
        filter_btn.clicked.connect(self._refresh_history)
        fl.addWidget(filter_btn)

        fl.addStretch()
        layout.addWidget(filter_bar)

        # History table
        self._hist_table = QTableWidget()
        self._hist_table.setColumnCount(7)
        self._hist_table.setHorizontalHeaderLabels([
            "Voucher No", "Date", "Time", "Customer",
            "Receipt Mode", "Amount", "Reference No"
        ])
        self._hist_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._hist_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._hist_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._hist_table.verticalHeader().setVisible(False)
        self._hist_table.setShowGrid(True)
        self._hist_table.setAlternatingRowColors(False)
        self._hist_table.setSortingEnabled(True)

        hv = self._hist_table.horizontalHeader()
        hv.setStretchLastSection(True)
        for col in range(7):
            if col == 3:
                hv.setSectionResizeMode(col, QHeaderView.Stretch)
            else:
                hv.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        hv.setStyleSheet(
            f"QHeaderView::section {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: none; border-bottom: 2px solid {_ACCENT};"
            f"  padding: 3px 6px; font-weight: bold; font-size: 12px;"
            f"  font-family: 'Segoe UI';"
            f"}}"
        )
        self._hist_table.setStyleSheet(
            f"QTableWidget {{"
            f"  background-color: {_DARK_BG}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; gridline-color: {_BORDER};"
            f"  font-size: 13px; font-family: 'Segoe UI';"
            f"  selection-background-color: {_ACCENT};"
            f"  selection-color: white;"
            f"}}"
            f"QTableWidget::item {{ padding: 2px 5px; }}"
        )
        layout.addWidget(self._hist_table, 1)

        return page

    def _flbl(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_LABEL_DIM)
        return lbl

    def _refresh_history(self):
        from_date = self._filter_from.date().toString("yyyy-MM-dd")
        to_date = self._filter_to.date().toString("yyyy-MM-dd")
        cust_id = self._filter_customer.currentData()

        receipts = CustomerReceiptDAO.get_all_filtered(
            date_from=from_date, date_to=to_date, customer_id=cust_id,
        )

        self._hist_table.setRowCount(len(receipts))
        for i, r in enumerate(receipts):
            self._hist_table.setItem(i, 0, QTableWidgetItem(r.get("voucher_no", "")))
            self._hist_table.setItem(i, 1, QTableWidgetItem(r.get("receipt_date", "")))
            self._hist_table.setItem(i, 2, QTableWidgetItem(r.get("receipt_time", "")))
            self._hist_table.setItem(i, 3, QTableWidgetItem(r.get("customer_name", "")))
            self._hist_table.setItem(i, 4, QTableWidgetItem(r.get("receipt_mode", "")))

            amt_item = QTableWidgetItem(f"{r.get('amount', 0.0):.2f}")
            amt_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._hist_table.setItem(i, 5, amt_item)

            self._hist_table.setItem(i, 6, QTableWidgetItem(r.get("reference_no", "")))

            self._hist_table.item(i, 0).setData(Qt.UserRole, r["id"])

    def _selected_id(self) -> int | None:
        rows = self._hist_table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        return self._hist_table.item(row, 0).data(Qt.UserRole)

    def _on_new(self):
        self._open_dialog()

    def _on_edit(self):
        try:
            auth.session.require(auth.PERM_EDIT_TRANSACTIONS)
        except auth.PermissionDenied as exc:
            QMessageBox.warning(self, "Permission denied", str(exc)); return
        rec_id = self._selected_id()
        if not rec_id:
            QMessageBox.information(self, "Edit Receipt", "Please select a receipt to edit.")
            return
        rec = CustomerReceiptDAO.get_by_id(rec_id)
        if not rec:
            QMessageBox.warning(self, "Edit Receipt", "Could not load receipt data.")
            return
        self._open_dialog(receipt=rec)

    def _on_print(self):
        receipt_id = self._selected_id()
        if not receipt_id:
            QMessageBox.information(self, "Print Receipt", "Please select a receipt to print.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Customer Receipt PDF", "customer_receipt.pdf", "PDF (*.pdf)")
        if not path:
            return
        try:
            output = generate_customer_receipt(receipt_id, path)
            QMessageBox.information(self, "PDF Saved", f"Customer receipt saved to:\n{output}")
        except DocumentPrintError as exc:
            QMessageBox.warning(self, "Print Receipt", str(exc))

    def _on_delete(self):
        try:
            auth.session.require(auth.PERM_DELETE_TRANSACTIONS)
        except auth.PermissionDenied as exc:
            QMessageBox.warning(self, "Permission denied", str(exc)); return
        rec_id = self._selected_id()
        if not rec_id:
            QMessageBox.information(self, "Delete Receipt", "Please select a receipt to delete.")
            return
        reply = QMessageBox.question(
            self, "Confirm Delete",
            "Are you sure you want to delete this customer receipt?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                CustomerReceiptDAO.delete_receipt(rec_id)
                self._refresh_history()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete receipt:\n{e}")

    def _open_dialog(self, receipt: dict | None = None):
        dlg = _CustomerReceiptEntryDialog(self, receipt=receipt)
        dlg.exec()
        if dlg.was_saved:
            self._refresh_history()
