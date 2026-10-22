"""User management: list MySQL accounts, create/edit/delete them, manage privileges."""
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSizePolicy, QTableWidget, QTableWidgetItem,
    QTabWidget, QToolBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import db, icons
from .config import ConnectionConfig
from .sql_editor import SqlHighlighter

q = db.quote_ident

# Static privileges that can be granted ON *.* (server level).
SERVER_PRIVILEGES = [
    "SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "INDEX", "ALTER", "REFERENCES",
    "CREATE VIEW", "SHOW VIEW", "CREATE ROUTINE", "ALTER ROUTINE", "EXECUTE", "TRIGGER", "EVENT",
    "CREATE TEMPORARY TABLES", "LOCK TABLES", "SHOW DATABASES", "PROCESS", "RELOAD", "SHUTDOWN", "FILE",
    "SUPER", "CREATE USER", "REPLICATION SLAVE", "REPLICATION CLIENT", "CREATE TABLESPACE",
]
# Privileges that can be granted ON `db`.* (database level).
DATABASE_PRIVILEGES = [
    "SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "INDEX", "ALTER", "REFERENCES",
    "CREATE VIEW", "SHOW VIEW", "CREATE ROUTINE", "ALTER ROUTINE", "EXECUTE", "TRIGGER", "EVENT",
    "CREATE TEMPORARY TABLES", "LOCK TABLES",
]


def _title(priv):
    return priv.title()


class UserDialog(QDialog):
    """Create or edit one account. Changes are applied as a list of SQL statements."""

    def __init__(self, conn, databases, account=None, lock_supported=True, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.account = account  # (user, host) when editing
        self.lock_supported = lock_supported
        self.setWindowTitle(f"Edit User {account[0]}@{account[1]}" if account else "New User")
        self.resize(760, 540)

        if account:
            self.orig_global, self.orig_grant_option, self.orig_db = db.user_privileges(conn, *account)
            self.orig_locked = self._is_locked(*account) if lock_supported else False
        else:
            self.orig_global, self.orig_grant_option, self.orig_db, self.orig_locked = set(), False, {}, False
        self.all_databases = databases

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

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addWidget(buttons)

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
        hint = QLabel("Privileges on all databases (ON *.*).")
        hint.setObjectName("muted")
        outer.addWidget(hint)
        grid = QGridLayout()
        self.server_boxes = {}
        for i, priv in enumerate(SERVER_PRIVILEGES):
            box = QCheckBox(_title(priv))
            box.setChecked(priv in self.orig_global)
            self.server_boxes[priv] = box
            grid.addWidget(box, i // 3, i % 3)
        outer.addLayout(grid)
        self.grant_option = QCheckBox("Grant Option (may grant its privileges to others)")
        self.grant_option.setChecked(self.orig_grant_option)
        outer.addWidget(self.grant_option)
        extra = sorted(self.orig_global - set(SERVER_PRIVILEGES))
        if extra:
            note = QLabel("Also granted (not changed here): " + ", ".join(extra))
            note.setWordWrap(True)
            note.setObjectName("muted")
            outer.addWidget(note)
        row = QHBoxLayout()
        for text, value in (("Select All", True), ("Clear All", False)):
            b = QPushButton(text)
            b.setAutoDefault(False)
            b.clicked.connect(lambda _, v=value: [x.setChecked(v) for x in self.server_boxes.values()])
            row.addWidget(b)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)
        return page

    def _database_page(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        bar = QToolBar()
        bar.setIconSize(QSize(16, 16))
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        bar.addAction(icons.icon("add"), "Add Privilege", self._add_database)
        bar.addAction(icons.icon("remove"), "Delete Privilege", self._remove_database)
        outer.addWidget(bar)
        self.db_table = QTableWidget(0, len(DATABASE_PRIVILEGES) + 1)
        self.db_table.setHorizontalHeaderLabels(["Database"] + [_title(p) for p in DATABASE_PRIVILEGES])
        self.db_table.verticalHeader().hide()
        header = self.db_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        fm = header.fontMetrics()
        for c in range(self.db_table.columnCount()):
            # stylesheet padding is not part of the size hint, so size the columns from the label text
            label = self.db_table.horizontalHeaderItem(c).text()
            self.db_table.setColumnWidth(c, max(fm.horizontalAdvance(label) + 28, 140 if c == 0 else 0))
        self.db_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        outer.addWidget(self.db_table)
        for name in sorted(self.orig_db):
            self._add_db_row(name, self.orig_db[name])
        return page

    def _add_db_row(self, name, privileges=()):
        r = self.db_table.rowCount()
        self.db_table.insertRow(r)
        item = QTableWidgetItem(icons.icon("database"), name)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.db_table.setItem(r, 0, item)
        for c, priv in enumerate(DATABASE_PRIVILEGES, start=1):
            holder = QWidget()
            box = QCheckBox()
            box.setChecked(priv in privileges)
            row = QHBoxLayout(holder)
            row.setContentsMargins(0, 0, 0, 0)
            row.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(box)
            self.db_table.setCellWidget(r, c, holder)

    def _db_rows(self):
        rows = {}
        for r in range(self.db_table.rowCount()):
            name = self.db_table.item(r, 0).text()
            rows[name] = {p for c, p in enumerate(DATABASE_PRIVILEGES, start=1) if self._box(r, c).isChecked()}
        return rows

    def _box(self, row, col) -> QCheckBox:
        return self.db_table.cellWidget(row, col).findChild(QCheckBox)

    def _add_database(self):
        present = set(self._db_rows())
        choices = [d for d in self.all_databases if d not in present]
        name, ok = QInputDialog.getItem(self, "Add Privilege", "Database (wildcards like app\\_% allowed):",
                                        choices, 0, True)
        name = name.strip()
        if ok and name and name not in present:
            self._add_db_row(name, {"SELECT"})

    def _remove_database(self):
        for r in sorted({i.row() for i in self.db_table.selectedIndexes()}, reverse=True):
            self.db_table.removeRow(r)

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

        wanted = {p for p, box in self.server_boxes.items() if box.isChecked()}
        current = self.orig_global & set(SERVER_PRIVILEGES)
        if wanted - current:
            sql.append(f"GRANT {', '.join(sorted(wanted - current))} ON *.* TO {acct}")
        if current - wanted:
            sql.append(f"REVOKE {', '.join(sorted(current - wanted))} ON *.* FROM {acct}")
        if self.grant_option.isChecked() and not self.orig_grant_option:
            sql.append(f"GRANT USAGE ON *.* TO {acct} WITH GRANT OPTION")
        elif not self.grant_option.isChecked() and self.orig_grant_option:
            sql.append(f"REVOKE GRANT OPTION ON *.* FROM {acct}")

        rows = self._db_rows()
        for name in sorted(set(rows) | set(self.orig_db)):
            want = rows.get(name, set())
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
