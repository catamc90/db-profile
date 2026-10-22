"""Table tab: browse/edit rows, view structure and DDL."""
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSizePolicy, QSpinBox,
    QSplitter, QTabWidget, QToolBar, QToolButton, QVBoxLayout, QWidget,
)

from . import db, icons
from .sql_editor import SqlHighlighter
from .config import ConnectionConfig
from .result_view import EditableResultModel, ResultModel, ResultView, display_value
from .worker import run_async

q = db.quote_ident
CELL_EDITOR_MAX_BYTES = 64 * 1024  # binary values are shown as hex, up to this many bytes


class _ElidedLabel(QLabel):
    """A one-line label that ends long text with "…" instead of cutting it off."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._full = ""

    def setText(self, text):
        self._full = text
        self._elide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def _elide(self):
        super().setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, max(0, self.width())))


class TableTab(QWidget):
    def __init__(self, cfg: ConnectionConfig, database: str, table: str, is_view: bool,
                 status_callback, start_page=0, parent=None):
        super().__init__(parent)
        self.cfg, self.database, self.table, self.is_view = cfg, database, table, is_view
        self.status = status_callback
        self.conn = None
        self.pk: list[str] = []
        self.offset = 0
        # Row count of the current filter. It is counted in the background after the rows are shown,
        # because COUNT(*) on a big table can take much longer than fetching one page.
        self.total: int | None = None
        self.total_exact = False
        self._count_gen = 0  # increases with every count, so a stale result is ignored
        self._count_thread = None  # server thread id of the running count, to cancel it
        self._last_after_count = False
        # Keyset paging (see _uses_keyset): where the current page starts, and the keys of its first/last row.
        # ("first",) | ("after", key) | ("before", key) | ("last", row count of the last page)
        self._anchor = ("first",)
        self._page_keys = None
        self.hidden_columns: set[str] = set()
        self._cell_loading = False
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
        # Toolbar like Navicat's table viewer: Cell Editor, Filter & Sort, Columns, Tools
        toolbar = QToolBar()
        toolbar.setObjectName("tableToolbar")
        toolbar.setIconSize(QSize(16, 16))
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.a_cell_editor = toolbar.addAction(icons.icon("cell_editor"), "Cell Editor")
        self.a_cell_editor.setToolTip("Show the full value of the current cell, and edit it")
        self.a_cell_editor.setCheckable(True)
        self.a_cell_editor.toggled.connect(self._toggle_cell_editor)
        self.a_filter = toolbar.addAction(icons.icon("filter"), "Filter && Sort")
        self.a_filter.setCheckable(True)
        self.a_filter.toggled.connect(self._toggle_filter)
        self.columns_menu = QMenu(self)
        self.columns_menu.aboutToShow.connect(self._fill_columns_menu)
        toolbar.addWidget(self._menu_button("columns", "Columns", self.columns_menu, "Show or hide columns"))
        tools_menu = QMenu(self)
        tools_menu.addAction(icons.icon("import"), "Import Wizard…", self._import)
        tools_menu.addAction(icons.icon("export"), "Export Wizard…", self._export)
        toolbar.addWidget(self._menu_button("tools", "Tools", tools_menu))

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
        self.sql_label = _ElidedLabel()
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

        # Cell editor: a side panel with the current cell's full value, hidden until toggled
        self.cell_panel = QFrame()
        self.cell_panel.setObjectName("cellPanel")
        panel = QVBoxLayout(self.cell_panel)
        panel.setContentsMargins(0, 0, 0, 0)
        panel.setSpacing(0)
        self.cell_head = QLabel()
        self.cell_head.setObjectName("cellHead")
        panel.addWidget(self.cell_head)
        self.cell_edit = QPlainTextEdit()
        self.cell_edit.setFont(self._mono())
        self.cell_edit.textChanged.connect(self._cell_text_changed)
        panel.addWidget(self.cell_edit)
        self.cell_panel.hide()
        self.view.selectionModel().currentChanged.connect(self._show_current_cell)
        self.model.modelReset.connect(self._show_current_cell)
        self.model.dataChanged.connect(lambda *_: None if self.cell_edit.hasFocus() else self._show_current_cell())

        grid = QSplitter(Qt.Orientation.Horizontal)
        grid.setHandleWidth(1)
        grid.setChildrenCollapsible(False)
        grid.addWidget(self.view)
        grid.addWidget(self.cell_panel)
        grid.setStretchFactor(0, 1)
        grid.setSizes([700, 260])

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar)
        layout.addWidget(self.filter_bar)
        layout.addWidget(grid, 1)
        layout.addWidget(bottom)
        return page

    @staticmethod
    def _menu_button(icon, text, menu, tip=None):
        b = QToolButton()
        b.setIcon(icons.icon(icon))
        b.setText(text)
        b.setToolTip(tip or text)
        b.setMenu(menu)
        b.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        b.setAutoRaise(True)
        return b

    # cell editor ----------------------------------------------------------
    def _toggle_cell_editor(self, on):
        self.cell_panel.setVisible(on)
        self._show_current_cell()

    def _show_current_cell(self, *_):
        if not self.cell_panel.isVisible():
            return
        idx = self.view.currentIndex()
        self._cell_loading = True
        try:
            if not idx.isValid():
                head, text, read_only, placeholder = "No cell selected", "", True, ""
            else:
                value = self.model.value(idx.row(), idx.column())
                name = self.model.columns[idx.column()]
                ctype = self.model.headerData(idx.column(), Qt.Orientation.Horizontal, Qt.ItemDataRole.UserRole + 1)
                head = f"{name}  ·  {ctype}" if ctype else name
                if isinstance(value, (bytes, bytearray)):
                    text = "0x" + bytes(value[:CELL_EDITOR_MAX_BYTES]).hex().upper()
                    if len(value) > CELL_EDITOR_MAX_BYTES:
                        text += f"…  ({len(value):,} bytes)"
                    read_only = True
                else:
                    text = "" if value is None else display_value(value)
                    read_only = not (self.model.flags(idx) & Qt.ItemFlag.ItemIsEditable)
                placeholder = "(NULL)" if value is None else ""
                if read_only:
                    head += "  ·  read only"
            self.cell_head.setText(head)
            self.cell_edit.setReadOnly(read_only)
            self.cell_edit.setPlaceholderText(placeholder)
            if self.cell_edit.toPlainText() != text:
                self.cell_edit.setPlainText(text)
        finally:
            self._cell_loading = False

    def _cell_text_changed(self):
        idx = self.view.currentIndex()
        if self._cell_loading or self.cell_edit.isReadOnly() or not idx.isValid():
            return
        text = self.cell_edit.toPlainText()
        if text == "" and self.model.value(idx.row(), idx.column()) is None:
            return  # an empty editor on a NULL cell keeps NULL; use Set NULL to clear a value
        self.model.set_cell(idx.row(), idx.column(), text)

    # columns --------------------------------------------------------------------
    def _fill_columns_menu(self):
        menu = self.columns_menu
        menu.clear()
        menu.addAction("Show All Columns", self._show_all_columns).setEnabled(bool(self.hidden_columns))
        menu.addSeparator()
        for i, name in enumerate(self.model.columns):
            ctype = self.model.headerData(i, Qt.Orientation.Horizontal, Qt.ItemDataRole.UserRole + 1)
            action = menu.addAction(f"{name}\t{ctype}" if ctype else name)
            action.setCheckable(True)
            action.setChecked(name not in self.hidden_columns)
            action.toggled.connect(lambda on, n=name: self._set_column_visible(n, on))

    def _set_column_visible(self, name, visible):
        if visible:
            self.hidden_columns.discard(name)
        elif len(self.hidden_columns) + 1 < len(self.model.columns):  # keep at least one column
            self.hidden_columns.add(name)
        self._apply_hidden_columns()

    def _show_all_columns(self):
        self.hidden_columns.clear()
        self._apply_hidden_columns()

    def _apply_hidden_columns(self):
        for i, name in enumerate(self.model.columns):
            self.view.setColumnHidden(i, name in self.hidden_columns)

    def _export(self):
        from .transfer_wizards import ExportWizard
        ExportWizard(self.cfg, self.database, [(self.table, "VIEW" if self.is_view else "BASE TABLE")],
                     [self.table], parent=self).exec()

    def _import(self):
        from .transfer_wizards import ImportWizard
        if self.is_view:
            QMessageBox.information(self, "Import", "Records can't be imported into a view.")
            return
        ImportWizard(self.cfg, self.database, [(self.table, "BASE TABLE")], self.table,
                     on_finished=self.load_data_force, parent=self).exec()

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

    def _uses_keyset(self):
        """Page by primary key instead of OFFSET when the rows are in primary key order.

        "WHERE pk > last key ORDER BY pk LIMIT n" reads only the rows it returns, while
        "LIMIT n OFFSET m" makes the server read and skip m rows first, which is slow on deep pages.
        """
        return bool(self.pk) and not self.is_view and not self.order.text().strip()

    def _key_condition(self, op, key):
        """Rows after (op ">") or before (op "<") key in primary key order; works for composite keys."""
        terms = []
        for i, col in enumerate(self.pk):
            parts = [f"{q(c)} = {self.conn.literal(v)}" for c, v in zip(self.pk[:i], key[:i])]
            parts.append(f"{q(col)} {op} {self.conn.literal(key[i])}")
            terms.append(" AND ".join(parts))
        return "(" + " OR ".join(f"({t})" if len(self.pk) > 1 else t for t in terms) + ")"

    def _select_sql(self):
        """Returns (page SQL, count SQL, whether the page comes back in reverse order)."""
        where = self.where.text().strip()
        sql = f"SELECT * FROM {self.fqn}"
        count_sql = f"SELECT COUNT(*) FROM {self.fqn}" + (f" WHERE {where}" if where else "")
        limit = self.limit.value()
        if not self._uses_keyset():
            if where:
                sql += f" WHERE {where}"
            if self.order.text().strip():
                sql += f" ORDER BY {self.order.text().strip()}"
            return sql + f" LIMIT {limit} OFFSET {self.offset}", count_sql, False
        kind = self._anchor[0]
        conditions = [f"({where})"] if where else []
        if kind in ("after", "before"):
            conditions.append(self._key_condition(">" if kind == "after" else "<", self._anchor[1]))
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        # Previous and last pages are read backwards from their end, then reversed.
        backwards = kind in ("before", "last")
        sql += " ORDER BY " + ", ".join(f"{q(c)} {'DESC' if backwards else 'ASC'}" for c in self.pk)
        sql += f" LIMIT {self._anchor[1] if kind == 'last' else limit}"
        return sql, count_sql, backwards

    def load_data(self, recount=True):
        """Fetch the current page. recount=False when only the page changed (the filter is the same)."""
        if self.busy or self.conn is None:
            return
        if self.model.has_changes() and not self._confirm_discard():
            return
        sql, count_sql, backwards = self._select_sql()
        self.sql_label.setText(sql)
        self.sql_label.setToolTip(sql)
        self._set_busy(True)
        if recount:
            self._cancel_count()
            self.total, self.total_exact = None, False
        estimate = recount and not self.is_view and not self.where.text().strip()

        def fetch():
            rs = db.execute(self.conn, sql, max_rows=self.limit.value())
            if backwards:
                rs.rows.reverse()
            # Without a filter the server's row estimate is instant; the exact count replaces it later.
            approx = db.estimated_rows(self.conn, self.database, self.table) if estimate else None
            return rs, approx
        run_async(fetch, on_done=lambda result: self._loaded(result, count_sql, recount), on_error=self._error)

    def _loaded(self, result, count_sql, recount):
        rs, approx = result
        self.model.editable = not self.is_view
        self.model.set_data(rs.columns, rs.rows, rs.types)
        self._apply_hidden_columns()
        self._page_keys = None
        if rs.rows and self.pk and all(c in rs.columns for c in self.pk):
            cols = [rs.columns.index(c) for c in self.pk]
            self._page_keys = ([rs.rows[0][i] for i in cols], [rs.rows[-1][i] for i in cols])
        self.view.fit_columns()
        if recount:
            if self.offset == 0 and rs.rowcount < self.limit.value():
                self.total, self.total_exact = rs.rowcount, True  # everything fits on this page
            else:
                if approx is not None:
                    self.total = max(approx, self.offset + rs.rowcount)
                self._start_count(count_sql)
        self._set_busy(False)
        self.status(f"{self.table}: {rs.rowcount} row(s) loaded in {rs.elapsed * 1000:.1f} ms")

    # counting rows in the background ----------------------------------------
    def _start_count(self, count_sql):
        self._count_gen += 1
        gen = self._count_gen

        def count():
            # Own connection: the tab's connection stays free for paging and editing meanwhile.
            conn = db.connect(self.cfg, self.database)
            try:
                if gen != self._count_gen:
                    return None
                self._count_thread = conn.thread_id()
                return db.execute(conn, count_sql).rows[0][0]
            finally:
                conn.close()

        def done(total):
            if gen != self._count_gen or total is None:
                return
            self._count_thread = None
            self.total, self.total_exact = total, True
            self._update_actions()
            if self._last_after_count:
                self._last_after_count = False
                self._goto(None)

        def failed(err):
            if gen == self._count_gen:
                self._count_thread = None
                self._last_after_count = False
                self.status(f"{self.table}: could not count rows: {err}")
                self._update_actions()
        run_async(count, on_done=done, on_error=failed)
        self._update_actions()

    def _cancel_count(self):
        """Stop a running count (its result would be for an old filter) so it doesn't keep the server busy."""
        self._count_gen += 1
        self._last_after_count = False
        thread_id, self._count_thread = self._count_thread, None
        if thread_id is None:
            return

        def kill():
            conn = db.connect(self.cfg)
            try:
                db.execute(conn, f"KILL QUERY {int(thread_id)}")
            finally:
                conn.close()
        run_async(kill, on_error=lambda _: None)  # the count may already have finished

    def _apply_filter(self):
        self.offset = 0
        self._anchor = ("first",)
        self.load_data()

    def _goto(self, offset):
        limit = self.limit.value()
        if offset is None:  # last page: needs the exact count
            if not self.total_exact:
                self._last_after_count = True
                self.status(f"{self.table}: counting rows to find the last page…")
                self._update_actions()
                return
            offset = max(0, (self.total - 1) // limit * limit)
            self._anchor = ("last", self.total - offset) if offset else ("first",)
        else:
            self._anchor = ("first",)
        if offset != self.offset:
            self.offset = offset
            self.load_data(recount=False)

    def _page(self, direction):
        new = self.offset + direction * self.limit.value()
        if new >= 0 and (direction < 0 or self._has_next_page()):
            if new == 0 or not self._uses_keyset():
                self._anchor = ("first",)
            elif self._page_keys is None:  # empty page: nothing to continue from, start over
                self._anchor = ("first",)
                new = 0
            else:
                first_key, last_key = self._page_keys
                self._anchor = ("after", last_key) if direction > 0 else ("before", first_key)
            self.offset = new
            self.load_data(recount=False)

    def _has_next_page(self):
        if self.total_exact:
            return self.offset + self.limit.value() < self.total
        return self.model.rowCount() - len(self.model.new_rows) >= self.limit.value()

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
        shown = self.model.rowCount()
        first = self.offset + 1 if shown else 0
        state = "  ·  unsaved changes" if changes else ("  ·  read only" if self.is_view else "")
        if self.total_exact:
            total, pages = f"{self.total:,}", f"{max(1, -(-self.total // limit)):,}"
        elif self.total is not None:  # server estimate while the exact count runs
            total, pages = f"~{self.total:,}", f"~{max(1, -(-self.total // limit)):,}"
        else:
            total, pages = "…", "…"
        counting = "" if self.total_exact else "  ·  counting…"
        self.info.setText(f"Records {first:,}–{self.offset + shown:,} of {total}{counting}{state}")
        self.info.setToolTip("" if self.total_exact else "The exact number of rows is being counted in the background")
        self.page_label.setText(f"{page:,} / {pages}")
        can_back = not self.busy and self.offset > 0
        can_fwd = not self.busy and self._has_next_page()
        self.a_first.setEnabled(can_back)
        self.a_prev.setEnabled(can_back)
        self.a_next.setEnabled(can_fwd)
        self.a_last.setEnabled(can_fwd and not self._last_after_count)

    def has_unsaved_changes(self):
        return self.model.has_changes()

    def close_connection(self):
        self._cancel_count()
        if self.conn:
            try:
                self.conn.close()
            except Exception:  # noqa: BLE001
                pass
