from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import screens
from database import init_database
from ui import theme
from ui.menu_data import MENUS
from ui.navigation_bar import NavigationBar


class PlaceholderPage(QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        p = theme.theme_manager.palette()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        label = QLabel(title)
        label.setStyleSheet(
            "font-size: 22px;"
            f"color: {p['text']};"
            "font-weight: bold;"
        )
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)


class PharmacyMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        init_database()
        self.setWindowTitle("Pharmacy Management System")
        self.resize(1280, 750)
        self.setMinimumSize(900, 600)

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self._nav = NavigationBar()
        self._nav.menu_action_triggered.connect(self._on_menu_action)
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
                elif menu_name == "Master" and item_name == "Backup & Restore":
                    page = screens.BackupRestorePage()
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
                self._stack.addWidget(page)
                self._page_map[f"{menu_name}:{item_name}"] = page_index
                page_index += 1

    def _on_menu_action(self, menu: str, action: str):
        key = f"{menu}:{action}"
        if key in self._page_map:
            self._stack.setCurrentIndex(self._page_map[key])
            self.setWindowTitle(f"Pharmacy Management System  -  {action}")

    # ── theme ────────────────────────────────────────────────────────
    def _apply_theme(self):
        p = theme.theme_manager.palette()
        self.setStyleSheet(
            f"QMainWindow {{ background-color: {p['bg']}; }}"
            "QLabel { font-family: 'Segoe UI', sans-serif; }"
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
