"""Small, ID-backed autocomplete edit used by report filters.

Unlike an editable ``QComboBox`` this control never opens the complete master
list on click.  It only presents a compact completion list after the user has
typed a search term, and keeps the selected database ID separately from the
display text.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QAbstractItemView, QCompleter, QLineEdit

from ui.theme import palette


class SearchableFilterEdit(QLineEdit):
    """A compact contains-match autocomplete whose value is a master ID."""

    max_visible_rows = 12

    def __init__(self, placeholder: str, parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self._selected_id = None
        self._setting_text = False
        self._model = QStandardItemModel(self)
        self._completer = QCompleter(self._model, self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchContains)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._completer.setMaxVisibleItems(self.max_visible_rows)
        popup = self._completer.popup()
        popup.setMaximumHeight(self.max_visible_rows * 26 + 4)
        popup.setSelectionMode(QAbstractItemView.SingleSelection)
        popup.setFocusPolicy(Qt.NoFocus)
        self.setCompleter(self._completer)
        self.textEdited.connect(self._on_text_edited)
        self._completer.activated.connect(self._on_completion_activated)
        self.refresh_theme()

    @property
    def selected_id(self):
        return self._selected_id

    def set_options(self, rows: list[dict], id_key: str, text_key: str) -> None:
        """Replace candidates while preserving no stale selection."""
        self._model.clear()
        for row in rows:
            item = QStandardItem(str(row[text_key] or ""))
            item.setData(row[id_key], Qt.UserRole)
            self._model.appendRow(item)
        self.clear_filter()

    def clear_filter(self) -> None:
        self._selected_id = None
        self._setting_text = True
        self.clear()
        self._setting_text = False
        self._completer.popup().hide()

    def refresh_theme(self) -> None:
        p = palette()
        self.setStyleSheet(
            "QLineEdit {"
            f" background-color: {p['surface']}; color: {p['text']};"
            f" border: 1px solid {p['border']}; border-radius: 2px;"
            " padding: 5px 8px; font-size: 12px; font-family: 'Segoe UI';"
            "} QLineEdit:focus {"
            f" border: 1px solid {p['accent']};"
            "}"
        )
        self._completer.popup().setStyleSheet(
            "QAbstractItemView {"
            f" background-color: {p['surface']}; color: {p['text']};"
            f" border: 1px solid {p['border']};"
            f" selection-background-color: {p['accent']}; selection-color: white;"
            " font: 12px 'Segoe UI'; outline: 0;"
            "} QAbstractItemView::item { min-height: 24px; padding: 1px 6px; }"
        )

    def _on_text_edited(self, text: str) -> None:
        # A typed display value must never retain a previous record ID.
        if not self._setting_text:
            self._selected_id = None
        if text.strip():
            self._completer.setCompletionPrefix(text)
            self._completer.complete()
        else:
            self._completer.popup().hide()

    def _on_completion_activated(self, index) -> None:
        # PySide may emit either a QModelIndex or the completed text.
        if not hasattr(index, "data"):
            index = self._completer.popup().currentIndex()
        if not index.isValid():
            return
        self._selected_id = index.data(Qt.UserRole)
        self._setting_text = True
        self.setText(str(index.data(Qt.DisplayRole) or ""))
        self._setting_text = False
        self._completer.popup().hide()

    def keyPressEvent(self, event) -> None:
        popup = self._completer.popup()
        key = event.key()
        if key == Qt.Key_Escape and popup.isVisible():
            popup.hide()
            event.accept()
            return
        if key in (Qt.Key_Down, Qt.Key_Up) and self.text().strip():
            if not popup.isVisible():
                self._completer.setCompletionPrefix(self.text())
                self._completer.complete()
            count = self._completer.completionCount()
            if count:
                current = popup.currentIndex().row()
                if current < 0:
                    current = 0
                elif key == Qt.Key_Down:
                    current = min(current + 1, count - 1)
                else:
                    current = max(current - 1, 0)
                self._completer.setCurrentRow(current)
                popup.setCurrentIndex(self._completer.completionModel().index(current, 0))
            event.accept()
            return
        if key in (Qt.Key_Return, Qt.Key_Enter) and popup.isVisible():
            current = popup.currentIndex()
            if not current.isValid() and self._completer.completionCount():
                current = self._completer.completionModel().index(0, 0)
            if current.isValid():
                self._on_completion_activated(current)
            event.accept()
            return
        super().keyPressEvent(event)

