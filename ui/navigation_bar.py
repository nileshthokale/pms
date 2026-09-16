from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMenu,
    QPushButton,
    QWidget,
)

from ui import theme
from ui.menu_data import MENUS


class NavigationBar(QWidget):
    """Top navigation bar with menu buttons and a day/night mode toggle."""

    menu_action_triggered = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NavigationBar")
        self.setFixedHeight(48)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(0)

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
            layout.addWidget(btn)

        layout.addStretch()

        self.theme_btn = QPushButton()
        self.theme_btn.setObjectName("ThemeButton")
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        self.theme_btn.setToolTip("Switch between day and night mode")
        self.theme_btn.clicked.connect(self._on_toggle_theme)
        layout.addWidget(self.theme_btn)

        theme.theme_manager.on_changed(self._apply_theme)
        self._apply_theme()

    # ── theme ────────────────────────────────────────────────────────
    def _apply_theme(self, mode: str | None = None):
        p = theme.theme_manager.palette()
        nav = theme.nav_palette()
        self.setStyleSheet(
            "#NavigationBar {"
            f"  background-color: {nav['bg']};"
            f"  border-bottom: 1px solid {nav['border']};"
            "}"
        )
        for btn in self.findChildren(QPushButton):
            if btn.objectName() == "NavButton":
                btn.setStyleSheet(
                    "#NavButton {"
                    f"  color: {nav['text']};"
                    "  background: transparent;"
                    "  border: none;"
                    "  padding: 8px 18px;"
                    "  font-size: 13px;"
                    "  font-weight: bold;"
                    "}"
                    "#NavButton:hover {"
                    f"  background-color: {nav['hover']};"
                    "}"
                    "#NavButton:pressed {"
                    f"  background-color: {nav['pressed']};"
                    "}"
                )
        for menu in self._menus:
            menu.setStyleSheet(
                "QMenu {"
                f"  background-color: {p['surface']};"
                f"  color: {p['text']};"
                f"  border: 1px solid {p['border']};"
                "  padding: 4px 0;"
                "}"
                "QMenu::item {"
                "  padding: 8px 24px;"
                "  font-size: 12px;"
                "}"
                "QMenu::item:selected {"
                f"  background-color: {p['accent']};"
                "  color: white;"
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
            "  border-radius: 3px;"
            "  padding: 6px 14px;"
            "  font-size: 12px;"
            "  font-weight: bold;"
            "  margin: 4px 4px;"
            "}"
            "#ThemeButton:hover {"
            f"  background-color: {nav['theme_btn_hover']};"
            "}"
        )

    def _on_toggle_theme(self):
        theme.theme_manager.toggle()
