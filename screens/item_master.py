from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from database.item_dao import ItemDAO
from database.unit_dao import UnitDAO
from database.company_dao import CompanyDAO
from database.drug_dao import DrugDAO
from database.category_dao import CategoryDAO
from database.tax_structures import (
    DEFAULT_TAX_VALUE,
    GST_TAX_STRUCTURES,
    VALID_TAX_VALUES,
    is_gst_rate,
    legacy_display,
)

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


def _tax_cell_text(stored: object) -> str:
    """Grid text for a stored tax value.

    The five GST rates show their full label so the list is readable; a
    legacy code is shown unchanged, marked only in the edit dialog so the
    list stays compact.
    """
    from database.tax_structures import display_for

    return display_for(stored)


class _IngredientRow(QWidget):
    """A single ingredient row with drug dropdown, power field, and delete button."""

    def __init__(self, drugs: list[dict], parent=None):
        super().__init__(parent)
        self._drugs = drugs

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.drug_combo = QComboBox()
        self.drug_combo.setMinimumWidth(200)
        self.drug_combo.setStyleSheet(
            f"QComboBox {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; border-radius: 2px;"
            f"  padding: 6px; font-size: 13px; font-family: 'Segoe UI';"
            f"}}"
            f"QComboBox:hover {{ border: 1px solid {_ACCENT}; }}"
            f"QComboBox::drop-down {{"
            f"  border: none; width: 24px;"
            f"}}"
            f"QComboBox::down-arrow {{"
            f"  image: none; border: none;"
            f"}}"
            f"QComboBox QAbstractItemView {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; selection-background-color: {_ACCENT};"
            f"  font-size: 13px; font-family: 'Segoe UI';"
            f"}}"
        )
        self.drug_combo.addItem("-- Select Drug --", None)
        for drug in drugs:
            self.drug_combo.addItem(drug["drug_name"], drug["id"])
        layout.addWidget(self.drug_combo)

        self.power_edit = QLineEdit()
        self.power_edit.setPlaceholderText("Power")
        self.power_edit.setMaximumWidth(120)
        self.power_edit.setStyleSheet(
            f"QLineEdit {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; border-radius: 2px;"
            f"  padding: 6px; font-size: 13px; font-family: 'Segoe UI';"
            f"}}"
            f"QLineEdit:focus {{ border: 1px solid {_ACCENT}; }}"
        )
        layout.addWidget(self.power_edit)

        self.delete_btn = QPushButton("X")
        self.delete_btn.setFixedSize(28, 28)
        self.delete_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {_ERROR}; color: white;"
            f"  border: none; border-radius: 2px; font-weight: bold; font-size: 12px;"
            f"}}"
            f"QPushButton:hover {{ background-color: #d32f2f; }}"
        )
        layout.addWidget(self.delete_btn)

        layout.addStretch()

    def get_data(self) -> dict | None:
        drug_id = self.drug_combo.currentData()
        if drug_id is None:
            return None
        return {
            "drug_id": drug_id,
            "drug_name": self.drug_combo.currentText(),
            "power": self.power_edit.text().strip(),
        }


