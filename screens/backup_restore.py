"""Backup & Restore page (Master → Backup & Restore).

The backup/restore behaviour is unchanged: every operation still goes
through the ``database.backup_restore`` service, restore still requires
explicit confirmation and still creates the automatic pre-restore safety
backup first.

Only the presentation changed — the page is now a compact dashboard:

  * a page-header strip with a Refresh action,
  * two information cards (Current Database / Last Backup) each with a
    status chip,
  * three quick-action tiles (Create / Validate / Restore),
  * a safety note.

Every colour comes from the centralized ``ui.theme`` palette and the
custom styles are re-applied in place by ``refresh_theme()``, so a
Day/Night mode switch never leaves stale colours behind.
"""

from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from database.backup_restore import (
    BackupError,
    create_backup,
    get_database_info,
    get_last_backup_info,
    restore_backup,
    validate_backup,
)
from database.connection import get_db_path
from database import auth
from ui import components as ui
from ui.theme import palette

_p = palette()
_DARK_BG = _p["bg"]
_SURFACE = _p["surface"]
_BORDER = _p["border"]
_ACCENT = _p["accent"]
_ACCENT_HOVER = _p["accent_hover"]
_TEXT = _p["text"]
_TEXT_DIM = _p["text_dim"]

_DANGER = "#c62828"
_DANGER_HOVER = "#d32f2f"

# Shown in place of a missing value — e.g. no modified date, no SHA yet.
_DASH = "—"

_BTN_PRIMARY = (
    f"QPushButton {{ background-color: {_ACCENT}; color: white;"
    f"  border: none; border-radius: 2px; padding: 10px 22px;"
    f"  font-weight: bold; font-size: 13px; font-family: 'Segoe UI'; }}"
    f"QPushButton:hover {{ background-color: {_ACCENT_HOVER}; }}"
)

_BTN_DANGER = (
    f"QPushButton {{ background-color: {_DANGER}; color: white;"
    f"  border: none; border-radius: 2px; padding: 10px 22px;"
    f"  font-weight: bold; font-size: 13px; font-family: 'Segoe UI'; }}"
    f"QPushButton:hover {{ background-color: {_DANGER_HOVER}; }}"
)

_BTN_SECONDARY = (
    f"QPushButton {{ background-color: {_BORDER}; color: {_TEXT};"
    f"  border: none; border-radius: 2px; padding: 10px 22px;"
    f"  font-size: 13px; font-family: 'Segoe UI'; }}"
    f"QPushButton:hover {{ background-color: #7d93a8; }}"
)

_CARD_STYLE = (
    f"QFrame {{ background-color: {_SURFACE};"
    f"  border: 1px solid {_BORDER}; border-radius: 2px; }}"
)

_TITLE_STYLE = (
    f"color: {_TEXT}; font-size: 14px; font-weight: bold;"
    f"background: transparent; font-family: 'Segoe UI';"
)

_VALUE_STYLE = (
    f"color: {_TEXT_DIM}; font-size: 12px;"
    f"background: transparent; font-family: 'Segoe UI';"
)

_NOTE_STYLE = (
    f"color: {_TEXT_DIM}; font-size: 11px;"
    f"background: transparent; font-family: 'Segoe UI';"
)


def _format_size(size_bytes: int) -> str:
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} bytes"


def _readable_fg(fill: str) -> str:
    """Plain black or white text colour — whichever reads on ``fill``."""
    r, g, b = (int(fill[i:i + 2], 16) / 255 for i in (1, 3, 5))

    def _linear(channel: float) -> float:
        if channel <= 0.03928:
            return channel / 12.92
        return ((channel + 0.055) / 1.055) ** 2.4

    # WCAG relative luminance; 0.179 is where black and white contrast tie.
    luminance = (
        0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)
    )
    return "#000000" if luminance > 0.179 else "#ffffff"


