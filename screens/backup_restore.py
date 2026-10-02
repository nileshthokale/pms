from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
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


class BackupRestorePage(QWidget):
    """Backup & Restore page (Master → Backup & Restore).

    Backs up and restores ONLY the new application's SQLite database.
    Restore requires explicit confirmation and always creates a
    pre-restore safety backup first.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {_DARK_BG};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ───────────────────────────────────────────────
        header = QWidget()
        header.setFixedHeight(56)
        header.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)

        title = QLabel("Backup & Restore")
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
        body.setContentsMargins(16, 16, 16, 16)
        body.setSpacing(12)

        # Database info card
        db_card = QFrame()
        db_card.setStyleSheet(_CARD_STYLE)
        db_layout = QVBoxLayout(db_card)
        db_layout.setContentsMargins(14, 12, 14, 12)
        db_layout.setSpacing(4)
        db_layout.addWidget(self._title("Current Database"))
        self._db_path_lbl = self._value("")
        self._db_path_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        db_layout.addWidget(self._db_path_lbl)
        self._db_size_lbl = self._value("")
        db_layout.addWidget(self._db_size_lbl)
        body.addWidget(db_card)

        # Last backup card
        backup_card = QFrame()
        backup_card.setStyleSheet(_CARD_STYLE)
        bk_layout = QVBoxLayout(backup_card)
        bk_layout.setContentsMargins(14, 12, 14, 12)
        bk_layout.setSpacing(4)
        bk_layout.addWidget(self._title("Last Backup"))
        self._last_backup_lbl = self._value("No backup recorded yet.")
        self._last_backup_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bk_layout.addWidget(self._last_backup_lbl)
        self._last_backup_sha_lbl = self._value("")
        self._last_backup_sha_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bk_layout.addWidget(self._last_backup_sha_lbl)
        body.addWidget(backup_card)

        # Actions
        actions = QHBoxLayout()
        actions.setSpacing(10)

        create_btn = QPushButton("Create Backup")
        create_btn.setStyleSheet(_BTN_PRIMARY)
        create_btn.clicked.connect(self._on_create_backup)
        actions.addWidget(create_btn)

        validate_btn = QPushButton("Validate Backup")
        validate_btn.setStyleSheet(_BTN_SECONDARY)
        validate_btn.clicked.connect(self._on_validate_backup)
        actions.addWidget(validate_btn)

        actions.addStretch()

        restore_btn = QPushButton("Restore Backup")
        restore_btn.setStyleSheet(_BTN_DANGER)
        restore_btn.clicked.connect(self._on_restore_backup)
        actions.addWidget(restore_btn)
        body.addLayout(actions)

        note = QLabel(
            "Backups contain the complete pharmacy SQLite database "
            "(schema + all data). Restoring replaces the current "
            "application data and requires confirmation; a safety backup "
            "of the current database is created automatically first."
        )
        note.setStyleSheet(_NOTE_STYLE)
        note.setWordWrap(True)
        body.addWidget(note)
        body.addStretch()
        root.addLayout(body)

        self._refresh()

    # ------------------------------------------------------------------
    def _title(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_TITLE_STYLE)
        return lbl

    def _value(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_VALUE_STYLE)
        lbl.setWordWrap(True)
        return lbl

    def _refresh(self):
        info = get_database_info()
        self._db_path_lbl.setText(f"Location: {info['path']}")
        exists = "present" if info["exists"] else "NOT FOUND"
        self._db_size_lbl.setText(
            f"Size: {_format_size(info['size_bytes'])} · "
            f"Tables: {info['table_count']} · Status: {exists}"
        )

        last = get_last_backup_info()
        if last:
            self._last_backup_lbl.setText(
                f"File: {last.get('path', '')} · "
                f"Size: {_format_size(last.get('size_bytes', 0))} · "
                f"Created: {last.get('created_at', '')}"
            )
            self._last_backup_sha_lbl.setText(
                f"SHA-256: {last.get('sha256', '')}"
            )
        else:
            self._last_backup_lbl.setText("No backup recorded yet.")
            self._last_backup_sha_lbl.setText("")

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
