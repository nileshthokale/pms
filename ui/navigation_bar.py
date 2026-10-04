"""Traditional desktop navigation bar for the Phase 6E light theme.

Layout (top → bottom):

    ┌──────────────────────────────────────────────────────────────┐
    │ Pharmacy Management System      FY 2026-2027  admin/ADMIN ...│  title strip
    ├──────────────────────────────────────────────────────────────┤
    │ Sales  Purchase  Account  Reports  Master                    │  menu strip
    └──────────────────────────────────────────────────────────────┘

The menu strip keeps the exact same five top-level menus and actions as
before, so every existing page still opens through the same signal.
Only the visual structure changed — no business logic or permissions were
modified.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui import theme
from ui import components as ui
from ui.menu_data import MENUS
from database import auth
from database import financial_year


class FinancialYearPickerDialog(QDialog):
    """Small popup for choosing which financial year to VIEW.

    Read-only by construction: it only returns the chosen row from the
    existing ``financial_years`` table.  It never activates a year, never
    creates one and never writes anything.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Financial Year")
        self.setModal(True)
        self.setFixedWidth(300)
        self._years: list[dict] = financial_year.get_financial_years()
        self._choice: dict | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        caption = QLabel("View history for financial year")
        caption.setStyleSheet(ui.label_style(dim=True, size=9))
        root.addWidget(caption)

        self.combo = QComboBox()
        ui.style_combo(self.combo)
        active = financial_year.get_active_financial_year()
        active_id = active["id"] if active else None
        for year in self._years:
            label = year["name"]
            if year["id"] == active_id:
                label = f"{label}  (active)"
            self.combo.addItem(label, year["id"])
        if self._years:
            index = self.combo.findData(active_id)
            self.combo.setCurrentIndex(index if index >= 0 else 0)
        root.addWidget(self.combo)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch()
        self.cancel_btn = ui.ActionButton("Cancel", "secondary")
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn = ui.ActionButton("Select", "primary")
        self.ok_btn.clicked.connect(self._accept)
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(self.ok_btn)
        root.addLayout(buttons)

    def _accept(self):
        data = self.combo.currentData()
        self._choice = next(
            (y for y in self._years if y["id"] == data), None
        )
        self.accept()

    def selected_year(self) -> dict | None:
        """The financial year the user chose, or None if cancelled."""
        return self._choice


