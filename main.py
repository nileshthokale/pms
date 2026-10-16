import sys

from PySide6.QtWidgets import QApplication

from database import auth
from database.connection import init_database
from database.financial_year import ensure_default_financial_year
from screens.login import run_login
from ui import PharmacyMainWindow
from ui import theme
from ui.input_rules import install_uppercase_input


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    # Light, traditional desktop theme is the application default; the
    # centralized palette + application-wide stylesheet also cover the
    # login dialog and every unstyled surface (no hardcoded colours).
    theme.apply_to_app(app)
    # Business-data text is upper-cased as it is typed, everywhere.  The
    # watcher is installed here — before the login dialog and before any
    # screen exists — so every field in the application is covered without
    # each screen having to opt in.  Password fields, read-only fields,
    # file dialogs and numeric spin boxes exclude themselves (see
    # ui/input_rules.py).
    install_uppercase_input(app)

    init_database()
    auth.ensure_auth_schema()
    ensure_default_financial_year()
    if not run_login():
        return

    window = PharmacyMainWindow()
    # The application starts maximized on a normal Windows desktop
    # (standard maximize: title bar and min/max/close controls stay).
    window.showMaximized()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
