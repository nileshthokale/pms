import sys

from PySide6.QtWidgets import QApplication

from ui import PharmacyMainWindow


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = PharmacyMainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
