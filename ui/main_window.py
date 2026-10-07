from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import screens
from database import init_database
from database import auth
from database import financial_year
from version import APP_TITLE
from ui import theme
from ui import components as ui
from ui.menu_data import MENUS
from ui.navigation_bar import NavigationBar


class PlaceholderPage(QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(ui.PageHeader(title))
        body = QLabel(title)
        body.setAlignment(Qt.AlignCenter)
        body.setStyleSheet(ui.label_style(dim=True, size=12))
        layout.addWidget(body, 1)


class PharmacyMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_default_financial_year()
        self.setWindowTitle(APP_TITLE)
        # Desktop-first: comfortable at 1366x768 and scales up to 1920x1080.
        self.resize(1366, 760)
        self.setMinimumSize(1024, 640)

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self._nav = NavigationBar()
        self._nav.menu_action_triggered.connect(self._on_menu_action)
        self._nav.logout_requested.connect(self._on_logout)
        self._nav.financial_year_view_requested.connect(
            self._on_financial_year_view
        )
        root_layout.addWidget(self._nav)

        self._stack = QStackedWidget()
        root_layout.addWidget(self._stack, 1)

        self._page_map: dict[str, int] = {}
        self._build_pages()

        theme.theme_manager.on_changed(self._on_theme_changed)
        self._apply_theme()

    def _build_pages(self):
        # Pages are resolved through the screens package attributes so a
        # theme switch (which reloads the screen modules) provides fresh
        # classes on rebuild.
        page_index = 0
        for menu_name, items in MENUS.items():
            for item_name in items:
                if menu_name == "Master" and item_name == "Company Master":
                    page = screens.CompanyMasterPage()
                elif menu_name == "Master" and item_name == "Unit Master":
                    page = screens.UnitMasterPage()
                elif menu_name == "Master" and item_name == "Drug Master":
                    page = screens.DrugMasterPage()
                elif menu_name == "Master" and item_name == "Supplier Master":
                    page = screens.SupplierMasterPage()
                elif menu_name == "Master" and item_name == "Customer Master":
                    page = screens.CustomerMasterPage()
                elif menu_name == "Master" and item_name == "Doctor Master":
                    page = screens.DoctorMasterPage()
                elif menu_name == "Master" and item_name == "Item Master":
                    page = screens.ItemMasterPage()
                elif menu_name == "Master" and item_name == "Category Master":
                    page = screens.CategoryMasterPage()
                elif menu_name == "Master" and item_name == "Backup & Restore":
                    page = screens.BackupRestorePage()
                elif menu_name == "Master" and item_name == "Import Data":
                    page = screens.ImportDataPage()
                elif menu_name == "Master" and item_name == "User Master":
                    page = screens.UserManagementPage()
                elif menu_name == "Master" and item_name == "Account Group":
                    page = screens.AccountGroupMasterPage()
                elif menu_name == "Master" and item_name == "Financial Year":
                    page = screens.FinancialYearPage()
                elif menu_name == "Purchase" and item_name == "New Purchase":
                    page = screens.PurchaseInvoicePage()
                elif menu_name == "Purchase" and item_name == "Purchase History":
                    page = screens.PurchaseInvoicePage()
                elif menu_name == "Reports" and item_name == "Stock Report":
                    page = screens.StockMasterPage()
                elif menu_name == "Reports" and item_name == "Sales Report":
                    page = screens.SalesReportPage()
                elif menu_name == "Reports" and item_name == "Purchase Report":
                    page = screens.PurchaseReportPage()
                elif menu_name == "Reports" and item_name == "Expiry Report":
                    page = screens.ExpiryReportPage()
                elif menu_name == "Reports" and item_name == "Party Wise Report":
                    page = screens.PartyWiseReportPage()
                elif menu_name == "Reports" and item_name == "GST Report":
                    page = screens.GSTReportPage()
                elif menu_name == "Sales" and item_name == "New Bill":
                    page = screens.CounterSalePage()
                elif menu_name == "Sales" and item_name == "Hold Bill":
                    page = screens.HoldBillPage()
                elif menu_name == "Sales" and item_name == "Day End":
                    page = screens.DayEndPage()
                elif menu_name == "Sales" and item_name == "Sales History":
                    page = screens.CounterSalePage()
                elif menu_name == "Sales" and item_name == "Return Bill":
                    page = screens.CreditNotePage()
                elif menu_name == "Purchase" and item_name == "Purchase Return":
                    page = screens.DebitNotePage()
                elif menu_name == "Purchase" and item_name == "Supplier Payment":
                    page = screens.SupplierPaymentPage()
                elif menu_name == "Account" and item_name == "Customer Receipt":
                    page = screens.CustomerReceiptPage()
                elif menu_name == "Account" and item_name == "Cash Book":
                    page = screens.CashBookPage()
                elif menu_name == "Account" and item_name == "Bank Book":
                    page = screens.BankBookPage()
                elif menu_name == "Account" and item_name == "Ledger":
                    page = screens.AccountLedgerPage()
                elif menu_name == "Account" and item_name == "Journal Entry":
                    page = screens.JournalEntryPage()
                elif menu_name == "Account" and item_name == "Account Roles":
                    page = screens.AccountRolesPage()
                elif menu_name == "Account" and item_name == "Trial Balance":
                    page = screens.TrialBalancePage()
                elif menu_name == "Account" and item_name == "Profit & Loss":
                    page = screens.ProfitLossPage()
                elif menu_name == "Account" and item_name == "Balance Sheet":
                    page = screens.BalanceSheetPage()
                else:
                    page = PlaceholderPage(f"{menu_name}  >  {item_name}")
                ui.polish_page(page)
                self._stack.addWidget(page)
                self._page_map[f"{menu_name}:{item_name}"] = page_index
                page_index += 1

    def _on_menu_action(self, menu: str, action: str):
        permission = auth.MENU_PERMISSIONS.get(action)
        if permission:
            try:
                auth.session.require(permission)
            except auth.PermissionDenied as exc:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Permission denied", str(exc))
                return
        key = f"{menu}:{action}"
        if key in self._page_map:
            self._stack.setCurrentIndex(self._page_map[key])
            self.setWindowTitle(f"{APP_TITLE}  -  {action}")
            self._nav.status_label.setText(f"{menu} / {action}")

    # ── financial-year viewing ──────────────────────────────────
    def _on_financial_year_view(self, year: dict):
        """Show Counter Sale history for a chosen financial year.

        This is a VIEW filter only.  The active financial year, the
        navigation and every other page are left exactly as they were.
        """
        for index in range(self._stack.count()):
            page = self._stack.widget(index)
            apply_view = getattr(page, "set_history_financial_year", None)
            if callable(apply_view):
                apply_view(year)

    # ── logout ───────────────────────────────────────────────────────
    def _on_logout(self):
        from PySide6.QtWidgets import QMessageBox
        answer = QMessageBox.question(
            self, "Logout", "Sign out of the application?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        auth.session.logout()
        from screens.login import run_login
        if not run_login(self):
            self.close()
            return
        self._nav.refresh_user()
        self.setWindowTitle(APP_TITLE)

    # ── theme ────────────────────────────────────────────────────────
    def _apply_theme(self):
        p = theme.theme_manager.palette()
        # Application-wide stylesheet styles dialogs and any widget that a
        # screen does not style itself.  Widget-level stylesheets in the
        # screens always win, so this is a safe global fallback.
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.stylesheet())
        self.setStyleSheet(
            f"QMainWindow, QStackedWidget, QWidget#CentralWorkspace"
            f" {{ background-color: {p['bg']}; }}"
        )

    def _on_theme_changed(self, mode: str):
        # Screen modules were reloaded with the new palette; rebuild the
        # page stack so every page re-renders in the new mode, keeping
        # the currently selected page selected.
        current_key = next(
            (k for k, v in self._page_map.items() if v == self._stack.currentIndex()),
            None,
        )
        while self._stack.count():
            widget = self._stack.widget(0)
            self._stack.removeWidget(widget)
            widget.deleteLater()
        self._page_map.clear()
        self._build_pages()
        self._apply_theme()
        if current_key is not None and current_key in self._page_map:
            self._stack.setCurrentIndex(self._page_map[current_key])
