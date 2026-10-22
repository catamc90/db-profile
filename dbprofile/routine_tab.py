"""Function / stored procedure designer: edit the CREATE statement, save it, execute it."""
import html
import re

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QMessageBox, QSplitter, QTabWidget, QTextEdit,
    QToolBar, QVBoxLayout, QWidget,
)

from . import db, icons
from .config import ConnectionConfig
from .result_view import ResultModel, ResultView
from .sql_editor import SqlEditor
from .worker import run_async

q = db.quote_ident
_IDENT = r"(?:`(?:[^`]|``)+`|[\w$]+)"
CREATE_RE = re.compile(
    rf"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?(?:DEFINER\s*=\s*\S+\s+)?(?:AGGREGATE\s+)?(FUNCTION|PROCEDURE)\s+"
    rf"(?:IF\s+NOT\s+EXISTS\s+)?((?:{_IDENT}\s*\.\s*)?{_IDENT})",
    re.IGNORECASE,
)

TEMPLATES = {
    "FUNCTION": (
        "CREATE FUNCTION `new_function`(`a` INT, `b` INT)\n"
        "RETURNS INT\n"
        "DETERMINISTIC\n"
        "BEGIN\n"
        "    RETURN a + b;\n"
        "END"
    ),
    "PROCEDURE": (
        "CREATE PROCEDURE `new_procedure`(IN `p_limit` INT)\n"
        "BEGIN\n"
        "    SELECT NOW() AS now, p_limit AS requested_limit;\n"
        "END"
    ),
}


def _unquote(ident: str) -> str:
    ident = ident.strip()
    if ident.startswith("`"):
        return ident[1:-1].replace("``", "`")
    return ident


def parse_create(sql: str):
    """Return (type, name) from a CREATE FUNCTION/PROCEDURE statement, or None."""
    m = CREATE_RE.search(sql)
    if not m:
        return None
    name = m.group(2)
    # Drop a "schema." prefix; the routine is always saved into this tab's database.
    parts = re.findall(_IDENT, name)
    return m.group(1).upper(), _unquote(parts[-1])


