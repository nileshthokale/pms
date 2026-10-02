"""Category Master: non-accounting, optional item classification."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from database import auth
from database.category_dao import CategoryDAO, CategoryError
from ui.theme import palette

_p = palette()
_BG, _SURFACE, _BORDER = _p["bg"], _p["surface"], _p["border"]
_ACCENT, _HOVER, _TEXT = _p["accent"], _p["accent_hover"], _p["text"]

_EDIT_STYLE = (
    f"QLineEdit {{ background-color: {_BG}; color: {_TEXT}; border: 1px solid {_BORDER};"
    " border-radius: 2px; padding: 7px; font-size: 13px; font-family: 'Segoe UI'; }"
    f"QLineEdit:focus {{ border: 1px solid {_ACCENT}; }}"
)
_PRIMARY = (
    f"QPushButton {{ background-color: {_ACCENT}; color: white; border: none; border-radius: 2px;"
    " padding: 8px 16px; font-weight: bold; font-size: 13px; }"
    f"QPushButton:hover {{ background-color: {_HOVER}; }}"
)
_SECONDARY = (
    f"QPushButton {{ background-color: {_BORDER}; color: {_TEXT}; border: none; border-radius: 2px;"
    " padding: 8px 16px; font-size: 13px; } QPushButton:hover { background-color: #7d93a8; }"
)


class _CategoryDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, *, category: dict | None = None):
        super().__init__(parent)
        self._category = category
        self._saved = False
        self.setWindowTitle("Edit Category" if category else "New Category")
        self.setMinimumWidth(430)
        self.setStyleSheet(f"QDialog {{ background-color: {_BG}; }} QLabel {{ color: {_TEXT}; }}")
        form = QFormLayout(self)
        form.setContentsMargins(24, 24, 24, 24)
        form.setSpacing(13)
        self._name = QLineEdit(); self._name.setPlaceholderText("Enter category name"); self._name.setStyleSheet(_EDIT_STYLE)
        self._description = QLineEdit(); self._description.setPlaceholderText("Optional description"); self._description.setStyleSheet(_EDIT_STYLE)
        self._active = QCheckBox("Active"); self._active.setStyleSheet(f"color: {_TEXT};")
        self._active.setChecked(True)
        form.addRow("Category Name *:", self._name)
        form.addRow("Description:", self._description)
        form.addRow("", self._active)
        if category:
            self._name.setText(category.get("category_name", ""))
            self._description.setText(category.get("description", "") or "")
            self._active.setChecked(bool(category.get("is_active")))
        buttons = QHBoxLayout(); buttons.addStretch()
        save = QPushButton("Save"); save.setStyleSheet(_PRIMARY); save.clicked.connect(self._save); buttons.addWidget(save)
        cancel = QPushButton("Cancel"); cancel.setStyleSheet(_SECONDARY); cancel.clicked.connect(self.reject); buttons.addWidget(cancel)
        form.addRow("", buttons)

    def _save(self):
        try:
            if self._category:
                CategoryDAO.update_category(self._category["id"], self._name.text(), self._description.text(), self._active.isChecked())
            else:
                CategoryDAO.create_category(self._name.text(), self._description.text(), self._active.isChecked())
        except CategoryError as exc:
            QMessageBox.warning(self, "Category", str(exc)); return
        self._saved = True
        self.accept()

    @property
    def was_saved(self) -> bool:
        return self._saved


class CategoryMasterPage(QWidget):
    """ADMIN-only administration page; all users may use categories in Item Master."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {_BG};")
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        header = QWidget(); header.setFixedHeight(56); header.setStyleSheet(f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};")
        layout = QHBoxLayout(header); layout.setContentsMargins(16, 0, 16, 0)
        title = QLabel("Category Master"); title.setStyleSheet(f"color: {_TEXT}; font-size: 18px; font-weight: bold; background: transparent;")
        layout.addWidget(title); layout.addStretch()
        self._new_btn = QPushButton("New"); self._new_btn.setStyleSheet(_PRIMARY); self._new_btn.clicked.connect(self._on_new); layout.addWidget(self._new_btn)
        self._edit_btn = QPushButton("Edit"); self._edit_btn.setStyleSheet(_SECONDARY); self._edit_btn.clicked.connect(self._on_edit); layout.addWidget(self._edit_btn)
        self._toggle_btn = QPushButton("Activate/Deactivate"); self._toggle_btn.setStyleSheet(_SECONDARY); self._toggle_btn.clicked.connect(self._on_toggle); layout.addWidget(self._toggle_btn)
        refresh = QPushButton("Refresh"); refresh.setStyleSheet(_SECONDARY); refresh.clicked.connect(self._refresh); layout.addWidget(refresh)
        root.addWidget(header)

        search = QWidget(); search.setFixedHeight(48); search.setStyleSheet(f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};")
        search_layout = QHBoxLayout(search); search_layout.setContentsMargins(16, 0, 16, 0)
        search_layout.addWidget(QLabel("Search:"))
        self._search = QLineEdit(); self._search.setPlaceholderText("Category name or description"); self._search.setFixedWidth(310); self._search.setStyleSheet(_EDIT_STYLE); self._search.returnPressed.connect(self._on_search); search_layout.addWidget(self._search)
        search_btn = QPushButton("Search"); search_btn.setStyleSheet(_PRIMARY); search_btn.clicked.connect(self._on_search); search_layout.addWidget(search_btn)
        search_layout.addStretch(); root.addWidget(search)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["ID", "Category Name", "Description", "Status"])
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers); self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection); self._table.verticalHeader().setVisible(False); self._table.setShowGrid(True)
        table_header = self._table.horizontalHeader(); table_header.setSectionResizeMode(0, QHeaderView.ResizeToContents); table_header.setSectionResizeMode(1, QHeaderView.Stretch); table_header.setSectionResizeMode(2, QHeaderView.Stretch); table_header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        table_header.setStyleSheet(f"QHeaderView::section {{ background-color: {_SURFACE}; color: {_TEXT}; border: none; border-bottom: 2px solid {_ACCENT}; padding: 4px 8px; font-weight: bold; }}")
        self._table.setStyleSheet(f"QTableWidget {{ background-color: {_BG}; color: {_TEXT}; border: 1px solid {_BORDER}; gridline-color: {_BORDER}; selection-background-color: {_ACCENT}; selection-color: white; }} QTableWidget::item {{ padding: 3px 6px; }}")
        root.addWidget(self._table, 1)
        self._refresh()

    def _allowed(self) -> bool:
        try:
            auth.session.require(auth.PERM_CATEGORY_MANAGEMENT)
            return True
        except auth.PermissionDenied as exc:
            QMessageBox.warning(self, "Permission denied", str(exc)); return False

    def _refresh(self, categories: list[dict] | None = None):
        categories = CategoryDAO.get_all_categories() if categories is None else categories
        self._table.setRowCount(len(categories))
        for row, category in enumerate(categories):
            values = (category["id"], category["category_name"], category.get("description") or "", "Active" if category.get("is_active") else "Inactive")
            for column, value in enumerate(values):
                self._table.setItem(row, column, QTableWidgetItem(str(value)))
            self._table.item(row, 0).setData(Qt.UserRole, category["id"])

    def _selected(self) -> dict | None:
        rows = self._table.selectionModel().selectedRows()
        return CategoryDAO.get_category(int(rows[0].data(Qt.UserRole))) if rows else None

    def _on_new(self):
        if not self._allowed(): return
        dialog = _CategoryDialog(self)
        if dialog.exec() and dialog.was_saved: self._refresh()

    def _on_edit(self):
        if not self._allowed(): return
        category = self._selected()
        if not category: QMessageBox.information(self, "Edit Category", "Please select a category to edit."); return
        dialog = _CategoryDialog(self, category=category)
        if dialog.exec() and dialog.was_saved: self._refresh()

    def _on_toggle(self):
        if not self._allowed(): return
        category = self._selected()
        if not category: QMessageBox.information(self, "Category", "Please select a category."); return
        try:
            (CategoryDAO.deactivate_category if category.get("is_active") else CategoryDAO.activate_category)(category["id"])
        except CategoryError as exc:
            QMessageBox.warning(self, "Category", str(exc)); return
        self._refresh()

    def _on_search(self):
        self._refresh(CategoryDAO.search_categories(self._search.text()))