def _mix(color_a: str, color_b: str, t: float) -> str:
    """Blend ``color_a`` towards ``color_b`` (0..1); #rrggbb in and out."""
    a = tuple(int(color_a[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(color_b[i:i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(
        f"{round(ca + (cb - ca) * t):02x}" for ca, cb in zip(a, b)
    )


def _format_stamp(stamp: datetime) -> str:
    """"16 Oct 2026 · 02:05 PM" — friendly date + time."""
    return (f"{stamp.day} {stamp.strftime('%b %Y')} · "
            f"{stamp.strftime('%I:%M %p')}")


def _format_created(value) -> str:
    """ISO timestamp → friendly stamp (raw text as fallback)."""
    text = str(value or "").strip()
    if not text:
        return _DASH
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return text
    return _format_stamp(stamp)


# ── reusable pieces ───────────────────────────────────────────────────

class _Badge(QLabel):
    """Small rounded initials chip shown in an information-card header."""

    def __init__(self, text: str, role: str = "accent",
                 parent: QWidget | None = None):
        super().__init__(text, parent)
        self._role = role
        self.setFixedSize(26, 26)
        self.setAlignment(Qt.AlignCenter)

    def apply_style(self, p: dict) -> None:
        fill = p.get(self._role, p["accent"])
        self.setStyleSheet(
            f"background-color: {fill}; color: {_readable_fg(fill)};"
            "border-radius: 7px; font-weight: bold;"
            "font-size: 11px; font-family: 'Segoe UI';"
        )


class _StatusPill(QLabel):
    """Rounded status chip — "Present", "Available", "Not Found", …"""

    _ROLES = {
        "success": "success",
        "danger": "danger",
        "warning": "warning",
        "info": "accent",
    }

    def __init__(self, parent: QWidget | None = None):
        super().__init__("", parent)
        self._level = "info"
        self.setAlignment(Qt.AlignCenter)

    def set_status(self, text: str, level: str = "info") -> None:
        self._level = level if level in self._ROLES else "info"
        self.setText(text)
        self.apply_style(palette())

    def apply_style(self, p: dict) -> None:
        fill = p.get(self._ROLES[self._level], p["accent"])
        self.setStyleSheet(
            f"background-color: {fill}; color: {_readable_fg(fill)};"
            "border-radius: 10px; padding: 2px 10px; font-weight: bold;"
            "font-size: 11px; font-family: 'Segoe UI';"
        )


class _InfoCard(QFrame):
    """White information card: badge + title + status chip, then rows."""

    def __init__(self, title: str, badge_text: str,
                 badge_role: str = "accent", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("InfoCard")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 13, 16, 15)
        outer.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(10)
        self.badge = _Badge(badge_text, badge_role)
        head.addWidget(self.badge)
        self.title = QLabel(title)
        head.addWidget(self.title)
        head.addStretch()
        self.pill = _StatusPill()
        head.addWidget(self.pill)
        outer.addLayout(head)

        self.divider = QFrame()
        self.divider.setFixedHeight(1)
        outer.addWidget(self.divider)

        self._captions: list[QLabel] = []
        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(14)
        self._grid.setVerticalSpacing(9)
        self._grid.setColumnMinimumWidth(0, 100)
        self._grid.setColumnStretch(1, 1)
        outer.addLayout(self._grid)

    def add_row(self, caption: str, widget: QWidget, *,
                selectable: bool = False) -> QWidget:
        label = QLabel(caption.upper())
        self._captions.append(label)
        row = self._grid.rowCount()
        self._grid.addWidget(label, row, 0, Qt.AlignLeft | Qt.AlignTop)
        if selectable:
            widget.setTextInteractionFlags(Qt.TextSelectableByMouse)
        widget.setWordWrap(True)
        self._grid.addWidget(widget, row, 1, Qt.AlignTop)
        return widget

    def apply_style(self, p: dict) -> None:
        self.setStyleSheet(
            f"#InfoCard {{ background-color: {p['bg']};"
            f"  border: 1px solid {p['border']}; border-radius: 8px; }}"
        )
        self.badge.apply_style(p)
        self.title.setStyleSheet(ui.section_title_style())
        self.divider.setStyleSheet(
            f"background-color: {p['border']}; border: none;"
        )
        for label in self._captions:
            label.setStyleSheet(ui.label_style(dim=True, size=12))
        self.pill.apply_style(p)


class _ActionCard(QFrame):
    """Quick-action tile: coloured dot + title, description, button."""

    def __init__(self, title: str, description: str, button: QWidget,
                 dot_role: str = "accent", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("ActionCard")
        self._dot_role = dot_role

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.dot = QLabel()
        self.dot.setFixedSize(10, 10)
        head.addWidget(self.dot)
        self.title = QLabel(title)
        head.addWidget(self.title)
        head.addStretch()
        outer.addLayout(head)

        self.description = QLabel(description)
        self.description.setWordWrap(True)
        outer.addWidget(self.description)

        outer.addStretch()
        outer.addWidget(button)

    def apply_style(self, p: dict) -> None:
        self.setStyleSheet(
            f"#ActionCard {{ background-color: {p['bg']};"
            f"  border: 1px solid {p['border']}; border-radius: 8px; }}"
        )
        fill = p.get(self._dot_role, p["accent"])
        self.dot.setStyleSheet(
            f"background-color: {fill}; border-radius: 5px;"
        )
        self.title.setStyleSheet(ui.label_style(bold=True, size=14))
        self.description.setStyleSheet(ui.label_style(dim=True, size=12))


# ── the page ──────────────────────────────────────────────────────────

class BackupRestorePage(QWidget):
    """Backup & Restore page (Master → Backup & Restore).

    Backs up and restores ONLY the new application's SQLite database.
    Restore requires explicit confirmation and always creates a
    pre-restore safety backup first.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ───────────────────────────────────────────────
        header = QWidget()
        self._header = header
        header.setFixedHeight(56)
        header.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)

        title = QLabel("Backup & Restore")
        self._header_title = title
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 18px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        hl.addWidget(title)
        hl.addStretch()

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setStyleSheet(_BTN_SECONDARY)
        refresh_btn.clicked.connect(self._refresh)
        hl.addWidget(refresh_btn)
        root.addWidget(header)

        # ── Body ─────────────────────────────────────────────────
        body = QVBoxLayout()
        body.setContentsMargins(18, 16, 18, 16)
        body.setSpacing(14)
        root.addLayout(body)

        # Information cards: current database / last backup.
        cards = QHBoxLayout()
        cards.setSpacing(14)

        self._db_card = _InfoCard("Current Database", "DB", "accent")
        self._db_path_lbl = self._db_card.add_row(
            "Location", QLabel(""), selectable=True
        )
        self._db_size_lbl = self._db_card.add_row("Overview", QLabel(""))
        self._db_modified_lbl = self._db_card.add_row("Modified", QLabel(""))
        cards.addWidget(self._db_card, 1)

        self._backup_card = _InfoCard("Last Backup", "BK", "warning")
        self._last_backup_lbl = self._backup_card.add_row(
            "File", QLabel(""), selectable=True
        )
        self._last_backup_size_lbl = self._backup_card.add_row(
            "Size", QLabel("")
        )
        self._last_backup_created_lbl = self._backup_card.add_row(
            "Created", QLabel("")
        )
        self._last_backup_sha_lbl = self._backup_card.add_row(
            "SHA-256", QLabel(""), selectable=True
        )
        cards.addWidget(self._backup_card, 1)
        body.addLayout(cards)

        # Quick actions.
        self._actions_title = QLabel("Quick Actions")
        body.addWidget(self._actions_title)

        actions = QHBoxLayout()
        actions.setSpacing(14)

        self._create_btn = ui.ActionButton("Create Backup", "primary",
                                           height=34)
        self._create_btn.setToolTip(
            "Save the complete pharmacy database to a file you choose"
        )
        self._create_btn.clicked.connect(self._on_create_backup)
        create_card = _ActionCard(
            "Create Backup",
            "Save the complete pharmacy database to a file you choose. "
            "Safe to run at any time — the current data is never changed.",
            self._create_btn, "accent",
        )

        self._validate_btn = ui.ActionButton("Validate Backup", "secondary",
                                             height=34)
        self._validate_btn.setToolTip(
            "Check that a backup file is complete and safe to restore"
        )
        self._validate_btn.clicked.connect(self._on_validate_backup)
        validate_card = _ActionCard(
            "Validate Backup",
            "Check that a backup file is complete, intact and safe to "
            "restore. Validation never changes any data.",
            self._validate_btn, "success",
        )

        self._restore_btn = ui.ActionButton("Restore Backup", "danger",
                                            height=34)
        self._restore_btn.setToolTip(
            "Replace all current application data with a validated backup"
        )
        self._restore_btn.clicked.connect(self._on_restore_backup)
        restore_card = _ActionCard(
            "Restore Backup",
            "Replace all current application data with a validated backup "
            "file you select.",
            self._restore_btn, "danger",
        )

        self._action_cards = [create_card, validate_card, restore_card]
        for card in self._action_cards:
            actions.addWidget(card, 1)
        body.addLayout(actions)

        # Safety note.
        self._note = QFrame()
        self._note.setObjectName("NoteBar")
        note_layout = QHBoxLayout(self._note)
        note_layout.setContentsMargins(14, 10, 14, 10)
        self._note_label = QLabel("")
        self._note_label.setWordWrap(True)
        note_layout.addWidget(self._note_label)
        body.addWidget(self._note)

        body.addStretch()

        self._apply_styles()
        self._refresh()

    # ------------------------------------------------------------------
    def _apply_styles(self) -> None:
        """Apply every custom colour from the live centralized palette."""
        p = palette()

        self.setStyleSheet(f"background-color: {p['surface_alt']};")

        # Header strip and title follow the live palette too.
        self._header.setStyleSheet(
            f"background-color: {p['surface']};"
            f"border-bottom: 1px solid {p['border']};"
        )
        self._header_title.setStyleSheet(
            f"color: {p['text']}; font-size: 18px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )

        self._db_card.apply_style(p)
        self._backup_card.apply_style(p)

        value_style = ui.label_style(size=13)
        for label in (
            self._db_path_lbl,
            self._db_size_lbl,
            self._db_modified_lbl,
            self._last_backup_lbl,
            self._last_backup_size_lbl,
            self._last_backup_created_lbl,
        ):
            label.setStyleSheet(value_style)
        self._last_backup_sha_lbl.setStyleSheet(ui.label_style(dim=True, size=12))

        self._actions_title.setStyleSheet(ui.section_title_style())
        for card in self._action_cards:
            card.apply_style(p)

        self._note.setStyleSheet(
            f"#NoteBar {{"
            f"  background-color: {_mix(p['bg'], p['warning'], 0.07)};"
            f"  border: 1px solid {_mix(p['border'], p['warning'], 0.35)};"
            f"  border-left: 4px solid {p['warning']};"
            "  border-radius: 8px;"
            "}"
        )
        self._note_label.setStyleSheet(
            f"font-size: 12px; font-family: 'Segoe UI';"
            "background: transparent;"
        )
        self._note_label.setText(
            f'<b style="color: {p["text"]}">Good to know:</b>'
            f'<span style="color: {p["text_dim"]}"> Restoring replaces all '
            "current application data. Every backup is validated before a "
            "restore, and a safety backup of the current database is "
            "created automatically before anything is replaced.</span>"
        )

    def refresh_theme(self) -> None:
        """Re-apply the live centralized palette (Day/Night switch)."""
        self._apply_styles()
        self._refresh()

    # ------------------------------------------------------------------
    def _refresh(self):
        info = get_database_info()
        self._db_path_lbl.setText(info["path"])
        self._db_size_lbl.setText(
            f"Size: {_format_size(info['size_bytes'])} · "
            f"Tables: {info['table_count']}"
        )
        if info["exists"]:
            self._db_card.pill.set_status("Present", "success")
            try:
                modified = _format_stamp(
                    datetime.fromtimestamp(os.path.getmtime(info["path"]))
                )
            except OSError:
                modified = _DASH
        else:
            self._db_card.pill.set_status("Not Found", "danger")
            modified = _DASH
        self._db_modified_lbl.setText(modified)

        last = get_last_backup_info()
        if last:
            self._last_backup_lbl.setText(last.get("path", "") or _DASH)
            try:
                size = int(last.get("size_bytes") or 0)
            except (TypeError, ValueError):
                size = 0
            self._last_backup_size_lbl.setText(_format_size(size))
            self._last_backup_created_lbl.setText(
                _format_created(last.get("created_at", ""))
            )
            self._last_backup_sha_lbl.setText(last.get("sha256") or _DASH)
            self._backup_card.pill.set_status("Available", "success")
        else:
            self._last_backup_lbl.setText("No backup recorded yet.")
            self._last_backup_size_lbl.setText(_DASH)
            self._last_backup_created_lbl.setText(_DASH)
            self._last_backup_sha_lbl.setText(_DASH)
            self._backup_card.pill.set_status("None Yet", "warning")

    # ------------------------------------------------------------------
    def _on_create_backup(self):
        try:
            auth.session.require(auth.PERM_BACKUP)
        except auth.PermissionDenied as exc:
            QMessageBox.warning(self, "Permission denied", str(exc)); return
        default_name = (
            "pharmacy_backup_"
            + datetime.now().strftime("%Y%m%d_%H%M%S")
            + ".db"
        )
        default_dir = os.path.dirname(os.path.abspath(get_db_path()))
        path, _ = QFileDialog.getSaveFileName(
            self, "Create Backup", os.path.join(default_dir, default_name),
            "SQLite Database (*.db)",
        )
        if not path:
            return
        try:
            info = create_backup(path)
        except BackupError as e:
            QMessageBox.critical(self, "Backup Failed", str(e))
            return
        QMessageBox.information(
            self,
            "Backup Created",
            f"Backup created successfully.\n\n"
            f"File: {info['path']}\n"
            f"Size: {_format_size(info['size_bytes'])}\n"
            f"SHA-256: {info['sha256']}",
        )
        self._refresh()

    def _on_validate_backup(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Validate Backup", "",
            "SQLite Database (*.db);;All Files (*)",
        )
        if not path:
            return
        result = validate_backup(path)
        if result["valid"]:
            QMessageBox.information(
                self,
                "Backup Valid",
                f"The backup is valid.\n\n"
                f"File: {result['path']}\n"
                f"Size: {_format_size(result['size_bytes'])}\n"
                f"Tables: {len(result['tables'])}\n"
                f"Integrity: {result['integrity']}\n"
                f"SHA-256: {result['sha256']}",
            )
        else:
            QMessageBox.warning(
                self,
                "Backup Invalid",
                f"This file is not a valid pharmacy backup.\n\n"
                f"Reason: {result['reason']}",
            )

    def _on_restore_backup(self):
        try:
            auth.session.require(auth.PERM_RESTORE)
        except auth.PermissionDenied as exc:
            QMessageBox.warning(self, "Permission denied", str(exc)); return
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Backup to Restore", "",
            "SQLite Database (*.db);;All Files (*)",
        )
        if not path:
            return

        # 1. Validate first — never restore an invalid file
        result = validate_backup(path)
        if not result["valid"]:
            QMessageBox.warning(
                self,
                "Restore Refused",
                f"The selected file is not a valid pharmacy backup and "
                f"will NOT be restored.\n\nReason: {result['reason']}",
            )
            return

        # 2. Strong explicit confirmation
        answer = QMessageBox.warning(
            self,
            "Confirm Restore",
            "RESTORE WILL REPLACE ALL CURRENT APPLICATION DATA.\n\n"
            f"Restore from:\n{result['path']}\n\n"
            f"Created size: {_format_size(result['size_bytes'])}\n"
            f"SHA-256: {result['sha256']}\n\n"
            "A safety backup of the current database will be created "
            "automatically before restoring.\n\n"
            "Do you want to continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        # 3. Restore (service creates the pre-restore safety backup)
        try:
            outcome = restore_backup(path)
        except BackupError as e:
            QMessageBox.critical(self, "Restore Failed", str(e))
            self._refresh()
            return

        QMessageBox.information(
            self,
            "Restore Complete",
            f"Database restored successfully.\n\n"
            f"Restored from: {outcome['source']}\n"
            f"Safety backup of the previous data: {outcome['safety_backup']}\n\n"
            "If the application shows outdated data, please restart the "
            "application.",
        )
        self._refresh()
