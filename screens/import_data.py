from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from database import auth, import_service
from ui import components as ui
from ui.theme import FONT_FAMILY, FONT_NAME, palette


# ── Step Indicator Bar ────────────────────────────────────────────────────────

class StepIndicatorBar(QFrame):
    """Clean, horizontal 4-step wizard progress indicator."""

    step_clicked = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("StepIndicatorBar")
        self._current_step = 0
        self._completed_steps: set[int] = set()

        self._steps = [
            ("1", "Choose Master"),
            ("2", "Select File"),
            ("3", "Match Columns"),
            ("4", "Review & Import"),
        ]

        self._buttons: list[QPushButton] = []
        self._arrows: list[QLabel] = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        for i, (num, label) in enumerate(self._steps):
            btn = QPushButton(f"  {num}  {label}  ")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, idx=i: self._on_step_click(idx))
            self._buttons.append(btn)
            layout.addWidget(btn)

            if i < len(self._steps) - 1:
                arrow = QLabel("→")
                arrow.setAlignment(Qt.AlignCenter)
                self._arrows.append(arrow)
                layout.addWidget(arrow)

        layout.addStretch()
        self.refresh_theme()

    def set_step(self, current: int, completed: set[int] | None = None) -> None:
        self._current_step = current
        if completed is not None:
            self._completed_steps = set(completed)
        self.refresh_theme()

    def _on_step_click(self, index: int) -> None:
        # User can navigate to current step, any completed step, or Step 0/1
        if index <= max(self._completed_steps, default=0) + 1 or index <= self._current_step:
            self.step_clicked.emit(index)

    def refresh_theme(self, p: dict[str, str] | None = None) -> None:
        p = p or palette()
        self.setStyleSheet(
            f"#StepIndicatorBar {{ background-color: {p['surface_alt']};"
            f" border-bottom: 1px solid {p['border']}; }}"
        )

        for i, btn in enumerate(self._buttons):
            num, label = self._steps[i]
            is_active = (i == self._current_step)
            is_done = (i in self._completed_steps)
            can_click = (i <= max(self._completed_steps, default=0) + 1 or i <= self._current_step)

            if is_done and not is_active:
                btn.setText(f"  ✓  {label}  ")
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: {p['surface']}; color: {p['success']};"
                    f" border: 1px solid {p['success']}; border-radius: 14px;"
                    f" font-weight: bold; font-size: 12px; padding: 4px 10px; }}"
                    f"QPushButton:hover {{ background-color: {p['selected']}; }}"
                )
                btn.setEnabled(True)
            elif is_active:
                btn.setText(f"  {num}  {label}  ")
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: {p['accent']}; color: #ffffff;"
                    f" border: 1px solid {p['accent_hover']}; border-radius: 14px;"
                    f" font-weight: bold; font-size: 12px; padding: 4px 12px; }}"
                )
                btn.setEnabled(True)
            else:
                btn.setText(f"  {num}  {label}  ")
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: transparent; color: {p['text_dim']};"
                    f" border: 1px dashed {p['border']}; border-radius: 14px;"
                    f" font-size: 12px; padding: 4px 10px; }}"
                    f"QPushButton:hover {{ border-color: {p['accent']}; color: {p['text']}; }}"
                )
                btn.setEnabled(can_click)

        for arrow in self._arrows:
            arrow.setStyleSheet(f"color: {p['text_dim']}; font-weight: bold; font-size: 13px;")


# ── Metric Dashboard Card ────────────────────────────────────────────────────

class MetricCard(QFrame):
    """Compact summary card displaying a single validation metric."""

    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("MetricCard")
        self._title_text = title
        self._color_role = "neutral"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        self._value_lbl = QLabel("0")
        self._value_lbl.setAlignment(Qt.AlignCenter)
        self._value_lbl.setFont(ui.readable_font(20, bold=True))
        layout.addWidget(self._value_lbl)

        self._title_lbl = QLabel(title.upper())
        self._title_lbl.setAlignment(Qt.AlignCenter)
        self._title_lbl.setFont(ui.readable_font(10, bold=True))
        layout.addWidget(self._title_lbl)

        self.refresh_theme()

    def set_value(self, val: int | str, color_role: str = "neutral") -> None:
        self._value_lbl.setText(str(val))
        self._color_role = color_role
        self.refresh_theme()

    def refresh_theme(self, p: dict[str, str] | None = None) -> None:
        p = p or palette()
        self.setStyleSheet(
            f"#MetricCard {{ background-color: {p['surface']};"
            f" border: 1px solid {p['border']}; border-radius: 4px; }}"
        )
        self._title_lbl.setStyleSheet(f"color: {p['text_dim']};")

        color_map = {
            "neutral": p["text"],
            "success": p["success"],
            "danger": p["danger"],
            "warning": p["warning"],
        }
        val_color = color_map.get(self._color_role, p["text"])
        self._value_lbl.setStyleSheet(f"color: {val_color};")


# ── Collapsible Advanced Options Section ─────────────────────────────────────

class CollapsibleSection(QWidget):
    """Toggleable collapsible panel for Advanced Options."""

    def __init__(self, title: str = "Advanced Options", parent: QWidget | None = None):
        super().__init__(parent)
        self._is_expanded = False
        self._title_text = title

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        self._toggle_btn = QPushButton(f"▶  {title}")
        self._toggle_btn.setCursor(Qt.PointingHandCursor)
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setChecked(False)
        self._toggle_btn.clicked.connect(self._toggle)
        outer.addWidget(self._toggle_btn)

        self._container = QFrame()
        self._container.setObjectName("CollapsibleContainer")
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(12, 10, 12, 10)
        self._container_layout.setSpacing(8)
        self._container.setVisible(False)
        outer.addWidget(self._container)

        self.refresh_theme()

    def _toggle(self) -> None:
        self._is_expanded = not self._is_expanded
        self._toggle_btn.setText(f"{'▼' if self._is_expanded else '▶'}  {self._title_text}")
        self._container.setVisible(self._is_expanded)

    def add_widget(self, widget: QWidget) -> None:
        self._container_layout.addWidget(widget)

    def add_layout(self, layout) -> None:
        self._container_layout.addLayout(layout)

    def refresh_theme(self, p: dict[str, str] | None = None) -> None:
        p = p or palette()
        self._toggle_btn.setStyleSheet(
            f"QPushButton {{ background-color: {p['surface_alt']}; color: {p['text']};"
            f" border: 1px solid {p['border']}; border-radius: 4px;"
            f" font-weight: bold; font-size: 12px; padding: 6px 12px; text-align: left; }}"
            f"QPushButton:hover {{ background-color: {p['surface']}; }}"
        )
        self._container.setStyleSheet(
            f"#CollapsibleContainer {{ background-color: {p['surface_alt']};"
            f" border: 1px solid {p['border']}; border-radius: 4px; }}"
        )


