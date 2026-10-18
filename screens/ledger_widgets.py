"""Reusable UI widgets and styling helpers for Detailed Ledger reports.

Provides:
- SearchableSelector: Editable, searchable combo box with contains-match autocomplete
  and master ID binding.
- make_date_edit: QDateEdit with visible calendar button and proper theme styling.
- Style helpers for buttons, summary cards, and tables.
"""

from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCompleter,
    QDateEdit,
    QLineEdit,
    QWidget,
)

from ui.components import ConstrainedComboBox
from ui.theme import date_subcontrols, palette, TYPE_INPUT


def combo_style(p: dict | None = None) -> str:
    p = p or palette()
    surface = p["surface"]
    text = p["text"]
    border = p["border"]
    accent = p["accent"]
    return (
        f"QComboBox {{"
        f"  background-color: {surface}; color: {text};"
        f"  border: 1px solid {border}; border-radius: 2px;"
        f"  padding: 4px 8px; font-size: 15px; font-family: 'Segoe UI';"
        f"}}"
        f"QComboBox:hover {{ border: 1px solid {accent}; }}"
        f"QComboBox::drop-down {{ border-left: 1px solid {border}; width: 22px; background: {surface}; }}"
        f"QComboBox QAbstractItemView {{"
        f"  background-color: {surface}; color: {text};"
        f"  border: 1px solid {border}; selection-background-color: {accent};"
        f"  selection-color: white; font-size: 15px; font-family: 'Segoe UI';"
        f"}}"
    )


def date_edit_style(p: dict | None = None) -> str:
    p = p or palette()
    surface = p["surface"]
    text = p["text"]
    border = p["border"]
    focus = p.get("focus", p["accent"])
    return (
        f"QDateEdit {{"
        f"  background-color: {surface}; color: {text};"
        f"  border: 1px solid {border}; border-radius: 2px;"
        f"  padding: 4px 6px; font-size: 15px; font-family: 'Segoe UI';"
        f"}}"
        f"QDateEdit:focus {{ border: 1px solid {focus}; }}"
        + date_subcontrols(p, width=22)
    )


def btn_primary_style(p: dict | None = None) -> str:
    p = p or palette()
    accent = p["accent"]
    accent_hover = p["accent_hover"]
    return (
        f"QPushButton {{ background-color: {accent}; color: white;"
        f"  border: none; border-radius: 2px; padding: 6px 16px;"
        f"  font-weight: bold; font-size: 14px; font-family: 'Segoe UI'; }}"
        f"QPushButton:hover {{ background-color: {accent_hover}; }}"
        f"QPushButton:pressed {{ background-color: {p.get('accent_pressed', accent)}; }}"
    )


def btn_secondary_style(p: dict | None = None) -> str:
    p = p or palette()
    border = p["border"]
    text = p["text"]
    text_dim = p.get("text_dim", "#7d93a8")
    return (
        f"QPushButton {{ background-color: {border}; color: {text};"
        f"  border: none; border-radius: 2px; padding: 6px 14px;"
        f"  font-size: 14px; font-family: 'Segoe UI'; }}"
        f"QPushButton:hover {{ background-color: {text_dim}; color: white; }}"
    )


def table_style(p: dict | None = None) -> str:
    p = p or palette()
    bg = p["bg"]
    text = p["text"]
    border = p["border"]
    accent = p["accent"]
    return (
        f"QTableWidget {{"
        f"  background-color: {bg}; color: {text};"
        f"  border: 1px solid {border}; gridline-color: {border};"
        f"  font-size: 14px; font-family: 'Segoe UI';"
        f"  selection-background-color: {accent}; selection-color: white;"
        f"}}"
        f"QTableWidget::item {{ padding: 3px 6px; }}"
    )


def table_header_style(p: dict | None = None) -> str:
    p = p or palette()
    surface = p["surface"]
    text = p["text"]
    accent = p["accent"]
    return (
        f"QHeaderView::section {{"
        f"  background-color: {surface}; color: {text};"
        f"  border: none; border-bottom: 2px solid {accent};"
        f"  padding: 4px 8px; font-weight: bold; font-size: 14px;"
        f"  font-family: 'Segoe UI';"
        f"}}"
    )


def make_date_edit(parent: QWidget | None = None, p: dict | None = None) -> QDateEdit:
    """Create a styled QDateEdit with visible calendar button and dd-MM-yyyy format."""
    d = QDateEdit(parent)
    d.setCalendarPopup(True)
    d.setDisplayFormat("dd-MM-yyyy")
    d.setStyleSheet(date_edit_style(p))
    d.setFixedHeight(32)
    return d