class _ItemDialog(QDialog):
    """Modal dialog for adding or editing an item."""

    def __init__(self, parent: QWidget | None = None, *, item: dict | None = None):
        super().__init__(parent)
        self._item = item
        self._saved = False
        self._ingredient_rows: list[_IngredientRow] = []
        # Index of the extra "legacy tax code" entry, when one was added for
        # an imported item.  See _select_tax_structure.
        self._legacy_tax_index: int | None = None

        self.setWindowTitle("Edit Item" if item else "Add New Item")
        self.setMinimumWidth(600)
        self.setMinimumHeight(650)
        self.setModal(True)
        self.setStyleSheet(
            f"QDialog {{ background-color: {_DARK_BG}; }}"
            f"QLabel {{ color: {_TEXT}; font-family: 'Segoe UI'; font-size: 13px; }}"
            f"QLineEdit {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; border-radius: 2px;"
            f"  padding: 8px; font-size: 13px;"
            f"}}"
            f"QLineEdit:focus {{ border: 1px solid {_ACCENT}; }}"
            f"QScrollArea {{ border: none; background: transparent; }}"
            f"QGroupBox {{"
            f"  color: {_TEXT}; font-weight: bold; font-size: 13px;"
            f"  border: 1px solid {_BORDER}; border-radius: 2px;"
            f"  margin-top: 12px; padding-top: 16px;"
            f"}}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; }}"
        )

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        container = QWidget()
        main_layout = QVBoxLayout(container)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(24, 24, 24, 24)

        # -- Item Details --
        details_group = QGroupBox("Item Details")
        form = QFormLayout(details_group)
        form.setSpacing(10)
        form.setContentsMargins(12, 20, 12, 12)

        self._item_name_edit = QLineEdit()
        self._item_name_edit.setPlaceholderText("Enter item name")
        form.addRow("Item Name *:", self._item_name_edit)

        self._unit_combo = QComboBox()
        self._unit_combo.setStyleSheet(
            f"QComboBox {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; border-radius: 2px;"
            f"  padding: 8px; font-size: 13px; font-family: 'Segoe UI';"
            f"}}"
            f"QComboBox:hover {{ border: 1px solid {_ACCENT}; }}"
            f"QComboBox::drop-down {{"
            f"  border: none; width: 24px;"
            f"}}"
            f"QComboBox::down-arrow {{ image: none; border: none; }}"
            f"QComboBox QAbstractItemView {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; selection-background-color: {_ACCENT};"
            f"  font-size: 13px; font-family: 'Segoe UI';"
            f"}}"
        )
        self._load_units()
        form.addRow("Unit:", self._unit_combo)

        self._company_combo = QComboBox()
        self._company_combo.setStyleSheet(
            f"QComboBox {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; border-radius: 2px;"
            f"  padding: 8px; font-size: 13px; font-family: 'Segoe UI';"
            f"}}"
            f"QComboBox:hover {{ border: 1px solid {_ACCENT}; }}"
            f"QComboBox::drop-down {{"
            f"  border: none; width: 24px;"
            f"}}"
            f"QComboBox::down-arrow {{ image: none; border: none; }}"
            f"QComboBox QAbstractItemView {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; selection-background-color: {_ACCENT};"
            f"  font-size: 13px; font-family: 'Segoe UI';"
            f"}}"
        )
        self._load_companies()
        form.addRow("Company:", self._company_combo)

        self._category_combo = QComboBox()
        self._category_combo.setStyleSheet(self._company_combo.styleSheet())
        self._load_categories()
        form.addRow("Category:", self._category_combo)

        self._pack_size_edit = QLineEdit()
        self._pack_size_edit.setPlaceholderText("e.g. 10x10, 30ml")
        form.addRow("Pack Size:", self._pack_size_edit)

        self._tax_structure_combo = QComboBox()
        self._tax_structure_combo.setStyleSheet(
            self._company_combo.styleSheet())
        # Exactly the five GST options for a new item, in dropdown order,
        # carrying the bare rate as the internal value.
        for text, value in GST_TAX_STRUCTURES:
            self._tax_structure_combo.addItem(text, value)
        # A new item defaults to ZERO GST: no non-zero rate is ever
        # pre-selected, so creating an item cannot imply a tax liability.
        self._tax_structure_combo.setCurrentIndex(
            self._tax_structure_combo.findData(DEFAULT_TAX_VALUE))
        form.addRow("Tax Structure:", self._tax_structure_combo)

        self._discount_edit = QLineEdit()
        self._discount_edit.setPlaceholderText("0.0")
        form.addRow("Discount (%):", self._discount_edit)

        self._mrp_edit = QLineEdit()
        self._mrp_edit.setPlaceholderText("0.00")
        form.addRow("MRP:", self._mrp_edit)

        self._rate_edit = QLineEdit()
        self._rate_edit.setPlaceholderText("0.00")
        form.addRow("Rate:", self._rate_edit)

        self._reorder_edit = QLineEdit()
        self._reorder_edit.setPlaceholderText("0")
        form.addRow("Reorder Stock Level:", self._reorder_edit)

        self._scheduled_edit = QLineEdit()
        self._scheduled_edit.setPlaceholderText("e.g. H1, H2, Schedule X")
        form.addRow("Scheduled:", self._scheduled_edit)

        self._location_edit = QLineEdit()
        self._location_edit.setPlaceholderText("e.g. Shelf A3, Rack 2")
        form.addRow("Location:", self._location_edit)

        self._pathy_edit = QLineEdit()
        self._pathy_edit.setPlaceholderText("e.g. Allopathy, Ayurvedic")
        form.addRow("Pathy:", self._pathy_edit)

        self._dpco_edit = QLineEdit()
        self._dpco_edit.setPlaceholderText("e.g. Yes, No")
        form.addRow("DPCO:", self._dpco_edit)

        main_layout.addWidget(details_group)

        # -- Ingredients Section --
        ingredients_group = QGroupBox("Ingredients")
        ing_layout = QVBoxLayout(ingredients_group)
        ing_layout.setSpacing(8)
        ing_layout.setContentsMargins(12, 20, 12, 12)

        self._ingredients_container = QWidget()
        self._ingredients_layout = QVBoxLayout(self._ingredients_container)
        self._ingredients_layout.setContentsMargins(0, 0, 0, 0)
        self._ingredients_layout.setSpacing(6)
        ing_layout.addWidget(self._ingredients_container)

        add_ing_btn = QPushButton("+ Add Ingredient")
        add_ing_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {_ACCENT}; color: white;"
            f"  border: none; border-radius: 2px; padding: 8px 16px;"
            f"  font-weight: bold; font-size: 13px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {_ACCENT_HOVER}; }}"
        )
        add_ing_btn.clicked.connect(self._add_ingredient_row)
        ing_layout.addWidget(add_ing_btn)

        main_layout.addWidget(ingredients_group)
        main_layout.addStretch()

        scroll.setWidget(container)

        # -- Main Layout --
        dlg_layout = QVBoxLayout(self)
        dlg_layout.setContentsMargins(0, 0, 0, 0)
        dlg_layout.addWidget(scroll)

        # -- Button Bar --
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(24, 12, 24, 24)
        btn_layout.addStretch()

        save_btn = QPushButton("Save")
        save_btn.setFixedWidth(90)
        save_btn.setStyleSheet(
            f"QPushButton {{ background-color: {_ACCENT}; color: white;"
            f"  border: none; border-radius: 2px; padding: 4px 8px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: {_ACCENT_HOVER}; }}"
        )
        save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(save_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedWidth(90)
        cancel_btn.setStyleSheet(
            f"QPushButton {{ background-color: {_BORDER}; color: {_TEXT};"
            f"  border: none; border-radius: 2px; padding: 8px; }}"
            f"QPushButton:hover {{ background-color: #7d93a8; }}"
        )
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        dlg_layout.addLayout(btn_layout)

        # -- Load existing data for edit --
        if item:
            self._populate(item)

    def _load_units(self):
        units = UnitDAO.get_all()
        self._unit_combo.addItem("-- Select Unit --", None)
        for u in units:
            self._unit_combo.addItem(u["unit_name"], u["id"])

    def _load_companies(self):
        companies = CompanyDAO.get_all()
        self._company_combo.addItem("-- Select Company --", None)
        for c in companies:
            self._company_combo.addItem(c["company_name"], c["id"])

    def _load_categories(self):
        """New items only see active categories; blank remains valid."""
        self._category_combo.addItem("-- Select Category --", None)
        for category in CategoryDAO.get_all_categories(include_inactive=False):
            self._category_combo.addItem(category["category_name"], category["id"])

    def _add_ingredient_row(self, drugs: list[dict] | None = None, power: str = ""):
        all_drugs = DrugDAO.get_all()
        row = _IngredientRow(all_drugs)
        if power:
            row.power_edit.setText(power)
        if drugs:
            for d in drugs:
                idx = row.drug_combo.findData(d["id"])
                if idx >= 0:
                    row.drug_combo.setCurrentIndex(idx)
        row.delete_btn.clicked.connect(lambda: self._remove_ingredient_row(row))
        self._ingredient_rows.append(row)
        self._ingredients_layout.addWidget(row)

    def _remove_ingredient_row(self, row: _IngredientRow):
        if row in self._ingredient_rows:
            self._ingredient_rows.remove(row)
            self._ingredients_layout.removeWidget(row)
            row.deleteLater()

    def _populate(self, item: dict):
        self._item_name_edit.setText(item.get("item_name", ""))

        unit_id = item.get("unit_id")
        if unit_id:
            idx = self._unit_combo.findData(unit_id)
            if idx >= 0:
                self._unit_combo.setCurrentIndex(idx)

        company_id = item.get("company_id")
        if company_id:
            idx = self._company_combo.findData(company_id)
            if idx >= 0:
                self._company_combo.setCurrentIndex(idx)

        category_id = item.get("category_id")
        if category_id:
            idx = self._category_combo.findData(category_id)
            if idx < 0:
                # A historical item may use a now-inactive category.  Keep it
                # visible and selected so editing unrelated item data is safe.
                category = CategoryDAO.get_category(category_id)
                if category:
                    suffix = " (Inactive)" if not category.get("is_active") else ""
                    self._category_combo.addItem(category["category_name"] + suffix, category_id)
                    idx = self._category_combo.findData(category_id)
            if idx >= 0:
                self._category_combo.setCurrentIndex(idx)

        self._pack_size_edit.setText(item.get("pack_size", ""))
        self._select_tax_structure(item.get("tax_structure", ""))
        self._discount_edit.setText(str(item.get("discount", 0.0)))
        self._mrp_edit.setText(str(item.get("mrp", 0.0)))
        self._rate_edit.setText(str(item.get("rate", 0.0)))
        self._reorder_edit.setText(str(item.get("reorder_stock_level", 0)))
        self._scheduled_edit.setText(item.get("scheduled", ""))
        self._location_edit.setText(item.get("location", ""))
        self._pathy_edit.setText(item.get("pathy", ""))
        self._dpco_edit.setText(item.get("dpco", ""))

        # Load existing ingredients
        if item.get("id"):
            ingredients = ItemDAO.get_ingredients(item["id"])
            for ing in ingredients:
                drug_data = [{"id": ing["drug_id"], "drug_name": ing["drug_name"]}] if ing.get("drug_id") else None
                self._add_ingredient_row(drugs=drug_data, power=ing.get("power", ""))

    def _select_tax_structure(self, stored: object) -> None:
        """Show an item's stored tax value without rewriting it.

        A value that is one of the five GST rates simply selects that entry.
        Anything else is a legacy tax code from the imported data: it is added
        as an extra, clearly-marked entry so the historical value stays
        visible and selected, and saving an unrelated field change keeps it
        exactly as it was.  Nothing is silently converted.
        """
        value = "" if stored is None else str(stored).strip()
        if not value:
            self._tax_structure_combo.setCurrentIndex(
                self._tax_structure_combo.findData(DEFAULT_TAX_VALUE))
            return

        index = self._tax_structure_combo.findData(value)
        if index < 0:
            # addItem() does not report the new row index, so derive it.
            self._tax_structure_combo.addItem(legacy_display(value), value)
            index = self._tax_structure_combo.findData(value)
            self._legacy_tax_index = index
        self._tax_structure_combo.setCurrentIndex(index)

    def _current_tax_value(self) -> str:
        """The internal tax value currently selected in the dropdown."""
        value = self._tax_structure_combo.currentData()
        return "" if value is None else str(value).strip()

    def _safe_float(self, text: str, default: float = 0.0) -> float:
        try:
            return float(text.strip()) if text.strip() else default
        except ValueError:
            return default

    def _safe_int(self, text: str, default: int = 0) -> int:
        try:
            return int(float(text.strip())) if text.strip() else default
        except ValueError:
            return default

    def _on_save(self):
        name = self._item_name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation", "Item Name is required.")
            return

        exclude_id = self._item["id"] if self._item else None
        if ItemDAO.name_exists(name, exclude_id):
            QMessageBox.warning(
                self, "Validation", "An item with this name already exists."
            )
            return

        unit_id = self._unit_combo.currentData()
        company_id = self._company_combo.currentData()
        category_id = self._category_combo.currentData()

        # Tax validation.  A NEW item may only be saved with one of the five
        # GST rates.  When EDITING an imported item, the original stored value
        # stays acceptable even though it is a legacy code, so opening an old
        # item and saving an unrelated field cannot fail or silently rewrite
        # its tax history.  Only an explicit choice of a different option
        # changes the value.
        tax_value = self._current_tax_value()
        original_tax = ""
        if self._item:
            original_tax = str(self._item.get("tax_structure") or "").strip()
        is_new_selection = (
            not self._item
            or tax_value != original_tax
            or is_gst_rate(original_tax)
        )
        if is_new_selection and tax_value not in VALID_TAX_VALUES:
            QMessageBox.warning(
                self,
                "Validation",
                "Please select one of the supported GST tax structures "
                "(GST 5%, 12%, 18%, 28% or ZERO GST).",
            )
            return

        kwargs = {
            "item_name": name,
            "unit_id": unit_id,
            "company_id": company_id,
            "category_id": category_id,
            "pack_size": self._pack_size_edit.text().strip(),
            "tax_structure": tax_value,
            "discount": self._safe_float(self._discount_edit.text()),
            "mrp": self._safe_float(self._mrp_edit.text()),
            "rate": self._safe_float(self._rate_edit.text()),
            "reorder_stock_level": self._safe_int(self._reorder_edit.text()),
            "scheduled": self._scheduled_edit.text().strip(),
            "location": self._location_edit.text().strip(),
            "pathy": self._pathy_edit.text().strip(),
            "dpco": self._dpco_edit.text().strip(),
        }

        # Gather ingredients
        ingredients = []
        for row in self._ingredient_rows:
            data = row.get_data()
            if data and data["drug_id"] is not None:
                ingredients.append(data)

        if self._item:
            ItemDAO.update(self._item["id"], **kwargs)
            ItemDAO.save_ingredients(self._item["id"], ingredients)
        else:
            item_id = ItemDAO.insert(**kwargs)
            ItemDAO.save_ingredients(item_id, ingredients)

        self._saved = True
        self.accept()

    @property
    def was_saved(self) -> bool:
        return self._saved


class ItemMasterPage(QWidget):
    """Item Master screen with search bar, table list, New and Edit buttons."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {_DARK_BG};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # -- Header bar --
        header = QWidget()
        header.setFixedHeight(56)
        header.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 0, 16, 0)

        title = QLabel("Item Master")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 18px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        header_layout.addWidget(title)
        header_layout.addStretch()

        new_btn = QPushButton("New")
        new_btn.setFixedWidth(90)
        new_btn.setStyleSheet(
            f"QPushButton {{ background-color: {_ACCENT}; color: white;"
            f"  border: none; border-radius: 2px; padding: 8px 16px;"
            f"  font-weight: bold; font-size: 13px; }}"
            f"QPushButton:hover {{ background-color: {_ACCENT_HOVER}; }}"
        )
        new_btn.clicked.connect(self._on_new)
        header_layout.addWidget(new_btn)

        edit_btn = QPushButton("Edit")
        edit_btn.setFixedWidth(90)
        edit_btn.setStyleSheet(
            f"QPushButton {{ background-color: {_BORDER}; color: {_TEXT};"
            f"  border: none; border-radius: 2px; padding: 8px 16px;"
            f"  font-size: 13px; }}"
            f"QPushButton:hover {{ background-color: #7d93a8; }}"
        )
        edit_btn.clicked.connect(self._on_edit)
        header_layout.addWidget(edit_btn)

        root.addWidget(header)

        # -- Search bar --
        search_bar = QWidget()
        search_bar.setFixedHeight(48)
        search_bar.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        search_layout = QHBoxLayout(search_bar)
        search_layout.setContentsMargins(16, 0, 16, 0)

        search_label = QLabel("Item Name:")
        search_label.setStyleSheet(
            f"color: {_TEXT}; font-size: 13px;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        search_layout.addWidget(search_label)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Enter item name to search")
        self._search_edit.setFixedWidth(300)
        self._search_edit.setStyleSheet(
            f"QLineEdit {{"
            f"  background-color: {_DARK_BG}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; border-radius: 2px;"
            f"  padding: 6px 10px; font-size: 13px;"
            f"  font-family: 'Segoe UI';"
            f"}}"
            f"QLineEdit:focus {{ border: 1px solid {_ACCENT}; }}"
        )
        self._search_edit.returnPressed.connect(self._on_search)
        search_layout.addWidget(self._search_edit)

        self._category_filter = QComboBox()
        self._category_filter.setFixedWidth(190)
        self._category_filter.setStyleSheet(
            f"QComboBox {{ background-color: {_DARK_BG}; color: {_TEXT}; border: 1px solid {_BORDER};"
            f" border-radius: 2px; padding: 6px; font-size: 13px; font-family: 'Segoe UI'; }}"
        )
        self._category_filter.addItem("All Categories", None)
        for category in CategoryDAO.get_all_categories(include_inactive=True):
            label = category["category_name"] + (" (Inactive)" if not category.get("is_active") else "")
            self._category_filter.addItem(label, category["id"])
        search_layout.addWidget(self._category_filter)

        search_btn = QPushButton("Search")
        search_btn.setFixedWidth(90)
        search_btn.setStyleSheet(
            f"QPushButton {{ background-color: {_ACCENT}; color: white;"
            f"  border: none; border-radius: 2px; padding: 6px 16px;"
            f"  font-weight: bold; font-size: 13px; }}"
            f"QPushButton:hover {{ background-color: {_ACCENT_HOVER}; }}"
        )
        search_btn.clicked.connect(self._on_search)
        search_layout.addWidget(search_btn)

        search_layout.addStretch()

        root.addWidget(search_bar)

        # -- Table --
        self._table = QTableWidget()
        self._table.setColumnCount(9)
        self._table.setHorizontalHeaderLabels([
            "ID", "Item Name", "Unit", "Category", "Pack Size", "Company", "Pathy", "Tax Structure", "Reorder Level"
        ])
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(True)
        self._table.setAlternatingRowColors(False)
        self._table.setSortingEnabled(True)

        header_view = self._table.horizontalHeader()
        header_view.setStretchLastSection(True)
        header_view.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.Stretch)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(8, QHeaderView.ResizeToContents)
        header_view.setStyleSheet(
            f"QHeaderView::section {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: none; border-bottom: 2px solid {_ACCENT};"
            f"  padding: 4px 8px; font-weight: bold; font-size: 12px;"
            f"  font-family: 'Segoe UI';"
            f"}}"
        )
        self._table.setStyleSheet(
            f"QTableWidget {{"
            f"  background-color: {_DARK_BG}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; gridline-color: {_BORDER};"
            f"  font-size: 13px; font-family: 'Segoe UI';"
            f"  selection-background-color: {_ACCENT};"
            f"  selection-color: white;"
            f"}}"
            f"QTableWidget::item {{ padding: 2px 6px; }}"
        )

        root.addWidget(self._table, 1)
        self._refresh()

    def _refresh(self, items: list[dict] | None = None):
        if items is None:
            items = ItemDAO.get_all()
        self._table.setRowCount(len(items))
        for row, item in enumerate(items):
            self._table.setItem(row, 0, QTableWidgetItem(str(item["id"])))
            self._table.setItem(row, 1, QTableWidgetItem(item["item_name"]))
            self._table.setItem(row, 2, QTableWidgetItem(item.get("unit_name", "") or ""))
            self._table.setItem(row, 3, QTableWidgetItem(item.get("category_name", "") or ""))
            self._table.setItem(row, 4, QTableWidgetItem(item.get("pack_size", "")))
            self._table.setItem(row, 5, QTableWidgetItem(item.get("company_name", "") or ""))
            self._table.setItem(row, 6, QTableWidgetItem(item.get("pathy", "")))
            self._table.setItem(row, 7, QTableWidgetItem(_tax_cell_text(item.get("tax_structure"))))
            self._table.setItem(row, 8, QTableWidgetItem(str(item.get("reorder_stock_level", 0))))

    def _selected_item(self) -> dict | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        return {
            "id": int(self._table.item(row, 0).text()),
            "item_name": self._table.item(row, 1).text(),
        }

    def _on_new(self):
        dlg = _ItemDialog(self)
        dlg.exec()
        if dlg.was_saved:
            self._refresh()

    def _on_edit(self):
        item = self._selected_item()
        if not item:
            QMessageBox.information(
                self, "Edit Item", "Please select an item to edit."
            )
            return
        full_item = ItemDAO.get_by_id(item["id"])
        if not full_item:
            QMessageBox.warning(
                self, "Edit Item", "Could not load item data."
            )
            return
        dlg = _ItemDialog(self, item=full_item)
        dlg.exec()
        if dlg.was_saved:
            self._refresh()

    def _on_search(self):
        search_text = self._search_edit.text().strip()
        category_id = self._category_filter.currentData()
        if not search_text and category_id is None:
            self._refresh()
        else:
            items = ItemDAO.search(search_text, category_id)
            self._refresh(items)
