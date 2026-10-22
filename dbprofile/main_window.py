from PyQt6.QtCore import QSettings, QSize, Qt
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QInputDialog, QLineEdit, QMainWindow, QMenu, QMessageBox, QSplitter, QTabWidget, QTreeWidget,
    QTreeWidgetItem,
)

from . import APP_NAME, APP_VERSION, db, icons
from .config import load_connections, save_connections
from .connection_dialog import ConnectionDialog
from .connections_dialogs import ExportConnectionsDialog, ImportConnectionsDialog
from .objects_tab import ROUTINE, ObjectsTab
from .query_tab import QueryTab
from .routine_tab import RoutineTab
from .table_tab import TableTab
from . import transfer_wizards
from .users_tab import UsersTab

ROLE = Qt.ItemDataRole.UserRole
CONNECTION, DATABASE, GROUP, TABLE, ROUTINE_ITEM, PLACEHOLDER = (
    "connection", "database", "group", "table", "routine", "placeholder")
# Object groups shown under each database in the tree, like Navicat.
GROUPS = [("Tables", "BASE TABLE"), ("Views", "VIEW"), ("Functions", ROUTINE)]
SYSTEM_SCHEMAS = {"information_schema", "mysql", "performance_schema", "sys"}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1200, 760)
        self.connections = load_connections()
        self.open_conns = {}  # connection id -> pymysql connection used by the tree
        self.query_counter = 0

        self.icons = {
            CONNECTION: icons.icon("connection"),
            "connection_closed": icons.icon("connection_closed"),
            DATABASE: icons.icon("database"),
            "database_closed": icons.icon("database_closed"),
            "BASE TABLE": icons.icon("table"),
            "VIEW": icons.icon("view"),
            "FUNCTION": icons.icon("function"),
            "PROCEDURE": icons.icon("procedure"),
            ROUTINE: icons.icon("function"),
        }

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.setIconSize(QSize(16, 16))
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.tree.itemExpanded.connect(self._expand)
        self.tree.itemDoubleClicked.connect(self._double_clicked)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.objects = ObjectsTab(self.icons)
        self.objects.open_requested.connect(self._open_from_objects)
        self.objects.new_query_requested.connect(self._query_from_objects)
        self.objects.drop_requested.connect(self.drop_objects)
        self.objects.open_routine_requested.connect(self._open_routines_from_objects)
        self.objects.import_requested.connect(
            lambda table: self.import_wizard(self.objects.cfg, self.objects.database, table or None))
        self.objects.export_requested.connect(
            lambda names: self.export_wizard(self.objects.cfg, self.objects.database, names))
        self.objects.new_routine_requested.connect(
            lambda: self.new_routine(self.objects.cfg, self.objects.database))
        self.tabs.addTab(self.objects, icons.icon("objects"), "Objects")
        # The Objects tab is permanent: no close button.
        self.tabs.tabBar().setTabButton(0, self.tabs.tabBar().ButtonPosition.RightSide, None)
        self.tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self._tab_menu)
        self.tabs.tabBar().installEventFilter(self)
        self.tree.currentItemChanged.connect(self._tree_selection_changed)

        splitter = QSplitter()
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self.tree)
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 940])
        self.setCentralWidget(splitter)

        self._build_actions()
        self._populate_tree()
        self.statusBar().showMessage("Ready")

        settings = QSettings("dbprofile", "dbprofile")
        if settings.value("geometry"):
            self.restoreGeometry(settings.value("geometry"))

    # actions / menus ----------------------------------------------------
    def _build_actions(self):
        tb = self.addToolBar("Main")
        tb.setObjectName("mainToolbar")
        tb.setMovable(False)
        tb.setIconSize(QSize(30, 30))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)

        new_conn = QAction(icons.icon("connection"), "Connection", self)
        new_conn.setToolTip("New connection")
        new_conn.triggered.connect(self.new_connection)
        new_query = QAction(icons.icon("new_query"), "New Query", self)
        new_query.setShortcut(QKeySequence("Ctrl+Q"))
        new_query.triggered.connect(lambda: self.new_query())
        show_tables = QAction(icons.icon("table"), "Table", self)
        show_tables.setToolTip("List the tables of the selected database")
        show_tables.triggered.connect(lambda: self.show_objects("BASE TABLE"))
        show_views = QAction(icons.icon("view"), "View", self)
        show_views.setToolTip("List the views of the selected database")
        show_views.triggered.connect(lambda: self.show_objects("VIEW"))
        show_functions = QAction(icons.icon("function"), "Function", self)
        show_functions.setToolTip("List the functions and procedures of the selected database")
        show_functions.triggered.connect(lambda: self.show_objects(ROUTINE))
        users = QAction(icons.icon("user"), "User", self)
        users.setToolTip("Manage the users of the selected connection")
        users.triggered.connect(lambda: self.open_users())
        refresh = QAction(icons.icon("refresh"), "Refresh", self)
        refresh.setShortcut(QKeySequence("Ctrl+R"))
        refresh.triggered.connect(self.refresh_selected)
        close_tab = QAction("Close Tab", self)
        close_tab.setShortcut(QKeySequence("Ctrl+W"))
        close_tab.triggered.connect(lambda: self.close_tab(self.tabs.currentIndex()))
        self.addAction(close_tab)
        for a in (new_conn, new_query, None, show_tables, show_views, show_functions, None, users, None, refresh):
            if a is None:
                tb.addSeparator()
            else:
                tb.addAction(a)

        menu = self.menuBar().addMenu("&File")
        menu.addAction(icons.icon("connection"), "New Connection…", self.new_connection)
        menu.addSeparator()
        menu.addAction(icons.icon("import"), "Import Connections…", self.import_connections)
        menu.addAction(icons.icon("export"), "Export Connections…", self.export_connections)
        menu.addSeparator()
        menu.addAction(new_query)
        menu.addAction(close_tab)
        menu.addSeparator()
        menu.addAction("Quit", QKeySequence.StandardKey.Quit, self.close)
        view = self.menuBar().addMenu("&View")
        view.addAction(show_tables)
        view.addAction(show_views)
        view.addAction(show_functions)
        view.addAction(users)
        view.addSeparator()
        view.addAction(refresh)
        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction("About", lambda: QMessageBox.about(
            self, f"About {APP_NAME}", f"<b>{APP_NAME}</b> {APP_VERSION}<br>A simple MySQL client for Linux."))

    def _tree_menu(self, pos):
        item = self.tree.itemAt(pos)
        menu = QMenu(self)
        if item is None:
            menu.addAction("New Connection…", self.new_connection)
            menu.addSeparator()
            menu.addAction(icons.icon("import"), "Import Connections…", self.import_connections)
            menu.addAction(icons.icon("export"), "Export Connections…", self.export_connections)
        else:
            kind = item.data(0, ROLE)["kind"]
            if kind == CONNECTION:
                cid = item.data(0, ROLE)["id"]
                if cid in self.open_conns:
                    menu.addAction("Close Connection", lambda: self.disconnect(item))
                else:
                    menu.addAction("Open Connection", lambda: item.setExpanded(True))
                menu.addAction("New Query", lambda: self.new_query(item))
                menu.addAction(icons.icon("user"), "Users", lambda: self.open_users(item))
                menu.addAction("Execute SQL File…", lambda: self.run_sql_file(item))
                menu.addSeparator()
                menu.addAction("New Database…", lambda: self.create_database(item))
                menu.addAction("Refresh", lambda: self.refresh(item))
                menu.addSeparator()
                menu.addAction("Edit Connection…", lambda: self.edit_connection(item))
                menu.addAction(icons.icon("export"), "Export Connection…",
                               lambda: self.export_connections(self._cfg(item)[0].id))
                menu.addAction("Delete Connection", lambda: self.delete_connection(item))
            elif kind == GROUP:
                info = item.data(0, ROLE)
                if info["group"] == ROUTINE:
                    menu.addAction(icons.icon("new_function"), "New Function…",
                                   lambda: self.new_routine(self._cfg(item)[0], info["db"]))
                menu.addAction("New Query", lambda: self.new_query(item))
                menu.addAction("Refresh", lambda: self.refresh(item))
            elif kind == ROUTINE_ITEM:
                menu.addAction(icons.icon("design_function"), "Design Function", lambda: self.open_routine(item))
                menu.addAction(icons.icon("run"), "Execute…", lambda: self.open_routine(item, execute=True))
                menu.addAction(icons.icon("new_function"), "New Function…",
                               lambda: self.new_routine(self._cfg(item)[0], item.data(0, ROLE)["db"]))
                menu.addSeparator()
                menu.addAction(icons.icon("drop_function"), "Delete Function…", lambda: self.drop_routine(item))
            elif kind == DATABASE:
                cfg, database = self._cfg(item)[0], item.data(0, ROLE)["db"]
                if self._is_loaded(item):
                    menu.addAction(icons.icon("database_closed"), "Close Database", lambda: self.close_database(item))
                else:
                    menu.addAction(icons.icon("database"), "Open Database", lambda: item.setExpanded(True))
                menu.addSeparator()
                menu.addAction("New Query", lambda: self.new_query(item))
                menu.addSeparator()
                menu.addAction(icons.icon("import"), "Import Wizard…", lambda: self.import_wizard(cfg, database))
                menu.addAction(icons.icon("export"), "Export Wizard…", lambda: self.export_wizard(cfg, database))
                menu.addSeparator()
                menu.addAction("Execute SQL File…", lambda: self.run_sql_file(item))
                dump = menu.addMenu("Dump SQL File")
                dump.addAction("Structure and Data…",
                               lambda: transfer_wizards.dump_sql_file(self, cfg, database, with_data=True))
                dump.addAction("Structure Only…",
                               lambda: transfer_wizards.dump_sql_file(self, cfg, database, with_data=False))
                menu.addSeparator()
                menu.addAction("Refresh", lambda: self.refresh(item))
                menu.addSeparator()
                menu.addAction("Drop Database…", lambda: self.drop_database(item))
            elif kind == TABLE:
                menu.addAction("Open Table", lambda: self.open_table(item))
                menu.addAction("Structure", lambda: self.open_table(item, page=1))
                menu.addAction("Show DDL", lambda: self.open_table(item, page=2))
                menu.addAction("New Query", lambda: self.new_query(item))
                menu.addSeparator()
                info = item.data(0, ROLE)
                cfg = self._cfg(item)[0]
                if info["type"] != "VIEW":
                    menu.addAction(icons.icon("import"), "Import Wizard…",
                                   lambda: self.import_wizard(cfg, info["db"], info["table"]))
                menu.addAction(icons.icon("export"), "Export Wizard…",
                               lambda: self.export_wizard(cfg, info["db"], [info["table"]]))
                menu.addSeparator()
                if item.data(0, ROLE)["type"] != "VIEW":
                    menu.addAction("Truncate Table…", lambda: self.truncate_table(item))
                menu.addAction("Drop…", lambda: self.drop_table(item))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # tree ---------------------------------------------------------------
    def _populate_tree(self):
        self.tree.clear()
        for cfg in self.connections:
            self._add_connection_item(cfg)

    def _add_connection_item(self, cfg):
        item = QTreeWidgetItem([cfg.name])
        item.setIcon(0, self.icons["connection_closed"])
        item.setToolTip(0, f"{cfg.user}@{cfg.host}:{cfg.port}")
        item.setData(0, ROLE, {"kind": CONNECTION, "id": cfg.id})
        self._add_placeholder(item)
        self.tree.addTopLevelItem(item)
        return item

    @staticmethod
    def _add_placeholder(item):
        ph = QTreeWidgetItem(["Loading…"])
        ph.setData(0, ROLE, {"kind": PLACEHOLDER})
        item.addChild(ph)

    def _cfg(self, item):
        while item.parent():
            item = item.parent()
        cid = item.data(0, ROLE)["id"]
        return next(c for c in self.connections if c.id == cid), item

    def _tree_conn(self, item):
        cfg, _ = self._cfg(item)
        conn = self.open_conns.get(cfg.id)
        if conn is None:
            if not cfg.password and not cfg.save_password:
                pw, ok = QInputDialog.getText(self, "Password", f"Password for {cfg.user}@{cfg.host}:",
                                              echo=QLineEdit.EchoMode.Password)
                if not ok:
                    raise ConnectionAbortedError("Cancelled")
                cfg.password = pw
            conn = db.connect(cfg)
            self.open_conns[cfg.id] = conn
        return conn

    def _expand(self, item):
        if item.childCount() != 1 or item.child(0).data(0, ROLE)["kind"] != PLACEHOLDER:
            return
        info = item.data(0, ROLE)
        if info["kind"] == GROUP:
            return  # groups are filled when their database is expanded
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            conn = self._tree_conn(item)
            if info["kind"] == CONNECTION:
                databases = db.list_databases(conn)
            else:
                tables = db.list_tables(conn, info["db"])
                routines = db.list_routines(conn, info["db"])
        except ConnectionAbortedError:
            item.setExpanded(False)
            return
        except Exception as e:  # noqa: BLE001
            item.setExpanded(False)
            if info["kind"] == CONNECTION:
                self._forget_conn(item)
            QMessageBox.critical(self, "Error", str(e))
            return
        finally:
            self.unsetCursor()

        item.takeChildren()
        if info["kind"] == CONNECTION:
            for name in databases:
                child = QTreeWidgetItem([name])
                child.setData(0, ROLE, {"kind": DATABASE, "db": name})
                child.setIcon(0, self.icons["database_closed"])
                if name in SYSTEM_SCHEMAS:
                    child.setForeground(0, self.palette().placeholderText())
                self._add_placeholder(child)
                item.addChild(child)
            item.setIcon(0, self.icons[CONNECTION])
            return

        database = info["db"]
        members = {
            "BASE TABLE": [(n, {"kind": TABLE, "db": database, "table": n, "type": t})
                           for n, t in tables if t != "VIEW"],
            "VIEW": [(n, {"kind": TABLE, "db": database, "table": n, "type": t}) for n, t in tables if t == "VIEW"],
            ROUTINE: [(n, {"kind": ROUTINE_ITEM, "db": database, "name": n, "type": t}) for n, t in routines],
        }
        for label, group in GROUPS:
            node = QTreeWidgetItem([label])
            node.setData(0, ROLE, {"kind": GROUP, "db": database, "group": group})
            node.setIcon(0, self.icons[group])
            for name, data in members[group]:
                child = QTreeWidgetItem([name])
                child.setData(0, ROLE, data)
                child.setIcon(0, self.icons[data["type"]])
                node.addChild(child)
            item.addChild(node)
        item.setIcon(0, self.icons[DATABASE])
        self.statusBar().showMessage(
            f"{database}: {len(members['BASE TABLE'])} table(s), {len(members['VIEW'])} view(s), "
            f"{len(routines)} function(s)")

    def _tree_selection_changed(self, item, _previous):
        if item is None:
            return
        info = item.data(0, ROLE)
        kind = info["kind"]
        if kind not in (DATABASE, GROUP, TABLE, ROUTINE_ITEM):
            return
        cfg, _ = self._cfg(item)
        conn = self.open_conns.get(cfg.id)
        if conn is None:
            return
        self.objects.kind = {DATABASE: None, GROUP: info.get("group"), TABLE: info.get("type"),
                             ROUTINE_ITEM: ROUTINE}[kind]
        try:
            self.objects.show_database(cfg, info["db"], conn, info.get("table") or info.get("name"))
        except Exception as e:  # noqa: BLE001
            self._status(f"Error: {e}")
            return
        if kind in (DATABASE, GROUP):
            self.tabs.setCurrentWidget(self.objects)

    def show_objects(self, kind):
        """Main toolbar Table/View buttons: list that kind of object in the Objects tab."""
        self.objects.set_kind(kind)
        self.tabs.setCurrentWidget(self.objects)

    def _db_item(self, cfg, database):
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if top.data(0, ROLE)["id"] == cfg.id:
                for j in range(top.childCount()):
                    if top.child(j).data(0, ROLE).get("db") == database:
                        return top.child(j)
        return None

    def drop_objects(self, objects, cfg=None, database=None):
        """Drop tables, views, functions or procedures given as [(name, type), ...]."""
        cfg, database = cfg or self.objects.cfg, database or self.objects.database
        item = self._db_item(cfg, database)
        if item is None or not objects:
            return
        labels = {"VIEW": "View", "FUNCTION": "Function", "PROCEDURE": "Procedure"}
        if len(objects) == 1:
            name, otype = objects[0]
            if not self._confirm_name(labels.get(otype, "Table"), name):
                return
        else:
            names = ", ".join(n for n, _ in objects)
            if QMessageBox.question(self, "Drop objects", f"Drop {len(objects)} objects? This cannot be undone.\n\n"
                                    f"{names}") != QMessageBox.StandardButton.Yes:
                return
        for name, otype in objects:
            keyword = {"VIEW": "VIEW", "FUNCTION": "FUNCTION", "PROCEDURE": "PROCEDURE"}.get(otype, "TABLE")
            self._close_object_tabs(cfg, database, name)
            if not self._run_ddl(item, f"DROP {keyword} {db.quote_ident(database)}.{db.quote_ident(name)}", item):
                break

    def _close_object_tabs(self, cfg, database, name):
        for i in reversed(range(self.tabs.count())):
            w = self.tabs.widget(i)
            if not isinstance(w, (TableTab, RoutineTab)) or (w.cfg.id, w.database) != (cfg.id, database):
                continue
            if (w.table if isinstance(w, TableTab) else w.name) == name:
                self.close_tab(i, force=True)

    def _open_routines_from_objects(self, routines):
        for name, rtype in routines:
            self.open_routine_by_name(self.objects.cfg, self.objects.database, name, rtype)

    def open_routine(self, item, execute=False):
        cfg, _ = self._cfg(item)
        info = item.data(0, ROLE)
        tab = self.open_routine_by_name(cfg, info["db"], info["name"], info["type"])
        if execute:
            # The definition loads in the background; execute once it is ready.
            if tab.conn is not None:
                tab.execute()
            else:
                self._execute_when_ready(tab)

    def _execute_when_ready(self, tab):
        from PyQt6.QtCore import QTimer

        def check():
            if tab.conn is not None and not tab.busy:
                tab.execute()
            elif self.tabs.indexOf(tab) >= 0:
                QTimer.singleShot(100, check)
        QTimer.singleShot(100, check)

    def open_routine_by_name(self, cfg, database, name, rtype):
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, RoutineTab) and (w.cfg.id, w.database, w.name) == (cfg.id, database, name):
                self.tabs.setCurrentIndex(i)
                return w
        tab = RoutineTab(cfg, database, name, rtype, self._status, self._routine_saved)
        idx = self.tabs.addTab(tab, self.icons[rtype], f"{name} @ {database}")
        self.tabs.setTabToolTip(idx, f"{cfg.name} / {database} / {rtype.lower()} {name}")
        self.tabs.setCurrentIndex(idx)
        return tab

    def new_routine(self, cfg, database):
        if cfg is None or not database:
            QMessageBox.information(self, APP_NAME, "Select a database first.")
            return
        kind, ok = QInputDialog.getItem(self, "New Function", "Type:", ["Function", "Procedure"], 0, False)
        if not ok:
            return
        rtype = kind.upper()
        tab = RoutineTab(cfg, database, None, rtype, self._status, self._routine_saved)
        idx = self.tabs.addTab(tab, self.icons[rtype], f"New {kind} @ {database}")
        self.tabs.setCurrentIndex(idx)

    def _routine_saved(self, tab):
        idx = self.tabs.indexOf(tab)
        if idx >= 0:
            self.tabs.setTabText(idx, f"{tab.name} @ {tab.database}")
            self.tabs.setTabIcon(idx, self.icons[tab.rtype])
        item = self._db_item(tab.cfg, tab.database)
        if item is not None:
            self.refresh(item)
        if (self.objects.cfg, self.objects.database) == (tab.cfg, tab.database):
            self.objects.reload()

    def drop_routine(self, item):
        cfg, _ = self._cfg(item)
        info = item.data(0, ROLE)
        self.drop_objects([(info["name"], info["type"])], cfg, info["db"])

    def _objects_of(self, cfg, database):
        item = self._db_item(cfg, database)
        return db.list_tables(self._tree_conn(item), database) if item is not None else []

    def _after_import(self, cfg, database):
        item = self._db_item(cfg, database)
        if item is not None:
            self.refresh(item)
        if (self.objects.cfg, self.objects.database) == (cfg, database):
            self.objects.reload()

    def import_wizard(self, cfg, database, table=None):
        if cfg is None or not database:
            QMessageBox.information(self, APP_NAME, "Select a database first.")
            return
        try:
            tables = self._objects_of(cfg, database)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Import Wizard", str(e))
            return
        transfer_wizards.ImportWizard(cfg, database, tables, table,
                                      on_finished=lambda: self._after_import(cfg, database), parent=self).exec()

    def export_wizard(self, cfg, database, preselect=()):
        if cfg is None or not database:
            QMessageBox.information(self, APP_NAME, "Select a database first.")
            return
        try:
            tables = self._objects_of(cfg, database)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Export Wizard", str(e))
            return
        transfer_wizards.ExportWizard(cfg, database, tables, preselect, parent=self).exec()

    def run_sql_file(self, item):
        cfg, top = self._cfg(item)
        database = item.data(0, ROLE).get("db")

        def done():
            self.refresh(top if database is None else item)
            if self.objects.database:
                self.objects.reload()
        transfer_wizards.execute_sql_file(self, cfg, database, on_finished=done)

    def open_users(self, item=None):
        item = item or self.tree.currentItem() or self.tree.topLevelItem(0)
        if item is None:
            QMessageBox.information(self, APP_NAME, "Create a connection first.")
            return
        cfg, _ = self._cfg(item)
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, UsersTab) and w.cfg.id == cfg.id:
                self.tabs.setCurrentIndex(i)
                return
        try:
            self._tree_conn(item)  # asks for an unsaved password
            tab = UsersTab(cfg, self._status)
        except ConnectionAbortedError:
            return
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Users", str(e))
            return
        idx = self.tabs.addTab(tab, icons.icon("user"), f"Users @ {cfg.name}")
        self.tabs.setCurrentIndex(idx)

    def _open_from_objects(self, tables, page):
        for name, ttype in tables:
            self.open_table_by_name(self.objects.cfg, self.objects.database, name, ttype, page)

    def _query_from_objects(self):
        cfg = self.objects.cfg
        self.query_counter += 1
        tab = QueryTab(cfg, self.objects.database, self._status)
        self.tabs.setCurrentIndex(self.tabs.addTab(tab, icons.icon("query"),
                                                   f"Query {self.query_counter} — {self.objects.database}"))
        tab.editor.setFocus()

    def _double_clicked(self, item, _col):
        kind = item.data(0, ROLE)["kind"]
        if kind == TABLE:
            self.open_table(item)
        elif kind == ROUTINE_ITEM:
            self.open_routine(item)

    def refresh(self, item):
        while item.data(0, ROLE)["kind"] not in (CONNECTION, DATABASE):
            item = item.parent()
        was_open = item.isExpanded()
        # Remember which object groups were open so the refresh keeps them open.
        open_groups = {item.child(i).text(0) for i in range(item.childCount()) if item.child(i).isExpanded()}
        item.setExpanded(False)
        item.takeChildren()
        self._add_placeholder(item)
        if was_open or item.data(0, ROLE)["kind"] == DATABASE:
            item.setExpanded(True)
            for i in range(item.childCount()):
                if item.child(i).text(0) in open_groups:
                    item.child(i).setExpanded(True)

    def refresh_selected(self):
        widget = self.tabs.currentWidget()
        if isinstance(widget, TableTab):
            widget.load_data()
        elif self.tree.currentItem():
            self.refresh(self.tree.currentItem())

    def _forget_conn(self, item):
        cfg, _ = self._cfg(item)
        conn = self.open_conns.pop(cfg.id, None)
        if conn:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def _is_loaded(item):
        """True once a tree node's children have been fetched (it is not just a placeholder)."""
        return not (item.childCount() == 1 and item.child(0).data(0, ROLE)["kind"] == PLACEHOLDER)

    def close_database(self, item):
        """Close an opened database: its table/function tabs, the Objects list and its tree node."""
        cfg, _ = self._cfg(item)
        database = item.data(0, ROLE)["db"]
        tabs = [self.tabs.widget(i) for i in range(self.tabs.count())
                if isinstance(self.tabs.widget(i), (TableTab, RoutineTab))
                and (self.tabs.widget(i).cfg.id, self.tabs.widget(i).database) == (cfg.id, database)]
        for w in tabs:
            if not self.close_tab(self.tabs.indexOf(w)):
                return  # the user kept a tab with unsaved changes; leave the database open
        # Block tree signals: moving the selection would otherwise reload the Objects list.
        self.tree.blockSignals(True)
        try:
            self.tree.setCurrentItem(item)
            item.setExpanded(False)
            item.takeChildren()
            self._add_placeholder(item)
            item.setIcon(0, self.icons["database_closed"])
        finally:
            self.tree.blockSignals(False)
        if (self.objects.cfg, self.objects.database) == (cfg, database):
            self.objects.clear()
        self._status(f"Closed database {database}")

    def disconnect(self, item):
        cfg, _ = self._cfg(item)
        if self.objects.cfg is cfg:
            self.objects.clear()
        self._forget_conn(item)
        item.setExpanded(False)
        item.takeChildren()
        self._add_placeholder(item)
        item.setIcon(0, self.icons["connection_closed"])

    # connections ----------------------------------------------------------
    def new_connection(self):
        dlg = ConnectionDialog(parent=self)
        if dlg.exec():
            cfg = dlg.result_config()
            self.connections.append(cfg)
            save_connections(self.connections)
            self.tree.setCurrentItem(self._add_connection_item(cfg))

    def edit_connection(self, item):
        cfg, top = self._cfg(item)
        dlg = ConnectionDialog(cfg, parent=self)
        if dlg.exec():
            new = dlg.result_config()
            if self.objects.cfg is cfg:
                self.objects.clear()
            self.connections[self.connections.index(cfg)] = new
            save_connections(self.connections)
            self.disconnect(top)
            top.setText(0, new.name)
            top.setToolTip(0, f"{new.user}@{new.host}:{new.port}")

    def _top_item(self, cfg_id):
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if top.data(0, ROLE)["id"] == cfg_id:
                return top
        return None

    def import_connections(self, path=None):
        dlg = ImportConnectionsDialog(self.connections, self)
        if path:
            dlg.load(path)
        if not dlg.exec():
            return
        added = replaced = 0
        for cfg, old in dlg.result_plan():
            if old is not None:
                top = self._top_item(old.id)
                if top is not None:
                    self.disconnect(top)
                    top.setText(0, cfg.name)
                    top.setToolTip(0, f"{cfg.user}@{cfg.host}:{cfg.port}")
                self.connections[self.connections.index(old)] = cfg
                replaced += 1
            else:
                self.connections.append(cfg)
                self._add_connection_item(cfg)
                added += 1
        save_connections(self.connections)
        self._status(f"Imported connections: {added} added, {replaced} replaced")

    def export_connections(self, selected_id=None):
        if not self.connections:
            QMessageBox.information(self, APP_NAME, "There are no connections to export.")
            return
        dlg = ExportConnectionsDialog(self.connections, selected_id, self)
        if dlg.exec():
            self._status(f"Connections exported to {dlg.saved_path}")

    def delete_connection(self, item):
        cfg, top = self._cfg(item)
        if QMessageBox.question(self, "Delete connection",
                                f"Delete the saved connection “{cfg.name}”?") != QMessageBox.StandardButton.Yes:
            return
        if self.objects.cfg is cfg:
            self.objects.clear()
        self._forget_conn(top)
        self.connections.remove(cfg)
        save_connections(self.connections)
        self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(top))

    # tabs ---------------------------------------------------------------
    def _status(self, text):
        self.statusBar().showMessage(text, 10000)

    def new_query(self, item=None):
        item = item or self.tree.currentItem()
        if item is None:
            if not self.connections:
                QMessageBox.information(self, APP_NAME, "Create a connection first.")
                return
            item = self.tree.topLevelItem(0)
        cfg, _ = self._cfg(item)
        try:
            self._tree_conn(item)  # validates credentials and asks for an unsaved password
        except ConnectionAbortedError:
            return
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Error", str(e))
            return
        database = item.data(0, ROLE).get("db")
        self.query_counter += 1
        tab = QueryTab(cfg, database, self._status)
        title = f"Query {self.query_counter}" + (f" — {database}" if database else "")
        self.tabs.setCurrentIndex(self.tabs.addTab(tab, icons.icon("query"), title))
        tab.editor.setFocus()

    def open_table(self, item, page=0):
        cfg, _ = self._cfg(item)
        info = item.data(0, ROLE)
        self.open_table_by_name(cfg, info["db"], info["table"], info["type"], page)

    def open_table_by_name(self, cfg, database, table, ttype, page=0):
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, TableTab) and (w.cfg.id, w.database, w.table) == (cfg.id, database, table):
                w.tabs.setCurrentIndex(page)
                self.tabs.setCurrentIndex(i)
                return
        tab = TableTab(cfg, database, table, ttype == "VIEW", self._status, page)
        idx = self.tabs.addTab(tab, self.icons.get(ttype, self.icons["BASE TABLE"]), f"{table} @ {database}")
        self.tabs.setTabToolTip(idx, f"{cfg.name} / {database} / {table}")
        self.tabs.setCurrentIndex(idx)

    def _tab_menu(self, pos):
        index = self.tabs.tabBar().tabAt(pos)
        if index < 0:
            return
        closable = [self.tabs.widget(i) for i in range(self.tabs.count()) if self.tabs.widget(i) is not self.objects]
        target = self.tabs.widget(index)
        menu = QMenu(self)
        if target is not self.objects:
            menu.addAction("Close", lambda: self.close_widgets([target]))
        menu.addAction("Close Others", lambda: self.close_widgets([w for w in closable if w is not target]))
        menu.addAction("Close Tabs to the Right", lambda: self.close_widgets(
            [self.tabs.widget(i) for i in range(index + 1, self.tabs.count()) if self.tabs.widget(i) is not self.objects]))
        menu.addAction("Close All", lambda: self.close_widgets(closable))
        menu.exec(self.tabs.tabBar().mapToGlobal(pos))

    def close_widgets(self, widgets):
        for w in widgets:
            idx = self.tabs.indexOf(w)
            if idx >= 0 and not self.close_tab(idx):
                break  # user kept a tab with unsaved changes

    def eventFilter(self, obj, event):
        # Middle-click closes a tab.
        if obj is self.tabs.tabBar() and event.type() == event.Type.MouseButtonRelease \
                and event.button() == Qt.MouseButton.MiddleButton:
            self.close_tab(self.tabs.tabBar().tabAt(event.position().toPoint()))
            return True
        return super().eventFilter(obj, event)

    def close_tab(self, index, force=False):
        """Close the tab at index; returns False if the user chose to keep it."""
        w = self.tabs.widget(index)
        if index < 0 or w is self.objects:
            return True
        if not force and getattr(w, "has_unsaved_changes", lambda: False)():
            if QMessageBox.question(self, "Unsaved changes",
                                    "This tab has unsaved changes. Close anyway?") != QMessageBox.StandardButton.Yes:
                return False
        if hasattr(w, "close_connection"):
            w.close_connection()
        self.tabs.removeTab(index)
        w.deleteLater()
        return True

    # database operations ---------------------------------------------------
    def _run_ddl(self, item, sql, refresh_item):
        try:
            db.execute(self._tree_conn(item), sql)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Error", str(e))
            return False
        self._status(f"OK: {sql}")
        self.refresh(refresh_item)
        if self.objects.database:
            try:
                self.objects.reload()
            except Exception:  # noqa: BLE001 - e.g. the shown database was just dropped
                self.objects.clear()
        return True

    def create_database(self, item):
        name, ok = QInputDialog.getText(self, "New Database", "Database name:")
        if ok and name.strip():
            _, top = self._cfg(item)
            self._run_ddl(item, f"CREATE DATABASE {db.quote_ident(name.strip())} "
                                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci", top)

    def _confirm_name(self, what, name):
        typed, ok = QInputDialog.getText(
            self, f"Drop {what}", f"This cannot be undone.\nType “{name}” to confirm dropping this {what.lower()}:")
        return ok and typed == name

    def drop_database(self, item):
        name = item.data(0, ROLE)["db"]
        if self._confirm_name("Database", name):
            if self.objects.database == name and self.objects.cfg is self._cfg(item)[0]:
                self.objects.clear()
            self._run_ddl(item, f"DROP DATABASE {db.quote_ident(name)}", item.parent())

    def drop_table(self, item):
        info = item.data(0, ROLE)
        kind = "View" if info["type"] == "VIEW" else "Table"
        if self._confirm_name(kind, info["table"]):
            self._run_ddl(item, f"DROP {kind.upper()} {db.quote_ident(info['db'])}.{db.quote_ident(info['table'])}",
                          item.parent())

    def truncate_table(self, item):
        info = item.data(0, ROLE)
        if QMessageBox.question(self, "Truncate table",
                                f"Delete ALL rows from “{info['table']}”? This cannot be undone.") \
                == QMessageBox.StandardButton.Yes:
            self._run_ddl(item, f"TRUNCATE TABLE {db.quote_ident(info['db'])}.{db.quote_ident(info['table'])}",
                          item)

    def closeEvent(self, event):
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if getattr(w, "has_unsaved_changes", lambda: False)():
                if QMessageBox.question(self, "Unsaved changes",
                                        "Some tabs have unsaved changes. Quit anyway?") \
                        != QMessageBox.StandardButton.Yes:
                    event.ignore()
                    return
                break
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if hasattr(w, "close_connection"):
                w.close_connection()
        for conn in self.open_conns.values():
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
        QSettings("dbprofile", "dbprofile").setValue("geometry", self.saveGeometry())
        event.accept()

