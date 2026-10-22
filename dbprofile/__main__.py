import os
import sys

from PyQt6.QtWidgets import QApplication

from . import APP_NAME, icons, theme
from .main_window import MainWindow


def _use_native_window_frames():
    """On GNOME Wayland, run through XWayland so windows and dialogs get GNOME's title bars and shadows.

    GNOME draws no window frames for Wayland clients, and Qt's fallback frame has no shadow, so a dialog
    such as Import Connections blends into the main window. Setting QT_QPA_PLATFORM overrides this.
    """
    if os.environ.get("QT_QPA_PLATFORM") or "-platform" in sys.argv:
        return
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
    if os.environ.get("XDG_SESSION_TYPE") == "wayland" and "GNOME" in desktop and os.environ.get("DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "xcb"


def main():
    _use_native_window_frames()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName("dbprofile")
    app.setWindowIcon(icons.icon("app"))
    theme.apply(app)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