class NavigationBar(QWidget):
    """Top application chrome: title strip + classic menu strip."""

    menu_action_triggered = Signal(str, str)
    logout_requested = Signal()
    financial_year_view_requested = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NavigationBar")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Row 1: title strip ───────────────────────────────────────
        title_bar = QFrame()
        title_bar.setObjectName("TitleBar")
        title_bar.setFixedHeight(30)
        tl = QHBoxLayout(title_bar)
        tl.setContentsMargins(10, 0, 8, 0)
        tl.setSpacing(8)

        self._brand_label = QLabel("Pharmacy Management System")
        self._brand_label.setObjectName("BrandLabel")
        tl.addWidget(self._brand_label)

        self._menu_hint = QLabel("")
        tl.addWidget(self._menu_hint)
        tl.addStretch()

        # Active financial year, shown as a button so a different year can
        # be picked for viewing.  It keeps its place and appearance in the
        # title strip; only the click behaviour is new.
        self.fy_button = QPushButton()
        self.fy_button.setObjectName("FinancialYearButton")
        self.fy_button.setFlat(True)
        self.fy_button.setCursor(Qt.PointingHandCursor)
        self.fy_button.setToolTip(
            "Active financial year — click to view history for another year"
        )
        self.fy_button.clicked.connect(self._on_financial_year_clicked)
        tl.addWidget(self.fy_button)

        self.user_label = QLabel()
        self.user_label.setToolTip("Signed-in user and role")
        tl.addWidget(self.user_label)

        self.theme_btn = QPushButton()
        self.theme_btn.setObjectName("ThemeButton")
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        self.theme_btn.setToolTip("Switch between day and night mode")
        self.theme_btn.clicked.connect(self._on_toggle_theme)
        tl.addWidget(self.theme_btn)

        self.logout_btn = QPushButton("Logout")
        self.logout_btn.setObjectName("LogoutButton")
        self.logout_btn.setCursor(Qt.PointingHandCursor)
        self.logout_btn.setToolTip("Sign out of the application")
        self.logout_btn.clicked.connect(self.logout_requested.emit)
        tl.addWidget(self.logout_btn)

        root.addWidget(title_bar)

        # ── Row 2: menu strip ────────────────────────────────────────
        menu_bar = QFrame()
        menu_bar.setObjectName("MenuBar")
        menu_bar.setFixedHeight(30)
        ml = QHBoxLayout(menu_bar)
        ml.setContentsMargins(4, 0, 8, 0)
        ml.setSpacing(0)

        self._menus: list[QMenu] = []
        for label, items in MENUS.items():
            btn = QPushButton(label)
            btn.setObjectName("NavButton")
            btn.setFlat(True)

            menu = QMenu(btn)
            for item_text in items:
                action = menu.addAction(item_text)
                action.triggered.connect(
                    lambda checked=False, m=label, a=item_text: self.menu_action_triggered.emit(m, a)
                )
            btn.setMenu(menu)
            self._menus.append(menu)
            ml.addWidget(btn)

        ml.addStretch()

        self.status_label = QLabel("")
        self.status_label.setObjectName("NavStatus")
        ml.addWidget(self.status_label)

        root.addWidget(menu_bar)

        theme.theme_manager.on_changed(self._apply_theme)
        self._apply_theme()

    # ── data ─────────────────────────────────────────────────────────
    def refresh_financial_year(self):
        active = financial_year.ensure_default_financial_year()
        self.fy_button.setText(f"FY {active['name']}")

    def _on_financial_year_clicked(self):
        """Open the small financial-year picker and report the choice.

        The picker is a view-only helper: it returns the row the user
        picked and nothing is written to the database here.
        """
        dialog = FinancialYearPickerDialog(self)
        dialog.exec()
        year = dialog.selected_year()
        if year:
            self.financial_year_view_requested.emit(year)

    def refresh_user(self):
        user = getattr(auth.session, "user", None)
        if user:
            self.user_label.setText(
                f"{user.get('username', '')} / {user.get('role', '')}"
            )
        else:
            self.user_label.setText("Not signed in")

    def refresh_indicators(self):
        self.refresh_financial_year()
        self.refresh_user()

    # ── theme ────────────────────────────────────────────────────────
    def _apply_theme(self, mode: str | None = None):
        p = theme.theme_manager.palette()
        nav = theme.nav_palette()

        self.setStyleSheet(
            f"#NavigationBar {{ background-color: {nav['bg']}; }}"
            f"#TitleBar {{"
            f"  background-color: {nav['bg']};"
            f"  border-bottom: 1px solid {nav['border']};"
            f"}}"
            f"#MenuBar {{"
            f"  background-color: {p['surface_alt']};"
            f"  border-bottom: 1px solid {p['border']};"
            f"}}"
            f"#TitleBar QLabel {{"
            f"  color: {nav['text']}; background: transparent;"
            f"  font-size: 9pt; font-family: {ui.FONT_FAMILY};"
            f"}}"
            f"#TitleBar QLabel#BrandLabel {{"
            f"  color: {nav['text']}; font-size: 11pt; font-weight: bold;"
            f"}}"
        )
        self._brand_label.setStyleSheet(
            f"color: {nav['text']}; font-size: 11pt; font-weight: bold;"
            f"font-family: {ui.FONT_FAMILY}; background: transparent;"
        )
        self.fy_button.setStyleSheet(
            "#FinancialYearButton {"
            f"  color: {nav['text']}; background: transparent;"
            "  border: 1px solid transparent; border-radius: 2px;"
            "  padding: 1px 6px; font-size: 9pt; font-weight: bold;"
            f"  font-family: {ui.FONT_FAMILY};"
            "}"
            "#FinancialYearButton:hover {"
            f"  background-color: {p['selected']};"
            f"  color: {p['selected_text']};"
            "}"
            "#FinancialYearButton:pressed {"
            f"  background-color: {p['surface']};"
            "}"
        )
        self.user_label.setStyleSheet(
            f"color: {nav['text']}; background: transparent;"
            f"font-size: 9pt; padding: 0 6px;"
            f"font-family: {ui.FONT_FAMILY};"
        )
        self._menu_hint.setStyleSheet(
            f"color: {nav['text']}; background: transparent;"
            f"font-size: 8pt; font-style: italic; padding-left: 8px;"
            f"font-family: {ui.FONT_FAMILY};"
        )
        self.status_label.setStyleSheet(
            f"color: {p['text_dim']}; background: transparent;"
            f"font-size: 8pt; padding-right: 6px;"
            f"font-family: {ui.FONT_FAMILY};"
        )

        for btn in self.findChildren(QPushButton):
            if btn.objectName() == "NavButton":
                btn.setStyleSheet(
                    "#NavButton {"
                    f"  color: {p['text']};"
                    "  background: transparent;"
                    "  border: none;"
                    "  padding: 4px 14px;"
                    f"  font-size: 9pt;"
                    f"  font-family: {ui.FONT_FAMILY};"
                    "}"
                    "#NavButton:hover {"
                    f"  background-color: {p['selected']};"
                    f"  color: {p['selected_text']};"
                    "}"
                    "#NavButton:pressed {"
                    f"  background-color: {p['surface']};"
                    "}"
                    "#NavButton::menu-indicator { image: none; width: 0; }"
                )
        for menu in self._menus:
            menu.setStyleSheet(
                "QMenu {"
                f"  background-color: {p['bg']};"
                f"  color: {p['text']};"
                f"  border: 1px solid {p['border']};"
                "  padding: 2px 0;"
                "}"
                "QMenu::item {"
                "  padding: 4px 22px;"
                f"  font-size: 9pt;"
                f"  font-family: {ui.FONT_FAMILY};"
                "}"
                "QMenu::item:selected {"
                f"  background-color: {p['selected']};"
                f"  color: {p['selected_text']};"
                "}"
            )

        self.logout_btn.setStyleSheet(
            "#LogoutButton {"
            "  color: #ffffff;"
            f"  background-color: {p['danger']};"
            "  border: 1px solid " + nav['border'] + ";"
            "  border-radius: 2px;"
            "  padding: 2px 10px;"
            f"  font-size: 9pt; font-family: {ui.FONT_FAMILY};"
            "}"
            "#LogoutButton:hover {"
            f"  background-color: {p['danger_hover']};"
            "}"
        )
        self.theme_btn.setText(
            "\u263E  Night Mode" if theme.theme_manager.is_dark()
            else "\u2600  Day Mode"
        )
        self.theme_btn.setStyleSheet(
            "#ThemeButton {"
            f"  color: {nav['theme_btn_text']};"
            f"  background-color: {nav['theme_btn_bg']};"
            "  border: none;"
            "  border-radius: 2px;"
            "  padding: 2px 10px;"
            f"  font-size: 9pt; font-family: {ui.FONT_FAMILY};"
            "}"
            "#ThemeButton:hover {"
            f"  background-color: {nav['theme_btn_hover']};"
            "}"
        )
        self.refresh_indicators()

    def _on_toggle_theme(self):
        theme.theme_manager.toggle()