class SearchableSelector(ConstrainedComboBox):
    """Searchable dropdown combo with case-insensitive contains-match completer.

    Works both as an interactive dropdown (clicking arrow shows options)
    and as an autocomplete field (typing filters the candidate list).
    """

    selection_changed = Signal(object)  # emits selected ID or None

    def __init__(
        self,
        placeholder: str = "-- Select --",
        parent: QWidget | None = None,
        max_visible: int = 10,
        max_height: int = 280,
    ):
        super().__init__(
            parent,
            max_visible_items=max_visible,
            max_popup_height=max_height,
        )
        self.setEditable(True)
        self.setInsertPolicy(ConstrainedComboBox.NoInsert)
        self.setFixedHeight(32)

        self._placeholder = placeholder
        self._id_map: dict[str, Any] = {}
        self._reverse_map: dict[Any, int] = {}  # id -> combo index

        line = self.lineEdit()
        if line is not None:
            line.setPlaceholderText(placeholder)
            line.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            line.editingFinished.connect(self._on_editing_finished)

        self._completer = QCompleter(self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchContains)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._completer.setMaxVisibleItems(max_visible)
        popup = self._completer.popup()
        if popup is not None:
            popup.setMaximumHeight(max_height)
            popup.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            popup.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setCompleter(self._completer)
        self._completer.activated[str].connect(self._on_completer_activated)

        self.currentIndexChanged.connect(self._on_index_changed)
        self.refresh_theme()

    def set_options(
        self,
        rows: list[dict],
        id_key: str = "id",
        name_key: str = "name",
        subtitle_key: str | None = None,
    ) -> None:
        """Populate options with id, display name, and optional subtitle."""
        self.blockSignals(True)
        self.clear()
        self._id_map.clear()
        self._reverse_map.clear()

        # Item 0 is empty placeholder
        self.addItem(self._placeholder, None)
        self._reverse_map[None] = 0

        for idx, row in enumerate(rows, start=1):
            name = str(row.get(name_key) or "").strip()
            item_id = row.get(id_key)
            if subtitle_key and row.get(subtitle_key):
                display = f"{name}  [{row[subtitle_key]}]"
            else:
                display = name

            self.addItem(display, item_id)
            self._id_map[display.casefold()] = item_id
            self._id_map[name.casefold()] = item_id
            self._reverse_map[item_id] = idx

        self.setCurrentIndex(0)
        self.blockSignals(False)

        line = self.lineEdit()
        if line is not None:
            line.clear()

    @property
    def selected_id(self) -> Any:
        return self.currentData()

    @property
    def selected_name(self) -> str:
        idx = self.currentIndex()
        if idx <= 0:
            return ""
        return self.currentText()

    def set_selected_id(self, item_id: Any) -> None:
        if item_id in self._reverse_map:
            idx = self._reverse_map[item_id]
            self.setCurrentIndex(idx)
        else:
            self.setCurrentIndex(0)

    def clear_selection(self) -> None:
        self.setCurrentIndex(0)
        line = self.lineEdit()
        if line is not None:
            line.clear()

    def _on_completer_activated(self, text: str) -> None:
        idx = self.findText(text)
        if idx >= 0:
            self.setCurrentIndex(idx)

    def _on_editing_finished(self) -> None:
        text = self.currentText().strip()
        if not text or text == self._placeholder:
            self.setCurrentIndex(0)
            return
        idx = self.findText(text, Qt.MatchFixedString | Qt.MatchCaseSensitive)
        if idx < 0:
            idx = self.findText(text, Qt.MatchContains)
        if idx >= 0:
            self.setCurrentIndex(idx)
        else:
            # Fall back to matched ID if known
            folded = text.casefold()
            if folded in self._id_map:
                self.set_selected_id(self._id_map[folded])

    def _on_index_changed(self, index: int) -> None:
        self.selection_changed.emit(self.currentData())

    def refresh_theme(self, p: dict | None = None) -> None:
        p = p or palette()
        self.setStyleSheet(combo_style(p))
        line = self.lineEdit()
        if line is not None:
            line.setStyleSheet(
                f"QLineEdit {{"
                f"  background-color: {p['surface']}; color: {p['text']};"
                f"  border: none; padding: 2px 4px; font-size: 15px;"
                f"  font-family: 'Segoe UI'; font-weight: bold;"
                f"}}"
            )
        popup = self._completer.popup()
        if popup is not None:
            popup.setStyleSheet(
                f"QAbstractItemView {{"
                f"  background-color: {p['surface']}; color: {p['text']};"
                f"  border: 1px solid {p['border']}; selection-background-color: {p['accent']};"
                f"  selection-color: white; font-size: {TYPE_INPUT}px; font-family: 'Segoe UI';"
                f"}}"
                f"QAbstractItemView::item {{ min-height: 24px; padding: 2px 6px; }}"
            )
