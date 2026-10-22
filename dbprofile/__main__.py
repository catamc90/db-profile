import sys

from PyQt6.QtWidgets import QApplication

from . import APP_NAME, theme
from .main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName("dbprofile")
    theme.apply(app)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
