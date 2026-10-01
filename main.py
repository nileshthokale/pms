import sys

from PySide6.QtWidgets import QApplication

from database import auth
from database.connection import init_database
from database.financial_year import ensure_default_financial_year
from screens.login import run_login
from ui import PharmacyMainWindow
from ui import theme


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    # Light, traditional desktop theme is the application default; the
    # application-wide stylesheet also covers the login dialog.
    app.setStyleSheet(theme.stylesheet())

    init_database()
    auth.ensure_auth_schema()
    ensure_default_financial_year()
    if not run_login():
        return

    window = PharmacyMainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
