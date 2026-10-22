"""User management: list MySQL accounts, create/edit/delete them, manage privileges."""
from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSplitter,
    QStackedWidget, QTabWidget, QToolBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import db, icons, theme
from .config import ConnectionConfig
from .sql_editor import SqlHighlighter

q = db.quote_ident

# Privileges grouped the way they are usually thought about. Database-level privileges are the
# first four groups; the server level (ON *.*) adds administration.
GROUPS = [
    ("Data", ["SELECT", "INSERT", "UPDATE", "DELETE"]),
    ("Structure", ["CREATE", "DROP", "ALTER", "INDEX", "REFERENCES", "CREATE VIEW", "SHOW VIEW", "TRIGGER"]),
    ("Routines & Events", ["CREATE ROUTINE", "ALTER ROUTINE", "EXECUTE", "EVENT"]),
    ("Other", ["CREATE TEMPORARY TABLES", "LOCK TABLES"]),
]
ADMIN_GROUP = ("Administration", ["CREATE USER", "PROCESS", "RELOAD", "SHUTDOWN", "SUPER", "FILE", "SHOW DATABASES",
                                  "REPLICATION SLAVE", "REPLICATION CLIENT", "CREATE TABLESPACE"])
SERVER_GROUPS = GROUPS + [ADMIN_GROUP]

DATABASE_PRIVILEGES = [p for _, privs in GROUPS for p in privs]
SERVER_PRIVILEGES = [p for _, privs in SERVER_GROUPS for p in privs]

DESCRIPTIONS = {
    "SELECT": "Read rows", "INSERT": "Add rows", "UPDATE": "Change rows", "DELETE": "Remove rows",
    "CREATE": "Create databases and tables", "DROP": "Drop databases, tables and views",
    "ALTER": "Change table structure", "INDEX": "Create and drop indexes", "REFERENCES": "Create foreign keys",
    "CREATE VIEW": "Create views", "SHOW VIEW": "See view definitions", "TRIGGER": "Create and drop triggers",
    "CREATE ROUTINE": "Create functions and procedures", "ALTER ROUTINE": "Change and drop functions and procedures",
    "EXECUTE": "Run functions and procedures", "EVENT": "Create and change scheduled events",
    "CREATE TEMPORARY TABLES": "Create temporary tables", "LOCK TABLES": "Use LOCK TABLES",
    "CREATE USER": "Create, rename and drop users", "PROCESS": "See every running query (SHOW PROCESSLIST)",
    "RELOAD": "Run FLUSH operations", "SHUTDOWN": "Shut down the server",
    "SUPER": "Administrative operations such as KILL and SET GLOBAL",
    "FILE": "Read and write files on the server host", "SHOW DATABASES": "See all database names",
    "REPLICATION SLAVE": "Read the binary log as a replica", "REPLICATION CLIENT": "Ask for replication status",
    "CREATE TABLESPACE": "Create and drop tablespaces",
}

READ_ONLY = {"SELECT", "SHOW VIEW"}
READ_WRITE = READ_ONLY | {"INSERT", "UPDATE", "DELETE", "EXECUTE", "CREATE TEMPORARY TABLES", "LOCK TABLES"}
PRESETS = [("Read Only", READ_ONLY), ("Read/Write", READ_WRITE), ("All", None), ("None", set())]


def _title(priv):
    return priv.title()


def summarize(privileges, available=DATABASE_PRIVILEGES):
    privs = set(privileges) & set(available)
    if not privs:
        return "No access"
    if privs == set(available):
        return "All privileges"
    if privs == READ_ONLY:
        return "Read only"
    if privs == READ_WRITE:
        return "Read/Write"
    return f"{len(privs)} privilege{'s' if len(privs) != 1 else ''}"


def _set_changed(widget, changed):
    """Mark a checkbox as different from what is stored on the server (styled by the theme)."""
    if widget.property("changed") != changed:
        widget.setProperty("changed", changed)
        widget.style().unpolish(widget)
        widget.style().polish(widget)


