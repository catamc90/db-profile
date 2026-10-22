"""Navicat-style object list: every table/view of the selected database."""
from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QLabel, QLineEdit, QMenu, QSizePolicy, QStackedWidget, QToolBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import APP_NAME, db, icons

SORT_ROLE = Qt.ItemDataRole.UserRole + 1
COLUMNS = ["Name", "Type", "Rows", "Engine", "Data Size", "Index Size", "Updated", "Collation", "Comment"]


def human_size(n):
    if n is None:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


class _Item(QTreeWidgetItem):
    """Sorts numeric columns by their raw value instead of the displayed text."""

    def __lt__(self, other):
        col = self.treeWidget().sortColumn()
        a, b = self.data(col, SORT_ROLE), other.data(col, SORT_ROLE)
        if a is not None or b is not None:
            return (a if a is not None else -1) < (b if b is not None else -1)
        return self.text(col).lower() < other.text(col).lower()


class ObjectsTab(QWidget):
    # list of (table, type) to open; page 0 = data, 1 = structure, 2 = DDL
    open_requested = pyqtSignal(list, int)
    new_query_requested = pyqtSignal()
    drop_requested = pyqtSignal(list)

    def __init__(self, type_icons, parent=None):
        super().__init__(parent)
        self.icons = type_icons
        self.cfg = None
        self.database = None
        self.kind = None  # None = all, or "BASE TABLE" / "VIEW"

        welcome = QLabel(
            f"<h2>{APP_NAME}</h2><p>A simple MySQL client.</p>"
            "<p>Create a connection with <b>New Connection</b>, then expand it in the left panel.<br>"
            "Select a database to list its tables here; double-click tables to open them in tabs.</p>"
        )
        welcome.setAlignment(Qt.AlignmentFlag.AlignCenter)

        page = QWidget()
        toolbar = QToolBar()
        toolbar.setIconSize(QSize(16, 16))
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.a_open = toolbar.addAction(icons.icon("open_table"), "Open Table", lambda: self._emit_open(0))
        self.a_design = toolbar.addAction(icons.icon("design_table"), "Design Table", lambda: self._emit_open(1))
        self.a_drop = toolbar.addAction(icons.icon("drop_table"), "Delete Table",
                                        lambda: self.drop_requested.emit(self._selected()))
        toolbar.addSeparator()
        toolbar.addAction(icons.icon("new_query"), "New Query", self.new_query_requested.emit)
        toolbar.addAction(icons.icon("refresh"), "Refresh", self.reload)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        self.title = QLabel()
        self.title.setObjectName("muted")
        self.title.setContentsMargins(0, 0, 8, 0)
        toolbar.addWidget(self.title)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Search")
        self.filter.setClearButtonEnabled(True)
        self.filter.setFixedWidth(200)
        self.filter.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self.filter)

        self.list = QTreeWidget()
        self.list.setColumnCount(len(COLUMNS))
        self.list.setHeaderLabels(COLUMNS)
        self.list.setRootIsDecorated(False)
        self.list.setAlternatingRowColors(False)
        self.list.setIconSize(QSize(16, 16))
        self.list.setSortingEnabled(True)
        self.list.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.list.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.list.itemDoubleClicked.connect(lambda *_: self._emit_open(0))
        self.list.itemSelectionChanged.connect(self._update_actions)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        for key in ("Return", "Enter"):
            QShortcut(QKeySequence(key), self.list, lambda: self._emit_open(0),
                      context=Qt.ShortcutContext.WidgetShortcut)

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(toolbar)
        layout.addWidget(self.list)

        self.stack = QStackedWidget()
        self.stack.addWidget(welcome)
        self.stack.addWidget(page)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.stack)
        self._update_actions()

    def show_database(self, cfg, database, conn, select_table=None):
        if (self.cfg, self.database) != (cfg, database):
            self.cfg, self.database, self.conn = cfg, database, conn
            self.filter.clear()
            self.reload()
        if select_table:
            for i in range(self.list.topLevelItemCount()):
                it = self.list.topLevelItem(i)
                if it.text(0) == select_table:
                    self.list.setCurrentItem(it)
                    self.list.scrollToItem(it)
                    break

    def clear(self):
        self.cfg = self.database = self.conn = None
        self.list.clear()
        self.stack.setCurrentIndex(0)

    def reload(self):
        if not self.database:
            return
        rs = db.execute(
            self.conn,
            "SELECT TABLE_NAME, TABLE_TYPE, TABLE_ROWS, ENGINE, DATA_LENGTH, INDEX_LENGTH, "
            "COALESCE(UPDATE_TIME, CREATE_TIME), TABLE_COLLATION, TABLE_COMMENT "
            "FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s",
            (self.database,),
        )
        self.list.setSortingEnabled(False)
        self.list.clear()
        for name, ttype, rows, engine, data_len, index_len, updated, collation, comment in rs.rows:
            is_view = ttype == "VIEW"
            it = _Item([
                name, "View" if is_view else "Table", "" if rows is None or is_view else f"{rows:,}",
                engine or "", human_size(data_len), human_size(index_len),
                str(updated or ""), collation or "", "" if is_view else (comment or ""),
            ])
            it.setIcon(0, self.icons["VIEW" if is_view else "BASE TABLE"])
            it.setData(0, Qt.ItemDataRole.UserRole, "VIEW" if is_view else "BASE TABLE")
            for col, raw in ((2, rows), (4, data_len), (5, index_len)):
                it.setData(col, SORT_ROLE, raw)
                it.setTextAlignment(col, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.list.addTopLevelItem(it)
        self.list.setSortingEnabled(True)
        for c in range(len(COLUMNS) - 1):
            self.list.resizeColumnToContents(c)
        self.list.setColumnWidth(0, max(self.list.columnWidth(0), 180))
        self.stack.setCurrentIndex(1)
        self._apply_filter(self.filter.text())

    def set_kind(self, kind):
        self.kind = kind
        self._apply_filter(self.filter.text())

    def _apply_filter(self, text):
        text = text.strip().lower()
        shown = 0
        for i in range(self.list.topLevelItemCount()):
            it = self.list.topLevelItem(i)
            hide = (bool(text) and text not in it.text(0).lower()) or \
                (self.kind is not None and it.data(0, Qt.ItemDataRole.UserRole) != self.kind)
            it.setHidden(hide)
            shown += not hide
        what = {None: "object", "BASE TABLE": "table", "VIEW": "view"}[self.kind]
        if self.database:
            self.title.setText(f"{self.database} — {shown} {what}{'' if shown == 1 else 's'}")

    def _selected(self):
        return [(it.text(0), it.data(0, Qt.ItemDataRole.UserRole))
                for it in self.list.selectedItems() if not it.isHidden()]

    def _emit_open(self, page):
        selected = self._selected()
        if selected:
            self.open_requested.emit(selected, page)

    def _update_actions(self):
        has = bool(self.list.selectedItems())
        for a in (self.a_open, self.a_design, self.a_drop):
            a.setEnabled(has)

    def _menu(self, pos):
        if not self.list.itemAt(pos):
            return
        n = len(self._selected())
        menu = QMenu(self)
        menu.addAction(icons.icon("open_table"), "Open Table" if n == 1 else f"Open {n} Tables",
                       lambda: self._emit_open(0))
        menu.addAction(icons.icon("design_table"), "Design Table", lambda: self._emit_open(1))
        menu.addAction("Show DDL", lambda: self._emit_open(2))
        menu.addSeparator()
        menu.addAction(icons.icon("new_query"), "New Query", self.new_query_requested.emit)
        menu.addSeparator()
        menu.addAction(icons.icon("drop_table"), "Delete Table" if n == 1 else f"Delete {n} Objects",
                       lambda: self.drop_requested.emit(self._selected()))
        menu.exec(self.list.viewport().mapToGlobal(pos))
