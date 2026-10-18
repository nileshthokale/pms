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
        body.setStyleSheet(ui.label_style(dim=True))
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
                elif menu_name == "Reports" and item_name == "Supplier Ledger":
                    page = screens.SupplierLedgerPage()
                elif menu_name == "Reports" and item_name == "Customer Ledger":
                    page = screens.CustomerLedgerPage()
                elif menu_name == "Reports" and item_name == "Itemwise Ledger":
                    page = screens.ItemwiseLedgerPage()
                elif menu_name == "Sales" and item_name == "New Bill":
                    page = screens.CounterSalePage()
                    # The Counter Sale toolbar's "Sales History" button is
                    # a second entry point: route it through the identical
                    # menu action so both open the same page, view and
                    # status text (one navigation path, no duplicate
                    # handlers or routes).
                    page.sales_history_requested.connect(
                        lambda: self._on_menu_action("Sales", "Sales History")
                    )
                elif menu_name == "Sales" and item_name == "Hold Bill":
                    page = screens.HoldBillPage()
                elif menu_name == "Sales" and item_name == "Day End":
                    page = screens.DayEndPage()
                elif menu_name == "Sales" and item_name == "Sales History":
                    page = screens.SalesHistoryPage()
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
        """Show every report for a chosen financial year.

        This is a VIEW filter only.  The active financial year is never
        changed and nothing is written; each page that defines
        ``set_history_financial_year`` scopes its own date filter to the
        chosen year (period reports use 1 April–31 March, position
        reports use the 31 March closing date).
        """
        for index in range(self._stack.count()):
            page = self._stack.widget(index)
            apply_view = getattr(page, "set_history_financial_year", None)
            if callable(apply_view):
                apply_view(year)
        self._nav.set_viewing_financial_year(year)

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
        # Centralized palette + application stylesheet so dialogs, message
        # boxes, menus, tooltips, combo dropdowns, completer popups and
        # calendar popups follow the Day/Night mode immediately.
        theme.apply_to_app()
        p = theme.theme_manager.palette()
        self.setStyleSheet(
            f"QMainWindow, QStackedWidget, QWidget#CentralWorkspace"
            f" {{ background-color: {p['bg']}; }}"
        )

    def _on_theme_changed(self, mode: str):
        # In-place refresh: every existing page keeps its state (bill
        # drafts, form inputs, selection, scroll position) and only its
        # colours are recomputed from the live centralized palette.  The
        # previous destroy-and-rebuild approach wiped in-progress drafts
        # on every Day/Night switch.
        self._apply_theme()
        for index in range(self._stack.count()):
            page = self._stack.widget(index)
            if page is None:
                continue
            self._refresh_widget_tree(page)
        self._refresh_open_dialogs()
        try:
            theme.repolish_all()
        except Exception:
            pass

    def _refresh_widget_tree(self, root):
        """Re-apply the live theme to an existing widget tree, in place.

        The page's own ``refresh_theme()`` has full role knowledge but is
        written per screen and, on Counter Sale, never reached the plain
        container chrome (the page title strip, the history filter bar and
        the right-side Bill panel).  The shared passes are therefore run as
        well: ``refresh_tree`` only touches components-tagged widgets and
        ``refresh_containers`` only rewrites baked background/border roles,
        so neither can disturb a screen's own styling.  State (drafts,
        selection, scroll) is preserved — nothing is rebuilt.
        """
        refreshed = False
        refresh = getattr(root, "refresh_theme", None)
        if callable(refresh):
            try:
                refresh()
                refreshed = True
            except Exception:
                refreshed = False
        # The shared passes always run.  They are disjoint by construction:
        # ``refresh_tree`` only touches components-tagged widgets and
        # ``refresh_containers`` skips exactly those (and any widget whose
        # style the screen owner already refreshed), so one can never undo
        # the other.
        try:
            ui.refresh_tree(root)
        except Exception:
            pass
        try:
            ui.refresh_containers(root)
        except Exception:
            pass
        if not refreshed:
            # Fallback for pages without an explicit refresh_theme():
            # components widgets, generic baked screen patterns (group
            # boxes, tables, inputs, buttons, labels, popups), then
            # repaint.
            try:
                ui.refresh_generic_screen(root)
            except Exception:
                pass
            try:
                ui.refresh_popups(root)
            except Exception:
                pass
        try:
            style = root.style()
            if style is not None:
                style.unpolish(root)
                style.polish(root)
            root.update()
        except Exception:
            pass

    def _refresh_open_dialogs(self):
        """Refresh visible dialogs owned by this window (in place).

        An open Sales Bill review popup (or any other modal) is not part of
        the page stack, so without this it kept its baked colours until it
        was closed and reopened.
        """
        try:
            from PySide6.QtWidgets import QApplication, QDialog
        except Exception:
            return
        try:
            widgets = list(QApplication.topLevelWidgets())
        except Exception:
            return
        for widget in widgets:
            try:
                if widget is self or not isinstance(widget, QDialog):
                    continue
                if not widget.isVisible() or not self.isAncestorOf(widget):
                    continue
            except Exception:
                continue
            self._refresh_widget_tree(widget)
