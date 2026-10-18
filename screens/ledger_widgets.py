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
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QLineEdit,
    QWidget,
)

from ui.components import ConstrainedComboBox, SearchableComboBox
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


class SearchableSelector(SearchableComboBox):
    """Searchable dropdown combo with case-insensitive contains-match autocomplete
    and master ID binding for Detailed Ledger reports.

    Inherits from the working SearchableComboBox implementation in ui.components,
    providing contains-match autocomplete, keyboard navigation, master ID binding,
    and text-to-ID validation.
    """

    def __init__(
        self,
        placeholder: str = "-- Select --",
        parent: QWidget | None = None,
        max_visible: int = 10,
        max_height: int = 280,
    ):
        super().__init__(
            parent,
            placeholder=placeholder,
            max_visible=max_visible,
            max_height=max_height,
        )

    def refresh_theme(self, p: dict | None = None) -> None:
        p = p or palette()
        super().refresh_theme(p)
        self.setStyleSheet(combo_style(p))

