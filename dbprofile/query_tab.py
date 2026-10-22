"""SQL editor tab: write a script, run it, see each statement's results, save it as a named query."""
import html

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QComboBox, QInputDialog, QLabel, QMessageBox, QSplitter, QTabWidget, QTextEdit, QToolBar, QVBoxLayout, QWidget,
)

from . import db, icons, saved_queries, sql_format
from .config import ConnectionConfig
from .result_view import ResultModel, ResultView
from .worker import run_async


class QueryTab(QWidget):
    saved = pyqtSignal(object, str, str)  # (tab, previous database or "", previous name or "")
    modified_changed = pyqtSignal(bool)

    def __init__(self, cfg: ConnectionConfig, database: str | None, status_callback, query_name=None, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.conn = None
        self.busy = False
        self.status = status_callback
        self.initial_database = database
        # A saved query belongs to one database; query_name is None until the query is saved.
        self.query_db = database if query_name else None
        self.query_name = query_name

        toolbar = QToolBar()
        toolbar.setIconSize(QSize(16, 16))
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        conn_label = QLabel()
        conn_label.setPixmap(icons.icon("connection").pixmap(16, 16))
        conn_label.setContentsMargins(4, 0, 4, 0)
        toolbar.addWidget(conn_label)
        name_label = QLabel(cfg.name)
        name_label.setContentsMargins(0, 0, 10, 0)
        toolbar.addWidget(name_label)
        self.db_combo = QComboBox()
        self.db_combo.setMinimumWidth(180)
        self.db_combo.activated.connect(self._use_database)
        toolbar.addWidget(self.db_combo)
        toolbar.addSeparator()
        self.save_action = QAction(icons.icon("save"), "Save", self)
        self.save_action.setToolTip("Save this query (Ctrl+S)")
        self.save_action.setShortcut(QKeySequence("Ctrl+S"))
        self.save_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.save_action.triggered.connect(lambda: self.save())
        self.addAction(self.save_action)
        toolbar.addAction(self.save_action)
        self.save_as_action = QAction("Save As…", self)
        self.save_as_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.save_as_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.save_as_action.triggered.connect(lambda: self.save(save_as=True))
        self.addAction(self.save_as_action)
        toolbar.addAction(self.save_as_action)
        toolbar.addSeparator()
        self.run_action = QAction(icons.icon("run"), "Run", self)
        self.run_action.setToolTip("Run all, or only the selected text (Ctrl+Enter / F5)")
        self.run_action.setShortcuts([QKeySequence("Ctrl+Return"), QKeySequence("F5")])
        self.run_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.run_action.triggered.connect(self.run)
        self.addAction(self.run_action)
        toolbar.addAction(self.run_action)
        self.stop_action = QAction(icons.icon("stop"), "Stop", self)
        self.stop_action.setEnabled(False)
        self.stop_action.triggered.connect(self.stop)
        toolbar.addAction(self.stop_action)
        toolbar.addSeparator()
        self.beautify_action = QAction(icons.icon("beautify"), "Beautify SQL", self)
        self.beautify_action.setToolTip("Format the SQL, or only the selected text (Ctrl+Shift+F)")
        self.beautify_action.setShortcut(QKeySequence("Ctrl+Shift+F"))
        self.beautify_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.beautify_action.triggered.connect(self.beautify)
        self.addAction(self.beautify_action)
        toolbar.addAction(self.beautify_action)
        toolbar.addSeparator()
        self.export_action = toolbar.addAction(icons.icon("export"), "Export Result", self._export_current)

        from .sql_editor import SqlEditor  # local import keeps module load light
        self.editor = SqlEditor()
        if query_name:
            self.editor.setPlainText(saved_queries.load(cfg.id, database, query_name))
            self.editor.document().setModified(False)
        self.editor.document().modificationChanged.connect(self.modified_changed.emit)
        self.editor.menu_actions = [self.run_action, self.beautify_action]
        self.results = QTabWidget()
        self.results.setObjectName("subTabs")
        self.results.setDocumentMode(True)
        self.messages = QTextEdit()
        self.messages.setReadOnly(True)
        self.messages.document().setDocumentMargin(8)
        self.results.addTab(self.messages, "Message")

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setHandleWidth(1)
        splitter.addWidget(self.editor)
        splitter.addWidget(self.results)
        splitter.setSizes([300, 300])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar)
        layout.addWidget(splitter)

        self._set_busy(True)
        run_async(self._open, database, on_done=self._opened, on_error=self._failed)

    # connection setup -------------------------------------------------
    def _open(self, database):
        conn = db.connect(self.cfg, database)
        return conn, db.list_databases(conn), db.current_database(conn)

    def _opened(self, result):
        self.conn, databases, current = result
        self.db_combo.addItem("(none)", None)
        for name in databases:
            self.db_combo.addItem(name, name)
        idx = self.db_combo.findData(current)
        self.db_combo.setCurrentIndex(max(idx, 0))
        self._log(f"Connected to {html.escape(self.cfg.name)}.", "gray")
        self._set_busy(False)
        self.editor.setFocus()

    def _failed(self, err):
        self._log(f"Error: {html.escape(str(err))}", "#c62828")
        self._set_busy(False)

    def _use_database(self):
        name = self.db_combo.currentData()
        if not self.conn or self.busy or not name:
            return
        self._set_busy(True)
        run_async(db.execute, self.conn, f"USE {db.quote_ident(name)}",
                  on_done=lambda _: self._set_busy(False), on_error=self._failed)

    # running ------------------------------------------------------------
    def run(self):
        sql = self.editor.sql_to_run().strip()
        if not sql or self.busy:
            return
        if self.conn is None:
            self._log("Not connected.", "#c62828")
            return
        while self.results.count() > 1:
            self.results.removeTab(1)
        self.messages.clear()
        self._set_busy(True)
        self.status("Running…")
        run_async(db.run_script, self.conn, sql, on_done=self._show_results, on_error=self._failed)

    def stop(self):
        if not self.busy or self.conn is None:
            return
        thread_id = self.conn.thread_id()

        def kill():
            c = db.connect(self.cfg)
            try:
                db.execute(c, f"KILL QUERY {int(thread_id)}")
            finally:
                c.close()
        run_async(kill, on_error=self._failed)

    def _show_results(self, results):
        self._set_busy(False)
        grids = 0
        total = 0.0
        for rs in results:
            short = html.escape(" ".join(rs.statement.split())[:200])
            if isinstance(rs, Exception):
                self._log(f"<b>{short}</b><br>Error: {html.escape(str(rs))}", "#c62828")
                self.results.setCurrentIndex(0)
                self.status("Query failed")
                return
            total += rs.elapsed
            if rs.columns is not None:
                grids += 1
                view = ResultView()
                view.setModel(ResultModel(rs.columns, rs.rows, view))
                view.fit_columns()
                self.results.addTab(view, f"Result {grids}")
                note = f"{rs.rowcount} row(s) returned"
                if rs.truncated:
                    note += f" (limited to first {db.MAX_FETCH_ROWS})"
            else:
                note = f"{rs.rowcount} row(s) affected"
            self._log(f"<b>{short}</b><br>{note} — {rs.elapsed * 1000:.1f} ms")
        if grids:
            self.results.setCurrentIndex(1)
        self.status(f"{len(results)} statement(s) executed in {total * 1000:.1f} ms")
        # The script may have switched databases with USE.
        run_async(db.current_database, self.conn, on_done=self._sync_db_combo)

    def _export_current(self):
        view = self.results.currentWidget()
        if not isinstance(view, ResultView):
            self.status("Select a result tab to export")
            return
        from .transfer_wizards import ExportWizard
        model = view.model()
        name = "query_result" if self.results.count() <= 2 else f"query_result_{self.results.currentIndex()}"
        ExportWizard(self.cfg, self.db_combo.currentData(), result=(model.columns, model.rows, name),
                     parent=self).exec()

    def _sync_db_combo(self, name):
        idx = self.db_combo.findData(name)
        if idx >= 0:
            self.db_combo.setCurrentIndex(idx)

    def _set_busy(self, busy):
        self.busy = busy
        self.run_action.setEnabled(not busy)
        self.stop_action.setEnabled(busy and self.conn is not None)
        self.db_combo.setEnabled(not busy)

    def _log(self, text, color=None):
        style = f' style="color:{color}"' if color else ""
        self.messages.append(f"<div{style}>{text}</div><br>")

    def beautify(self):
        selection_only = self.editor.textCursor().hasSelection()
        sql = self.editor.sql_to_run()
        if not sql.strip():
            return
        try:
            formatted = sql_format.beautify(sql)
        except Exception as e:  # noqa: BLE001 - never lose the user's text over a formatting problem
            QMessageBox.warning(self, "Beautify SQL", str(e))
            return
        if formatted != sql:
            self.editor.replace_text(formatted, selection_only)
        self.status("SQL beautified" + (" (selection)" if selection_only else ""))

    # saving -------------------------------------------------------------
    def is_modified(self):
        doc = self.editor.document()
        return doc.isModified() and (self.query_name is not None or bool(self.editor.toPlainText().strip()))

    def _target_database(self, save_as):
        if self.query_db and not save_as:
            return self.query_db
        return self.db_combo.currentData() or (self.initial_database if self.conn is None else None) \
            or self.query_db

    def save(self, save_as=False):
        """Save the editor text as a named query of its database. Returns True when saved."""
        database = self._target_database(save_as)
        if not database:
            QMessageBox.information(self, "Save Query",
                                    "Choose a database in the toolbar first: saved queries belong to a database.")
            return False
        name = self.query_name
        if save_as or not name:
            while True:
                name, ok = QInputDialog.getText(self, "Save Query" if not save_as else "Save Query As",
                                                f"Query name (in {database}):", text=name or "Untitled")
                if not ok:
                    return False
                name = name.strip()
                error = saved_queries.validate_name(name)
                if error:
                    QMessageBox.warning(self, "Save Query", error)
                    continue
                if (database, name) != (self.query_db, self.query_name) \
                        and saved_queries.exists(self.cfg.id, database, name):
                    if QMessageBox.question(self, "Save Query", f"A query named “{name}” already exists in "
                                            f"{database}. Replace it?") != QMessageBox.StandardButton.Yes:
                        continue
                break
        try:
            saved_queries.save(self.cfg.id, database, name, self.editor.toPlainText())
        except OSError as e:
            QMessageBox.critical(self, "Save Query", f"Could not save the query:\n{e}")
            return False
        previous = (self.query_db or "", self.query_name or "")
        self.query_db, self.query_name = database, name
        self.editor.document().setModified(False)
        self.status(f"Saved query {name} in {database}")
        self.saved.emit(self, *previous)
        return True

    def confirm_close(self):
        """Ask to save unsaved edits before the tab closes. Returns False to keep the tab open."""
        if not self.is_modified():
            return True
        what = f"the query “{self.query_name}”" if self.query_name else "this new query"
        answer = QMessageBox.question(
            self, "Save Query", f"Do you want to save the changes to {what}?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Save:
            return self.save()
        return answer == QMessageBox.StandardButton.Discard

    def close_connection(self):
        if self.conn:
            try:
                self.conn.close()
            except Exception:  # noqa: BLE001
                pass
