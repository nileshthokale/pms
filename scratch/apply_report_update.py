import re

with open('screens/purchase_report.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = """    def _on_clear(self):
        self.supplier_edit.clear_filter()
        self.company_edit.clear_filter()
        self.item_edit.clear_filter()
        self.invoice_edit.clear()
        self.voucher_edit.clear()
        self.batch_edit.clear()
        self._on_generate()"""

replacement = """    def _on_clear(self):
        self.supplier_edit.clear_filter()
        self.company_edit.clear_filter()
        self.item_edit.clear_filter()
        self.invoice_edit.clear()
        self.voucher_edit.clear()
        self.batch_edit.clear()
        self._on_generate()

    def _on_row_double_clicked(self, row: int, column: int):
        item = self._table.item(row, 0)
        if not item:
            return
        purchase_id = item.data(Qt.UserRole)
        if purchase_id:
            self._open_invoice(purchase_id)

    def _on_edit_selected_invoice(self):
        row = self._table.currentRow()
        if row < 0:
            QMessageBox.information(
                self, "Edit Invoice", "Please select an invoice from the table to edit."
            )
            return
        item = self._table.item(row, 0)
        if not item:
            return
        purchase_id = item.data(Qt.UserRole)
        if not purchase_id:
            QMessageBox.warning(
                self, "Edit Invoice", "The selected row does not contain a valid purchase ID."
            )
            return
        self._open_invoice(purchase_id)

    def _open_invoice(self, purchase_id: int):
        try:
            inv = PurchaseDAO.get_by_id(purchase_id)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to load invoice:\n{exc}")
            return
        if not inv:
            QMessageBox.warning(self, "Edit Invoice", "Could not load invoice data from database.")
            return

        dlg = _InvoiceDialog(self, invoice=inv)
        dlg.exec()
        if getattr(dlg, "was_saved", False):
            self._on_generate()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if self._table.hasFocus() or self._table.currentRow() >= 0:
                self._on_edit_selected_invoice()
                event.accept()
                return
        super().keyPressEvent(event)"""

if target in content:
    content = content.replace(target, replacement, 1)
    with open('screens/purchase_report.py', 'w', encoding='utf-8', newline='') as f:
        f.write(content)
    print("Updated purchase_report.py successfully")
else:
    print("Target not found in purchase_report.py")
