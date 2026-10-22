"""Navicat-style object list for the selected database: tables/views or functions/procedures."""
from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QLabel, QLineEdit, QMenu, QSizePolicy, QStackedWidget, QToolBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import APP_NAME, db, icons

SORT_ROLE = Qt.ItemDataRole.UserRole + 1
TYPE_ROLE = Qt.ItemDataRole.UserRole
ROUTINE = "ROUTINE"  # kind used for functions + procedures
TABLE_COLUMNS = ["Name", "Type", "Rows", "Engine", "Data Size", "Index Size", "Updated", "Collation", "Comment"]
ROUTINE_COLUMNS = ["Name", "Type", "Returns", "Deterministic", "Security", "Definer", "Created", "Modified", "Comment"]


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
    # list of (routine name, "FUNCTION" | "PROCEDURE")
    open_routine_requested = pyqtSignal(list)
    new_routine_requested = pyqtSignal()
    new_query_requested = pyqtSignal()
    drop_requested = pyqtSignal(list)
    import_requested = pyqtSignal(str)  # preselected table ("" = none)
    export_requested = pyqtSignal(list)  # preselected table names

    def __init__(self, type_icons, parent=None):
        super().__init__(parent)
        self.icons = type_icons
        self.cfg = None
        self.database = None
        self.conn = None
        self.kind = None  # None = tables + views, "BASE TABLE", "VIEW" or ROUTINE
        self.loaded_mode = None

        welcome = QLabel(
            f"<h2>{APP_NAME}</h2><p>A simple MySQL client.</p>"
            "<p>Create a connection with <b>Connection</b>, then expand it in the left panel.<br>"
            "Select a database to list its objects here; double-click to open them in tabs.</p>"
        )
        welcome.setAlignment(Qt.AlignmentFlag.AlignCenter)

        page = QWidget()
        toolbar = QToolBar()
        toolbar.setIconSize(QSize(16, 16))
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.a_open = toolbar.addAction(icons.icon("open_table"), "Open Table", self._open_selected)
        self.a_design = toolbar.addAction(icons.icon("design_table"), "Design Table", lambda: self._emit_open(1))
        self.a_new_routine = toolbar.addAction(icons.icon("new_function"), "New Function",
                                               self.new_routine_requested.emit)
        self.a_drop = toolbar.addAction(icons.icon("drop_table"), "Delete Table",
                                        lambda: self.drop_requested.emit(self._selected()))
        toolbar.addSeparator()
        self.a_import = toolbar.addAction(icons.icon("import"), "Import Wizard", self._emit_import)
        self.a_export = toolbar.addAction(icons.icon("export"), "Export Wizard",
                                          lambda: self.export_requested.emit([n for n, _ in self._selected()]))
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
        self.list.setRootIsDecorated(False)
        self.list.setIconSize(QSize(16, 16))
        self.list.setSortingEnabled(True)
        self.list.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.list.itemDoubleClicked.connect(self._open_selected)
        self.list.itemSelectionChanged.connect(self._update_actions)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        for key in ("Return", "Enter"):
            QShortcut(QKeySequence(key), self.list, self._open_selected, context=Qt.ShortcutContext.WidgetShortcut)

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

    @property
    def mode(self):
        return "routines" if self.kind == ROUTINE else "tables"

    def show_database(self, cfg, database, conn, select_name=None):
        if (self.cfg, self.database) != (cfg, database) or self.loaded_mode != self.mode:
            if (self.cfg, self.database) != (cfg, database):
                self.filter.clear()
            self.cfg, self.database, self.conn = cfg, database, conn
            self.reload()
        else:
            self._apply_filter()
        if select_name:
            for i in range(self.list.topLevelItemCount()):
                it = self.list.topLevelItem(i)
                if it.text(0) == select_name:
                    self.list.setCurrentItem(it)
                    self.list.scrollToItem(it)
                    break

    def clear(self):
        self.cfg = self.database = self.conn = None
        self.loaded_mode = None
        self.list.clear()
        self.stack.setCurrentIndex(0)

    def set_kind(self, kind):
        self.kind = kind
        if self.database and self.loaded_mode != self.mode:
            self.reload()
        else:
            self._apply_filter(self.filter.text())

    # loading ------------------------------------------------------------
    def reload(self):
        if not self.database:
            return
        self.list.setSortingEnabled(False)
        self.list.clear()
        if self.mode == "routines":
            self._load_routines()
        else:
            self._load_tables()
        self.loaded_mode = self.mode
        self.list.setSortingEnabled(True)
        self.list.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        for c in range(self.list.columnCount() - 1):
            self.list.resizeColumnToContents(c)
        self.list.setColumnWidth(0, max(self.list.columnWidth(0), 180))
        self.stack.setCurrentIndex(1)
        self._update_toolbar()
        self._apply_filter(self.filter.text())

    def _load_tables(self):
        self.list.setColumnCount(len(TABLE_COLUMNS))
        self.list.setHeaderLabels(TABLE_COLUMNS)
        rs = db.execute(
            self.conn,
            "SELECT TABLE_NAME, TABLE_TYPE, TABLE_ROWS, ENGINE, DATA_LENGTH, INDEX_LENGTH, "
            "COALESCE(UPDATE_TIME, CREATE_TIME), TABLE_COLLATION, TABLE_COMMENT "
            "FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s",
            (self.database,),
        )
        for name, ttype, rows, engine, data_len, index_len, updated, collation, comment in rs.rows:
            is_view = ttype == "VIEW"
            it = _Item([
                name, "View" if is_view else "Table", "" if rows is None or is_view else f"{rows:,}",
                engine or "", human_size(data_len), human_size(index_len),
                str(updated or ""), collation or "", "" if is_view else (comment or ""),
            ])
            it.setIcon(0, self.icons["VIEW" if is_view else "BASE TABLE"])
            it.setData(0, TYPE_ROLE, "VIEW" if is_view else "BASE TABLE")
            for col, raw in ((2, rows), (4, data_len), (5, index_len)):
                it.setData(col, SORT_ROLE, raw)
                it.setTextAlignment(col, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.list.addTopLevelItem(it)

    def _load_routines(self):
        self.list.setColumnCount(len(ROUTINE_COLUMNS))
        self.list.setHeaderLabels(ROUTINE_COLUMNS)
        for name, rtype, returns, deterministic, security, definer, created, modified, comment in \
                db.list_routines(self.conn, self.database, details=True):
            it = _Item([name, rtype.title(), returns or "", "YES" if deterministic == "YES" else "NO",
                        security or "", definer or "", str(created or ""), str(modified or ""), comment or ""])
            it.setIcon(0, self.icons[rtype])
            it.setData(0, TYPE_ROLE, rtype)
            self.list.addTopLevelItem(it)

    # filtering / selection ----------------------------------------------------
    def _apply_filter(self, text=None):
        text = (self.filter.text() if text is None else text).strip().lower()
        shown = 0
        for i in range(self.list.topLevelItemCount()):
            it = self.list.topLevelItem(i)
            wrong_kind = self.kind in ("BASE TABLE", "VIEW") and it.data(0, TYPE_ROLE) != self.kind
            hide = (bool(text) and text not in it.text(0).lower()) or wrong_kind
            it.setHidden(hide)
            shown += not hide
        what = {None: "object", "BASE TABLE": "table", "VIEW": "view", ROUTINE: "function"}[self.kind]
        if self.database:
            self.title.setText(f"{self.database} — {shown} {what}{'' if shown == 1 else 's'}")

    def _selected(self):
        return [(it.text(0), it.data(0, TYPE_ROLE)) for it in self.list.selectedItems() if not it.isHidden()]

    def _open_selected(self, *_):
        if self.mode == "routines":
            selected = self._selected()
            if selected:
                self.open_routine_requested.emit(selected)
        else:
            self._emit_open(0)

    def _emit_import(self):
        tables = [n for n, t in self._selected() if t == "BASE TABLE"]
        self.import_requested.emit(tables[0] if len(tables) == 1 else "")

    def _emit_open(self, page):
        selected = self._selected()
        if selected:
            self.open_requested.emit(selected, page)

    def _update_toolbar(self):
        routines = self.mode == "routines"
        self.a_open.setText("Design Function" if routines else "Open Table")
        self.a_open.setIcon(icons.icon("design_function" if routines else "open_table"))
        self.a_design.setVisible(not routines)
        self.a_new_routine.setVisible(routines)
        self.a_import.setVisible(not routines)
        self.a_export.setVisible(not routines)
        self.a_drop.setText("Delete Function" if routines else "Delete Table")
        self.a_drop.setIcon(icons.icon("drop_function" if routines else "drop_table"))

    def _update_actions(self):
        has = bool(self.list.selectedItems())
        for a in (self.a_open, self.a_design, self.a_drop):
            a.setEnabled(has)

    def _menu(self, pos):
        menu = QMenu(self)
        n = len(self._selected()) if self.list.itemAt(pos) else 0
        if self.mode == "routines":
            if n:
                menu.addAction(icons.icon("design_function"), "Design Function", self._open_selected)
            menu.addAction(icons.icon("new_function"), "New Function…", self.new_routine_requested.emit)
            if n:
                menu.addSeparator()
                menu.addAction(icons.icon("drop_function"), "Delete Function" if n == 1 else f"Delete {n} Functions",
                               lambda: self.drop_requested.emit(self._selected()))
        else:
            if not n:
                return
            menu.addAction(icons.icon("open_table"), "Open Table" if n == 1 else f"Open {n} Tables",
                           lambda: self._emit_open(0))
            menu.addAction(icons.icon("design_table"), "Design Table", lambda: self._emit_open(1))
            menu.addAction("Show DDL", lambda: self._emit_open(2))
            menu.addSeparator()
            menu.addAction(icons.icon("new_query"), "New Query", self.new_query_requested.emit)
            menu.addSeparator()
            menu.addAction(icons.icon("import"), "Import Wizard…", self._emit_import)
            menu.addAction(icons.icon("export"), "Export Wizard…",
                           lambda: self.export_requested.emit([n for n, _ in self._selected()]))
            menu.addSeparator()
            menu.addAction(icons.icon("drop_table"), "Delete Table" if n == 1 else f"Delete {n} Objects",
                           lambda: self.drop_requested.emit(self._selected()))
        menu.exec(self.list.viewport().mapToGlobal(pos))
