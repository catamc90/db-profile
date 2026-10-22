"""Flat, Navicat-like light theme: Fusion style + palette + stylesheet. No gradients or shadows."""
import os

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

from . import icons

ACCENT = "#2d7ff9"
ACCENT_HOVER = "#1f6fe5"
SELECTION = "#cfe2fc"
HOVER = "#e7ebf1"
WINDOW = "#f3f3f3"
PANEL = "#f7f7f7"
BORDER = "#dcdcdc"
INPUT_BORDER = "#cbcbcb"
TEXT = "#262626"
MUTED = "#7a7a7a"

STYLESHEET = """
* { outline: 0; }
QMainWindow, QDialog { background: %(WINDOW)s; }
QWidget { color: %(TEXT)s; }
QLabel { background: transparent; }

/* menus */
QMenuBar { background: %(PANEL)s; border: none; padding: 1px 2px; }
QMenuBar::item { background: transparent; padding: 4px 10px; border-radius: 3px; }
QMenuBar::item:selected { background: %(HOVER)s; }
QMenu { background: #ffffff; border: 1px solid #c8c8c8; padding: 4px 0; }
QMenu::item { padding: 5px 26px 5px 22px; background: transparent; }
QMenu::item:selected { background: %(ACCENT)s; color: #ffffff; }
QMenu::item:disabled { color: #a8a8a8; }
QMenu::separator { height: 1px; background: #e6e6e6; margin: 4px 0; }

/* tool bars */
QToolBar { background: %(PANEL)s; border: none; border-bottom: 1px solid %(BORDER)s; padding: 3px 6px; spacing: 2px; }
QToolBar::separator { background: %(BORDER)s; width: 1px; margin: 5px 6px; }
QToolButton { background: transparent; border: 1px solid transparent; border-radius: 4px; padding: 3px 6px; }
QToolButton:hover { background: %(HOVER)s; }
QToolButton:pressed, QToolButton:checked { background: #d8dee7; }
QToolButton:disabled { color: #ababab; }
QToolBar#mainToolbar { background: %(PANEL)s; padding: 4px 8px; border-bottom: 1px solid %(BORDER)s; }
QToolBar#mainToolbar QToolButton { padding: 4px 8px; min-width: 64px; }

/* item views */
QTreeView, QTreeWidget, QTableView, QListView {
    background: #ffffff; border: none;
    selection-background-color: %(SELECTION)s; selection-color: %(TEXT)s;
}
QTreeView::item { padding: 3px 2px; border: none; }
QTreeView::item:hover { background: #f0f4fa; }
QTreeView::item:selected { background: %(SELECTION)s; color: %(TEXT)s; }
QTableView { gridline-color: #e4e4e4; alternate-background-color: #f8fafc; }
QTableView::item { padding: 0 4px; }
QTableView::item:selected { background: %(SELECTION)s; color: %(TEXT)s; }
QHeaderView { background: %(PANEL)s; border: none; }
QHeaderView::section {
    background: %(PANEL)s; color: #3a3a3a; border: none;
    border-right: 1px solid #e2e2e2; border-bottom: 1px solid #e2e2e2; padding: 4px 6px;
}
QHeaderView::section:vertical { color: #8f8f8f; padding: 0 6px; }
QHeaderView::section:hover { background: #eef1f5; }
QHeaderView::down-arrow { image: url(%(ICONS)s/arrow_down.png); width: 9px; height: 9px; subcontrol-position: center right; padding-right: 4px; }
QHeaderView::up-arrow { image: url(%(ICONS)s/arrow_up.png); width: 9px; height: 9px; subcontrol-position: center right; padding-right: 4px; }
QTableCornerButton::section { background: %(PANEL)s; border: none; border-right: 1px solid #e2e2e2; border-bottom: 1px solid #e2e2e2; }

/* editors */
QPlainTextEdit, QTextEdit { background: #ffffff; border: none; selection-background-color: #b9d4fb; selection-color: %(TEXT)s; }

/* main document tabs */
QTabWidget::pane { border: none; border-top: 1px solid %(BORDER)s; background: #ffffff; }
QTabWidget::tab-bar { left: 0; }
QTabBar { background: transparent; }
QTabBar::tab {
    background: transparent; color: #5a5a5a; border: none; border-right: 1px solid %(BORDER)s;
    border-top: 2px solid transparent; padding: 6px 10px 6px 12px; min-width: 50px;
}
QTabBar::tab:hover:!selected { background: #e9e9e9; }
QTabBar::tab:selected { background: #ffffff; color: #1a1a1a; border-top: 2px solid %(ACCENT)s; }
QTabBar::close-button { image: url(%(ICONS)s/close.png); subcontrol-position: right; margin: 2px; border-radius: 2px; }
QTabBar::close-button:hover { image: url(%(ICONS)s/close_hover.png); background: #dcdcdc; }
QTabBar QToolButton { background: %(WINDOW)s; border: none; }

/* secondary tabs (Data/Structure/DDL, query results) */
QTabWidget#subTabs::pane { border: none; border-top: 1px solid #e6e6e6; background: #ffffff; }
QTabWidget#subTabs > QTabBar { background: #ffffff; }
QTabWidget#subTabs > QTabBar::tab {
    background: transparent; color: #5a5a5a; border: none; border-bottom: 2px solid transparent;
    padding: 5px 12px; min-width: 40px;
}
QTabWidget#subTabs > QTabBar::tab:hover:!selected { color: %(TEXT)s; background: transparent; }
QTabWidget#subTabs > QTabBar::tab:selected { color: %(ACCENT)s; border-bottom: 2px solid %(ACCENT)s; }

/* inputs */
QLineEdit, QSpinBox, QComboBox {
    background: #ffffff; border: 1px solid %(INPUT_BORDER)s; border-radius: 3px;
    padding: 3px 6px; min-height: 18px; selection-background-color: %(ACCENT)s; selection-color: #ffffff;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: %(ACCENT)s; }
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled { background: #f4f4f4; color: #a0a0a0; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox::down-arrow { image: url(%(ICONS)s/arrow_down.png); width: 10px; height: 10px; }
QComboBox QAbstractItemView {
    background: #ffffff; border: 1px solid #c8c8c8; outline: 0;
    selection-background-color: %(ACCENT)s; selection-color: #ffffff;
}
QSpinBox { padding-right: 18px; }
QSpinBox::up-button, QSpinBox::down-button { border: none; background: transparent; width: 16px; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: %(HOVER)s; }
QSpinBox::up-arrow { image: url(%(ICONS)s/arrow_up.png); width: 9px; height: 9px; }
QSpinBox::down-arrow { image: url(%(ICONS)s/arrow_down.png); width: 9px; height: 9px; }

QPushButton {
    background: #ffffff; border: 1px solid #c4c4c4; border-radius: 3px;
    padding: 4px 14px; min-height: 18px; min-width: 64px;
}
QPushButton:hover { background: #f2f2f2; }
QPushButton:pressed { background: #e5e5e5; }
QPushButton:default { background: %(ACCENT)s; border-color: %(ACCENT)s; color: #ffffff; }
QPushButton:default:hover { background: %(ACCENT_HOVER)s; }
QPushButton:disabled { background: #f4f4f4; border-color: #dddddd; color: #a8a8a8; }

QCheckBox { spacing: 6px; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #b5b5b5; border-radius: 3px; background: #ffffff; }
QCheckBox::indicator:hover { border-color: %(ACCENT)s; }
QCheckBox::indicator:checked { background: %(ACCENT)s; border-color: %(ACCENT)s; image: url(%(ICONS)s/check.png); }
QCheckBox::indicator:indeterminate { background: %(ACCENT)s; border-color: %(ACCENT)s; image: url(%(ICONS)s/dash.png); }
QCheckBox[changed="true"] { color: %(ACCENT)s; font-weight: 600; }
QCheckBox#groupHead { font-weight: 600; }

/* privilege groups (user editor) */
QFrame#privGroup { background: #ffffff; border: 1px solid #e3e3e3; border-radius: 4px; }
QFrame#privGroup QCheckBox { background: transparent; }
QFrame#hline { background: #ececec; max-height: 1px; min-height: 1px; border: none; }
QPushButton#chip { min-width: 0; padding: 3px 10px; border-radius: 11px; background: #ffffff; }
QPushButton#chip:hover { border-color: %(ACCENT)s; color: %(ACCENT)s; }

QRadioButton { spacing: 6px; }
QRadioButton::indicator { width: 14px; height: 14px; border: 1px solid #b5b5b5; border-radius: 8px; background: #ffffff; }
QRadioButton::indicator:hover { border-color: %(ACCENT)s; }
QRadioButton::indicator:checked { border: 5px solid %(ACCENT)s; width: 6px; height: 6px; }
QRadioButton::indicator:disabled { background: #f0f0f0; border-color: #d0d0d0; }

QProgressBar { background: #ffffff; border: 1px solid %(INPUT_BORDER)s; border-radius: 3px; text-align: center; min-height: 16px; }
QProgressBar::chunk { background: %(ACCENT)s; border-radius: 2px; }

QWizard QLabel#qt_wizard_title { font-weight: bold; }

/* scroll bars */
QScrollBar:vertical { background: transparent; width: 11px; margin: 0; }
QScrollBar:horizontal { background: transparent; height: 11px; margin: 0; }
QScrollBar::handle:vertical { background: #cacaca; border-radius: 4px; min-height: 28px; margin: 2px; }
QScrollBar::handle:horizontal { background: #cacaca; border-radius: 4px; min-width: 28px; margin: 2px; }
QScrollBar::handle:hover { background: #a8a8a8; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; border: none; background: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QAbstractScrollArea::corner { background: transparent; }

QSplitter::handle { background: %(BORDER)s; }
QSplitter::handle:horizontal { width: 1px; }
QSplitter::handle:vertical { height: 1px; }

QStatusBar { background: %(PANEL)s; border-top: 1px solid %(BORDER)s; color: #555555; }
QStatusBar::item { border: none; }
QToolTip { background: #ffffff; color: %(TEXT)s; border: 1px solid #c8c8c8; padding: 4px 6px; }

/* bars inside table tabs */
QFrame#filterBar { background: #fafafa; border: none; border-bottom: 1px solid #e6e6e6; }
QFrame#bottomBar { background: %(PANEL)s; border: none; border-top: 1px solid %(BORDER)s; }
QFrame#bottomBar QToolButton { padding: 2px; border-radius: 3px; }
QLabel#sqlLabel, QLabel#muted { color: %(MUTED)s; }
QFrame#vline { background: %(BORDER)s; max-width: 1px; min-width: 1px; margin: 3px 4px; }
"""


