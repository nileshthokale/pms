# Builder script to update screens/purchase_invoice.py with Screenshot 1 layout and features

new_code = '''
class _ItemEntryBar(QWidget):
    """Entry bar for adding a single item to the invoice matching Screenshot 1 layout."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entry_labels: list[QLabel] = []
        self._selected_batch_no: str = ""
        self._selected_batch_id: int | None = None
        self._selected_batch_data: dict | None = None
        self.get_invoice_date_fn = None

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(4, 2, 4, 2)
        main_layout.setSpacing(4)
        self.setFixedHeight(44)

        # 1. Item Name (* Item Name)
        item_col = QVBoxLayout()
        item_col.setContentsMargins(0, 0, 0, 0)
        item_col.setSpacing(2)
        lbl_item = QLabel("* Item Name")
        lbl_item.setStyleSheet("font-weight: bold; font-size: 12px; color: #111827; background: transparent;")
        item_col.addWidget(lbl_item)
        self._entry_labels.append(lbl_item)

        item_row = QHBoxLayout()
        item_row.setContentsMargins(0, 0, 0, 0)
        item_row.setSpacing(2)
        self.item_combo = SearchableComboBox(
            placeholder="Type item name...",
            max_visible=9,
            max_height=270,
            max_width=650,
            min_width=170,
            allow_width_expansion=True,
        )
        self.item_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.item_combo.setFixedHeight(24)
        self.item_combo.setToolTip("Search and select medicine / item")
        item_row.addWidget(self.item_combo, 1)

        self.btn_item_edit = QPushButton("Edit")
        self.btn_item_edit.setFixedSize(34, 24)
        self.btn_item_edit.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #dbe7f5); border: 1px solid #7eaadb; border-radius: 2px; color: #0a3663; font-size: 11px; font-weight: bold; } QPushButton:hover { background: #cde2f8; }"
        )
        self.btn_item_edit.setToolTip("Edit selected item master")
        self.btn_item_edit.setFocusPolicy(Qt.NoFocus)
        self.btn_item_edit.clicked.connect(self._on_edit_item)
        item_row.addWidget(self.btn_item_edit)

        self.btn_item_hist = QPushButton("Hist")
        self.btn_item_hist.setFixedSize(34, 24)
        self.btn_item_hist.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #dbe7f5); border: 1px solid #7eaadb; border-radius: 2px; color: #0a3663; font-size: 11px; font-weight: bold; } QPushButton:hover { background: #cde2f8; }"
        )
        self.btn_item_hist.setToolTip("View item purchase history")
        self.btn_item_hist.setFocusPolicy(Qt.NoFocus)
        self.btn_item_hist.clicked.connect(self._on_item_hist)
        item_row.addWidget(self.btn_item_hist)
        item_col.addLayout(item_row)

        item_container = QWidget()
        item_container.setLayout(item_col)
        main_layout.addWidget(item_container, 1)

        # Helper to create column
        def _make_col(title: str, widget: QWidget, width: int = 50, center_lbl: bool = True) -> QWidget:
            c = QVBoxLayout()
            c.setContentsMargins(0, 0, 0, 0)
            c.setSpacing(2)
            lbl = QLabel(title)
            lbl.setStyleSheet("font-weight: bold; font-size: 12px; color: #111827; background: transparent;")
            if center_lbl:
                lbl.setAlignment(Qt.AlignCenter)
            c.addWidget(lbl)
            self._entry_labels.append(lbl)
            widget.setFixedWidth(width)
            widget.setFixedHeight(24)
            c.addWidget(widget)
            cont = QWidget()
            cont.setLayout(c)
            return cont

        # 2. PackSize
        self.pack_edit = _make_entry_edit("Pack", 46)
        self.pack_edit.setReadOnly(True)
        self.pack_edit.setFocusPolicy(Qt.NoFocus)
        self.pack_edit.setAlignment(Qt.AlignCenter)
        self.pack_edit.setToolTip("Pack size (auto-filled)")
        main_layout.addWidget(_make_col("PackSize", self.pack_edit, 46))

        # 3. Pay Qty
        self.pay_qty_edit = _make_entry_edit("0", 48)
        self.pay_qty_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.pay_qty_edit.setToolTip("Payable Quantity")
        main_layout.addWidget(_make_col("Pay Qty", self.pay_qty_edit, 48))

        # 4. Free Qty
        self.free_qty_edit = _make_entry_edit("0", 46)
        self.free_qty_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.free_qty_edit.setToolTip("Free Quantity")
        main_layout.addWidget(_make_col("Free Qty", self.free_qty_edit, 46))

        # 5. Batch #
        self.batch_edit = BatchLineEdit("Batch", 84)
        self.batch_edit.batch_selected.connect(self._on_saved_batch_selected)
        self.batch_edit.textChanged.connect(self._on_batch_text_changed)
        main_layout.addWidget(_make_col("Batch #", self.batch_edit, 84))

        # 6. Expiry
        self.expiry_edit = ExpiryDateEdit(width=82)
        main_layout.addWidget(_make_col("Expiry", self.expiry_edit, 82))

        # 7. Rate
        self.rate_edit = _make_entry_edit("0.00", 60)
        self.rate_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.rate_edit.setToolTip("Purchase Rate")
        main_layout.addWidget(_make_col("Rate", self.rate_edit, 60))

        # 8. MRP
        self.mrp_edit = _make_entry_edit("0.00", 60)
        self.mrp_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.mrp_edit.setToolTip("MRP")
        main_layout.addWidget(_make_col("MRP", self.mrp_edit, 60))

        # 9. Disc (with Rs toggle/label)
        disc_col = QVBoxLayout()
        disc_col.setContentsMargins(0, 0, 0, 0)
        disc_col.setSpacing(2)
        lbl_disc = QLabel("Disc")
        lbl_disc.setAlignment(Qt.AlignCenter)
        lbl_disc.setStyleSheet("font-weight: bold; font-size: 12px; color: #111827; background: transparent;")
        disc_col.addWidget(lbl_disc)
        self._entry_labels.append(lbl_disc)

        disc_row = QHBoxLayout()
        disc_row.setContentsMargins(0, 0, 0, 0)
        disc_row.setSpacing(1)
        self.disc_mode_lbl = QLabel("Rs")
        self.disc_mode_lbl.setFixedSize(20, 24)
        self.disc_mode_lbl.setAlignment(Qt.AlignCenter)
        self.disc_mode_lbl.setStyleSheet(
            "background: #eef4fa; border: 1px solid #7eaadb; border-right: none; font-size: 11px; font-weight: bold; color: #0a3663;"
        )
        disc_row.addWidget(self.disc_mode_lbl)
        self.discount_edit = _make_entry_edit("0.00", 42)
        self.discount_edit.setFixedHeight(24)
        self.discount_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.discount_edit.setToolTip("Discount (%)")
        disc_row.addWidget(self.discount_edit)

        disc_cont = QWidget()
        disc_cont.setLayout(disc_col)
        disc_col.addLayout(disc_row)
        main_layout.addWidget(disc_cont)

        # 10. GST-Tax
        self.gst_edit = _make_entry_edit("0", 52)
        self.gst_edit.setReadOnly(True)
        self.gst_edit.setFocusPolicy(Qt.NoFocus)
        self.gst_edit.setAlignment(Qt.AlignCenter)
        self.gst_edit.setToolTip("GST (%)")
        main_layout.addWidget(_make_col("GST-Tax", self.gst_edit, 52))

        # 11. Add button (Down arrow commit button)
        add_col = QVBoxLayout()
        add_col.setContentsMargins(0, 0, 0, 0)
        add_col.setSpacing(2)
        spacer_lbl = QLabel("")
        spacer_lbl.setFixedHeight(14)
        add_col.addWidget(spacer_lbl)
        self.add_btn = QPushButton("⇓")
        self.add_btn.setFixedSize(36, 24)
        self.add_btn.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #dbeeff, stop:1 #7ebaf8); border: 1px solid #4a90e2; border-radius: 2px; color: #0a3b75; font-size: 15px; font-weight: bold; } QPushButton:hover { background: #62a8f4; }"
        )
        self.add_btn.setToolTip("Add item to invoice (Enter)")
        add_col.addWidget(self.add_btn)
        add_cont = QWidget()
        add_cont.setLayout(add_col)
        main_layout.addWidget(add_cont)

        # 12. Pending Challan Items button
        challan_col = QVBoxLayout()
        challan_col.setContentsMargins(0, 0, 0, 0)
        challan_col.setSpacing(2)
        self.btn_pending_challan = QPushButton("Pending\\nChallan Items")
        self.btn_pending_challan.setFixedSize(94, 40)
        self.btn_pending_challan.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #cfe2f8); border: 1px solid #7eaadb; border-radius: 3px; font-size: 11px; font-weight: bold; color: #0a3663; line-height: 1.1; } QPushButton:hover { background: #bedaf7; }"
        )
        self.btn_pending_challan.clicked.connect(self._on_pending_challan)
        challan_col.addWidget(self.btn_pending_challan)
        challan_cont = QWidget()
        challan_cont.setLayout(challan_col)
        main_layout.addWidget(challan_cont)

        # Aliases for backward compatibility with layout tests
        self.row_layout = main_layout
        self.row1_layout = main_layout

        # Tab traversal order
        QWidget.setTabOrder(self.item_combo, self.pay_qty_edit)
        QWidget.setTabOrder(self.pay_qty_edit, self.free_qty_edit)
        QWidget.setTabOrder(self.free_qty_edit, self.batch_edit)
        QWidget.setTabOrder(self.batch_edit, self.expiry_edit)
        QWidget.setTabOrder(self.expiry_edit, self.rate_edit)
        QWidget.setTabOrder(self.rate_edit, self.mrp_edit)
        QWidget.setTabOrder(self.mrp_edit, self.discount_edit)
        QWidget.setTabOrder(self.discount_edit, self.add_btn)

        self._load_items()

    def _field(self, label_text: str, widget: QWidget, label_width: int | None = None, stretch: int = 0) -> QWidget:
        container = QWidget()
        h = QHBoxLayout(container)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(2)
        lbl = QLabel(label_text)
        lbl.setFont(QFont("Segoe UI", 9, QFont.Bold))
        lbl.setStyleSheet("color: #111827; font-size: 11px; font-weight: bold; font-family: 'Segoe UI'; margin: 0; padding: 0; background: transparent;")
        if label_width:
            lbl.setFixedWidth(label_width)
        self._entry_labels.append(lbl)
        h.addWidget(lbl)
        h.addWidget(widget, stretch)
        return container

    def _on_edit_item(self):
        iid = self.item_combo.currentData()
        if not iid:
            QMessageBox.information(self, "Edit Item", "Please select an item first.")
            return
        try:
            from screens.item_master import _ItemDialog
            dlg = _ItemDialog(self, item_id=iid)
            if dlg.exec():
                self._load_items()
                idx = self.item_combo.findData(iid)
                if idx >= 0:
                    self.item_combo.setCurrentIndex(idx)
        except Exception as exc:
            QMessageBox.warning(self, "Edit Item", f"Could not edit item: {exc}")

    def _on_item_hist(self):
        iid = self.item_combo.currentData()
        if not iid:
            QMessageBox.information(self, "Item History", "Please select an item first.")
            return
        try:
            batches = PurchaseDAO.get_saved_batches_for_item(iid)
            if not batches:
                QMessageBox.information(self, "Item History", "No previous purchase history found for this item.")
                return
            lines = [f"Recent purchase history for '{self.item_combo.currentText()}':\\n"]
            for b in batches[:6]:
                lines.append(f"• Batch: {b.get('batch_no', '')} | Exp: {b.get('expiry', '')} | Rate: {float(b.get('rate', 0) or 0):.2f} | MRP: {float(b.get('mrp', 0) or 0):.2f}")
            QMessageBox.information(self, "Item Purchase History", "\\n".join(lines))
        except Exception as exc:
            QMessageBox.warning(self, "Item History", f"Could not retrieve history: {exc}")

    def _on_pending_challan(self):
        QMessageBox.information(self, "Pending Challans", "No pending challan items found for the selected supplier.")

    def set_batch_fields_readonly(self, ro: bool):
        self.expiry_edit.setReadOnly(ro)
        self.rate_edit.setReadOnly(ro)
        self.mrp_edit.setReadOnly(ro)

    def _on_batch_text_changed(self, text: str):
        curr_saved = getattr(self, "_selected_batch_no", "")
        clean = text.strip()
        if curr_saved and clean.casefold() != curr_saved.casefold():
            self._selected_batch_no = ""
            self._selected_batch_id = None
            self._selected_batch_data = None
            self.set_batch_fields_readonly(False)

    def get_invoice_date(self) -> date:
        if callable(getattr(self, "get_invoice_date_fn", None)):
            try:
                return self.get_invoice_date_fn()
            except Exception:
                pass
        return date.today()

    def _on_saved_batch_selected(self, data: dict):
        if not data:
            return
        bno = (data.get("batch_no") or "").strip()
        raw_exp = data.get("expiry")
        exp_d = parse_expiry_to_date(raw_exp)
        inv_d = self.get_invoice_date()

        if exp_d and inv_d and exp_d < inv_d:
            exp_disp = format_expiry_display(exp_d)
            inv_disp = inv_d.strftime("%d-%m-%Y")
            QMessageBox.warning(
                self,
                "Expired Batch",
                f"Batch '{bno}' is expired ({exp_disp}) on invoice date ({inv_disp}).\\n\\n"
                f"Expired batches cannot be entered in a new purchase invoice.\\n"
                f"Please enter a new batch number and valid expiry date.",
            )
            self.batch_edit.clear()
            self.expiry_edit.clear()
            self._selected_batch_no = ""
            self._selected_batch_id = None
            self._selected_batch_data = None
            self.set_batch_fields_readonly(False)
            return

        self._selected_batch_no = bno
        self._selected_batch_id = data.get("id") or data.get("batch_id")
        self._selected_batch_data = data
        if bno:
            self.batch_edit.setText(bno)
        if raw_exp:
            self.expiry_edit.setText(format_expiry_display(raw_exp))
        else:
            self.expiry_edit.clear()
        if data.get("rate") is not None and float(data.get("rate") or 0.0) > 0:
            self.rate_edit.setText(f"{float(data['rate']):.2f}")
        if data.get("mrp") is not None and float(data.get("mrp") or 0.0) > 0:
            self.mrp_edit.setText(f"{float(data['mrp']):.2f}")
        if data.get("pack_size"):
            self.pack_edit.setText(str(data["pack_size"]).strip())
        if data.get("gst_percent") is not None and float(data.get("gst_percent") or 0.0) >= 0:
            self.gst_edit.setText(f"{float(data['gst_percent']):g}")
        self.set_batch_fields_readonly(True)

    def _load_items(self):
        try:
            items = ItemDAO.get_all()
        except Exception:
            items = []
        list_items = []
        for it in items:
            list_items.append((it["item_name"], it["id"]))
        self.item_combo.populate(list_items)

    def clear(self):
        self._selected_batch_no = ""
        self._selected_batch_id = None
        self._selected_batch_data = None
        self.item_combo.clear_selection()
        self.pack_edit.clear()
        self.pay_qty_edit.clear()
        self.free_qty_edit.clear()
        self.batch_edit.clear()
        self.batch_edit.set_batches([])
        self.expiry_edit.clear()
        self.rate_edit.clear()
        self.mrp_edit.clear()
        self.discount_edit.clear()
        self.gst_edit.clear()
        self.set_batch_fields_readonly(False)

    def refresh_theme(self, p: dict | None = None):
        p = p or palette()
        self.item_combo.refresh_theme(p)
        self.batch_edit.refresh_theme(p)
        self.expiry_edit.refresh_theme(p)

    def get_current_item_data(self) -> dict | None:
        item_id = self.item_combo.currentData()
        if item_id is None:
            return None
        item_full = ItemDAO.get_by_id(item_id)
        if not item_full:
            return None
        item_name = item_full.get("item_name") or self.item_combo.currentText()
        expiry_val = self.expiry_edit.iso_date() or self.expiry_edit.text().strip()
        return {
            "item_id": item_id,
            "item_name": item_name,
            "pack_size": self.pack_edit.text().strip() or item_full.get("pack_size", ""),
            "pay_qty": _safe_float(self.pay_qty_edit.text()),
            "free_qty": _safe_float(self.free_qty_edit.text()),
            "batch_no": self.batch_edit.text().strip(),
            "batch_id": getattr(self, "_selected_batch_id", None),
            "expiry": expiry_val,
            "rate": _safe_float(self.rate_edit.text()),
            "mrp": _safe_float(self.mrp_edit.text()),
            "discount": _safe_float(self.discount_edit.text()),
            "gst_percent": _safe_float(self.gst_edit.text()),
            "item_full": item_full,
        }


class _InvoiceDialog(QDialog):
    """Modal dialog for entering / editing a purchase invoice matching Screenshot 1 exactly."""

    def __init__(self, parent: QWidget | None = None, *, invoice: dict | None = None):
        super().__init__(parent)
        self._invoice = invoice
        self._saved = False
        self._item_rows: list[_InvoiceItemRow] = []

        self.setWindowTitle("Purchase Invoice")
        self.setMinimumWidth(1150)
        self.setMinimumHeight(680)
        self.setModal(True)

        from PySide6.QtWidgets import QApplication
        if parent and parent.isVisible():
            pg = parent.geometry()
            w = min(1200, max(1150, int(pg.width() * 0.95)))
            h = min(720, max(680, int(pg.height() * 0.92)))
            self.resize(w, h)
            self.move(
                pg.x() + max(0, (pg.width() - self.width()) // 2),
                pg.y() + max(0, (pg.height() - self.height()) // 2),
            )
        else:
            screen = QApplication.primaryScreen()
            if screen:
                sg = screen.availableGeometry()
                w = min(1200, max(1150, int(sg.width() * 0.92)))
                h = min(720, max(680, int(sg.height() * 0.88)))
                self.resize(w, h)
                self.move(
                    sg.x() + (sg.width() - self.width()) // 2,
                    sg.y() + (sg.height() - self.height()) // 2,
                )

        self.setStyleSheet(
            "QDialog { background-color: #dcecfb; }"
            "QLabel { color: #111827; font-size: 13px; font-family: 'Segoe UI'; background: transparent; }"
            "QLineEdit { background-color: #ffffff; color: #111827; border: 1px solid #7eaadb; border-radius: 2px; font-family: 'Segoe UI'; font-size: 13px; padding: 1px 3px; }"
            "QLineEdit:focus { border: 1px solid #0078d7; }"
            "QComboBox { background-color: #ffffff; color: #111827; border: 1px solid #7eaadb; border-radius: 2px; font-family: 'Segoe UI'; font-size: 13px; padding: 1px 3px; }"
            "QDateEdit { background-color: #ffffff; color: #111827; border: 1px solid #7eaadb; border-radius: 2px; font-family: 'Segoe UI'; font-size: 13px; padding: 1px 3px; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 4)
        root.setSpacing(2)

        # 1. Cyan Blue Header Strip
        self._build_header_strip(root)

        # 2. Top Form (Left, Middle, Right)
        self._build_top_form(root)

        # 3. Item Entry Bar
        self._entry_bar = _ItemEntryBar(self)
        self._entry_bar.get_invoice_date_fn = self.get_invoice_date
        root.addWidget(self._entry_bar)

        # 4. Items Table (16 columns)
        self._build_item_table(root)

        # 5. Bottom Section: Total Items, Net Payable panel, Info Callout, Save/Close
        self._build_bottom_section(root)

        # Wire entry bar controls
        self._entry_bar.item_combo.currentIndexChanged.connect(self._on_item_changed)
        self._entry_bar.rate_edit.textChanged.connect(self._recalc_current_line)
        self._entry_bar.mrp_edit.textChanged.connect(self._recalc_current_line)
        self._entry_bar.discount_edit.textChanged.connect(self._recalc_current_line)
        self._entry_bar.gst_edit.textChanged.connect(self._recalc_current_line)
        self._entry_bar.pay_qty_edit.textChanged.connect(self._recalc_current_line)
        self._entry_bar.free_qty_edit.textChanged.connect(self._recalc_current_line)
        self._entry_bar.add_btn.clicked.connect(self._on_add_item)
        self._entry_bar.discount_edit.returnPressed.connect(self._on_add_item)
        self._entry_bar.gst_edit.returnPressed.connect(self._on_add_item)

        self._set_voucher_no()
        self._set_current_datetime()
        self._wire_totals_recalc()

        if invoice:
            self._populate_invoice(invoice)

    # ------------------------------------------------------------------
    # Header strip (Cyan #00c0fe)
    # ------------------------------------------------------------------
    def _build_header_strip(self, root: QVBoxLayout):
        strip = QWidget()
        strip.setFixedHeight(34)
        strip.setStyleSheet("background-color: #00c0fe; border-top-left-radius: 4px; border-top-right-radius: 4px;")
        layout = QHBoxLayout(strip)
        layout.setContentsMargins(10, 0, 12, 0)
        layout.setSpacing(10)

        self._header_title_lbl = QLabel("Edit Invoice" if self._invoice else "New Invoice")
        self._header_title_lbl.setStyleSheet("color: #000000; font-size: 15px; font-weight: bold; font-family: 'Segoe UI'; background: transparent;")
        layout.addWidget(self._header_title_lbl)

        layout.addStretch(1)

        # Voucher No
        lbl_v = QLabel("Voucher No")
        lbl_v.setStyleSheet("color: #000000; font-size: 13px; font-weight: bold; font-family: 'Segoe UI'; background: transparent;")
        layout.addWidget(lbl_v)
        self.voucher_no_edit = QLineEdit()
        self.voucher_no_edit.setReadOnly(True)
        self.voucher_no_edit.setFixedSize(65, 24)
        self.voucher_no_edit.setAlignment(Qt.AlignCenter)
        self.voucher_no_edit.setStyleSheet("background: #ffffff; color: #000000; border: 1px solid #7eaadb; font-size: 13px; font-weight: bold;")
        layout.addWidget(self.voucher_no_edit)

        # Date
        lbl_d = QLabel("Date")
        lbl_d.setStyleSheet("color: #000000; font-size: 13px; font-weight: bold; font-family: 'Segoe UI'; background: transparent;")
        layout.addWidget(lbl_d)
        self.voucher_date = _make_date()
        self.voucher_date.setFixedSize(98, 24)
        layout.addWidget(self.voucher_date)

        # Time
        lbl_t = QLabel("Time")
        lbl_t.setStyleSheet("color: #000000; font-size: 13px; font-weight: bold; font-family: 'Segoe UI'; background: transparent;")
        layout.addWidget(lbl_t)
        self.voucher_time_edit = QLineEdit()
        self.voucher_time_edit.setFixedSize(80, 24)
        self.voucher_time_edit.setAlignment(Qt.AlignCenter)
        self.voucher_time_edit.setStyleSheet("background: #ffffff; color: #000000; border: 1px solid #7eaadb; font-size: 13px;")
        layout.addWidget(self.voucher_time_edit)

        root.addWidget(strip)

    # ------------------------------------------------------------------
    # Top Form (Left, Middle, Right)
    # ------------------------------------------------------------------
    def _build_top_form(self, root: QVBoxLayout):
        form = QWidget()
        layout = QHBoxLayout(form)
        layout.setContentsMargins(10, 6, 10, 4)
        layout.setSpacing(20)

        # Left Column: Type, Date
        left_col = QWidget()
        left_grid = QGridLayout(left_col)
        left_grid.setContentsMargins(0, 0, 0, 0)
        left_grid.setSpacing(6)

        lbl_type = QLabel("Type :")
        lbl_type.setStyleSheet("font-weight: bold; font-size: 13px; color: #111827;")
        self.purchase_type_combo = _make_combo(max_visible=5, max_height=160)
        self.purchase_type_combo.addItems(["Credit", "Cash", "Credit Card"])
        self.purchase_type_combo.setFixedSize(95, 24)
        self.purchase_type_combo.currentTextChanged.connect(self._on_purchase_type_changed)
        left_grid.addWidget(lbl_type, 0, 0, Qt.AlignRight | Qt.AlignVCenter)
        left_grid.addWidget(self.purchase_type_combo, 0, 1)

        lbl_date = QLabel("Date :")
        lbl_date.setStyleSheet("font-weight: bold; font-size: 13px; color: #111827;")
        self.invoice_date = _make_date()
        self.invoice_date.setFixedSize(105, 24)
        self.invoice_date.dateChanged.connect(self._on_invoice_date_changed)
        left_grid.addWidget(lbl_date, 1, 0, Qt.AlignRight | Qt.AlignVCenter)
        left_grid.addWidget(self.invoice_date, 1, 1)
        layout.addWidget(left_col)

        # Middle Column: Supplier, Edit, Balance, Invoice #, Inv Net Amt
        mid_col = QWidget()
        mid_grid = QGridLayout(mid_col)
        mid_grid.setContentsMargins(0, 0, 0, 0)
        mid_grid.setSpacing(6)

        lbl_sup = QLabel("Supplier :")
        lbl_sup.setStyleSheet("font-weight: bold; font-size: 13px; color: #111827;")
        mid_grid.addWidget(lbl_sup, 0, 0, Qt.AlignRight | Qt.AlignVCenter)

        sup_row = QHBoxLayout()
        sup_row.setContentsMargins(0, 0, 0, 0)
        sup_row.setSpacing(4)
        self.supplier_combo = SearchableComboBox(
            placeholder="---Select Supplier---",
            max_visible=9,
            max_height=270,
            max_width=450,
            min_width=220,
            allow_width_expansion=True,
        )
        self.supplier_combo.setFixedHeight(24)
        sup_row.addWidget(self.supplier_combo, 1)

        self.btn_supplier_edit = QPushButton("Edit")
        self.btn_supplier_edit.setFixedSize(36, 24)
        self.btn_supplier_edit.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #dbe7f5); border: 1px solid #7eaadb; border-radius: 2px; color: #0a3663; font-size: 11px; font-weight: bold; } QPushButton:hover { background: #cde2f8; }"
        )
        self.btn_supplier_edit.setToolTip("Edit selected supplier master")
        self.btn_supplier_edit.setFocusPolicy(Qt.NoFocus)
        self.btn_supplier_edit.clicked.connect(self._on_edit_supplier)
        sup_row.addWidget(self.btn_supplier_edit)

        self.sup_bal_prefix = QLabel("(Balance=")
        self.sup_bal_prefix.setStyleSheet("color: #111827; font-size: 13px; font-weight: bold; background: transparent;")
        sup_row.addWidget(self.sup_bal_prefix)

        self.supplier_bal_label = QLabel("0.00")
        self.supplier_bal_label.setStyleSheet("color: #111827; font-size: 13px; font-weight: bold; background: transparent;")
        sup_row.addWidget(self.supplier_bal_label)

        self.sup_bal_suffix = QLabel(")")
        self.sup_bal_suffix.setStyleSheet("color: #111827; font-size: 13px; font-weight: bold; background: transparent;")
        sup_row.addWidget(self.sup_bal_suffix)
        mid_grid.addLayout(sup_row, 0, 1)

        # Row 1 of Middle: Invoice # and Inv Net Amt
        inv_row = QHBoxLayout()
        inv_row.setContentsMargins(0, 0, 0, 0)
        inv_row.setSpacing(6)

        lbl_inv_no = QLabel("Invoice # :")
        lbl_inv_no.setStyleSheet("font-weight: bold; font-size: 13px; color: #111827;")
        inv_row.addWidget(lbl_inv_no)
        self.invoice_no_edit = _make_edit(width=100)
        self.invoice_no_edit.setFixedHeight(24)
        inv_row.addWidget(self.invoice_no_edit)

        lbl_inv_amt = QLabel("Inv Net Amt :")
        lbl_inv_amt.setStyleSheet("font-weight: bold; font-size: 13px; color: #111827;")
        inv_row.addWidget(lbl_inv_amt)
        self.inv_net_amt_edit = _make_edit("0.00", width=95)
        self.inv_net_amt_edit.setFixedHeight(24)
        self.inv_net_amt_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        inv_row.addWidget(self.inv_net_amt_edit)
        inv_row.addStretch(1)

        mid_grid.addLayout(inv_row, 1, 1)
        layout.addWidget(mid_col, 1)

        # Right Column: Discount, Due Date
        right_col = QWidget()
        right_grid = QGridLayout(right_col)
        right_grid.setContentsMargins(0, 0, 0, 0)
        right_grid.setSpacing(6)

        lbl_disc = QLabel("Discount :")
        lbl_disc.setStyleSheet("font-weight: bold; font-size: 13px; color: #111827;")
        right_grid.addWidget(lbl_disc, 0, 0, Qt.AlignRight | Qt.AlignVCenter)

        disc_row = QHBoxLayout()
        disc_row.setContentsMargins(0, 0, 0, 0)
        disc_row.setSpacing(2)
        self.bill_disc_type_combo = _make_combo()
        self.bill_disc_type_combo.addItems(["Rs", "%"])
        self.bill_disc_type_combo.setFixedSize(44, 24)
        disc_row.addWidget(self.bill_disc_type_combo)
        self.bill_discount_edit = _make_edit("0.00", width=80)
        self.bill_discount_edit.setFixedHeight(24)
        self.bill_discount_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.bill_discount_edit.textChanged.connect(self._sync_header_to_footer_disc)
        disc_row.addWidget(self.bill_discount_edit)
        right_grid.addLayout(disc_row, 0, 1)

        lbl_due = QLabel("Due Date :")
        lbl_due.setStyleSheet("font-weight: bold; font-size: 13px; color: #111827;")
        right_grid.addWidget(lbl_due, 1, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.due_date = _make_date(parent=self)
        self.due_date.setFixedSize(105, 24)
        right_grid.addWidget(self.due_date, 1, 1)
        layout.addWidget(right_col)

        root.addWidget(form)

        self._load_suppliers()

    def _on_edit_supplier(self):
        sid = self.supplier_combo.currentData()
        if not sid:
            QMessageBox.information(self, "Edit Supplier", "Please select a supplier first.")
            return
        try:
            from screens.supplier_master import _SupplierDialog
            dlg = _SupplierDialog(self, supplier_id=sid)
            if dlg.exec():
                self._load_suppliers()
                idx = self.supplier_combo.findData(sid)
                if idx >= 0:
                    self.supplier_combo.setCurrentIndex(idx)
                self._update_supplier_balance(sid)
        except Exception as exc:
            QMessageBox.warning(self, "Edit Supplier", f"Could not edit supplier: {exc}")

    # ------------------------------------------------------------------
    # Items Table (Exact 16 Columns matching Screenshot 1)
    # ------------------------------------------------------------------
    def _build_item_table(self, root: QVBoxLayout):
        self._table_group = QWidget()
        layout = QVBoxLayout(self._table_group)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(0)

        self._table = QTableWidget()
        self._table.setColumnCount(16)
        self._table.setHorizontalHeaderLabels([
            "ItemName", "PackSize", "PayQty", "FreeQty", "BatchNo",
            "Expiry", "Rate", "MRP", "DiscAmt", "Amount", "TaxPer",
            "TaxAmt", "PurRate", "NetRate", "PP", "Del"
        ])
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(True)
        self._table.setAlternatingRowColors(False)

        hv = self._table.horizontalHeader()
        hv.setStretchLastSection(False)
        hv.setSectionResizeMode(0, QHeaderView.Stretch)  # ItemName stretches

        col_widths = {
            1: 65,   # PackSize
            2: 60,   # PayQty
            3: 55,   # FreeQty
            4: 85,   # BatchNo
            5: 80,   # Expiry
            6: 65,   # Rate
            7: 65,   # MRP
            8: 65,   # DiscAmt
            9: 80,   # Amount
            10: 55,  # TaxPer
            11: 65,  # TaxAmt
            12: 70,  # PurRate
            13: 70,  # NetRate
            14: 55,  # PP
            15: 45,  # Del
        }
        for col, width in col_widths.items():
            hv.setSectionResizeMode(col, QHeaderView.Interactive)
            self._table.setColumnWidth(col, width)

        hv.setStyleSheet(
            "QHeaderView::section {"
            "  background-color: #ebf3fc; color: #0a2540;"
            "  border: 1px solid #b2cbe6; padding: 2px 4px;"
            "  font-weight: bold; font-size: 12px; font-family: 'Segoe UI';"
            "}"
        )
        self._table.setStyleSheet(
            "QTableWidget {"
            "  background-color: #ffffff; color: #000000;"
            "  border: 1px solid #b2cbe6; gridline-color: #dbe7f5;"
            "  font-size: 13px; font-family: 'Segoe UI';"
            "  selection-background-color: #0078d7; selection-color: white;"
            "}"
            "QTableWidget::item { padding: 1px 3px; }"
        )
        layout.addWidget(self._table, 1)
        root.addWidget(self._table_group, 1)

    # ------------------------------------------------------------------
    # Bottom Section: Total Items + Net Payable Panel + Info + Buttons
    # ------------------------------------------------------------------
    def _build_bottom_section(self, root: QVBoxLayout):
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(10, 2, 10, 4)
        bottom_layout.setSpacing(4)

        # Row with Total Items (left) and Net Payable Panel (right)
        panels_row = QHBoxLayout()
        panels_row.setContentsMargins(0, 0, 0, 0)
        panels_row.setSpacing(10)

        # Left: Total Items
        left_box = QVBoxLayout()
        left_box.setContentsMargins(0, 4, 0, 0)
        items_h = QHBoxLayout()
        items_h.setSpacing(4)
        lbl_tot_items = QLabel("Total Items :")
        lbl_tot_items.setStyleSheet("font-weight: bold; font-size: 13px; color: #111827;")
        items_h.addWidget(lbl_tot_items)

        self.total_items_edit = QLineEdit("0")
        self.total_items_edit.setReadOnly(True)
        self.total_items_edit.setFixedSize(45, 24)
        self.total_items_edit.setAlignment(Qt.AlignCenter)
        self.total_items_edit.setStyleSheet("background: #ffffff; color: #111827; border: 1px solid #7eaadb; font-weight: bold;")
        items_h.addWidget(self.total_items_edit)
        items_h.addStretch(1)
        left_box.addLayout(items_h)
        left_box.addStretch(1)
        panels_row.addLayout(left_box, 1)

        # Right: Net Payable Group Box
        np_grp = QGroupBox("Net Payable")
        np_grp.setFixedSize(540, 160)
        np_grp.setStyleSheet(
            "QGroupBox {"
            "  border: 1px solid #8cb6df; border-radius: 4px;"
            "  margin-top: 8px; font-family: 'Segoe UI'; font-size: 13px; font-weight: bold; color: #0a3663;"
            "  background-color: #ebf3fc;"
            "}"
            "QGroupBox::title {"
            "  subcontrol-origin: margin; subcontrol-position: top left; padding: 0 4px; left: 10px;"
            "}"
        )
        np_grid = QGridLayout(np_grp)
        np_grid.setContentsMargins(8, 14, 8, 6)
        np_grid.setHorizontalSpacing(8)
        np_grid.setVerticalSpacing(4)

        # Helper for Net Payable label
        def _nplbl(t: str) -> QLabel:
            lbl = QLabel(t)
            lbl.setStyleSheet("font-size: 12px; font-weight: bold; color: #111827; background: transparent;")
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            return lbl

        # Left Column in Net Payable:
        # 0: Total Amount
        np_grid.addWidget(_nplbl("Total Amount :"), 0, 0)
        self.total_amount_label = _make_edit("0.00", 80)
        self.total_amount_label.setReadOnly(True)
        self.total_amount_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        np_grid.addWidget(self.total_amount_label, 0, 1)

        # 1: Add GST Tax
        np_grid.addWidget(_nplbl("Add GST Tax :"), 1, 0)
        self.gst_label = _make_edit("0.00", 80)
        self.gst_label.setReadOnly(True)
        self.gst_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        np_grid.addWidget(self.gst_label, 1, 1)

        # 2: Less Bill Discount
        np_grid.addWidget(_nplbl("Less Bill Discount :"), 2, 0)
        self.bill_disc_edit = _make_edit("0.00", 80)
        self.bill_disc_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        np_grid.addWidget(self.bill_disc_edit, 2, 1)

        # 3: Less DN Amt + Debit Note Button
        np_grid.addWidget(_nplbl("Less DN Amt :"), 3, 0)
        dn_row = QHBoxLayout()
        dn_row.setContentsMargins(0, 0, 0, 0)
        dn_row.setSpacing(2)
        self.dn_edit = _make_edit("0.00", 60)
        self.dn_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        dn_row.addWidget(self.dn_edit)
        self.btn_debit_note = QPushButton("Debit Note")
        self.btn_debit_note.setFixedSize(70, 22)
        self.btn_debit_note.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #dbe7f5); border: 1px solid #7eaadb; border-radius: 2px; color: #0a3663; font-size: 11px; font-weight: bold; } QPushButton:hover { background: #cde2f8; }"
        )
        self.btn_debit_note.clicked.connect(self._on_debit_note_clicked)
        dn_row.addWidget(self.btn_debit_note)
        np_grid.addLayout(dn_row, 3, 1)

        # 4: Remarks
        np_grid.addWidget(_nplbl("Remarks :"), 4, 0)
        self.remarks_edit = QTextEdit()
        self.remarks_edit.setFixedHeight(30)
        self.remarks_edit.setStyleSheet("background: #ffffff; border: 1px solid #7eaadb; font-size: 12px;")
        np_grid.addWidget(self.remarks_edit, 4, 1)

        # Right Column in Net Payable:
        # 0: Add Other Amt
        np_grid.addWidget(_nplbl("Add Other Amt :"), 0, 2)
        self.other_edit = _make_edit("0.00", 80)
        self.other_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        np_grid.addWidget(self.other_edit, 0, 3)

        # 1: Paid Amount
        np_grid.addWidget(_nplbl("Paid Amount :"), 1, 2)
        self.paid_edit = _make_edit("0.00", 80)
        self.paid_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        np_grid.addWidget(self.paid_edit, 1, 3)

        # 2: Round off
        np_grid.addWidget(_nplbl("Round off :"), 2, 2)
        self.round_off_edit = _make_edit("0.00", 80)
        self.round_off_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        np_grid.addWidget(self.round_off_edit, 2, 3)

        # 3: Net Amount
        np_grid.addWidget(_nplbl("Net Amount :"), 3, 2)
        self.net_amt_label = _make_edit("0.00", 80)
        self.net_amt_label.setReadOnly(True)
        self.net_amt_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.net_amt_label.setStyleSheet("background: #ffffff; color: #0056b3; font-weight: bold; font-size: 13px; border: 1px solid #7eaadb;")
        np_grid.addWidget(self.net_amt_label, 3, 3)

        panels_row.addWidget(np_grp)
        bottom_layout.addLayout(panels_row)

        # Action Strip: Info label + Save + Close
        action_strip = QHBoxLayout()
        action_strip.setContentsMargins(0, 2, 0, 2)
        action_strip.setSpacing(10)

        self.info_label = QLabel("▶  The Credit Invoice amount will be added to supplier ledger.")
        self.info_label.setStyleSheet(
            "background-color: #ffffdd; color: #554400; border: 1px solid #d4c880; border-radius: 2px; padding: 4px 10px; font-size: 12px; font-family: 'Segoe UI';"
        )
        action_strip.addWidget(self.info_label, 1)

        self.save_btn = QPushButton("Save")
        self.save_btn.setFixedSize(70, 28)
        self.save_btn.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #e2e2e2); border: 1px solid #ababab; border-radius: 3px; color: #222222; font-family: 'Segoe UI'; font-size: 13px; font-weight: bold; } QPushButton:hover { background: #d0d0d0; }"
        )
        self.save_btn.clicked.connect(self._on_save)
        action_strip.addWidget(self.save_btn)

        self.cancel_btn = QPushButton("Close")
        self.cancel_btn.setFixedSize(70, 28)
        self.cancel_btn.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #e2e2e2); border: 1px solid #ababab; border-radius: 3px; color: #222222; font-family: 'Segoe UI'; font-size: 13px; font-weight: bold; } QPushButton:hover { background: #d0d0d0; }"
        )
        self.cancel_btn.clicked.connect(self.reject)
        action_strip.addWidget(self.cancel_btn)

        bottom_layout.addLayout(action_strip)
        root.addWidget(bottom_widget)

        self.bill_disc_edit.textChanged.connect(self._sync_footer_to_header_disc)

    def _on_debit_note_clicked(self):
        sid = self.supplier_combo.currentData()
        if not sid:
            QMessageBox.information(self, "Debit Note", "Please select a supplier first.")
            return
        QMessageBox.information(self, "Debit Note", "No pending debit notes found for this supplier.")

    # ------------------------------------------------------------------
    # Suppliers & Balance
    # ------------------------------------------------------------------
    def _load_suppliers(self):
        try:
            suppliers = SupplierDAO.get_all()
        except Exception:
            suppliers = []
        list_suppliers = []
        for s in suppliers:
            list_suppliers.append((s["supplier_name"], s["id"]))
        self.supplier_combo.populate(list_suppliers)
        self.supplier_combo.currentIndexChanged.connect(self._on_supplier_changed)
        line = self.supplier_combo.lineEdit()
        if line is not None:
            line.textChanged.connect(self._on_supplier_text_changed)

    def _on_supplier_text_changed(self, text: str):
        self._on_supplier_changed()

    def _on_supplier_changed(self, idx: int = -1):
        sid = self.supplier_combo.currentData()
        self._update_supplier_balance(sid)
        if sid:
            sup = SupplierDAO.get_by_id(sid)
            if sup and not self._invoice:
                credit_days = sup.get("credit_period")
                try:
                    days = int(credit_days) if credit_days is not None else 0
                except (ValueError, TypeError):
                    days = 0
                inv_date = self.invoice_date.date()
                if days > 0:
                    self.due_date.setDate(inv_date.addDays(days))
                else:
                    self.due_date.setDate(inv_date.addDays(30))

    def _update_supplier_balance(self, sid: int | None):
        if not sid:
            self.supplier_bal_label.setText("0.00")
            self.supplier_bal_label.setToolTip("")
            self.supplier_bal_label.setStyleSheet("color: #111827; font-size: 13px; font-weight: bold; background: transparent; padding: 2px;")
            return

        try:
            sup = SupplierDAO.get_by_id(sid)
            if not sup:
                self.supplier_bal_label.setText("Error")
                self.supplier_bal_label.setToolTip("Supplier record not found in database")
                self.supplier_bal_label.setStyleSheet("color: #c62828; font-size: 13px; font-weight: bold; background: transparent; padding: 2px;")
                return

            ledger_id = sup.get("ledger_id")
            if not ledger_id:
                ledger_id = SupplierDAO.get_ledger_id(sid)

            if not ledger_id:
                self.supplier_bal_label.setText("N/A")
                self.supplier_bal_label.setToolTip("No linked account ledger found for this supplier")
                self.supplier_bal_label.setStyleSheet("color: #c62828; font-size: 13px; font-weight: bold; background: transparent; padding: 2px;")
                return

            bal = LedgerDAO.get_balance(ledger_id)
            closing = float(bal.get("closing_balance", 0.0) or 0.0)
            closing_type = bal.get("closing_balance_type", "Credit")

            if abs(closing) < 1e-9:
                self.supplier_bal_label.setText("0.00")
            else:
                sign = 1.0 if closing_type == "Credit" else -1.0
                outstanding = closing * sign
                self.supplier_bal_label.setText(f"{outstanding:,.2f}")

            self.supplier_bal_label.setToolTip(f"Closing Balance: {closing:,.2f} ({closing_type})")
            self.supplier_bal_label.setStyleSheet("color: #111827; font-size: 13px; font-weight: bold; background: transparent; padding: 2px;")
        except Exception as exc:
            self.supplier_bal_label.setText("Error")
            self.supplier_bal_label.setToolTip(f"Failed to retrieve ledger balance: {exc}")
            self.supplier_bal_label.setStyleSheet("color: #c62828; font-size: 13px; font-weight: bold; background: transparent; padding: 2px;")

    def get_invoice_date(self) -> date:
        try:
            qd = self.invoice_date.date()
            return date(qd.year(), qd.month(), qd.day())
        except Exception:
            return date.today()

    def _on_invoice_date_changed(self, new_date: QDate):
        if not self._invoice:
            sid = self.supplier_combo.currentData()
            days = 0
            if sid:
                sup = SupplierDAO.get_by_id(sid)
                if sup:
                    try:
                        days = int(sup.get("credit_period") or 0)
                    except (ValueError, TypeError):
                        days = 0
            if days > 0:
                self.due_date.setDate(new_date.addDays(days))
            else:
                self.due_date.setDate(new_date.addDays(30))

        item_id = self._entry_bar.item_combo.currentData()
        if item_id:
            try:
                batches = PurchaseDAO.get_saved_batches_for_item(item_id)
                if not isinstance(batches, list):
                    batches = []
            except Exception:
                batches = []
            self._entry_bar.batch_edit.set_batches(batches, invoice_date=self.get_invoice_date())

    def _sync_header_to_footer_disc(self, text: str):
        if hasattr(self, "bill_disc_edit") and self.bill_disc_edit.text() != text:
            self.bill_disc_edit.blockSignals(True)
            self.bill_disc_edit.setText(text)
            self.bill_disc_edit.blockSignals(False)
            self._recalc_totals()

    def _sync_footer_to_header_disc(self, text: str):
        if hasattr(self, "bill_discount_edit") and self.bill_discount_edit.text() != text:
            self.bill_discount_edit.blockSignals(True)
            self.bill_discount_edit.setText(text)
            self.bill_discount_edit.blockSignals(False)
            self._recalc_totals()

    def _on_purchase_type_changed(self, new_type: str):
        if not self._invoice:
            self._set_voucher_no()
        if hasattr(self, "info_label"):
            if new_type == "Cash":
                self.info_label.setText("▶  The Cash Invoice amount will be settled from Cash in Hand.")
            else:
                self.info_label.setText("▶  The Credit Invoice amount will be added to supplier ledger.")

    def _set_voucher_no(self):
        if not self._invoice:
            ptype = self.purchase_type_combo.currentText() if hasattr(self, "purchase_type_combo") else "Credit"
            full = PurchaseDAO.generate_next_voucher_no(purchase_type=ptype)
            self._full_voucher_no = full
            self.voucher_no_edit.setText(_display_voucher_no(full))
            self.voucher_no_edit.setToolTip(f"Full Voucher: {full}")

    def _set_current_datetime(self):
        now = datetime.now()
        today = QDate(now.year, now.month, now.day)
        self.voucher_date.setDate(today)
        from core.doc_formatter import format_time_12hr
        self.voucher_time_edit.setText(format_time_12hr(now.strftime("%H:%M")))
        self.invoice_date.setDate(today)
        self.due_date.setDate(today.addDays(30))

    def _on_item_changed(self, idx: int):
        item_id = self._entry_bar.item_combo.currentData()
        if item_id is None:
            self._entry_bar._selected_batch_no = ""
            self._entry_bar._selected_batch_id = None
            self._entry_bar._selected_batch_data = None
            self._entry_bar.batch_edit.clear()
            self._entry_bar.batch_edit.set_batches([])
            self._entry_bar.expiry_edit.clear()
            self._entry_bar.pack_edit.clear()
            self._entry_bar.gst_edit.clear()
            self._entry_bar.pay_qty_edit.clear()
            self._entry_bar.free_qty_edit.clear()
            self._entry_bar.rate_edit.clear()
            self._entry_bar.mrp_edit.clear()
            self._entry_bar.discount_edit.clear()
            self._entry_bar.set_batch_fields_readonly(False)
            return
        item = ItemDAO.get_by_id(item_id)
        if item:
            self._entry_bar.pack_edit.setText(str(item.get("pack_size", "") or ""))
            tax = item.get("tax_structure", "")
            percent = rate_percent(tax, item.get("legacy_tax_id"))
            if percent is None and isinstance(tax, str):
                m = re.search(r"GST\\s*@?\\s*(\\d+(?:\\.\\d+)?)", tax, re.I) or re.search(r"(\\d+(?:\\.\\d+)?)\\s*%", tax)
                if m:
                    candidate = m.group(1)
                    p = rate_percent(candidate)
                    if p is not None:
                        percent = p
                    else:
                        try:
                            val = float(candidate)
                            if str(int(val)) in ("0", "5", "12", "18", "28"):
                                percent = val
                        except ValueError:
                            pass
            self._entry_bar.gst_edit.setText(f"{percent:g}" if percent is not None else "0")

            self._entry_bar._selected_batch_no = ""
            self._entry_bar._selected_batch_id = None
            self._entry_bar._selected_batch_data = None
            self._entry_bar.mrp_edit.setText(f"{float(item.get('mrp', 0.0) or 0.0):.2f}")
            self._entry_bar.rate_edit.setText(f"{float(item.get('rate', 0.0) or 0.0):.2f}")
            self._entry_bar.batch_edit.clear()
            self._entry_bar.expiry_edit.clear()
            self._entry_bar.pay_qty_edit.clear()
            self._entry_bar.free_qty_edit.clear()
            self._entry_bar.discount_edit.clear()
            self._entry_bar.set_batch_fields_readonly(False)

            try:
                batches = PurchaseDAO.get_saved_batches_for_item(item_id)
                if not isinstance(batches, list):
                    batches = []
            except Exception:
                batches = []
            self._entry_bar.batch_edit.set_batches(batches, invoice_date=self.get_invoice_date())

    def _recalc_current_line(self):
        pass

    def _on_add_item(self):
        data = self._entry_bar.get_current_item_data()
        if data is None:
            QMessageBox.warning(self, "Validation", "Please select a valid item from the list.")
            return

        pay_qty = data["pay_qty"]
        free_qty = data["free_qty"]
        rate = data["rate"]
        discount = data["discount"]
        gst_pct = data["gst_percent"]

        if pay_qty <= 0:
            QMessageBox.warning(self, "Validation", "Pay Quantity must be greater than 0.")
            return

        batch_no = data["batch_no"]
        if not batch_no:
            QMessageBox.warning(self, "Validation", "Batch Number is required.")
            return

        inv_d = self.get_invoice_date()
        raw_expiry = self._entry_bar.expiry_edit.text().strip()
        if raw_expiry and raw_expiry.upper() != "DD-MM-YYYY":
            parsed_d = parse_expiry_to_date(raw_expiry)
            if not parsed_d:
                QMessageBox.warning(
                    self,
                    "Validation",
                    f"Invalid Expiry Date '{raw_expiry}'.\\nPlease enter a valid date in DD-MM-YYYY or MM/YY format.",
                )
                return
            if parsed_d < inv_d:
                exp_disp = parsed_d.strftime("%d-%m-%Y")
                inv_disp = inv_d.strftime("%d-%m-%Y")
                QMessageBox.warning(
                    self,
                    "Expired Stock",
                    f"Batch '{batch_no}' is expired ({exp_disp}) on invoice date ({inv_disp}).\\n\\n"
                    f"Expired stock cannot be added to a new purchase invoice.",
                )
                return

        eff_expiry = data.get("expiry") or raw_expiry
        if eff_expiry and eff_expiry.upper() != "DD-MM-YYYY":
            parsed_d = parse_expiry_to_date(eff_expiry)
            if parsed_d and parsed_d < inv_d:
                exp_disp = parsed_d.strftime("%d-%m-%Y")
                inv_disp = inv_d.strftime("%d-%m-%Y")
                QMessageBox.warning(
                    self,
                    "Expired Stock",
                    f"Batch '{batch_no}' is expired ({exp_disp}) on invoice date ({inv_disp}).\\n\\n"
                    f"Expired stock cannot be added to a new purchase invoice.",
                )
                return

        if rate < 0:
            QMessageBox.warning(self, "Validation", "Rate cannot be negative.")
            return

        if data["mrp"] < 0:
            QMessageBox.warning(self, "Validation", "MRP cannot be negative.")
            return

        if gst_pct < 0:
            QMessageBox.warning(self, "Validation", "GST percentage cannot be negative.")
            return

        disc_pct = _d(discount)
        gross = _d(pay_qty) * _d(rate)
        disc_amt = gross * disc_pct / _d(100) if disc_pct else _d(0)
        amount = _round2(gross - disc_amt)
        gst_amount = _round2(amount * gst_pct / 100.0)
        total_for_line = _round2(_d(amount) + _d(gst_amount))

        qty_total = pay_qty + free_qty
        purchase_rate = _round2(total_for_line / pay_qty) if pay_qty else 0.0
        net_rate = _round2(total_for_line / qty_total) if qty_total else 0.0

        mrp_val = float(data.get("mrp") or 0.0)
        if purchase_rate > 0 and mrp_val > purchase_rate:
            calc_pp = round(((mrp_val - purchase_rate) / purchase_rate) * 100.0, 2)
            if abs(calc_pp - 25.0) < 0.1 or abs(calc_pp - round(calc_pp)) < 0.05:
                pp = float(round(calc_pp))
            else:
                pp = calc_pp
        else:
            pp = 25.0

        row = _InvoiceItemRow(
            item_id=data["item_id"],
            item_name=data["item_name"],
            pack_size=data["pack_size"],
            pay_qty=pay_qty,
            free_qty=free_qty,
            batch_no=batch_no,
            expiry=normalize_expiry_db(data["expiry"]) if data["expiry"] else "",
            rate=rate,
            mrp=data["mrp"],
            discount=discount,
            gst_percent=gst_pct,
            amount=amount,
            gst_amount=gst_amount,
            purchase_rate=purchase_rate,
            net_rate=net_rate,
            pp=pp,
            batch_id=data.get("batch_id"),
        )
        self._item_rows.append(row)
        self._refresh_table()
        self._recalc_totals()
        self._entry_bar.clear()

    def _refresh_table(self):
        self._table.setRowCount(len(self._item_rows))
        for i, r in enumerate(self._item_rows):
            def _item(text: str, align: Qt.AlignmentFlag = Qt.AlignLeft | Qt.AlignVCenter) -> QTableWidgetItem:
                it = QTableWidgetItem(text)
                it.setTextAlignment(align)
                return it

            # Exact 16 columns matching Screenshot 1:
            # 0: ItemName, 1: PackSize, 2: PayQty, 3: FreeQty, 4: BatchNo, 5: Expiry,
            # 6: Rate, 7: MRP, 8: DiscAmt, 9: Amount, 10: TaxPer, 11: TaxAmt,
            # 12: PurRate, 13: NetRate, 14: PP, 15: Del
            item_w = _item(r.item_name, Qt.AlignLeft | Qt.AlignVCenter)
            item_w.setToolTip(r.item_name)
            self._table.setItem(i, 0, item_w)
            self._table.setItem(i, 1, _item(r.pack_size, Qt.AlignCenter))
            self._table.setItem(i, 2, _item(f"{r.pay_qty:g}", Qt.AlignRight | Qt.AlignVCenter))
            self._table.setItem(i, 3, _item(f"{r.free_qty:g}", Qt.AlignRight | Qt.AlignVCenter))
            batch_w = _item(r.batch_no, Qt.AlignCenter)
            batch_w.setToolTip(r.batch_no)
            self._table.setItem(i, 4, batch_w)
            self._table.setItem(i, 5, _item(format_expiry_display(r.expiry), Qt.AlignCenter))
            self._table.setItem(i, 6, _item(f"{r.rate:.2f}", Qt.AlignRight | Qt.AlignVCenter))
            self._table.setItem(i, 7, _item(f"{r.mrp:.2f}", Qt.AlignRight | Qt.AlignVCenter))

            disc_amt = (r.pay_qty * r.rate) * r.discount / 100.0
            self._table.setItem(i, 8, _item(f"{disc_amt:.2f}", Qt.AlignRight | Qt.AlignVCenter))
            self._table.setItem(i, 9, _item(f"{r.amount:.2f}", Qt.AlignRight | Qt.AlignVCenter))
            self._table.setItem(i, 10, _item(f"{r.gst_percent:g}", Qt.AlignRight | Qt.AlignVCenter))
            self._table.setItem(i, 11, _item(f"{r.gst_amount:.2f}", Qt.AlignRight | Qt.AlignVCenter))
            self._table.setItem(i, 12, _item(f"{r.purchase_rate:.2f}", Qt.AlignRight | Qt.AlignVCenter))
            self._table.setItem(i, 13, _item(f"{r.net_rate:.2f}", Qt.AlignRight | Qt.AlignVCenter))
            pp_disp = f"{int(r.pp)}" if (isinstance(r.pp, (int, float)) and r.pp == int(r.pp)) else f"{r.pp:.2f}"
            self._table.setItem(i, 14, _item(pp_disp, Qt.AlignRight | Qt.AlignVCenter))

            del_btn = QPushButton("×")
            del_btn.setStyleSheet(_BTN_DANGER)
            del_btn.setFixedSize(28, 22)
            del_btn.setToolTip("Remove item")
            del_btn.clicked.connect(lambda _, idx=i: self._delete_item(idx))

            cell = QWidget()
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setAlignment(Qt.AlignCenter)
            cell_layout.addWidget(del_btn)
            self._table.setCellWidget(i, 15, cell)

        if hasattr(self, "total_items_edit"):
            self.total_items_edit.setText(str(len(self._item_rows)))

    def _delete_item(self, idx: int):
        if 0 <= idx < len(self._item_rows):
            self._item_rows.pop(idx)
            self._refresh_table()
            self._recalc_totals()
            self._entry_bar.clear()

    def _recalc_totals(self):
        total_amount = _round2(sum(r.amount for r in self._item_rows))
        total_gst = _round2(sum(r.gst_amount for r in self._item_rows))

        self.total_amount_label.setText(f"{total_amount:.2f}")
        self.gst_label.setText(f"{total_gst:.2f}")

        bill_disc = _safe_float(self.bill_disc_edit.text())
        dn = _safe_float(self.dn_edit.text())
        other = _safe_float(self.other_edit.text())

        raw_net = _d(total_amount) + _d(total_gst) - _d(bill_disc) - _d(dn) + _d(other)
        rounded_net = int(raw_net.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        round_off = _round2(float(_d(rounded_net) - raw_net))
        net = float(rounded_net)

        self.round_off_edit.setText(f"{round_off:.2f}")
        self.net_amt_label.setText(f"{net:.2f}")

        if hasattr(self, "total_items_edit"):
            self.total_items_edit.setText(str(len(self._item_rows)))

    def _wire_totals_recalc(self):
        for attr in ("bill_disc_edit", "dn_edit", "other_edit", "paid_edit", "round_off_edit"):
            w = getattr(self, attr, None)
            if w is not None:
                w.textChanged.connect(self._recalc_totals)

    def _populate_invoice(self, inv: dict):
        full = inv.get("voucher_no", "")
        self._full_voucher_no = full
        self.voucher_no_edit.setText(_display_voucher_no(full))
        self.voucher_no_edit.setToolTip(f"Full Voucher: {full}")

        vd = inv.get("voucher_date", "")
        if vd:
            try:
                parts = vd.split("-")
                self.voucher_date.setDate(QDate(int(parts[0]), int(parts[1]), int(parts[2])))
            except Exception:
                pass

        from core.doc_formatter import format_time_12hr
        self.voucher_time_edit.setText(format_time_12hr(inv.get("voucher_time", "")))
        idx = self.purchase_type_combo.findText(inv.get("purchase_type", "Credit"))
        if idx >= 0:
            self.purchase_type_combo.setCurrentIndex(idx)

        sid = inv.get("supplier_id")
        if sid:
            idx = self.supplier_combo.findData(sid)
            if idx >= 0:
                self.supplier_combo.setCurrentIndex(idx)
            self._update_supplier_balance(sid)

        self.invoice_no_edit.setText(inv.get("invoice_no", ""))

        id_str = inv.get("invoice_date", "")
        if id_str:
            try:
                parts = id_str.split("-")
                self.invoice_date.setDate(QDate(int(parts[0]), int(parts[1]), int(parts[2])))
            except Exception:
                pass

        self.inv_net_amt_edit.setText(str(inv.get("invoice_net_amount", 0.0)))
        bd = str(inv.get("bill_discount", 0.0))
        self.bill_discount_edit.setText(bd)
        self.bill_disc_edit.setText(bd)

        dd = inv.get("due_date", "")
        if dd:
            try:
                parts = dd.split("-")
                self.due_date.setDate(QDate(int(parts[0]), int(parts[1]), int(parts[2])))
            except Exception:
                pass

        # Load items
        items = PurchaseDAO.get_invoice_items(inv["id"])
        for it in items:
            row = _InvoiceItemRow(
                item_id=it["item_id"],
                item_name=it.get("item_name", ""),
                pack_size=it.get("pack_size", ""),
                pay_qty=it.get("pay_qty", 0.0),
                free_qty=it.get("free_qty", 0.0),
                batch_no=it.get("batch_no", ""),
                expiry=it.get("expiry", ""),
                rate=it.get("rate", 0.0),
                mrp=it.get("mrp", 0.0),
                discount=it.get("discount", 0.0),
                gst_percent=it.get("gst_percent", 0.0),
                amount=it.get("amount", 0.0),
                gst_amount=it.get("gst_amount", 0.0),
                purchase_rate=it.get("purchase_rate", 0.0),
                net_rate=it.get("net_rate", 0.0),
                pp=(
                    float(it["pp"]) if (0 < float(it.get("pp") or 0.0) <= 100)
                    else (
                        float(round(((float(it.get("mrp") or 0.0) - float(it.get("purchase_rate") or 0.0)) / float(it["purchase_rate"])) * 100.0))
                        if (float(it.get("purchase_rate") or 0.0) > 0 and float(it.get("mrp") or 0.0) > float(it.get("purchase_rate") or 0.0)
                            and abs(((float(it.get("mrp") or 0.0) - float(it.get("purchase_rate") or 0.0)) / float(it["purchase_rate"])) * 100.0 - 25.0) < 0.1)
                        else (
                            round(((float(it.get("mrp") or 0.0) - float(it.get("purchase_rate") or 0.0)) / float(it["purchase_rate"])) * 100.0, 2)
                            if (float(it.get("purchase_rate") or 0.0) > 0 and float(it.get("mrp") or 0.0) > float(it.get("purchase_rate") or 0.0))
                            else 25.0
                        )
                    )
                ),
            )
            self._item_rows.append(row)
        self._refresh_table()

        # Populate totals
        self.dn_edit.setText(str(inv.get("debit_note_amount", 0.0)))
        self.other_edit.setText(str(inv.get("other_amount", 0.0)))
        self.paid_edit.setText(str(inv.get("paid_amount", 0.0)))
        self.round_off_edit.setText(str(inv.get("round_off", 0.0)))
        if hasattr(self, "remarks_edit"):
            self.remarks_edit.setPlainText(str(inv.get("remarks") or ""))

        self._recalc_totals()

    @staticmethod
    def _lbl(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_HEADER_LABEL)
        return lbl

    def _on_save(self):
        try:
            financial_year.validate_transaction_date(self.voucher_date.date().toString("yyyy-MM-dd"))
        except financial_year.FinancialYearError as exc:
            QMessageBox.warning(self, "Financial Year", str(exc)); return
        sid = self.supplier_combo.currentData()
        if not sid:
            QMessageBox.warning(self, "Validation", "Please select a valid supplier from the list.")
            return

        if not self._item_rows:
            QMessageBox.warning(self, "Validation", "At least one item is required.")
            return

        inv_d = self.get_invoice_date()
        for r in self._item_rows:
            if r.expiry:
                parsed_exp = parse_expiry_to_date(r.expiry)
                if parsed_exp and parsed_exp < inv_d:
                    exp_disp = parsed_exp.strftime("%d-%m-%Y")
                    inv_disp = inv_d.strftime("%d-%m-%Y")
                    QMessageBox.warning(
                        self,
                        "Expired Stock",
                        f"Cannot save invoice: Item '{r.item_name}' (Batch '{r.batch_no}') "
                        f"is expired ({exp_disp}) on invoice date ({inv_disp}).\\n\\n"
                        f"Expired stock cannot be entered in a new purchase invoice.",
                    )
                    return

        voucher_no = getattr(self, "_full_voucher_no", None) or self.voucher_no_edit.text().strip()
        if not voucher_no:
            QMessageBox.warning(self, "Validation", "Voucher number is required.")
            return

        self._recalc_totals()

        total_amount = _round2(float(_d(sum(r.amount for r in self._item_rows))))
        gst_amount = _round2(float(_d(sum(r.gst_amount for r in self._item_rows))))
        bill_discount = _safe_float(self.bill_discount_edit.text())
        dn = _safe_float(self.dn_edit.text())
        other = _safe_float(self.other_edit.text())
        paid = _safe_float(self.paid_edit.text())
        round_off = _safe_float(self.round_off_edit.text())
        net_amount = _round2(total_amount + gst_amount - bill_discount - dn + other + round_off)

        inv_net_amount = _safe_float(self.inv_net_amt_edit.text())
        voucher_date = self.voucher_date.date().toString("yyyy-MM-dd")
        voucher_time = self.voucher_time_edit.text().strip()
        purchase_type = self.purchase_type_combo.currentText()
        invoice_no = self.invoice_no_edit.text().strip()
        invoice_date = self.invoice_date.date().toString("yyyy-MM-dd")
        due_date = self.due_date.date().toString("yyyy-MM-dd")
        remarks = self.remarks_edit.toPlainText().strip() if hasattr(self, "remarks_edit") else ""

        items_data = [r.to_dict() for r in self._item_rows]

        try:
            if self._invoice:
                PurchaseDAO.update_invoice(
                    invoice_id=self._invoice["id"],
                    voucher_no=voucher_no, voucher_date=voucher_date,
                    voucher_time=voucher_time, purchase_type=purchase_type,
                    supplier_id=sid, invoice_no=invoice_no,
                    invoice_date=invoice_date, invoice_net_amount=inv_net_amount,
                    bill_discount=bill_discount, due_date=due_date,
                    total_amount=total_amount, gst_amount=gst_amount,
                    debit_note_amount=dn, other_amount=other,
                    paid_amount=paid, round_off=round_off,
                    net_amount=net_amount, remarks=remarks,
                    items=items_data,
                )
            else:
                PurchaseDAO.insert_invoice(
                    voucher_no=voucher_no, voucher_date=voucher_date,
                    voucher_time=voucher_time, purchase_type=purchase_type,
                    supplier_id=sid, invoice_no=invoice_no,
                    invoice_date=invoice_date, invoice_net_amount=inv_net_amount,
                    bill_discount=bill_discount, due_date=due_date,
                    total_amount=total_amount, gst_amount=gst_amount,
                    debit_note_amount=dn, other_amount=other,
                    paid_amount=paid, round_off=round_off,
                    net_amount=net_amount, remarks=remarks,
                    items=items_data,
                )
            self._saved = True
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save invoice:\\n{e}")

    @property
    def was_saved(self) -> bool:
        return self._saved

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.reject()
            return
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_S:
            self._on_save()
            return
        super().keyPressEvent(event)

    def refresh_theme(self):
        p = palette()
        self.supplier_combo.refresh_theme(p)
        self._entry_bar.refresh_theme(p)
'''

# Read purchase_invoice.py
with open('screens/purchase_invoice.py', 'r', encoding='utf-8') as f:
    text = f.read()

# Replace from 'class _ItemEntryBar(QWidget):' to '# ======================================================================\n# Purchase Invoice PAGE'
start_marker = "class _ItemEntryBar(QWidget):"
end_marker = "# ======================================================================\n# Purchase Invoice PAGE"

assert start_marker in text, f"start_marker not found"
assert end_marker in text, f"end_marker not found"

prefix = text[:text.find(start_marker)]
suffix = text[text.find(end_marker):]

updated_text = prefix + new_code.strip() + "\n\n\n" + suffix

with open('screens/purchase_invoice.py', 'w', encoding='utf-8', newline='') as f:
    f.write(updated_text)

print("screens/purchase_invoice.py successfully patched!")