# ── Main Import Data Page ────────────────────────────────────────────────────

class ImportDataPage(QWidget):
    """Modern 4-step master-data import wizard for pharmacy users.

    Steps:
      1. Choose What to Import (Company, Item, Supplier, Customer, Doctor, etc.)
      2. Select Your File (CSV or Excel XLSX, Inspect, Sheet Selection)
      3. Match Your Columns (Auto match, field dropdowns, required indicators)
      4. Review and Import (Validation counts, sample rows preview, error list, safe import)
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("ImportDataPage")

        self._data: dict[str, Any] | None = None
        self._preview: dict[str, Any] | None = None
        self._mapping: dict[str, str] = {}
        self._file_path: str = ""

        # Main Layout
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 1. Page Header Strip
        self._page_header = ui.PageHeader("Master / Import Data")
        
        # Header action buttons (secondary actions)
        self._btn_template = ui.ActionButton("Download Template", "secondary", height=28)
        self._btn_template.setToolTip("Download blank CSV/Excel template with supported fields")
        self._btn_template.clicked.connect(self._template)
        
        self._btn_history = ui.ActionButton("Import History", "secondary", height=28)
        self._btn_history.setToolTip("View audit log of previous imports")
        self._btn_history.clicked.connect(self._history)
        
        self._page_header.add_actions([self._btn_template, self._btn_history])
        root.addWidget(self._page_header)

        # 2. Step Indicator Bar
        self._step_bar = StepIndicatorBar()
        self._step_bar.step_clicked.connect(self._go_to_step)
        root.addWidget(self._step_bar)

        # 3. Wizard Stack (Pages 0, 1, 2)
        # Page 0: Initial View (Step 1: Choose Master + Step 2: Select File)
        # Page 1: Step 3 (Match Columns)
        # Page 2: Step 4 (Review and Import)
        self._stack = QStackedWidget()
        root.addWidget(self._stack, 1)

        self._build_page_0_setup()
        self._build_page_1_mapping()
        self._build_page_2_review()

        self._update_wizard_state(step=0)
        self.refresh_theme()

    # ── Wizard Page 0: Choose Master & Select File (Steps 1 & 2) ─────────────

    def _build_page_0_setup(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(14)

        # ── Step 1: Choose What to Import Card ──
        self._card_step1 = QFrame()
        self._card_step1.setObjectName("Step1Card")
        step1_layout = QVBoxLayout(self._card_step1)
        step1_layout.setContentsMargins(14, 12, 14, 12)
        step1_layout.setSpacing(10)

        s1_title_row = QHBoxLayout()
        s1_title = QLabel("Step 1 — Choose What to Import")
        s1_title.setFont(ui.readable_font(13, bold=True))
        s1_title_row.addWidget(s1_title)
        s1_title_row.addStretch()
        step1_layout.addLayout(s1_title_row)

        s1_desc = QLabel("Select the type of master records you want to import into your pharmacy system:")
        s1_desc.setStyleSheet(ui.label_style(dim=True))
        step1_layout.addWidget(s1_desc)

        # Dropdown selection
        select_row = QHBoxLayout()
        lbl_master = QLabel("Master Type:")
        lbl_master.setFont(ui.readable_font(12, bold=True))
        select_row.addWidget(lbl_master)

        self._master_combo = ui.style_combo(QComboBox())
        self._master_combo.setMinimumWidth(220)
        self._master_combo.addItems([import_service.DISPLAY_NAMES[m] for m in import_service.MASTER_TYPES])
        self._master_combo.currentTextChanged.connect(self._on_master_changed)
        select_row.addWidget(self._master_combo)

        # Quick-select master pills
        select_row.addSpacing(16)
        lbl_quick = QLabel("Quick Select:")
        lbl_quick.setStyleSheet(ui.label_style(dim=True))
        select_row.addWidget(lbl_quick)

        self._master_pill_group = QButtonGroup(self)
        for m in import_service.MASTER_TYPES:
            d_name = import_service.DISPLAY_NAMES[m]
            pill = QPushButton(d_name)
            pill.setCursor(Qt.PointingHandCursor)
            pill.clicked.connect(lambda checked=False, name=d_name: self._master_combo.setCurrentText(name))
            select_row.addWidget(pill)

        select_row.addStretch()
        step1_layout.addLayout(select_row)

        # Master info badge
        self._master_info_lbl = QLabel()
        self._master_info_lbl.setWordWrap(True)
        self._master_info_lbl.setStyleSheet(
            "padding: 8px 12px; border-radius: 4px; font-size: 12px;"
        )
        step1_layout.addWidget(self._master_info_lbl)
        self._update_master_info()

        layout.addWidget(self._card_step1)

        # ── Step 2: Select Your File Card ──
        self._card_step2 = QFrame()
        self._card_step2.setObjectName("Step2Card")
        step2_layout = QVBoxLayout(self._card_step2)
        step2_layout.setContentsMargins(14, 12, 14, 12)
        step2_layout.setSpacing(10)

        s2_title_row = QHBoxLayout()
        s2_title = QLabel("Step 2 — Select Your File")
        s2_title.setFont(ui.readable_font(13, bold=True))
        s2_title_row.addWidget(s2_title)
        s2_title_row.addStretch()
        step2_layout.addLayout(s2_title_row)

        # File Dropzone / Status Box
        self._dropzone = QFrame()
        self._dropzone.setObjectName("FileDropzone")
        dz_layout = QHBoxLayout(self._dropzone)
        dz_layout.setContentsMargins(14, 12, 14, 12)
        dz_layout.setSpacing(12)

        self._file_icon_lbl = QLabel("📁")
        self._file_icon_lbl.setFont(ui.readable_font(24))
        dz_layout.addWidget(self._file_icon_lbl)

        file_text_vbox = QVBoxLayout()
        file_text_vbox.setSpacing(3)
        self._file_name_lbl = QLabel("No file selected")
        self._file_name_lbl.setFont(ui.readable_font(13, bold=True))
        file_text_vbox.addWidget(self._file_name_lbl)

        self._file_details_lbl = QLabel("Please choose a CSV or Excel (.xlsx) file to import.")
        self._file_details_lbl.setStyleSheet(ui.label_style(dim=True))
        file_text_vbox.addWidget(self._file_details_lbl)
        dz_layout.addLayout(file_text_vbox, 1)

        # Primary Browse button
        self._btn_browse = ui.ActionButton("Browse File", "primary", height=34)
        self._btn_browse.clicked.connect(self._browse)
        dz_layout.addWidget(self._btn_browse)

        # Refresh / Inspect button
        self._btn_inspect = ui.ActionButton("Inspect File", "secondary", height=34)
        self._btn_inspect.setEnabled(False)
        self._btn_inspect.clicked.connect(self._inspect)
        dz_layout.addWidget(self._btn_inspect)

        step2_layout.addWidget(self._dropzone)

        # Excel Sheet Selector (revealed if workbook has multiple sheets)
        self._sheet_row_widget = QWidget()
        sheet_row = QHBoxLayout(self._sheet_row_widget)
        sheet_row.setContentsMargins(0, 0, 0, 0)
        sheet_row.setSpacing(8)

        lbl_sheet = QLabel("Worksheet in Excel Workbook:")
        lbl_sheet.setFont(ui.readable_font(12, bold=True))
        sheet_row.addWidget(lbl_sheet)

        self._sheet_combo = ui.style_combo(QComboBox())
        self._sheet_combo.setMinimumWidth(200)
        self._sheet_combo.currentTextChanged.connect(self._on_sheet_changed)
        sheet_row.addWidget(self._sheet_combo)
        sheet_row.addStretch()
        self._sheet_row_widget.setVisible(False)
        step2_layout.addWidget(self._sheet_row_widget)

        # Format help text
        fmt_note = QLabel("✓ Supported formats: UTF-8 CSV (.csv) and Microsoft Excel (.xlsx).  Legacy .xls is not supported.")
        fmt_note.setStyleSheet(ui.label_style(dim=True))
        step2_layout.addWidget(fmt_note)

        layout.addWidget(self._card_step2)

        # ── Helpful Instructions Card ──
        self._guide_box = QFrame()
        self._guide_box.setObjectName("GuideBox")
        guide_layout = QVBoxLayout(self._guide_box)
        guide_layout.setContentsMargins(12, 10, 12, 10)
        guide_layout.setSpacing(4)

        guide_title = QLabel("💡 Master Data Import Guide")
        guide_title.setFont(ui.readable_font(12, bold=True))
        guide_layout.addWidget(guide_title)

        guide_text = QLabel(
            "• Step 1: Pick the master type (e.g., Company, Item, Supplier, Customer).\n"
            "• Step 2: Browse and inspect your CSV or Excel file.\n"
            "• Step 3: Match your spreadsheet columns with pharmacy application fields.\n"
            "• Step 4: Review data preview, check validation results, and confirm import.\n"
            "• Safety: Preview and validation are 100% read-only. Database writes only happen when you click 'Import Data'."
        )
        guide_text.setStyleSheet(ui.label_style(dim=True))
        guide_layout.addWidget(guide_text)
        layout.addWidget(self._guide_box)

        layout.addStretch()

        # ── Bottom Action Bar for Page 0 ──
        bot_bar = QHBoxLayout()
        self._btn_step1_next = ui.ActionButton("Inspect File & Match Columns →", "primary", height=36)
        self._btn_step1_next.setEnabled(False)
        self._btn_step1_next.clicked.connect(self._inspect_and_proceed)
        bot_bar.addStretch()
        bot_bar.addWidget(self._btn_step1_next)
        layout.addLayout(bot_bar)

        scroll.setWidget(container)
        self._stack.addWidget(scroll)

    # ── Wizard Page 1: Match Your Columns (Step 3) ───────────────────────────

    def _build_page_1_mapping(self) -> None:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        # Top breadcrumb / source chip
        top_bar = QHBoxLayout()
        self._mapping_title = QLabel("Step 3 — Match Your Columns")
        self._mapping_title.setFont(ui.readable_font(13, bold=True))
        top_bar.addWidget(self._mapping_title)

        top_bar.addSpacing(16)
        self._mapping_info_chip = QLabel("")
        self._mapping_info_chip.setStyleSheet(
            "padding: 4px 10px; border-radius: 12px; font-size: 11px; font-weight: bold;"
        )
        top_bar.addWidget(self._mapping_info_chip)

        top_bar.addStretch()

        # Sheet selector on mapping page as well (for quick sheet switching)
        self._mapping_sheet_label = QLabel("Worksheet:")
        self._mapping_sheet_label.setFont(ui.readable_font(12, bold=True))
        top_bar.addWidget(self._mapping_sheet_label)

        self._mapping_sheet_combo = ui.style_combo(QComboBox())
        self._mapping_sheet_combo.setMinimumWidth(160)
        self._mapping_sheet_combo.currentTextChanged.connect(self._on_mapping_sheet_changed)
        top_bar.addWidget(self._mapping_sheet_combo)

        layout.addLayout(top_bar)

        # Toolbar above mapping table
        tb_layout = QHBoxLayout()
        self._btn_auto_map = ui.ActionButton("Auto Match Columns", "primary", height=30)
        self._btn_auto_map.clicked.connect(self._auto_map)
        tb_layout.addWidget(self._btn_auto_map)

        self._mapping_status_lbl = QLabel("Map each source column to a target application field.")
        self._mapping_status_lbl.setStyleSheet(ui.label_style(dim=True))
        tb_layout.addWidget(self._mapping_status_lbl)

        tb_layout.addStretch()
        layout.addLayout(tb_layout)

        # Missing required fields alert banner
        self._missing_req_banner = QFrame()
        self._missing_req_banner.setObjectName("MissingReqBanner")
        mrb_layout = QHBoxLayout(self._missing_req_banner)
        mrb_layout.setContentsMargins(10, 6, 10, 6)
        self._missing_req_lbl = QLabel("")
        self._missing_req_lbl.setFont(ui.readable_font(11, bold=True))
        mrb_layout.addWidget(self._missing_req_lbl)
        self._missing_req_banner.setVisible(False)
        layout.addWidget(self._missing_req_banner)

        # Mapping Table: [File Column | Import Into | Result]
        self._mapping_table = QTableWidget(0, 3)
        self._mapping_table.setHorizontalHeaderLabels(["File Column", "Import Into", "Result"])
        ui.style_data_table(self._mapping_table, stretch_columns=(0, 1))
        self._mapping_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._mapping_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._mapping_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._mapping_table.verticalHeader().setDefaultSectionSize(ui.ROW_HEIGHT)
        layout.addWidget(self._mapping_table, 1)

        # Bottom Navigation Bar
        bot_bar = QHBoxLayout()
        btn_back = ui.ActionButton("← Back to File Selection", "secondary", height=34)
        btn_back.clicked.connect(lambda: self._go_to_step(1))
        bot_bar.addWidget(btn_back)

        bot_bar.addStretch()

        self._btn_step2_next = ui.ActionButton("Validate & Review Data →", "primary", height=34)
        self._btn_step2_next.clicked.connect(self._validate_and_proceed)
        bot_bar.addWidget(self._btn_step2_next)

        layout.addLayout(bot_bar)

        self._stack.addWidget(container)

    # ── Wizard Page 2: Review and Import (Step 4) ────────────────────────────

    def _build_page_2_review(self) -> None:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        # Top strip
        top_bar = QHBoxLayout()
        self._review_title = QLabel("Step 4 — Review and Import")
        self._review_title.setFont(ui.readable_font(13, bold=True))
        top_bar.addWidget(self._review_title)

        top_bar.addSpacing(16)
        self._review_info_chip = QLabel("")
        self._review_info_chip.setStyleSheet(
            "padding: 4px 10px; border-radius: 12px; font-size: 11px; font-weight: bold;"
        )
        top_bar.addWidget(self._review_info_chip)
        top_bar.addStretch()
        layout.addLayout(top_bar)

        # ── Metric Dashboard Cards ──
        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(10)

        self._card_total = MetricCard("Total Rows Found")
        self._card_valid = MetricCard("Valid Rows")
        self._card_invalid = MetricCard("Invalid Rows")
        self._card_duplicates = MetricCard("Duplicate Rows")
        self._card_missing_req = MetricCard("Missing Required")

        metrics_row.addWidget(self._card_total)
        metrics_row.addWidget(self._card_valid)
        metrics_row.addWidget(self._card_invalid)
        metrics_row.addWidget(self._card_duplicates)
        metrics_row.addWidget(self._card_missing_req)
        layout.addLayout(metrics_row)

        # ── Tabbed View: Sample Data Preview & Validation Issues ──
        self._review_tabs = QTabWidget()
        self._review_tabs.setObjectName("ReviewTabs")

        # Tab 1: Sample Data Preview
        tab_preview = QWidget()
        pv_layout = QVBoxLayout(tab_preview)
        pv_layout.setContentsMargins(8, 8, 8, 8)
        pv_layout.setSpacing(6)

        self._pv_note = QLabel("Sample rows with mapped target fields:")
        self._pv_note.setStyleSheet(ui.label_style(dim=True))
        pv_layout.addWidget(self._pv_note)

        self._preview_table = QTableWidget(0, 0)
        ui.style_data_table(self._preview_table)
        self._preview_table.verticalHeader().setDefaultSectionSize(ui.ROW_HEIGHT)
        pv_layout.addWidget(self._preview_table, 1)
        self._review_tabs.addTab(tab_preview, "Sample Rows Preview")

        # Tab 2: Validation Issues & Explanations
        tab_issues = QWidget()
        iss_layout = QVBoxLayout(tab_issues)
        iss_layout.setContentsMargins(8, 8, 8, 8)
        iss_layout.setSpacing(6)

        # Success banner (shown if 0 issues)
        self._clean_banner = QFrame()
        self._clean_banner.setObjectName("CleanBanner")
        cb_layout = QHBoxLayout(self._clean_banner)
        cb_layout.setContentsMargins(12, 10, 12, 10)
        self._clean_lbl = QLabel("✓ All rows passed validation successfully! Data is clean and ready for import.")
        self._clean_lbl.setFont(ui.readable_font(12, bold=True))
        cb_layout.addWidget(self._clean_lbl)
        iss_layout.addWidget(self._clean_banner)

        # Issues table (shown if issues exist)
        self._issues_table = QTableWidget(0, 5)
        self._issues_table.setHorizontalHeaderLabels(["Row", "Field", "Value", "Issue / Explanation", "Severity"])
        ui.style_data_table(self._issues_table, stretch_columns=(3,))
        self._issues_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._issues_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._issues_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._issues_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self._issues_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self._issues_table.verticalHeader().setDefaultSectionSize(ui.ROW_HEIGHT)
        iss_layout.addWidget(self._issues_table, 1)

        self._review_tabs.addTab(tab_issues, "Validation Issues (0)")
        layout.addWidget(self._review_tabs, 1)

        # ── Collapsible Advanced Options: Duplicate Handling ──
        self._adv_section = CollapsibleSection("Advanced Options: Duplicate Records Handling")

        dup_box = QVBoxLayout()
        dup_box.setSpacing(6)

        dup_desc = QLabel("How should the system handle records that already exist in the database or are duplicated within your file?")
        dup_desc.setStyleSheet(ui.label_style(dim=True))
        dup_box.addWidget(dup_desc)

        dup_row = QHBoxLayout()
        dup_row.setSpacing(18)

        self._rb_skip = QRadioButton("Skip duplicates (Recommended)")
        self._rb_skip.setToolTip("Existing database records are preserved. Duplicates in the file are skipped.")
        self._rb_skip.setChecked(True)

        self._rb_update = QRadioButton("Update existing records")
        self._rb_update.setToolTip("Overwrite existing database records with the new values from this file.")

        self._rb_cancel = QRadioButton("Cancel entire import")
        self._rb_cancel.setToolTip("Stop and roll back the entire import if any duplicate record is detected.")

        self._dup_group = QButtonGroup(self)
        self._dup_group.addButton(self._rb_skip, 0)
        self._dup_group.addButton(self._rb_update, 1)
        self._dup_group.addButton(self._rb_cancel, 2)

        dup_row.addWidget(self._rb_skip)
        dup_row.addWidget(self._rb_update)
        dup_row.addWidget(self._rb_cancel)
        dup_row.addStretch()
        dup_box.addLayout(dup_row)

        self._adv_section.add_layout(dup_box)
        layout.addWidget(self._adv_section)

        # ── Bottom Action Bar for Page 2 ──
        bot_bar = QHBoxLayout()

        btn_back_to_map = ui.ActionButton("← Back to Column Mapping", "secondary", height=34)
        btn_back_to_map.clicked.connect(lambda: self._go_to_step(2))
        bot_bar.addWidget(btn_back_to_map)

        btn_revalidate = ui.ActionButton("Re-Validate Data", "secondary", height=34)
        btn_revalidate.clicked.connect(self._validate)
        bot_bar.addWidget(btn_revalidate)

        bot_bar.addStretch()

        self._btn_import = ui.ActionButton("Import Data", "success", height=34)
        self._btn_import.setEnabled(False)
        self._btn_import.clicked.connect(self._import)
        bot_bar.addWidget(self._btn_import)

        layout.addLayout(bot_bar)

        self._stack.addWidget(container)

    # ── Wizard Navigation & State ────────────────────────────────────────────

    def _update_wizard_state(self, step: int) -> None:
        """Update wizard stack page and step indicator."""
        completed: set[int] = set()
        if self._data is not None:
            completed.add(0)
            completed.add(1)
        if self._preview is not None:
            completed.add(2)

        # Mapping between 4-step wizard and 3 stack pages:
        # Step 0 or 1 -> Page 0 (Setup / File)
        # Step 2 -> Page 1 (Column Mapping)
        # Step 3 -> Page 2 (Review and Import)
        if step in (0, 1):
            page_idx = 0
        elif step == 2:
            page_idx = 1
        else:
            page_idx = 2

        self._stack.setCurrentIndex(page_idx)
        self._step_bar.set_step(step, completed)

    def _go_to_step(self, step_idx: int) -> None:
        """User clicked a step in the step indicator bar."""
        if step_idx in (0, 1):
            self._update_wizard_state(step=step_idx)
        elif step_idx == 2:
            if self._data is None:
                QMessageBox.information(self, "Step 3", "Please browse and inspect a file first.")
                return
            self._update_wizard_state(step=2)
        elif step_idx == 3:
            if self._preview is None:
                if self._data is not None:
                    self._validate_and_proceed()
                else:
                    QMessageBox.information(self, "Step 4", "Please inspect a file and validate columns first.")
                return
            self._update_wizard_state(step=3)

    # ── Master Type Selection ────────────────────────────────────────────────

    def _master_type(self) -> str:
        return self._master_combo.currentText().casefold()

    def _on_master_changed(self) -> None:
        self._update_master_info()
        self._reset_mapping()

    def _update_master_info(self) -> None:
        master = self._master_type()
        info_texts = {
            "company": "🏢 <b>Company Master:</b> Imports pharmaceutical manufacturers and marketing company names and short codes.",
            "unit": "📏 <b>Unit Master:</b> Imports packaging & measurement units (e.g., TAB, STRIP, BOTTLE, BOX, VIAL).",
            "drug": "💊 <b>Drug Master:</b> Imports generic formulation names, molecules, and chemical ingredients.",
            "supplier": "🚚 <b>Supplier Master:</b> Imports distributors and vendors with contact numbers, GST/VAT details, credit terms, and automatically creates linked Sundry Creditor ledger accounts.",
            "customer": "👥 <b>Customer Master:</b> Imports clients and patients with contact numbers, credit limits, and automatically creates linked Sundry Debtor ledger accounts.",
            "doctor": "👨‍⚕️ <b>Doctor Master:</b> Imports prescribing doctors, specialties, cities, and phone numbers.",
            "item": "📦 <b>Item Master:</b> Imports medicines & products with packaging, pricing (MRP, Rate), tax structures, and references to Company, Unit, Category, and Drug. <i>Ensure referenced Company, Unit, and Drug masters are imported first.</i>",
        }
        self._master_info_lbl.setText(info_texts.get(master, f"Imports {master.title()} master records."))

    def _reset_mapping(self) -> None:
        self._data = None
        self._preview = None
        self._mapping = {}
        self._mapping_table.setRowCount(0)
        self._preview_table.setRowCount(0)
        self._preview_table.setColumnCount(0)
        self._issues_table.setRowCount(0)
        self._btn_step1_next.setEnabled(False)
        self._btn_import.setEnabled(False)
        if hasattr(self, "_step_bar"):
            self._update_wizard_state(step=0)

    # ── File Selection & Inspection (Step 2) ─────────────────────────────────

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Master Import File",
            "",
            "Supported Files (*.csv *.xlsx);;CSV Files (*.csv);;Excel Files (*.xlsx)",
        )
        if path:
            self._file_path = path
            p = Path(path)
            fmt = p.suffix.upper().lstrip(".")
            size_kb = p.stat().st_size / 1024.0

            self._file_name_lbl.setText(p.name)
            self._file_details_lbl.setText(f"Format: {fmt}  •  Size: {size_kb:.1f} KB  •  Path: {path}")
            self._file_icon_lbl.setText("📊" if fmt == "XLSX" else "📄")

            self._sheet_combo.blockSignals(True)
            self._sheet_combo.clear()
            self._sheet_combo.blockSignals(False)
            self._sheet_row_widget.setVisible(False)

            self._btn_inspect.setEnabled(True)
            self._btn_step1_next.setEnabled(True)
            self._inspect()

    def _inspect(self) -> bool:
        if not self._file_path or not Path(self._file_path).is_file():
            return False

        try:
            selected_sheet = self._sheet_combo.currentText() or None
            data = import_service.inspect_file(self._file_path, selected_sheet)

            # Multi-sheet workbook handling
            if "sheets" in data:
                sheets = data["sheets"]
                self._sheet_combo.blockSignals(True)
                self._sheet_combo.clear()
                self._sheet_combo.addItems(sheets)
                self._sheet_combo.blockSignals(False)
                self._sheet_row_widget.setVisible(len(sheets) > 1)

                self._mapping_sheet_combo.blockSignals(True)
                self._mapping_sheet_combo.clear()
                self._mapping_sheet_combo.addItems(sheets)
                self._mapping_sheet_combo.blockSignals(False)
                self._mapping_sheet_label.setVisible(len(sheets) > 1)
                self._mapping_sheet_combo.setVisible(len(sheets) > 1)

                if sheets:
                    data = import_service.inspect_file(self._file_path, sheets[0])
            else:
                self._sheet_row_widget.setVisible(False)
                self._mapping_sheet_label.setVisible(False)
                self._mapping_sheet_combo.setVisible(False)

            self._data = data
            self._mapping = import_service.detect_columns(data.get("headers", []), self._master_type())
            self._show_mapping()

            total_cols = len(data.get("headers", []))
            total_rows = len(data.get("rows", []))
            self._file_details_lbl.setText(
                f"Inspected: {total_cols} columns detected, {total_rows} data rows found."
            )
            self._btn_step1_next.setEnabled(True)
            return True
        except Exception as exc:
            QMessageBox.warning(self, "Inspect Failed", f"Could not inspect file:\n{exc}")
            return False

    def _inspect_and_proceed(self) -> None:
        if self._inspect():
            self._update_wizard_state(step=2)

    def _on_sheet_changed(self, sheet_name: str) -> None:
        if sheet_name and self._file_path:
            self._mapping_sheet_combo.blockSignals(True)
            self._mapping_sheet_combo.setCurrentText(sheet_name)
            self._mapping_sheet_combo.blockSignals(False)
            self._inspect()

    def _on_mapping_sheet_changed(self, sheet_name: str) -> None:
        if sheet_name and self._file_path:
            self._sheet_combo.blockSignals(True)
            self._sheet_combo.setCurrentText(sheet_name)
            self._sheet_combo.blockSignals(False)
            self._inspect()

    # ── Column Mapping (Step 3) ──────────────────────────────────────────────

    def _show_mapping(self) -> None:
        self._mapping_table.setRowCount(0)
        if not self._data:
            return

        master = self._master_type()
        field_defs = import_service.FIELD_DEFINITIONS[master]
        field_names = list(field_defs)

        headers = self._data.get("headers", [])
        p_name = Path(self._file_path).name if self._file_path else ""
        sheet_text = f" • Sheet: {self._sheet_combo.currentText()}" if self._sheet_row_widget.isVisible() else ""
        self._mapping_info_chip.setText(f"{self._master_combo.currentText()} Master • File: {p_name}{sheet_text}")

        # Build dropdown items with "(Required)" indicators
        display_to_field: dict[str, str] = {"(unmapped)": "(unmapped)"}
        combo_items = ["(unmapped)"]
        for f in field_names:
            is_req = field_defs[f].get("required", False)
            disp = f"{f}  * (Required)" if is_req else f"{f}  (Optional)"
            display_to_field[disp] = f
            combo_items.append(disp)

        # 1. Populate rows for each source column in the file
        for col_idx, source in enumerate(headers):
            target_field = self._mapping.get(source, "(unmapped)")
            row = self._mapping_table.rowCount()
            self._mapping_table.insertRow(row)

            # Col 0: File Column
            item_src = QTableWidgetItem(source)
            item_src.setFont(ui.readable_font(12, bold=True))
            item_src.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self._mapping_table.setItem(row, 0, item_src)

            # Col 1: Import Into (styled QComboBox)
            combo = ui.style_combo(QComboBox())
            combo.addItems(combo_items)

            # Select target
            selected_disp = "(unmapped)"
            for disp, f in display_to_field.items():
                if f == target_field:
                    selected_disp = disp
                    break
            combo.setCurrentText(selected_disp)
            combo.setProperty("display_to_field", display_to_field)
            combo.currentTextChanged.connect(self._on_mapping_combo_changed)
            self._mapping_table.setCellWidget(row, 1, combo)

            # Col 2: Result Status
            self._update_row_status(row, target_field, master)

        # 2. Check for required target fields missing entirely from mapping
        mapped_targets = set(self._mapping.values())
        missing_required = []
        for f, defn in field_defs.items():
            if defn.get("required") and f not in mapped_targets:
                missing_required.append(f)
                row = self._mapping_table.rowCount()
                self._mapping_table.insertRow(row)

                item_src = QTableWidgetItem("(no source column in file)")
                item_src.setForeground(QColor("#b23a3a"))
                f_italic = ui.readable_font(11)
                f_italic.setItalic(True)
                item_src.setFont(f_italic)
                item_src.setFlags(Qt.ItemIsEnabled)
                self._mapping_table.setItem(row, 0, item_src)

                item_target = QTableWidgetItem(f"{f}  * (Required)")
                item_target.setFont(ui.readable_font(12, bold=True))
                item_target.setFlags(Qt.ItemIsEnabled)
                self._mapping_table.setItem(row, 1, item_target)

                item_res = QTableWidgetItem("⚠️ Required target missing")
                item_res.setFont(ui.readable_font(11, bold=True))
                item_res.setForeground(QColor("#b23a3a"))
                self._mapping_table.setItem(row, 2, item_res)

        self._update_mapping_summary(missing_required)

    def _update_row_status(self, row: int, target_field: str, master: str) -> None:
        field_defs = import_service.FIELD_DEFINITIONS[master]
        p = palette()

        if target_field == "(unmapped)":
            item = QTableWidgetItem("Optional (Unmapped)")
            item.setForeground(QColor(p['text_dim']))
        else:
            is_req = field_defs.get(target_field, {}).get("required", False)
            if is_req:
                item = QTableWidgetItem("✓ Matched (Required)")
                item.setFont(ui.readable_font(11, bold=True))
                item.setForeground(QColor(p['success']))
            else:
                item = QTableWidgetItem("✓ Matched (Optional)")
                item.setForeground(QColor(p['accent']))

        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self._mapping_table.setItem(row, 2, item)

    def _on_mapping_combo_changed(self) -> None:
        master = self._master_type()
        field_defs = import_service.FIELD_DEFINITIONS[master]
        mapped_targets: set[str] = set()

        for row in range(self._mapping_table.rowCount()):
            combo = self._mapping_table.cellWidget(row, 1)
            if combo is None:
                continue
            display_to_field = combo.property("display_to_field") or {}
            target_field = display_to_field.get(combo.currentText(), "(unmapped)")
            if target_field != "(unmapped)":
                mapped_targets.add(target_field)
            self._update_row_status(row, target_field, master)

        missing_required = [f for f, d in field_defs.items() if d.get("required") and f not in mapped_targets]
        self._update_mapping_summary(missing_required)

    def _update_mapping_summary(self, missing_required: list[str]) -> None:
        master = self._master_type()
        field_defs = import_service.FIELD_DEFINITIONS[master]
        current_map = self._current_mapping()

        req_fields = [f for f, d in field_defs.items() if d.get("required")]
        mapped_req = sum(1 for f in req_fields if f in current_map.values())
        mapped_opt = len(current_map) - mapped_req

        self._mapping_status_lbl.setText(
            f"✓ {mapped_req} of {len(req_fields)} required fields mapped  •  "
            f"{mapped_opt} optional fields mapped"
        )

        p = palette()
        if missing_required:
            missing_str = ", ".join(f"'{m}'" for m in missing_required)
            self._missing_req_lbl.setText(
                f"⚠️ Required field mapping missing: {missing_str}. Please select a source column for each required field."
            )
            self._missing_req_banner.setStyleSheet(
                f"#MissingReqBanner {{ background-color: {p['surface_alt']};"
                f" border: 1px solid {p['danger']}; border-radius: 4px; color: {p['danger']}; }}"
            )
            self._missing_req_banner.setVisible(True)
        else:
            self._missing_req_banner.setVisible(False)

    def _auto_map(self) -> None:
        if not self._data:
            return
        self._mapping = import_service.detect_columns(self._data.get("headers", []), self._master_type())
        self._show_mapping()

    def _current_mapping(self) -> dict[str, str]:
        mapping = {}
        for row in range(self._mapping_table.rowCount()):
            item_src = self._mapping_table.item(row, 0)
            if not item_src:
                continue
            source = item_src.text()
            if source == "(no source column in file)":
                continue
            combo = self._mapping_table.cellWidget(row, 1)
            if combo is None:
                continue
            display_to_field = combo.property("display_to_field") or {}
            target = display_to_field.get(combo.currentText(), "(unmapped)")
            if target != "(unmapped)":
                mapping[source] = target
        return mapping

    def _validate_and_proceed(self) -> None:
        self._validate()
        if self._preview is not None:
            self._update_wizard_state(step=3)

    # ── Review and Validate (Step 4) ─────────────────────────────────────────

    def _validate(self) -> None:
        if not self._data:
            QMessageBox.information(self, "Validation", "Select and inspect a file first.")
            return

        self._mapping = self._current_mapping()
        self._preview = import_service.preview_import(self._master_type(), self._data, self._mapping)
        self._preview["filename"] = self._file_path

        p_name = Path(self._file_path).name if self._file_path else ""
        self._review_info_chip.setText(f"{self._master_combo.currentText()} Master • File: {p_name}")

        # Update Metric Dashboard
        total = self._preview["total_rows"]
        valid = self._preview["valid_rows"]
        invalid = self._preview["invalid_rows"]
        dups = len(self._preview["duplicate_rows"])
        missing_req = len(self._preview["missing_required_fields"])

        self._card_total.set_value(total, "neutral")
        self._card_valid.set_value(valid, "success")
        self._card_invalid.set_value(invalid, "danger" if invalid > 0 else "success")
        self._card_duplicates.set_value(dups, "warning" if dups > 0 else "neutral")
        self._card_missing_req.set_value(missing_req, "danger" if missing_req > 0 else "success")

        # 1. Populate Sample Rows Preview Table
        sample_rows = self._preview.get("sample_rows", [])
        headers = list(self._mapping.values()) if self._mapping else list(self._data.get("headers", []))
        self._preview_table.clear()
        self._preview_table.setColumnCount(len(headers))
        self._preview_table.setHorizontalHeaderLabels(headers)
        self._preview_table.setRowCount(len(sample_rows))

        # Invert mapping to find source column for each mapped target
        inv_map = {tgt: src for src, tgt in self._mapping.items()}

        for r_idx, row_dict in enumerate(sample_rows):
            for c_idx, tgt_col in enumerate(headers):
                src_key = inv_map.get(tgt_col, tgt_col)
                val = row_dict.get(src_key, "")
                item = QTableWidgetItem(str(val))
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self._preview_table.setItem(r_idx, c_idx, item)

        self._pv_note.setText(f"Displaying {len(sample_rows)} sample rows using current column mappings:")

        # 2. Populate Validation Issues Table
        issues = self._preview.get("issues", [])
        self._issues_table.setRowCount(len(issues))

        p = palette()
        for r_idx, iss in enumerate(issues):
            row_num = str(iss.get("row", ""))
            field = str(iss.get("field", ""))
            val = str(iss.get("value", ""))
            msg = str(iss.get("message", ""))
            sev = str(iss.get("severity", "error"))

            for c_idx, text in enumerate((row_num, field, val, msg, sev)):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                if sev == "error":
                    item.setForeground(QColor(p['danger']))
                elif sev == "warning":
                    item.setForeground(QColor(p['warning']))
                self._issues_table.setItem(r_idx, c_idx, item)

        self._review_tabs.setTabText(1, f"Validation Issues ({len(issues)})")
        self._clean_banner.setVisible(len(issues) == 0)
        self._issues_table.setVisible(len(issues) > 0)

        # Enable/Disable Import Data button according to existing rules
        can_import = (invalid == 0 and valid > 0)
        self._btn_import.setEnabled(can_import)

        if not can_import:
            if invalid > 0:
                self._btn_import.setToolTip(f"Cannot import: {invalid} rows have validation errors. Fix them in Step 3 or in your file.")
            elif valid == 0:
                self._btn_import.setToolTip("Cannot import: No valid records found.")
        else:
            self._btn_import.setToolTip(f"Ready to import {valid} valid records into the database.")

    # ── Database Import Execution ────────────────────────────────────────────

    def _import(self) -> None:
        try:
            auth.session.require(auth.PERM_IMPORT_DATA)
        except auth.PermissionDenied as exc:
            QMessageBox.warning(self, "Permission Denied", str(exc))
            return

        if not self._preview:
            self._validate()

        if not self._preview or self._preview.get("invalid_rows", 0) > 0:
            QMessageBox.warning(
                self,
                "Cannot Import",
                "Your data contains validation errors. Please correct the mappings or fix the source file before importing.",
            )
            return

        valid_count = self._preview.get("valid_rows", 0)
        master_title = self._master_combo.currentText()

        confirm = QMessageBox.question(
            self,
            "Confirm Master Data Import",
            f"Are you sure you want to import {valid_count} validated {master_title} records into the database?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        # Determine duplicate mode from Advanced Options radio group
        dup_idx = self._dup_group.checkedId()
        mode_map = {0: "skip", 1: "update", 2: "cancel"}
        mode = mode_map.get(dup_idx, "skip")

        try:
            result = import_service.import_rows(
                self._master_type(),
                self._preview,
                duplicate_mode=mode,
                confirm=True,
            )
            report = import_service.generate_import_report(result)
            QMessageBox.information(
                self,
                "Import Complete",
                f"Master data import completed successfully!\n\n{report}",
            )
            self._reset_mapping()
        except Exception as exc:
            QMessageBox.critical(self, "Import Failed", f"An error occurred during import:\n{exc}")

    # ── Secondary Actions: Template & History ────────────────────────────────

    def _template(self) -> None:
        fmt = "xlsx" if import_service.openpyxl is not None else "csv"
        suffix = f".{fmt}"
        master = self._master_type()
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Import Template",
            f"{master}_template{suffix}",
            f"{fmt.upper()} (*{suffix})",
        )
        if path:
            try:
                Path(path).write_bytes(import_service.get_import_template(master, fmt))
                QMessageBox.information(
                    self,
                    "Template Saved",
                    f"Blank template for '{master.title()}' saved successfully to:\n{path}",
                )
            except Exception as exc:
                QMessageBox.warning(self, "Template Failed", f"Could not create template:\n{exc}")

    def _history(self) -> None:
        history = import_service.get_import_history()
        if not history:
            QMessageBox.information(self, "Import History", "No imports have been recorded yet.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Recent Import History")
        dialog.resize(980, 420)
        p = palette()
        dialog.setStyleSheet(f"background-color: {p['bg']}; color: {p['text']};")

        dlg_layout = QVBoxLayout(dialog)
        dlg_layout.setContentsMargins(14, 12, 14, 12)
        dlg_layout.setSpacing(10)

        header_lbl = QLabel("Audit Log: Recent Master Data Imports")
        header_lbl.setFont(ui.readable_font(13, bold=True))
        dlg_layout.addWidget(header_lbl)

        table = QTableWidget(len(history), 8)
        table.setHorizontalHeaderLabels([
            "Date/Time (UTC)", "Master Type", "Source Filename", "Total Rows",
            "Inserted", "Updated", "Skipped", "Failed",
        ])
        ui.style_data_table(table)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)

        for row_index, record in enumerate(history):
            values = (
                record.get("timestamp", ""),
                str(record.get("master_type", "")).title(),
                record.get("filename", ""),
                record.get("total_rows", 0),
                record.get("inserted", 0),
                record.get("updated", 0),
                record.get("skipped", 0),
                record.get("failed", 0),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                table.setItem(row_index, column, item)

        dlg_layout.addWidget(table, 1)

        btn_close = QPushButton("Close")
        btn_close.setMinimumHeight(ui.CONTROL_HEIGHT)
        btn_close.clicked.connect(dialog.accept)
        dlg_layout.addWidget(btn_close, alignment=Qt.AlignRight)

        dialog.exec()

    # ── Day / Night Theme Refresh ────────────────────────────────────────────

    def refresh_theme(self) -> None:
        """Re-apply live Day/Night colors in place (state preserved)."""
        p = palette()
        self.setStyleSheet(f"background-color: {p['bg']}; color: {p['text']}; font-family: {FONT_FAMILY};")

        # Step Indicator
        self._step_bar.refresh_theme(p)

        # Step 1 & 2 Cards
        card_style = (
            f"background-color: {p['surface_alt']}; border: 1px solid {p['border']}; border-radius: 4px;"
        )
        self._card_step1.setStyleSheet(f"#Step1Card {{ {card_style} }}")
        self._card_step2.setStyleSheet(f"#Step2Card {{ {card_style} }}")
        self._guide_box.setStyleSheet(f"#GuideBox {{ {card_style} }}")

        # Dropzone
        self._dropzone.setStyleSheet(
            f"#FileDropzone {{ background-color: {p['surface']};"
            f" border: 1px dashed {p['border']}; border-radius: 4px; }}"
        )

        # Master info badge
        self._master_info_lbl.setStyleSheet(
            f"background-color: {p['surface']}; color: {p['text']};"
            f" border: 1px solid {p['border']}; border-radius: 4px; padding: 8px 12px;"
        )

        # Quick select pills
        for btn in self._card_step1.findChildren(QPushButton):
            if btn.text() in [import_service.DISPLAY_NAMES[m] for m in import_service.MASTER_TYPES]:
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: {p['surface']}; color: {p['text']};"
                    f" border: 1px solid {p['border']}; border-radius: 12px;"
                    f" font-size: 11px; padding: 3px 10px; }}"
                    f"QPushButton:hover {{ background-color: {p['selected']}; border-color: {p['accent']}; }}"
                )

        # Chips
        chip_style = (
            f"background-color: {p['surface']}; color: {p['accent']};"
            f" border: 1px solid {p['border']}; border-radius: 12px; padding: 4px 10px;"
        )
        self._mapping_info_chip.setStyleSheet(chip_style)
        self._review_info_chip.setStyleSheet(chip_style)

        # Metric cards
        self._card_total.refresh_theme(p)
        self._card_valid.refresh_theme(p)
        self._card_invalid.refresh_theme(p)
        self._card_duplicates.refresh_theme(p)
        self._card_missing_req.refresh_theme(p)

        # Advanced Options Collapsible
        self._adv_section.refresh_theme(p)

        # Clean Banner
        self._clean_banner.setStyleSheet(
            f"#CleanBanner {{ background-color: {p['surface_alt']};"
            f" border: 1px solid {p['success']}; border-radius: 4px; color: {p['success']}; }}"
        )
        self._clean_lbl.setStyleSheet(f"color: {p['success']};")

        # Tables
        ui.style_data_table(self._mapping_table, stretch_columns=(0, 1))
        ui.style_data_table(self._preview_table)
        ui.style_data_table(self._issues_table, stretch_columns=(3,))

        # Missing required banner
        if self._missing_req_banner.isVisible():
            self._missing_req_banner.setStyleSheet(
                f"#MissingReqBanner {{ background-color: {p['surface_alt']};"
                f" border: 1px solid {p['danger']}; border-radius: 4px; color: {p['danger']}; }}"
            )