class ParamsDialog(QDialog):
    """Ask for IN / INOUT argument values before executing a routine."""

    def __init__(self, name, params, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Execute {name}")
        self.setMinimumWidth(420)
        form = QFormLayout(self)
        hint = QLabel("Enter each value as an SQL expression, e.g. <code>42</code>, <code>'text'</code>, "
                      "<code>NOW()</code> or <code>NULL</code>.")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        form.addRow(hint)
        self.edits = []
        for mode, pname, dtd in params:
            label = f"{mode} {pname}  ({dtd})"
            if mode == "OUT":
                out = QLabel(f"→ @{pname}")
                out.setObjectName("muted")
                form.addRow(label, out)
                self.edits.append(None)
            else:
                edit = QLineEdit()
                edit.setPlaceholderText("NULL")
                form.addRow(label, edit)
                self.edits.append(edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Execute")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self):
        return [None if e is None else (e.text().strip() or "NULL") for e in self.edits]


class RoutineTab(QWidget):
    def __init__(self, cfg: ConnectionConfig, database: str, name: str | None, rtype: str,
                 status_callback, on_saved=None, parent=None):
        super().__init__(parent)
        self.cfg, self.database = cfg, database
        self.name, self.rtype = name, rtype  # name is None for a routine that is not saved yet
        self.status = status_callback
        self.on_saved = on_saved  # called with (tab) after a successful save
        self.conn = None
        self.busy = False
        self.original = None  # definition as stored on the server
        self.params = []

        toolbar = QToolBar()
        toolbar.setIconSize(QSize(16, 16))
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.a_save = QAction(icons.icon("save"), "Save", self)
        self.a_save.setShortcut(QKeySequence("Ctrl+S"))
        self.a_save.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.a_save.triggered.connect(self.save)
        self.addAction(self.a_save)
        toolbar.addAction(self.a_save)
        toolbar.addSeparator()
        self.a_execute = QAction(icons.icon("run"), "Execute", self)
        self.a_execute.setShortcuts([QKeySequence("F5"), QKeySequence("Ctrl+Return")])
        self.a_execute.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.a_execute.setToolTip("Execute (F5)")
        self.a_execute.triggered.connect(self.execute)
        self.addAction(self.a_execute)
        toolbar.addAction(self.a_execute)
        self.info = QLabel()
        self.info.setObjectName("muted")
        self.info.setContentsMargins(12, 0, 0, 0)
        toolbar.addWidget(self.info)

        self.editor = SqlEditor()
        self.editor.textChanged.connect(self._update_actions)
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
        splitter.setSizes([380, 200])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar)
        layout.addWidget(splitter)

        self._set_busy(True)
        run_async(self._open, on_done=self._opened, on_error=self._failed)

    # loading --------------------------------------------------------------
    def _open(self):
        conn = db.connect(self.cfg, self.database)
        if self.name is None:
            return conn, None, []
        definition = db.routine_definition(conn, self.database, self.name, self.rtype)
        return conn, definition, db.routine_params(conn, self.database, self.name, self.rtype)

    def _opened(self, result):
        self.conn, self.original, self.params = result
        self.editor.setPlainText(self.original or TEMPLATES[self.rtype])
        self._set_busy(False)
        self.editor.setFocus()

    def _failed(self, err):
        self._set_busy(False)
        self._log(f"Error: {html.escape(str(err))}", "#c62828")
        self.results.setCurrentIndex(0)
        self.status("Error")

    # saving -------------------------------------------------------------
    def is_modified(self):
        return self.original is None or self.editor.toPlainText().strip() != self.original.strip()

    def save(self):
        if self.busy or self.conn is None:
            return
        sql = self.editor.toPlainText().strip().rstrip(";").strip()
        parsed = parse_create(sql)
        if parsed is None:
            QMessageBox.warning(self, "Cannot save",
                                "The editor must contain a single CREATE FUNCTION or CREATE PROCEDURE statement.")
            return
        new_type, new_name = parsed
        old = (self.rtype, self.name, self.original)
        if old[1] is not None and (new_type, new_name) != (old[0], old[1]):
            target = f"{new_type.lower()} {new_name}"
            if QMessageBox.question(self, "Rename", f"The name or type changed. Save as {target} and drop the old "
                                    f"{old[0].lower()} {old[1]}?") != QMessageBox.StandardButton.Yes:
                return

        def apply():
            conn = self.conn
            restored = False
            if old[1] is not None:
                db.execute(conn, f"DROP {old[0]} IF EXISTS {q(self.database)}.{q(old[1])}")
            elif new_name:
                # Creating: refuse to silently replace an existing routine.
                if any(n == new_name and t == new_type for n, t in db.list_routines(conn, self.database)):
                    raise ValueError(f"A {new_type.lower()} named {new_name} already exists.")
            try:
                db.execute(conn, sql)
            except Exception as e:
                if old[2]:
                    try:
                        db.execute(conn, old[2])  # put the previous version back
                        restored = True
                    except Exception:  # noqa: BLE001
                        pass
                e.restored = restored
                raise
            definition = db.routine_definition(conn, self.database, new_name, new_type)
            return new_type, new_name, definition, db.routine_params(conn, self.database, new_name, new_type)

        self._set_busy(True)
        run_async(apply, on_done=self._saved, on_error=self._save_failed)

    def _saved(self, result):
        self.rtype, self.name, self.original, self.params = result
        self._set_busy(False)
        self._log(f"Saved {self.rtype.lower()} <b>{html.escape(self.name)}</b>.")
        self.status(f"Saved {self.rtype.lower()} {self.name}")
        if self.on_saved:
            self.on_saved(self)

    def _save_failed(self, err):
        self._set_busy(False)
        note = "<br>The previous version was restored." if getattr(err, "restored", False) else ""
        self._log(f"Save failed: {html.escape(str(err))}{note}", "#c62828")
        self.results.setCurrentIndex(0)
        QMessageBox.critical(self, "Save failed", str(err) + ("\n\nThe previous version was restored." if note else ""))

    # executing ------------------------------------------------------------
    def execute(self):
        if self.busy or self.conn is None:
            return
        if self.name is None or self.is_modified():
            QMessageBox.information(self, "Save first", "Save the changes before executing.")
            return
        values = []
        if self.params:
            dlg = ParamsDialog(self.name, self.params, self)
            if not dlg.exec():
                return
            values = dlg.values()
        # IN parameters take the value directly; OUT / INOUT go through session variables.
        args = [value if mode == "IN" else "@" + re.sub(r"\W", "_", pname)
                for (mode, pname, _), value in zip(self.params, values)]
        target = f"{q(self.database)}.{q(self.name)}"
        if self.rtype == "FUNCTION":
            statements = [f"SELECT {target}({', '.join(args)}) AS {q(self.name)}"]
        else:
            # INOUT parameters: load the given value into the session variable first.
            statements = []
            for (mode, _, _), arg, value in zip(self.params, args, values):
                if mode == "INOUT":
                    statements.append(f"SET {arg} = {value}")
            statements.append(f"CALL {target}({', '.join(args)})")
            outs = [a for (mode, _, _), a in zip(self.params, args) if mode in ("OUT", "INOUT")]
            if outs:
                statements.append("SELECT " + ", ".join(outs))

        def run():
            results = []
            for stmt in statements:
                results.extend(db.execute_all(self.conn, stmt))
            return results

        while self.results.count() > 1:
            self.results.removeTab(1)
        self._set_busy(True)
        run_async(run, on_done=self._executed, on_error=self._failed)

    def _executed(self, results):
        self._set_busy(False)
        grids = 0
        for rs in results:
            short = html.escape(" ".join(rs.statement.split())[:200])
            if rs.columns is not None:
                grids += 1
                view = ResultView()
                view.setModel(ResultModel(rs.columns, rs.rows, view, rs.types))
                view.fit_columns()
                self.results.addTab(view, f"Result {grids}")
                note = f"{rs.rowcount} row(s) returned"
            else:
                note = f"{rs.rowcount} row(s) affected"
            self._log(f"<b>{short}</b><br>{note} — {rs.elapsed * 1000:.1f} ms")
        self.results.setCurrentIndex(1 if grids else 0)
        self.status(f"Executed {self.name}")

    # state --------------------------------------------------------------
    def _set_busy(self, busy):
        self.busy = busy
        self._update_actions()

    def _update_actions(self):
        ready = not self.busy and self.conn is not None
        self.a_save.setEnabled(ready)
        self.a_execute.setEnabled(ready and self.name is not None)
        kind = "Function" if self.rtype == "FUNCTION" else "Procedure"
        state = " — not saved" if self.conn is not None and self.is_modified() else ""
        self.info.setText(f"{kind} · {self.database}{state}")

    def _log(self, text, color=None):
        style = f' style="color:{color}"' if color else ""
        self.messages.append(f"<div{style}>{text}</div><br>")

    def has_unsaved_changes(self):
        return self.conn is not None and self.original is not None and self.is_modified()

    def close_connection(self):
        if self.conn:
            try:
                self.conn.close()
            except Exception:  # noqa: BLE001
                pass