class PrivilegePanel(QWidget):
    """Privilege checkboxes in titled groups, each with a tri-state "select group" box."""

    changed = pyqtSignal()

    def __init__(self, groups, parent=None):
        super().__init__(parent)
        self.boxes: dict[str, QCheckBox] = {}
        self.group_boxes = []
        self.original: set[str] = set()
        self._updating = False
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        for i, (title, privs) in enumerate(groups):
            frame = QFrame()
            frame.setObjectName("privGroup")
            box = QVBoxLayout(frame)
            box.setContentsMargins(12, 8, 12, 10)
            box.setSpacing(5)
            head = QCheckBox(title.replace("&", "&&"))  # "&" would otherwise mark a shortcut key
            head.setObjectName("groupHead")
            head.setTristate(True)
            head.clicked.connect(lambda _, h=head, p=privs: self._toggle_group(h, p))
            box.addWidget(head)
            line = QFrame()
            line.setObjectName("hline")
            box.addWidget(line)
            for priv in privs:
                cb = QCheckBox(_title(priv))
                cb.setToolTip(f"{priv}\n{DESCRIPTIONS.get(priv, '')}")
                cb.toggled.connect(self._on_toggle)
                self.boxes[priv] = cb
                box.addWidget(cb)
            box.addStretch(1)
            self.group_boxes.append((head, privs))
            grid.addWidget(frame, i // 2, i % 2)
        grid.setRowStretch(grid.rowCount(), 1)

    def _toggle_group(self, head, privs):
        on = head.checkState() != Qt.CheckState.Unchecked
        if head.checkState() == Qt.CheckState.PartiallyChecked:
            on = True  # clicking a partly checked group selects all of it
        self._updating = True
        for p in privs:
            self.boxes[p].setChecked(on)
        self._updating = False
        self._refresh()

    def _on_toggle(self, _):
        if not self._updating:
            self._refresh()

    def _refresh(self):
        for head, privs in self.group_boxes:
            n = sum(self.boxes[p].isChecked() for p in privs)
            head.setCheckState(Qt.CheckState.Checked if n == len(privs) else
                               Qt.CheckState.Unchecked if n == 0 else Qt.CheckState.PartiallyChecked)
        for priv, cb in self.boxes.items():
            _set_changed(cb, cb.isChecked() != (priv in self.original))
        self.changed.emit()

    def set_privileges(self, privileges, original=None):
        self._updating = True
        for priv, cb in self.boxes.items():
            cb.setChecked(priv in privileges)
        self._updating = False
        if original is not None:
            self.original = set(original)
        self._refresh()

    def privileges(self) -> set[str]:
        return {p for p, cb in self.boxes.items() if cb.isChecked()}

    def apply_preset(self, preset):
        self.set_privileges(set(self.boxes) if preset is None else preset & set(self.boxes))

    def filter(self, text):
        text = text.strip().lower()
        for priv, cb in self.boxes.items():
            cb.setVisible(not text or text in priv.lower() or text in DESCRIPTIONS.get(priv, "").lower())


def _preset_bar(panel, presets, extra=()):
    row = QHBoxLayout()
    row.setSpacing(6)
    label = QLabel("Quick set:")
    label.setObjectName("muted")
    row.addWidget(label)
    for text, preset in list(presets) + list(extra):
        b = QPushButton(text)
        b.setAutoDefault(False)
        b.setObjectName("chip")
        b.clicked.connect(lambda _, p=preset: panel.apply_preset(p) if not callable(p) else p())
        row.addWidget(b)
    row.addStretch(1)
    return row


class AddDatabasesDialog(QDialog):
    """Pick one or more databases (or type a pattern such as app\\_%) to grant privileges on."""

    def __init__(self, databases, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Privilege")
        self.resize(360, 420)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.list = QListWidget()
        for name in databases:
            it = QListWidgetItem(icons.icon("database"), name)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Unchecked)
            self.list.addItem(it)
        self.list.itemClicked.connect(lambda it: it.setCheckState(
            Qt.CheckState.Unchecked if it.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked))
        self.pattern = QLineEdit()
        self.pattern.setPlaceholderText("or a pattern, e.g. app\\_%")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Add")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.search)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.pattern)
        layout.addWidget(buttons)

    def _filter(self, text):
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(bool(text) and text.lower() not in it.text().lower())

    def selected(self):
        names = [self.list.item(i).text() for i in range(self.list.count())
                 if self.list.item(i).checkState() == Qt.CheckState.Checked]
        if self.pattern.text().strip():
            names.append(self.pattern.text().strip())
        return names


class UserDialog(QDialog):
    """Create or edit one account. Changes are applied as a list of SQL statements."""

    def __init__(self, conn, databases, account=None, lock_supported=True, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.account = account  # (user, host) when editing
        self.lock_supported = lock_supported
        self.setWindowTitle(f"Edit User — {account[0]}@{account[1]}" if account else "New User")
        self.resize(860, 620)

        if account:
            self.orig_global, self.orig_grant_option, self.orig_db = db.user_privileges(conn, *account)
            self.orig_locked = self._is_locked(*account) if lock_supported else False
        else:
            self.orig_global, self.orig_grant_option, self.orig_db, self.orig_locked = set(), False, {}, False
        self.all_databases = databases
        # Database privileges being edited: {database: set of privileges}
        self.db_privs = {name: set(privs) & set(DATABASE_PRIVILEGES) for name, privs in self.orig_db.items()}
        self.current_db = None
        self.pending = QLabel()  # created first: the pages report changes while they are built
        self.pending.setObjectName("muted")

        self.tabs = QTabWidget()
        self.tabs.setObjectName("subTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._general_page(lock_supported), "General")
        self.tabs.addTab(self._server_page(), "Server Privileges")
        self.tabs.addTab(self._database_page(), "Privileges")
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview_hl = SqlHighlighter(self.preview.document())
        self.tabs.addTab(self.preview, "SQL Preview")
        self.tabs.currentChanged.connect(self._tab_changed)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(self.pending, 1)
        bottom.addWidget(buttons)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addLayout(bottom)
        self._update_summary()

    def _is_locked(self, user, host):
        rows = db.execute(self.conn, "SELECT account_locked FROM mysql.user WHERE User = %s AND Host = %s",
                          (user, host)).rows
        return bool(rows) and rows[0][0] == "Y"

    # pages ----------------------------------------------------------------
    def _general_page(self, lock_supported):
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(16, 16, 16, 16)
        self.user = QLineEdit(self.account[0] if self.account else "")
        self.host = QLineEdit(self.account[1] if self.account else "%")
        self.host.setToolTip("% = any host, localhost = local connections only")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
        if self.account:
            self.password.setPlaceholderText("leave empty to keep the current password")
        self.locked = QCheckBox("Account locked")
        self.locked.setChecked(self.orig_locked)
        self.locked.setVisible(lock_supported)
        for w in (self.user, self.host, self.password, self.confirm):
            w.textChanged.connect(self._update_summary)
        self.locked.toggled.connect(self._update_summary)
        form.addRow("User name:", self.user)
        form.addRow("Host:", self.host)
        form.addRow("Password:", self.password)
        form.addRow("Confirm password:", self.confirm)
        form.addRow("", self.locked)
        return page

    def _server_page(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(16, 12, 16, 12)
        top = QHBoxLayout()
        hint = QLabel("Privileges on <b>all databases</b> (ON *.*). Changed items are shown in blue.")
        hint.setObjectName("muted")
        top.addWidget(hint, 1)
        search = QLineEdit()
        search.setPlaceholderText("Search privileges")
        search.setClearButtonEnabled(True)
        search.setFixedWidth(200)
        top.addWidget(search)
        outer.addLayout(top)

        self.server_panel = PrivilegePanel(SERVER_GROUPS)
        self.server_panel.set_privileges(self.orig_global, original=self.orig_global)
        self.server_panel.changed.connect(self._update_summary)
        search.textChanged.connect(self.server_panel.filter)
        outer.addLayout(_preset_bar(self.server_panel, PRESETS, [
            ("Reset", lambda: self.server_panel.set_privileges(self.orig_global))]))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        holder = QWidget()
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(0, 4, 0, 0)
        holder_layout.addWidget(self.server_panel)
        self.grant_option = QCheckBox("Grant Option — may give its own privileges to other users")
        self.grant_option.setChecked(self.orig_grant_option)
        self.grant_option.toggled.connect(lambda on: (_set_changed(self.grant_option, on != self.orig_grant_option),
                                                      self._update_summary()))
        holder_layout.addWidget(self.grant_option)
        extra = sorted(self.orig_global - set(SERVER_PRIVILEGES))
        if extra:
            note = QLabel("Also granted (dynamic privileges, not changed here): " + ", ".join(extra))
            note.setWordWrap(True)
            note.setObjectName("muted")
            holder_layout.addWidget(note)
        holder_layout.addStretch(1)
        scroll.setWidget(holder)
        outer.addWidget(scroll, 1)
        return page

    def _database_page(self):
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter()
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)

        # left: databases with access
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        bar = QToolBar()
        bar.setIconSize(QSize(16, 16))
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        bar.addAction(icons.icon("add"), "Add Privilege", self._add_databases)
        self.a_remove_db = bar.addAction(icons.icon("remove"), "Remove", self._remove_databases)
        left_layout.addWidget(bar)
        self.db_list = QTreeWidget()
        self.db_list.setHeaderLabels(["Database", "Access"])
        self.db_list.setRootIsDecorated(False)
        self.db_list.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.db_list.currentItemChanged.connect(self._db_selected)
        left_layout.addWidget(self.db_list)

        # right: privileges of the selected database
        self.db_stack = QStackedWidget()
        empty = QLabel("Add a database on the left to grant privileges on it.")
        empty.setObjectName("muted")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(16, 12, 16, 12)
        self.db_title = QLabel()
        detail_layout.addWidget(self.db_title)
        self.db_panel = PrivilegePanel(GROUPS)
        self.db_panel.changed.connect(self._db_privs_changed)
        detail_layout.addLayout(_preset_bar(self.db_panel, PRESETS))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.db_panel)
        detail_layout.addWidget(scroll, 1)
        self.db_stack.addWidget(empty)
        self.db_stack.addWidget(detail)

        splitter.addWidget(left)
        splitter.addWidget(self.db_stack)
        splitter.setSizes([260, 560])
        outer.addWidget(splitter)
        self._fill_db_list()
        return page

    # database privileges --------------------------------------------------------
    def _fill_db_list(self, select=None):
        self.db_list.blockSignals(True)
        self.db_list.clear()
        for name in sorted(set(self.db_privs) | set(self.orig_db)):
            it = QTreeWidgetItem([name, ""])
            it.setIcon(0, icons.icon("database"))
            it.setData(0, Qt.ItemDataRole.UserRole, name)
            self.db_list.addTopLevelItem(it)
            self._update_db_item(it)
        self.db_list.resizeColumnToContents(0)
        self.db_list.setColumnWidth(0, max(self.db_list.columnWidth(0) + 12, 130))
        self.db_list.blockSignals(False)
        target = select or (self.db_list.topLevelItem(0).text(0) if self.db_list.topLevelItemCount() else None)
        for i in range(self.db_list.topLevelItemCount()):
            if self.db_list.topLevelItem(i).text(0) == target:
                self.db_list.setCurrentItem(self.db_list.topLevelItem(i))
                break
        else:
            self._db_selected(None, None)

    def _update_db_item(self, it):
        name = it.data(0, Qt.ItemDataRole.UserRole)
        privs = self.db_privs.get(name, set())
        removed = name not in self.db_privs
        it.setText(1, "Removed" if removed else summarize(privs))
        changed = removed or privs != (self.orig_db.get(name, set()) & set(DATABASE_PRIVILEGES))
        font = it.font(0)
        font.setItalic(removed)
        for col in (0, 1):
            it.setFont(col, font)
            it.setForeground(col, QColor(theme.MUTED if removed else theme.ACCENT if changed else theme.TEXT))

    def _db_selected(self, current, _previous):
        name = current.data(0, Qt.ItemDataRole.UserRole) if current else None
        self.current_db = name
        if name is None:
            self.db_stack.setCurrentIndex(0)
            return
        self.db_stack.setCurrentIndex(1)
        self.db_title.setText(f"Privileges on <b>{name}</b>.*")
        if name not in self.db_privs:  # selecting a removed database restores it for editing
            self.db_privs[name] = set()
        self.db_panel.set_privileges(self.db_privs[name], original=self.orig_db.get(name, set()))

    def _db_privs_changed(self):
        if self.current_db is None:
            return
        self.db_privs[self.current_db] = self.db_panel.privileges()
        it = self.db_list.currentItem()
        if it is not None:
            self._update_db_item(it)
        self._update_summary()

    def _add_databases(self):
        choices = [d for d in self.all_databases if d not in self.db_privs]
        dlg = AddDatabasesDialog(choices, self)
        if not dlg.exec():
            return
        added = [n for n in dlg.selected() if n]
        for name in added:
            self.db_privs.setdefault(name, set(READ_ONLY))
        if added:
            self._fill_db_list(select=added[0])
            self._update_summary()

    def _remove_databases(self):
        names = [it.data(0, Qt.ItemDataRole.UserRole) for it in self.db_list.selectedItems()]
        for name in names:
            self.db_privs.pop(name, None)
        self.current_db = None
        self._fill_db_list()  # selects the first remaining database, or shows the empty hint
        self._update_summary()

    # summary / preview --------------------------------------------------------
    def _update_summary(self, *_):
        try:
            n = len(self.statements())
        except ValueError as e:
            self.pending.setText(str(e))
            return
        self.pending.setText("No changes" if n == 0 else f"{n} change{'s' if n != 1 else ''} to apply "
                             "(see SQL Preview)")
        server = len(self.server_panel.privileges()) + self.grant_option.isChecked()
        self.tabs.setTabText(1, f"Server Privileges ({server})" if server else "Server Privileges")
        dbs = sum(1 for p in self.db_privs.values() if p)
        self.tabs.setTabText(2, f"Privileges ({dbs})" if dbs else "Privileges")

    def _tab_changed(self, index):
        if self.tabs.widget(index) is self.preview:
            try:
                sql = self.statements()
                self.preview.setPlainText(";\n".join(sql) + ";" if sql else "-- no changes")
            except ValueError as e:
                self.preview.setPlainText(f"-- {e}")

    # SQL ----------------------------------------------------------------
    def statements(self) -> list[str]:
        lit = self.conn.literal
        user, host = self.user.text().strip(), self.host.text().strip() or "%"
        if not user:
            raise ValueError("User name is required.")
        if self.password.text() != self.confirm.text():
            raise ValueError("Passwords do not match.")
        acct = f"{lit(user)}@{lit(host)}"
        sql = []
        if self.account is None:
            stmt = f"CREATE USER {acct}"
            if self.password.text():
                stmt += f" IDENTIFIED BY {lit(self.password.text())}"
            sql.append(stmt)
        else:
            if (user, host) != tuple(self.account):
                sql.append(f"RENAME USER {lit(self.account[0])}@{lit(self.account[1])} TO {acct}")
            if self.password.text():
                sql.append(f"ALTER USER {acct} IDENTIFIED BY {lit(self.password.text())}")
        if self.lock_supported and self.locked.isChecked() != self.orig_locked:
            sql.append(f"ALTER USER {acct} ACCOUNT {'LOCK' if self.locked.isChecked() else 'UNLOCK'}")

        wanted = self.server_panel.privileges()
        current = self.orig_global & set(SERVER_PRIVILEGES)
        if wanted - current:
            sql.append(f"GRANT {', '.join(sorted(wanted - current))} ON *.* TO {acct}")
        if current - wanted:
            sql.append(f"REVOKE {', '.join(sorted(current - wanted))} ON *.* FROM {acct}")
        if self.grant_option.isChecked() and not self.orig_grant_option:
            sql.append(f"GRANT USAGE ON *.* TO {acct} WITH GRANT OPTION")
        elif not self.grant_option.isChecked() and self.orig_grant_option:
            sql.append(f"REVOKE GRANT OPTION ON *.* FROM {acct}")

        for name in sorted(set(self.db_privs) | set(self.orig_db)):
            want = self.db_privs.get(name, set())
            have = self.orig_db.get(name, set()) & set(DATABASE_PRIVILEGES)
            target = f"{q(name)}.*"
            if want - have:
                sql.append(f"GRANT {', '.join(sorted(want - have))} ON {target} TO {acct}")
            if have - want:
                sql.append(f"REVOKE {', '.join(sorted(have - want))} ON {target} FROM {acct}")
        return sql

    def save(self):
        try:
            statements = self.statements()
        except ValueError as e:
            QMessageBox.warning(self, "Cannot save", str(e))
            return
        done = []
        for stmt in statements:
            try:
                db.execute(self.conn, stmt)
            except Exception as e:  # noqa: BLE001
                applied = "\n".join(done) or "(none)"
                QMessageBox.critical(self, "Save failed", f"{e}\n\nFailed statement:\n{stmt}\n\n"
                                     f"Already applied:\n{applied}")
                if done:
                    self.accept()  # some changes went through; let the list refresh
                return
            done.append(stmt)
        self.accept()


class UsersTab(QWidget):
    def __init__(self, cfg: ConnectionConfig, status_callback, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.status = status_callback
        self.conn = db.connect(cfg)
        self.lock_supported = False

        toolbar = QToolBar()
        toolbar.setIconSize(QSize(16, 16))
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.addAction(icons.icon("new_user"), "New User", self.new_user)
        self.a_edit = toolbar.addAction(icons.icon("edit_user"), "Edit User", self.edit_user)
        self.a_drop = toolbar.addAction(icons.icon("drop_user"), "Delete User", self.drop_users)
        toolbar.addSeparator()
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
        self.list.setSortingEnabled(True)
        self.list.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.list.itemDoubleClicked.connect(self.edit_user)
        self.list.itemSelectionChanged.connect(self._update_actions)
        for key in ("Return", "Enter"):
            QShortcut(QKeySequence(key), self.list, self.edit_user, context=Qt.ShortcutContext.WidgetShortcut)
        QShortcut(QKeySequence("Delete"), self.list, self.drop_users, context=Qt.ShortcutContext.WidgetShortcut)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar)
        layout.addWidget(self.list)
        self.reload()

    def reload(self):
        users = db.list_users(self.conn)
        self.lock_supported = bool(users) and "account_locked" in users[0]
        columns = ["User", "Host", "Authentication", "Locked", "Password Expired"]
        self.list.setColumnCount(len(columns))
        self.list.setHeaderLabels(columns)
        self.list.setSortingEnabled(False)
        self.list.clear()
        for u in users:
            name, host = u.get("User", ""), u.get("Host", "")
            it = QTreeWidgetItem([
                name or "(anonymous)", host, u.get("plugin") or "",
                "Yes" if u.get("account_locked") == "Y" else "",
                "Yes" if u.get("password_expired") == "Y" else "",
            ])
            it.setIcon(0, icons.icon("user"))
            it.setData(0, Qt.ItemDataRole.UserRole, (name, host))
            self.list.addTopLevelItem(it)
        self.list.setSortingEnabled(True)
        self.list.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        for c in range(len(columns)):
            self.list.resizeColumnToContents(c)
        self.list.setColumnWidth(0, max(self.list.columnWidth(0), 200))
        self._apply_filter()
        self._update_actions()

    def _apply_filter(self, *_):
        text = self.filter.text().strip().lower()
        shown = 0
        for i in range(self.list.topLevelItemCount()):
            it = self.list.topLevelItem(i)
            hide = bool(text) and text not in f"{it.text(0)}@{it.text(1)}".lower()
            it.setHidden(hide)
            shown += not hide
        self.title.setText(f"{self.cfg.name} — {shown} user{'' if shown == 1 else 's'}")

    def _selected(self):
        return [it.data(0, Qt.ItemDataRole.UserRole) for it in self.list.selectedItems() if not it.isHidden()]

    def _update_actions(self):
        n = len(self._selected())
        self.a_edit.setEnabled(n == 1)
        self.a_drop.setEnabled(n > 0)

    def _open_dialog(self, account=None):
        try:
            databases = db.list_databases(self.conn)
            dlg = UserDialog(self.conn, databases, account, self.lock_supported, self)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Error", str(e))
            return
        if dlg.exec():
            self.status("User saved")
            self.reload()

    def new_user(self):
        self._open_dialog()

    def edit_user(self, *_):
        selected = self._selected()
        if len(selected) == 1:
            self._open_dialog(selected[0])

    def drop_users(self):
        selected = self._selected()
        if not selected:
            return
        names = ", ".join(f"{u}@{h}" for u, h in selected)
        if QMessageBox.question(self, "Delete User", f"Delete {len(selected)} user(s)? This cannot be undone.\n\n"
                                f"{names}") != QMessageBox.StandardButton.Yes:
            return
        lit = self.conn.literal
        for user, host in selected:
            try:
                db.execute(self.conn, f"DROP USER {lit(user)}@{lit(host)}")
            except Exception as e:  # noqa: BLE001
                QMessageBox.critical(self, "Error", f"{user}@{host}: {e}")
                break
        self.status(f"Deleted {names}")
        self.reload()

    def close_connection(self):
        try:
            self.conn.close()
        except Exception:  # noqa: BLE001
            pass
