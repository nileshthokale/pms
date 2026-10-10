from __future__ import annotations

from PySide6.QtCore import QPointF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCompleter,
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
# Ingredient-row remove button.  Hover and pressed are *darker* than the
# resting fill (the previous #d32f2f was visibly lighter, so the state change
# read backwards).
_ERROR_HOVER = "#a3281c"
_ERROR_PRESSED = "#8c2118"
# Focus deepens the fill as well as drawing a white ring: the dialog behind
# the button is white, so a white ring on its own is close to invisible.
_ERROR_FOCUS = "#9c2b1e"

# Geometry of that button, in px.  The square is deliberately the same height
# as the Drug and Power controls beside it, so the row lines up.
_REMOVE_BTN_PX = 30
_REMOVE_GLYPH_PX = 14
_REMOVE_GLYPH_STROKE = 2.4
_REMOVE_TOOLTIP = "Remove ingredient"


def _tax_cell_text(item: dict) -> str:
    """Grid text for an item row.

    Provenance first: a non-NULL ``legacy_tax_id`` always shows the
    explicit mapping-required flag; otherwise the genuine GST label.
    """
    from database.tax_structures import resolve_tax_display

    return resolve_tax_display(item.get("tax_structure"), item.get("legacy_tax_id"))


_DRUG_POPUP_MAX_ROWS = 12
"""Rows the drug selector shows at once.

Twelve rows at the dialog's 13 px font stand roughly 280 px tall, so the
popup stays a compact list.  Before this cap the combo opened one row per
drug in the master, tall enough to cover most of the dialog.
"""

_DRUG_POPUP_MAX_WIDTH = 640
"""Hard ceiling for the drug popup, so no single name can span the screen.

640 px still fits the longest real drug names (45 chars at the dialog's
13 px font need ~590 px) inside a 1366 px window with room to spare.
"""


def _drug_combo_style() -> str:
    """Styling shared by the drug selector and the popup it opens."""
    return (
        f"QComboBox {{"
        f"  background-color: {_SURFACE}; color: {_TEXT};"
        f"  border: 1px solid {_BORDER}; border-radius: 2px;"
        f"  padding: 6px; font-size: 13px; font-family: 'Segoe UI';"
        f"}}"
        f"QComboBox:hover {{ border: 1px solid {_ACCENT}; }}"
        f"QComboBox::drop-down {{ border: none; width: 24px; }}"
        f"QComboBox::down-arrow {{ image: none; border: none; }}"
        # The editable field lives inside the combo: strip the boxed
        # QLineEdit look the dialog's own stylesheet would give it.
        f"QComboBox QLineEdit {{"
        f"  background: transparent; border: none; padding: 0px;"
        f"  color: {_TEXT}; font-size: 13px; font-family: 'Segoe UI';"
        f"}}"
    )


def _drug_popup_style(selector: str = "QAbstractItemView") -> str:
    """Dark list styling for the combo and completer popups."""
    return (
        f"{selector} {{"
        f"  background-color: {_SURFACE}; color: {_TEXT};"
        f"  border: 1px solid {_BORDER}; selection-background-color: {_ACCENT};"
        f"  selection-color: white; outline: none;"
        f"  font-size: 13px; font-family: 'Segoe UI';"
        f"}}"
    )


