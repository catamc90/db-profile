"""Table tab: browse/edit rows, view structure and DDL."""
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSizePolicy, QSpinBox,
    QTabWidget, QToolBar, QToolButton, QVBoxLayout, QWidget,
)

from . import db, icons
from .sql_editor import SqlHighlighter
from .config import ConnectionConfig
from .result_view import EditableResultModel, ResultModel, ResultView
from .worker import run_async

q = db.quote_ident


class TableTab(QWidget):
    def __init__(self, cfg: ConnectionConfig, database: str, table: str, is_view: bool,
                 status_callback, start_page=0, parent=None):
        super().__init__(parent)
        self.cfg, self.database, self.table, self.is_view = cfg, database, table, is_view
        self.status = status_callback
        self.conn = None
        self.pk: list[str] = []
        self.offset = 0
        self.total = 0
        self.busy = False
        self.fqn = f"{q(database)}.{q(table)}"

        self.tabs = QTabWidget()
        self.tabs.setObjectName("subTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._build_data_page(), "Data")
        self.structure_view = ResultView()
        self.structure_view.setModel(ResultModel(parent=self.structure_view))
        self.tabs.addTab(self.structure_view, "Structure")
        self.ddl_view = QPlainTextEdit()
        self.ddl_view.setReadOnly(True)
        self.ddl_view.setFont(self._mono())
        self.ddl_highlighter = SqlHighlighter(self.ddl_view.document())
        self.tabs.addTab(self.ddl_view, "DDL")
        self.tabs.setCurrentIndex(start_page)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tabs)

        self._set_busy(True)
        run_async(self._open, on_done=self._opened, on_error=self._error)

    @staticmethod
    def _mono():
        from PyQt6.QtGui import QFontDatabase
        return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)

    def _action(self, icon, text, slot, tip=None):
        a = QAction(icons.icon(icon), text, self)
        a.setToolTip(tip or text)
        a.triggered.connect(slot)
        return a

    @staticmethod
    def _bar_button(action):
        b = QToolButton()
        b.setDefaultAction(action)
        b.setAutoRaise(True)
        b.setIconSize(QSize(16, 16))
        return b

    @staticmethod
    def _vline():
        line = QFrame()
        line.setObjectName("vline")
        line.setFixedHeight(16)
        return line

    def _build_data_page(self):
        page = QWidget()
        toolbar = QToolBar()
        toolbar.setIconSize(QSize(16, 16))
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.a_filter = toolbar.addAction(icons.icon("filter"), "Filter && Sort")
        self.a_filter.setCheckable(True)
        self.a_filter.toggled.connect(self._toggle_filter)
        toolbar.addAction(icons.icon("export"), "Export", lambda: self.view.export_csv())

        # Filter bar, hidden until "Filter & Sort" is toggled (like Navicat)
        self.filter_bar = QFrame()
        self.filter_bar.setObjectName("filterBar")
        filters = QHBoxLayout(self.filter_bar)
        filters.setContentsMargins(8, 5, 8, 5)
        self.where = QLineEdit()
        self.where.setPlaceholderText("e.g. id > 10 AND name LIKE 'a%'")
        self.where.returnPressed.connect(self._apply_filter)
        self.order = QLineEdit()
        self.order.setPlaceholderText("e.g. id DESC")
        self.order.returnPressed.connect(self._apply_filter)
        filters.addWidget(QLabel("WHERE"))
        filters.addWidget(self.where, 3)
        filters.addSpacing(6)
        filters.addWidget(QLabel("ORDER BY"))
        filters.addWidget(self.order, 1)
        apply = QPushButton("Apply")
        apply.setDefault(True)
        apply.clicked.connect(self._apply_filter)
        filters.addWidget(apply)
        self.filter_bar.hide()

        self.view = ResultView()
        self.model = EditableResultModel(self.view)
        self.view.setModel(self.model)
        self.model.dataChanged.connect(self._update_actions)
        self.model.layoutChanged.connect(self._update_actions)
        self.model.rowsInserted.connect(self._update_actions)
        self.model.rowsRemoved.connect(self._update_actions)

        self.a_add = self._action("add", "Add Row", self.add_row, "Add record")
        self.a_delete = self._action("remove", "Delete Row", self.delete_rows, "Delete record")
        self.a_save = self._action("apply", "Apply Changes", self.save, "Apply changes (Ctrl+S)")
        self.a_save.setShortcut("Ctrl+S")
        self.a_save.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.addAction(self.a_save)
        self.a_discard = self._action("discard", "Discard Changes", self.discard, "Discard changes")
        self.a_refresh = self._action("refresh", "Refresh", self.load_data, "Refresh (Ctrl+R)")
        self.a_null = self._action("set_null", "Set NULL", self.set_null)
        self.a_first = self._action("first", "First Page", lambda: self._goto(0))
        self.a_prev = self._action("prev", "Previous Page", lambda: self._page(-1))
        self.a_next = self._action("next", "Next Page", lambda: self._page(1))
        self.a_last = self._action("last", "Last Page", lambda: self._goto(None))
        self.view.extra_actions += [self.a_null, self.a_add, self.a_delete]

        # Bottom bar: record buttons | SQL | record info + paging (Navicat layout)
        bottom = QFrame()
        bottom.setObjectName("bottomBar")
        bar = QHBoxLayout(bottom)
        bar.setContentsMargins(4, 2, 6, 2)
        bar.setSpacing(1)
        for a in (self.a_add, self.a_delete, self.a_save, self.a_discard):
            bar.addWidget(self._bar_button(a))
        bar.addWidget(self._vline())
        bar.addWidget(self._bar_button(self.a_refresh))
        bar.addSpacing(8)
        self.sql_label = QLabel()
        self.sql_label.setObjectName("sqlLabel")
        self.sql_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.sql_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bar.addWidget(self.sql_label, 1)
        self.info = QLabel()
        self.info.setObjectName("muted")
        bar.addWidget(self.info)
        bar.addSpacing(8)
        bar.addWidget(self._bar_button(self.a_first))
        bar.addWidget(self._bar_button(self.a_prev))
        self.page_label = QLabel()
        self.page_label.setMinimumWidth(36)
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bar.addWidget(self.page_label)
        bar.addWidget(self._bar_button(self.a_next))
        bar.addWidget(self._bar_button(self.a_last))
        bar.addSpacing(6)
        limit_label = QLabel("Limit")
        limit_label.setObjectName("muted")
        bar.addWidget(limit_label)
        bar.addSpacing(4)
        self.limit = QSpinBox()
        self.limit.setRange(10, 100000)
        self.limit.setSingleStep(100)
        self.limit.setValue(1000)
        self.limit.setToolTip("Records per page")
        self.limit.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.limit.setFixedWidth(64)
        self.limit.editingFinished.connect(self._apply_filter)
        bar.addWidget(self.limit)

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar)
        layout.addWidget(self.filter_bar)
        layout.addWidget(self.view)
        layout.addWidget(bottom)
        return page

    def _toggle_filter(self, on):
        self.filter_bar.setVisible(on)
        if on:
            self.where.setFocus()

    # loading ------------------------------------------------------------
    def _open(self):
        conn = db.connect(self.cfg, self.database)
        pk = db.primary_key(conn, self.database, self.table)
        structure = db.execute(conn, f"SHOW FULL COLUMNS FROM {self.fqn}")
        kind = "VIEW" if self.is_view else "TABLE"
        ddl = db.execute(conn, f"SHOW CREATE {kind} {self.fqn}").rows[0][1]
        return conn, pk, structure, ddl

    def _opened(self, result):
        self.conn, self.pk, structure, ddl = result
        self.structure_view.model().set_data(structure.columns, structure.rows)
        self.structure_view.fit_columns()
        self.ddl_view.setPlainText(ddl)
        self.busy = False
        self.load_data()

    def _select_sql(self):
        sql = f"SELECT * FROM {self.fqn}"
        if self.where.text().strip():
            sql += f" WHERE {self.where.text().strip()}"
        count_sql = sql.replace("SELECT *", "SELECT COUNT(*)", 1)
        if self.order.text().strip():
            sql += f" ORDER BY {self.order.text().strip()}"
        sql += f" LIMIT {self.limit.value()} OFFSET {self.offset}"
        return sql, count_sql

    def load_data(self):
        if self.busy or self.conn is None:
            return
        if self.model.has_changes() and not self._confirm_discard():
            return
        sql, count_sql = self._select_sql()
        self.sql_label.setText(sql)
        self.sql_label.setToolTip(sql)
        self._set_busy(True)

        def fetch():
            rs = db.execute(self.conn, sql, max_rows=self.limit.value())
            total = db.execute(self.conn, count_sql).rows[0][0]
            return rs, total
        run_async(fetch, on_done=self._loaded, on_error=self._error)

    def _loaded(self, result):
        rs, self.total = result
        self.model.editable = not self.is_view
        self.model.set_data(rs.columns, rs.rows)
        self.view.fit_columns()
        self._set_busy(False)
        self.status(f"{self.table}: {rs.rowcount} row(s) loaded in {rs.elapsed * 1000:.1f} ms")

    def _apply_filter(self):
        self.offset = 0
        self.load_data()

    def _goto(self, offset):
        limit = self.limit.value()
        if offset is None:  # last page
            offset = max(0, (self.total - 1) // limit * limit)
        if offset != self.offset:
            self.offset = offset
            self.load_data()

    def _page(self, direction):
        new = self.offset + direction * self.limit.value()
        if 0 <= new < max(self.total, 1):
            self.offset = new
            self.load_data()

    # editing ------------------------------------------------------------
    def add_row(self):
        row = self.model.add_row()
        self.view.scrollToBottom()
        self.view.setCurrentIndex(self.model.index(row, 0))

    def _selected_rows(self):
        return sorted({i.row() for i in self.view.selectedIndexes()})

    def delete_rows(self):
        rows = self._selected_rows()
        if rows and not self.pk and any(r not in self.model.new_rows for r in rows):
            QMessageBox.warning(self, "No primary key",
                                "This table has no primary key, so rows can't be deleted from the grid.\n"
                                "Use a DELETE statement in a query tab instead.")
            return
        self.model.toggle_delete(rows)

    def set_null(self):
        if not self.model.editable:
            return
        for idx in self.view.selectedIndexes():
            if self.model.flags(idx) & Qt.ItemFlag.ItemIsEditable:
                self.model.set_cell(idx.row(), idx.column(), None)

    def discard(self):
        self.load_data_force()

    def load_data_force(self):
        self.model.reset_changes()
        self.load_data()

    def _build_changes(self):
        m = self.model
        statements = []
        cols = m.columns
        pk_idx = [cols.index(c) for c in self.pk if c in cols]

        def where_pk(row):
            if not pk_idx or len(pk_idx) != len(self.pk):
                raise ValueError("This table has no primary key (or it is not in the result), "
                                 "so existing rows can't be updated from the grid.")
            parts = [f"{q(cols[i])} = %s" for i in pk_idx]
            return " AND ".join(parts), [m.original[row][i] for i in pk_idx]

        for r in sorted(m.deleted_rows):
            cond, args = where_pk(r)
            statements.append((f"DELETE FROM {self.fqn} WHERE {cond} LIMIT 1", args))
        changed_rows = sorted({r for r, _ in m.changed if r not in m.deleted_rows})
        for r in changed_rows:
            cs = sorted(c for rr, c in m.changed if rr == r)
            cond, args = where_pk(r)
            sets = ", ".join(f"{q(cols[c])} = %s" for c in cs)
            statements.append((f"UPDATE {self.fqn} SET {sets} WHERE {cond} LIMIT 1",
                               [m.rows[r][c] for c in cs] + args))
        for r in sorted(m.new_rows):
            cs = [c for c in range(len(cols)) if m.rows[r][c] is not None]
            if not cs:
                statements.append((f"INSERT INTO {self.fqn} () VALUES ()", []))
                continue
            names = ", ".join(q(cols[c]) for c in cs)
            marks = ", ".join(["%s"] * len(cs))
            statements.append((f"INSERT INTO {self.fqn} ({names}) VALUES ({marks})",
                               [m.rows[r][c] for c in cs]))
        return statements

    def save(self):
        if self.busy or not self.model.has_changes():
            return
        self.view.setFocus()  # commit an open cell editor
        try:
            statements = self._build_changes()
        except ValueError as e:
            QMessageBox.warning(self, "Cannot save", str(e))
            return

        def apply():
            self.conn.ping(reconnect=True)
            self.conn.begin()
            try:
                for sql, args in statements:
                    with self.conn.cursor() as cur:
                        cur.execute(sql, args)
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
            return len(statements)

        self._set_busy(True)
        run_async(apply, on_done=self._saved, on_error=self._save_failed)

    def _saved(self, count):
        self._set_busy(False)
        self.status(f"{count} change(s) saved to {self.table}")
        self.load_data_force()

    def _save_failed(self, err):
        self._set_busy(False)
        QMessageBox.critical(self, "Save failed", f"No changes were saved.\n\n{err}")

    def _confirm_discard(self):
        answer = QMessageBox.question(self, "Unsaved changes", "Discard unsaved changes?")
        return answer == QMessageBox.StandardButton.Yes

    # state --------------------------------------------------------------
    def _error(self, err):
        self._set_busy(False)
        self.status(f"Error: {err}")
        QMessageBox.critical(self, "Error", str(err))

    def _set_busy(self, busy):
        self.busy = busy
        self.a_refresh.setEnabled(not busy)
        self.a_filter.setEnabled(not busy)
        self._update_actions()

    def _update_actions(self, *_):
        editable = not self.busy and self.model.editable
        changes = self.model.has_changes()
        for a in (self.a_add, self.a_delete, self.a_null):
            a.setEnabled(editable)
        self.a_save.setEnabled(editable and changes)
        self.a_discard.setEnabled(editable and changes)
        limit = self.limit.value()
        page = self.offset // limit + 1
        pages = max(1, -(-self.total // limit))
        shown = self.model.rowCount()
        first = self.offset + 1 if shown else 0
        state = "  ·  unsaved changes" if changes else ("  ·  read only" if self.is_view else "")
        self.info.setText(f"Records {first}–{self.offset + shown} of {self.total}{state}")
        self.page_label.setText(f"{page} / {pages}")
        can_back = not self.busy and self.offset > 0
        can_fwd = not self.busy and self.offset + limit < self.total
        self.a_first.setEnabled(can_back)
        self.a_prev.setEnabled(can_back)
        self.a_next.setEnabled(can_fwd)
        self.a_last.setEnabled(can_fwd)

    def has_unsaved_changes(self):
        return self.model.has_changes()

    def close_connection(self):
        if self.conn:
            try:
                self.conn.close()
            except Exception:  # noqa: BLE001
                pass
