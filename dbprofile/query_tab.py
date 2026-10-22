"""SQL editor tab: write a script, run it, see each statement's results."""
import html

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QComboBox, QLabel, QSplitter, QTabWidget, QTextEdit, QToolBar, QVBoxLayout, QWidget,
)

from . import db, icons
from .config import ConnectionConfig
from .result_view import ResultModel, ResultView
from .worker import run_async


class QueryTab(QWidget):
    def __init__(self, cfg: ConnectionConfig, database: str | None, status_callback, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.conn = None
        self.busy = False
        self.status = status_callback

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
        self.export_action = toolbar.addAction(icons.icon("export"), "Export Result", self._export_current)

        from .sql_editor import SqlEditor  # local import keeps module load light
        self.editor = SqlEditor()
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
        if isinstance(view, ResultView):
            view.export_csv()
        else:
            self.status("Select a result tab to export")

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

    def close_connection(self):
        if self.conn:
            try:
                self.conn.close()
            except Exception:  # noqa: BLE001
                pass