class _DrugComboBox(QComboBox):
    """Compact, searchable drug selector.

    A plain combo box holding the whole drug master opens a popup tall
    enough to cover the dialog.  This one is editable and carries a
    case-insensitive "contains" completer, so typing ``PARACET`` narrows the
    list to the matching drugs.  Both popups — the combo's own and the
    completer's — are capped at :data:`_DRUG_POPUP_MAX_ROWS` visible rows and
    are only as wide as the longest drug name they have to show.
    """

    drug_picked = Signal()
    """A drug was chosen from the popup, by mouse or by keyboard.

    Deliberately *not* ``currentIndexChanged``: that also fires for the
    programmatic ``setCurrentIndex`` in :meth:`select_drug`, which would make
    the dialog's drug-choice refresh re-enter itself.
    """

    def __init__(self, drugs: list[dict], parent=None):
        super().__init__(parent)
        self._drugs: list[dict] = []

        self.setMinimumWidth(200)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setMaxVisibleItems(_DRUG_POPUP_MAX_ROWS)
        self.setPlaceholderText("-- Select Drug --")
        if self.lineEdit() is not None:
            self.lineEdit().setPlaceholderText("-- Select Drug --")
            # Enter and focus-out must leave a real drug behind, never a
            # half-typed name that no longer matches the selected index.
            self.lineEdit().editingFinished.connect(self._sync_selection_to_text)
            self.lineEdit().textEdited.connect(self._filter_as_typed)
            # Navigation keys are handled in eventFilter(): the line edit
            # consumes Up/Down/Return itself, so they never reach the combo's
            # keyPressEvent via propagation.
            self.lineEdit().installEventFilter(self)

        # One model instance for the combo *and* the completer: the filter
        # and the selection therefore can never disagree.
        self._model = QStandardItemModel(self)
        self.setModel(self._model)

        completer = QCompleter(self._model, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.setMaxVisibleItems(_DRUG_POPUP_MAX_ROWS)
        self.setCompleter(completer)

        # Either popup can produce the pick — the combo's own list when the
        # arrow is clicked, the completer's when the user types.
        self.activated.connect(self._on_pick)
        completer.activated.connect(self._on_pick)

        self.setStyleSheet(
            _drug_combo_style() + _drug_popup_style("QComboBox QAbstractItemView")
        )
        popup = completer.popup()
        if popup is not None:
            popup.setStyleSheet(_drug_popup_style())
            popup.setObjectName("drug_completer_popup")

        self.set_drugs(drugs)

    # -- population ---------------------------------------------------

    def set_drugs(self, drugs: list[dict]) -> None:
        """Replace the offered drugs, keeping the current choice selected."""
        previous = self.currentData()
        self.dismiss_popup()
        self._drugs = list(drugs)
        self._model.clear()
        for drug in drugs:
            entry = QStandardItem(drug["drug_name"])
            entry.setData(drug["id"], Qt.ItemDataRole.UserRole)
            self._model.appendRow(entry)
        self._fit_popup_width()
        self.select_drug(previous)

    def select_drug(self, drug_id: int | None) -> None:
        """Show ``drug_id`` as the chosen drug, or clear the field."""
        index = -1
        if drug_id is not None:
            index = self.findData(drug_id, Qt.ItemDataRole.UserRole)
        if index >= 0:
            self.setCurrentIndex(index)
        else:
            # No selection: the greyed placeholder stands in for a drug.
            self.setCurrentIndex(-1)
            self.setEditText("")

    def drug_id(self) -> int | None:
        """The chosen drug's id, or ``None`` while nothing is chosen."""
        return self.currentData()

    def chosen_name(self) -> str:
        """The chosen drug's name, or ``""`` while nothing is chosen."""
        return self.currentText() if self.currentData() is not None else ""

    # -- popup behaviour ----------------------------------------------

    def _on_pick(self, *_args) -> None:
        """Relay a mouse or keyboard pick from either popup."""
        self.drug_picked.emit()

    def dismiss_popup(self) -> None:
        """Close the combo popup and the completer popup."""
        self.hidePopup()
        popup = self.completer().popup()
        if popup is not None:
            popup.hide()

    def _fit_popup_width(self) -> None:
        """Size the popup for the longest name it can show, and no wider."""
        metrics = self.fontMetrics()
        widest = max(
            (metrics.horizontalAdvance(drug["drug_name"]) for drug in self._drugs),
            default=0,
        )
        # Room for the selection highlight and the scrollbar gutter.
        width = min(widest + 40, _DRUG_POPUP_MAX_WIDTH)
        popup = self.completer().popup()
        if popup is not None:
            popup.setMinimumWidth(width)

    def _filter_as_typed(self, text: str) -> None:
        """Narrow the list as the user types, without losing the selection.

        Keeps the previously chosen drug selected while the filter is being
        edited; :meth:`_sync_selection_to_text` reconciles the index once the
        user commits the text with Enter or by leaving the field.
        """
        completer = self.completer()
        completer.setCompletionPrefix(text)
        if text:
            completer.complete()
        else:
            popup = completer.popup()
            if popup is not None:
                popup.hide()

    def _sync_selection_to_text(self) -> None:
        """Commit typed text onto an exactly-named drug, or clear the field.

        Matched manually and case-insensitively: Qt offers no
        case-insensitive fixed-string flag for ``findText``.
        """
        typed = self.currentText().strip().casefold()
        index = -1
        for row in range(self.count()):
            if self.itemText(row).strip().casefold() == typed:
                index = row
                break
        self.setCurrentIndex(index)
        if index < 0:
            self.setEditText("")

    def eventFilter(self, watched, event) -> bool:
        """Steer popup navigation keys pressed inside the line edit."""
        from PySide6.QtCore import QEvent

        if (watched is self.lineEdit()
                and event.type() == QEvent.Type.KeyPress
                and self._popup_key(event.key())):
            return True
        return super().eventFilter(watched, event)

    def _popup_key(self, key: int) -> bool:
        """Handle one navigation key against the visible popup, if any."""
        popup = self.completer().popup()
        if popup is None or not popup.isVisible():
            return False
        if key == Qt.Key.Key_Escape:
            self.dismiss_popup()
            return True
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            model = popup.model()
            count = model.rowCount() if model is not None else 0
            if count:
                step = 1 if key == Qt.Key.Key_Down else -1
                row = (popup.currentIndex().row() + step) % count
                popup.setCurrentIndex(model.index(row, 0))
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            index = popup.currentIndex()
            if index.isValid():
                self._commit_model_row(index)
                return True
        return False

    def keyPressEvent(self, event):
        """Keyboard-friendly popup: navigate, commit, or dismiss explicitly.

        Covers keys pressed while the combo itself (rather than its line
        edit) has focus; line-edit keys go through eventFilter instead.
        """
        if self._popup_key(event.key()):
            event.accept()
            return
        super().keyPressEvent(event)

    def _commit_model_row(self, proxy_index) -> None:
        """Commit a completion-list entry as the chosen drug.

        ``proxy_index`` belongs to the completer's (filtered proxy) model,
        so the drug id is read from the index itself — proxy row numbers do
        not match the full drug list.
        """
        drug_id = proxy_index.data(Qt.ItemDataRole.UserRole)
        self.dismiss_popup()
        self.select_drug(drug_id)
        self._on_pick()


def _remove_icon(size: int = _REMOVE_GLYPH_PX,
                 stroke: float = _REMOVE_GLYPH_STROKE,
                 colour: str = "#ffffff") -> QIcon:
    """The white ✕ for the ingredient remove button, painted into an icon.

    The glyph is *drawn* rather than set as the button caption on purpose.  A
    caption is laid out inside the button's contents rect, and the
    application stylesheet's global ``QPushButton { padding: 6px 14px; }``
    collapses that rect to zero width on a 30 px square: the red fill
    rendered, the "X" never did.  A painted icon is immune both to that
    inherited padding and to whether the platform's UI font happens to carry
    U+2715 MULTIPLICATION X.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(QColor(colour))
    pen.setWidthF(stroke)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    # Inset by half the stroke so the round caps stay inside the pixmap.
    inset = stroke / 2.0 + 0.5
    far = size - inset
    painter.drawLine(QPointF(inset, inset), QPointF(far, far))
    painter.drawLine(QPointF(far, inset), QPointF(inset, far))
    painter.end()
    return QIcon(pixmap)


def _remove_button_style() -> str:
    """Stylesheet for the ingredient remove button."""
    return (
        f"QPushButton {{"
        f"  background-color: {_ERROR};"
        f"  border: none; border-radius: 3px;"
        # Pinned to zero: the global QPushButton rule would otherwise reserve
        # 6px x 14px of a 30 px square for a caption that no longer exists.
        f"  padding: 0px; margin: 0px;"
        f"}}"
        f"QPushButton:hover {{ background-color: {_ERROR_HOVER}; }}"
        f"QPushButton:pressed {{ background-color: {_ERROR_PRESSED}; }}"
        f"QPushButton:focus {{"
        f"  background-color: {_ERROR_FOCUS};"
        f"  border: 2px solid #ffffff;"
        f"}}"
    )


class _IngredientRow(QWidget):
    """A single ingredient row with drug selector, power field, and delete button."""

    drug_changed = Signal()

    def __init__(self, drugs: list[dict], parent=None):
        super().__init__(parent)
        self._drugs = drugs

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.drug_combo = _DrugComboBox(drugs)
        self.drug_combo.drug_picked.connect(self._on_drug_activated)
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

        self.delete_btn = QPushButton()
        self.delete_btn.setIcon(_remove_icon())
        self.delete_btn.setIconSize(QSize(_REMOVE_GLYPH_PX, _REMOVE_GLYPH_PX))
        self.delete_btn.setFixedSize(_REMOVE_BTN_PX, _REMOVE_BTN_PX)
        self.delete_btn.setToolTip(_REMOVE_TOOLTIP)
        self.delete_btn.setAccessibleName(_REMOVE_TOOLTIP)
        self.delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_btn.setStyleSheet(_remove_button_style())
        layout.addWidget(self.delete_btn)

        layout.addStretch()

    def _on_drug_activated(self) -> None:
        """A drug was picked from the popup, by mouse or by keyboard."""
        self.drug_changed.emit()

    def set_drug_choices(self, drugs: list[dict]) -> None:
        """Offer ``drugs`` in this row, keeping its chosen drug selected."""
        self._drugs = drugs
        self.drug_combo.set_drugs(drugs)

    def get_data(self) -> dict | None:
        drug_id = self.drug_combo.drug_id()
        if drug_id is None:
            return None
        return {
            "drug_id": drug_id,
            "drug_name": self.drug_combo.chosen_name(),
            "power": self.power_edit.text().strip(),
        }


class _ItemDialog(QDialog):
    """Modal dialog for adding or editing an item."""

    def __init__(self, parent: QWidget | None = None, *, item: dict | None = None):
        super().__init__(parent)
        self._item = item
        self._saved = False
        self._ingredient_rows: list[_IngredientRow] = []
        # One read of the drug master for the whole dialog: the rows only
        # ever narrow this list, they never re-query it.
        self._all_drugs: list[dict] = DrugDAO.get_all()
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

        # Whether the user touched the tax dropdown since the dialog opened.
        # An untouched edit must preserve an EMPTY tax value (and provenance)
        # verbatim instead of falling through to the GST default selection.
        self._tax_touched = False
        self._tax_structure_combo.currentIndexChanged.connect(self._mark_tax_touched)

    def _mark_tax_touched(self, _index: int) -> None:
        self._tax_touched = True

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

    def _add_ingredient_row(self, drugs: list[dict] | None = None, power: str = ""):
        row = _IngredientRow(self._all_drugs)
        if power:
            row.power_edit.setText(power)
        if drugs:
            for d in drugs:
                row.drug_combo.select_drug(d["id"])
        row.drug_changed.connect(self._refresh_drug_choices)
        row.delete_btn.clicked.connect(lambda: self._remove_ingredient_row(row))
        self._ingredient_rows.append(row)
        self._ingredients_layout.addWidget(row)
        self._refresh_drug_choices()

    def _refresh_drug_choices(self):
        """Offer each row only the drugs no other row has taken.

        A drug can only be added to an item once, so a drug chosen in one row
        disappears from every other row's list.  A row's own current drug is
        always kept on offer: an item whose stored ingredients already
        contain a duplicate keeps showing — and keeps saving — exactly what
        is in the database, so editing an unrelated field cannot silently
        drop a stored ingredient.
        """
        chosen = []
        for row in self._ingredient_rows:
            data = row.get_data()
            chosen.append(data["drug_id"] if data else None)

        for index, row in enumerate(self._ingredient_rows):
            taken = {
                drug_id
                for position, drug_id in enumerate(chosen)
                if position != index and drug_id is not None
            }
            offer = [d for d in self._all_drugs if d["id"] not in taken]
            own = chosen[index]
            if own is not None and all(d["id"] != own for d in offer):
                offer.extend(d for d in self._all_drugs if d["id"] == own)
            row.set_drug_choices(offer)

    def _remove_ingredient_row(self, row: _IngredientRow):
        if row in self._ingredient_rows:
            self._ingredient_rows.remove(row)
            self._ingredients_layout.removeWidget(row)
            row.deleteLater()
            self._refresh_drug_choices()

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

        self._pack_size_edit.setText(item.get("pack_size", ""))
        self._select_tax_structure(item)
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

    def _select_tax_structure(self, item: dict) -> None:
        """Show an item's stored tax value without rewriting it.

        Provenance first: a non-NULL ``legacy_tax_id`` always gets its own
        flagged entry — even ``12`` — so the dialog never presents an
        unverified code as GST.  A NULL provenance selects the genuine GST
        entry.  Saving an unrelated field change keeps value and provenance
        exactly as they were.          Nothing is silently converted.
        """
        value = "" if item.get("tax_structure") is None else str(item.get("tax_structure")).strip()
        legacy = item.get("legacy_tax_id")
        if not value:
            self._tax_structure_combo.setCurrentIndex(
                self._tax_structure_combo.findData(DEFAULT_TAX_VALUE))
            return

        if legacy is not None:
            shown = str(legacy).strip()
            self._tax_structure_combo.addItem(legacy_display(shown or value), value)
            # The flagged entry is appended last; findData() could return an
            # earlier GST option sharing the same numeric data (e.g. '12').
            index = self._tax_structure_combo.count() - 1
            self._legacy_tax_index = index
            self._tax_structure_combo.setCurrentIndex(index)
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
        unit_id = self._unit_combo.currentData()
        if ItemDAO.name_exists(name, unit_id, exclude_id):
            QMessageBox.warning(
                self, "Validation", "An item with this name and unit already exists."
            )
            return

        company_id = self._company_combo.currentData()

        # Tax validation.  A NEW item may only be saved with one of the five
        # GST rates.  When EDITING an imported item, the original stored value
        # stays acceptable even though it is a legacy code, so opening an old
        # item and saving an unrelated field cannot fail or silently rewrite
        # its tax history.  Only an explicit choice of a different option
        # changes the value.
        tax_value = self._current_tax_value()
        original_tax = ""
        original_legacy = None
        if self._item:
            original_tax = str(self._item.get("tax_structure") or "").strip()
            original_legacy = self._item.get("legacy_tax_id")
        if self._item and not self._tax_touched:
            # Untouched edit: keep value and provenance byte-for-byte,
            # including EMPTY tax values that display the GST default.
            tax_value = original_tax
            new_legacy_tax_id = original_legacy
        else:
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

            if not self._item:
                new_legacy_tax_id = None
            elif tax_value != original_tax:
                # Deliberate conversion: the new GST value replaces the legacy
                # code, so provenance is cleared.  Nothing converts automatically.
                new_legacy_tax_id = None
            else:
                new_legacy_tax_id = original_legacy

        kwargs = {
            "item_name": name,
            "unit_id": unit_id,
            "company_id": company_id,
            # Item Master no longer edits Category, but ItemDAO.update always
            # writes the column.  Carry the stored value straight through, so
            # saving any other field leaves an existing item's category
            # exactly as it was; only a brand new item starts out blank.
            "category_id": self._item.get("category_id") if self._item else None,
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
            "legacy_tax_id": new_legacy_tax_id,
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
            self._table.setItem(row, 7, QTableWidgetItem(_tax_cell_text(item)))
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
        if not search_text:
            self._refresh()
        else:
            items = ItemDAO.search(search_text)
            self._refresh(items)