def _palette() -> QPalette:
    pal = QPalette()
    colors = {
        QPalette.ColorRole.Window: WINDOW,
        QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: "#ffffff",
        QPalette.ColorRole.AlternateBase: "#f6f7f9",
        QPalette.ColorRole.Text: TEXT,
        QPalette.ColorRole.Button: PANEL,
        QPalette.ColorRole.ButtonText: TEXT,
        QPalette.ColorRole.BrightText: "#ffffff",
        QPalette.ColorRole.Highlight: ACCENT,
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.ToolTipBase: "#ffffff",
        QPalette.ColorRole.ToolTipText: TEXT,
        QPalette.ColorRole.PlaceholderText: "#9a9a9a",
        QPalette.ColorRole.Link: ACCENT,
        # Fusion derives bevels from these; keep them flat and close to the window colour.
        QPalette.ColorRole.Light: "#ffffff",
        QPalette.ColorRole.Midlight: "#ececec",
        QPalette.ColorRole.Mid: BORDER,
        QPalette.ColorRole.Dark: "#bdbdbd",
        QPalette.ColorRole.Shadow: "#bdbdbd",
    }
    for role, color in colors.items():
        pal.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor("#a8a8a8"))
    return pal


def _write_glyphs() -> str:
    """Render the small images the stylesheet needs (1x and @2x) into the cache dir."""
    cache = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "dbprofile", "theme")
    os.makedirs(cache, exist_ok=True)
    glyphs = {
        "close": lambda p: icons.close(p, icons.GRAY),
        "close_hover": lambda p: icons.close(p, icons.DARK),
        "arrow_down": icons.arrow_down,
        "arrow_up": icons.arrow_up,
        "check": icons.check,
        "dash": icons.dash,
    }
    for name, draw in glyphs.items():
        icons.save_png(draw, os.path.join(cache, f"{name}.png"), 16)
        icons.save_png(draw, os.path.join(cache, f"{name}@2x.png"), 32)
    return cache


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setPalette(_palette())
    values = {k: v for k, v in globals().items() if k.isupper() and isinstance(v, str)}
    values["ICONS"] = _write_glyphs()
    app.setStyleSheet(STYLESHEET % values)
