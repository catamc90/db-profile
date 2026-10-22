"""Navicat-style Import / Export wizards, plus SQL dump / execute-file dialogs."""
import os
import time

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QRadioButton, QSpinBox, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
    QWizard, QWizardPage,
)

from . import db, icons, transfer
from .result_view import ResultModel, ResultView

DELIMITERS = [("Comma ( , )", ","), ("Tab", "\t"), ("Semicolon ( ; )", ";"), ("Pipe ( | )", "|"), ("Space", " ")]
QUOTES = [('Double quote ( " )', '"'), ("Single quote ( ' )", "'"), ("None", "")]
ENCODINGS = [("UTF-8", "utf-8"), ("UTF-8 with BOM", "utf-8-sig"), ("Latin-1 (ISO-8859-1)", "latin-1"),
             ("Windows-1252", "cp1252"), ("UTF-16", "utf-16")]
LINE_ENDINGS = [("CRLF (Windows)", "\r\n"), ("LF (Linux / macOS)", "\n")]


def _combo(items, current=None):
    box = QComboBox()
    for label, value in items:
        box.addItem(label, value)
    if current is not None:
        idx = box.findData(current)
        box.setCurrentIndex(max(idx, 0))
    return box


def _hint(text):
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


# --- background task + progress panel -------------------------------------------------
class Task(QThread):
    progress = pyqtSignal(int, int, str)
    message = pyqtSignal(str)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            result = self.fn(self._progress, self.message.emit, lambda: self._cancel)
        except transfer.Cancelled:
            self.failed.emit("Cancelled by user")
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))
        else:
            self.done.emit(result)

    def _progress(self, done, total, text):
        self.progress.emit(min(int(done), 2**31 - 1), min(int(total or 0), 2**31 - 1), text)


class RunPanel(QWidget):
    """Progress bar + log, like the last page of Navicat's wizards."""

    finished = pyqtSignal(bool, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.task = None
        self.started_at = 0.0
        self.status = QLabel("Click Start to begin.")
        self.bar = QProgressBar()
        self.bar.setTextVisible(True)
        self.bar.setValue(0)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.log_view.setStyleSheet("QPlainTextEdit { border: 1px solid #dcdcdc; }")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.status)
        layout.addWidget(self.bar)
        layout.addWidget(self.log_view, 1)

    @property
    def running(self):
        return self.task is not None and self.task.isRunning()

    def start(self, fn):
        self.log_view.clear()
        self.bar.setRange(0, 0)  # busy until the first progress report
        self.started_at = time.perf_counter()
        self.log("[MSG] Started")
        self.task = Task(fn, self)
        self.task.progress.connect(self._progress)
        self.task.message.connect(self.log)
        self.task.done.connect(self._done)
        self.task.failed.connect(self._failed)
        self.task.start()

    def cancel(self):
        if self.running:
            self.task.cancel()
            self.task.wait(10000)

    def log(self, text):
        self.log_view.appendPlainText(text)

    def _progress(self, done, total, text):
        if total > 0:
            self.bar.setRange(0, total)
            self.bar.setValue(min(done, total))
        self.status.setText(text)

    def _elapsed(self):
        return f"{time.perf_counter() - self.started_at:.2f}s"

    def _done(self, result):
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.log(f"[MSG] Finished successfully — {self._elapsed()}")
        self.status.setText("Finished successfully")
        self.finished.emit(True, result)

    def _failed(self, error):
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.log(f"[ERR] {error}")
        self.log(f"[MSG] Finished with errors — {self._elapsed()}")
        self.status.setText("Finished with errors")
        self.finished.emit(False, error)


class RunPage(QWizardPage):
    def __init__(self, title, start_text="Start"):
        super().__init__()
        self.setTitle(title)
        self.setSubTitle("Click Start to run. You can watch the progress and messages below.")
        self.panel = RunPanel()
        self.start_btn = QPushButton(start_text)
        self.start_btn.setDefault(True)
        self.start_btn.clicked.connect(self._start)
        self.panel.finished.connect(self._finished)
        self.complete = False
        self.on_start = None  # callable returning the task function
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.start_btn)
        layout = QVBoxLayout(self)
        layout.addWidget(self.panel, 1)
        layout.addLayout(row)

    def initializePage(self):
        self.complete = False
        self.start_btn.setEnabled(True)
        self.panel.status.setText("Click Start to begin.")
        self.panel.bar.setRange(0, 1)
        self.panel.bar.setValue(0)

    def _start(self):
        fn = self.on_start()
        if fn is None:
            return
        self.start_btn.setEnabled(False)
        self.wizard().button(QWizard.WizardButton.BackButton).setEnabled(False)
        self.panel.start(fn)

    def _finished(self, ok, _result):
        self.complete = True
        self.start_btn.setEnabled(True)
        self.start_btn.setText("Start Again")
        self.wizard().button(QWizard.WizardButton.BackButton).setEnabled(True)
        self.completeChanged.emit()

    def isComplete(self):
        return self.complete


class _Wizard(QWizard):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWizardStyle(QWizard.WizardStyle.ClassicStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnLastPage, False)
        self.setOption(QWizard.WizardOption.HaveHelpButton, False)
        self.resize(820, 600)

    def reject(self):
        run = self.currentPage()
        if isinstance(run, RunPage) and run.panel.running:
            if QMessageBox.question(self, "Cancel", "Stop the running task?") != QMessageBox.StandardButton.Yes:
                return
            run.panel.cancel()
        super().reject()


class FormatPage(QWizardPage):
    def __init__(self, title, formats, subtitle):
        super().__init__()
        self.setTitle(title)
        self.setSubTitle(subtitle)
        self.group = QButtonGroup(self)
        layout = QVBoxLayout(self)
        for i, (key, label) in enumerate(formats.items()):
            radio = QRadioButton(label)
            radio.setProperty("fmt", key)
            radio.setChecked(i == 0)
            self.group.addButton(radio)
            layout.addWidget(radio)
        layout.addStretch(1)

    def fmt(self):
        return self.group.checkedButton().property("fmt")


# --- Export wizard -----------------------------------------------------------------
class ExportObjectsPage(QWizardPage):
    def __init__(self, wizard_):
        super().__init__()
        self.wz = wizard_
        self.setTitle("Select objects and output files")
        self.setSubTitle("Choose the tables to export and where to save them.")
        self.folder = QLineEdit(os.path.expanduser("~"))
        browse = QPushButton("Browse…")
        browse.setAutoDefault(False)
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(QLabel("Output folder:"))
        row.addWidget(self.folder, 1)
        row.addWidget(browse)
        self.folder.textChanged.connect(self._refresh_paths)

        self.list = QTreeWidget()
        self.list.setHeaderLabels(["Source", "Output file"])
        self.list.setRootIsDecorated(False)
        self.list.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.list.itemChanged.connect(lambda *_: self.completeChanged.emit())
        buttons = QHBoxLayout()
        for text, state in (("Select All", Qt.CheckState.Checked), ("Deselect All", Qt.CheckState.Unchecked)):
            b = QPushButton(text)
            b.setAutoDefault(False)
            b.clicked.connect(lambda _, s=state: self._check_all(s))
            buttons.addWidget(b)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(self.list, 1)
        layout.addLayout(buttons)
        self._filled = False

    def initializePage(self):
        if self.wz.result is not None:
            self.list.hide()
        if not self._filled and self.wz.result is None:
            for name, ttype in self.wz.objects:
                it = QTreeWidgetItem([name, ""])
                it.setIcon(0, icons.icon("view" if ttype == "VIEW" else "table"))
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(0, Qt.CheckState.Checked if name in self.wz.preselect or not self.wz.preselect
                                 else Qt.CheckState.Unchecked)
                self.list.addTopLevelItem(it)
            self._filled = True
        self._refresh_paths()

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, "Output folder", self.folder.text())
        if path:
            self.folder.setText(path)

    def _check_all(self, state):
        for i in range(self.list.topLevelItemCount()):
            self.list.topLevelItem(i).setCheckState(0, state)

    def _refresh_paths(self):
        fmt = self.wz.fmt()
        for i in range(self.list.topLevelItemCount()):
            it = self.list.topLevelItem(i)
            it.setText(1, transfer.default_path(self.folder.text(), it.text(0), fmt))

    def selected(self):
        return [(self.list.topLevelItem(i).text(0), self.list.topLevelItem(i).text(1))
                for i in range(self.list.topLevelItemCount())
                if self.list.topLevelItem(i).checkState(0) == Qt.CheckState.Checked]

    def isComplete(self):
        return bool(self.folder.text().strip()) and (self.wz.result is not None or bool(self.selected()))

    def validatePage(self):
        folder = self.folder.text().strip()
        if not os.path.isdir(folder):
            QMessageBox.warning(self, "Export", f"The folder does not exist:\n{folder}")
            return False
        return True


class ExportOptionsPage(QWizardPage):
    def __init__(self, wizard_):
        super().__init__()
        self.wz = wizard_
        self.setTitle("Additional options")
        self.setSubTitle("Set the format options for the output files.")
        self.header = QCheckBox("Include column titles")
        self.delimiter = _combo(DELIMITERS)
        self.quote = _combo(QUOTES)
        self.line_ending = _combo(LINE_ENDINGS)
        self.encoding = _combo(ENCODINGS)
        self.null_text = QLineEdit()
        self.null_text.setPlaceholderText("empty")
        self.pretty = QCheckBox("Pretty print (indented)")
        self.create = QCheckBox("Include CREATE TABLE statements")
        self.drop = QCheckBox("Add DROP TABLE IF EXISTS before CREATE")
        self.rows_per_insert = QSpinBox()
        self.rows_per_insert.setRange(1, 10000)
        self.form = QFormLayout(self)
        self.rows = []
        for label, widget in (("", self.header), ("Field delimiter:", self.delimiter),
                              ("Text qualifier:", self.quote), ("Record delimiter:", self.line_ending),
                              ("Encoding:", self.encoding), ("NULL written as:", self.null_text),
                              ("", self.pretty), ("", self.create), ("", self.drop),
                              ("Records per INSERT:", self.rows_per_insert)):
            self.form.addRow(label, widget)
            self.rows.append(widget)

    def initializePage(self):
        fmt = self.wz.fmt()
        opts = transfer.default_export_options(fmt)
        visible = {
            "csv": [self.header, self.delimiter, self.quote, self.line_ending, self.encoding, self.null_text],
            "txt": [self.header, self.delimiter, self.quote, self.line_ending, self.encoding, self.null_text],
            "json": [self.pretty],
            "xml": [],
            "html": [],
            "xlsx": [self.header],
            "sql": [self.create, self.drop, self.rows_per_insert],
        }[fmt]
        if self.wz.result is not None and fmt == "sql":
            visible = [self.rows_per_insert]
        for w in self.rows:
            self.form.setRowVisible(w, w in visible)
        self.header.setChecked(opts.get("header", True))
        self.delimiter.setCurrentIndex(max(0, self.delimiter.findData(opts.get("delimiter", ","))))
        self.quote.setCurrentIndex(max(0, self.quote.findData(opts.get("quote", '"'))))
        self.line_ending.setCurrentIndex(max(0, self.line_ending.findData(opts.get("line_ending", "\r\n"))))
        self.encoding.setCurrentIndex(0)
        self.pretty.setChecked(opts.get("pretty", True))
        self.create.setChecked(opts.get("create", True))
        self.drop.setChecked(opts.get("drop", True))
        self.rows_per_insert.setValue(opts.get("rows_per_insert", 100))
        if not visible:
            self.setSubTitle("This format has no additional options.")

    def options(self):
        return {
            "header": self.header.isChecked(), "delimiter": self.delimiter.currentData(),
            "quote": self.quote.currentData(), "line_ending": self.line_ending.currentData(),
            "encoding": self.encoding.currentData(), "null_text": self.null_text.text(),
            "pretty": self.pretty.isChecked(), "create": self.create.isChecked(), "drop": self.drop.isChecked(),
            "rows_per_insert": self.rows_per_insert.value(),
        }


class ExportWizard(_Wizard):
    """Export tables (or one in-memory result set) to CSV, TXT, JSON, XML, HTML, Excel or SQL."""

    def __init__(self, cfg, database=None, objects=(), preselect=(), result=None, parent=None):
        super().__init__("Export Wizard", parent)
        self.cfg, self.database = cfg, database
        self.objects = list(objects)  # [(name, type)]
        self.preselect = set(preselect)
        self.result = result  # (columns, rows, name) for exporting a query result
        self.format_page = FormatPage("Export format", {k: v[0] for k, v in transfer.EXPORT_FORMATS.items()},
                                      "Choose the format of the exported files.")
        self.objects_page = ExportObjectsPage(self)
        self.options_page = ExportOptionsPage(self)
        self.run_page = RunPage("Export")
        self.run_page.on_start = self._task
        for page in (self.format_page, self.objects_page, self.options_page, self.run_page):
            self.addPage(page)

    def fmt(self):
        return self.format_page.fmt()

    def _task(self):
        fmt, options = self.fmt(), self.options_page.options()
        folder = self.objects_page.folder.text().strip()
        cfg, database = self.cfg, self.database
        if self.result is not None:
            columns, rows, name = self.result
            path = transfer.default_path(folder, name, fmt)
            if os.path.exists(path) and not self._confirm_overwrite([path]):
                return None

            def run(progress, log, cancelled):
                conn = db.connect(cfg) if fmt == "sql" else None
                try:
                    n = transfer.export_rows(columns, rows, fmt, path, dict(options, target_table=name), name, conn)
                finally:
                    if conn:
                        conn.close()
                log(f"[MSG] {name}: {n:,} rows → {path}")
                return n
            return run

        targets = self.objects_page.selected()
        existing = [p for _, p in targets if os.path.exists(p)]
        if existing and not self._confirm_overwrite(existing):
            return None

        def run(progress, log, cancelled):
            conn = db.connect(cfg, database)
            try:
                total = 0
                for i, (table, path) in enumerate(targets, 1):
                    log(f"[EXP] {table} → {path}")
                    n = transfer.export_table(conn, database, table, fmt, path, options,
                                              lambda d, t, m: progress(d, t, f"({i}/{len(targets)}) {m}"),
                                              cancelled)
                    log(f"[MSG] {table}: {n:,} rows exported")
                    total += n
                return total
            finally:
                conn.close()
        return run

    def _confirm_overwrite(self, paths):
        names = "\n".join(paths[:10]) + ("\n…" if len(paths) > 10 else "")
        return QMessageBox.question(self, "Overwrite files", f"These files already exist and will be replaced:\n\n"
                                    f"{names}") == QMessageBox.StandardButton.Yes


# --- Import wizard -----------------------------------------------------------------
class ImportSourcePage(QWizardPage):
    def __init__(self, wizard_):
        super().__init__()
        self.wz = wizard_
        self.setTitle("Source file")
        self.setSubTitle("Choose the file to import and how to read it. The preview shows the first records.")
        self.path = QLineEdit()
        self.path.textChanged.connect(self._schedule_preview)
        browse = QPushButton("Browse…")
        browse.setAutoDefault(False)
        browse.clicked.connect(self._browse)
        self.delimiter = _combo(DELIMITERS)
        self.quote = _combo(QUOTES)
        self.encoding = _combo(ENCODINGS, "utf-8-sig")
        self.encoding.setItemText(self.encoding.findData("utf-8-sig"), "UTF-8 (auto-detect BOM)")
        self.encoding.removeItem(self.encoding.findData("utf-8"))
        self.sheet = QComboBox()
        self.header = QCheckBox("First row contains field names")
        self.header.setChecked(True)
        self.skip = QSpinBox()
        self.skip.setRange(0, 1000000)
        for w in (self.delimiter, self.quote, self.encoding, self.sheet):
            w.currentIndexChanged.connect(self._schedule_preview)
        self.header.toggled.connect(self._schedule_preview)
        self.skip.valueChanged.connect(self._schedule_preview)

        file_row = QHBoxLayout()
        file_row.addWidget(self.path, 1)
        file_row.addWidget(browse)
        grid = QGridLayout()
        self.option_widgets = {}
        cells = [("Field delimiter:", self.delimiter), ("Text qualifier:", self.quote), ("Encoding:", self.encoding),
                 ("Sheet:", self.sheet), ("Skip lines:", self.skip)]
        for i, (label, widget) in enumerate(cells):
            lab = QLabel(label)
            grid.addWidget(lab, i // 2, (i % 2) * 2)
            grid.addWidget(widget, i // 2, (i % 2) * 2 + 1)
            self.option_widgets[widget] = lab
        grid.addWidget(self.header, 3, 0, 1, 4)
        self.preview_view = ResultView()
        self.preview_view.setModel(ResultModel(parent=self.preview_view))
        self.error = QLabel()
        self.error.setStyleSheet("color: #c62828")
        self.error.setWordWrap(True)
        form = QFormLayout()
        form.addRow("Import from:", file_row)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(grid)
        layout.addWidget(self.error)
        layout.addWidget(self.preview_view, 1)
        self.columns = []
        self.sample = []

    def initializePage(self):
        fmt = self.wz.fmt()
        delimited = fmt in ("csv", "txt")
        for w in (self.delimiter, self.quote, self.encoding):
            w.setVisible(delimited)
            self.option_widgets[w].setVisible(delimited)
        self.sheet.setVisible(fmt == "xlsx")
        self.option_widgets[self.sheet].setVisible(fmt == "xlsx")
        self.skip.setVisible(fmt != "json")
        self.option_widgets[self.skip].setVisible(fmt != "json")
        self.header.setVisible(fmt != "json")
        if fmt == "txt":
            self.delimiter.setCurrentIndex(self.delimiter.findData("\t"))
        elif fmt == "csv":
            self.delimiter.setCurrentIndex(self.delimiter.findData(","))
        if self.path.text() and not self.path.text().lower().endswith("." + fmt):
            self.path.clear()
        self._preview()

    def _browse(self):
        fmt = self.wz.fmt()
        path, _ = QFileDialog.getOpenFileName(self, "Import from", os.path.expanduser("~"),
                                              f"{transfer.IMPORT_FORMATS[fmt]};;All files (*)")
        if path:
            self.path.setText(path)

    def options(self):
        return {"delimiter": self.delimiter.currentData(), "quote": self.quote.currentData(),
                "encoding": self.encoding.currentData(), "header": self.header.isChecked(),
                "skip": self.skip.value(), "sheet": self.sheet.currentText() or None}

    def _schedule_preview(self, *_):
        self._preview()

    def _preview(self):
        self.columns, self.sample = [], []
        path = self.path.text().strip()
        model = self.preview_view.model()
        model.set_data([], [])
        self.error.clear()
        if not path:
            self.completeChanged.emit()
            return
        if not os.path.isfile(path):
            self.error.setText("File not found.")
            self.completeChanged.emit()
            return
        fmt = self.wz.fmt()
        try:
            if fmt == "xlsx" and self.sheet.count() == 0:
                self.sheet.blockSignals(True)
                self.sheet.addItems(transfer.xlsx_sheets(path))
                self.sheet.blockSignals(False)
            self.columns, self.sample = transfer.preview(fmt, path, self.options(), limit=1000)
        except Exception as e:  # noqa: BLE001
            self.error.setText(f"Cannot read the file: {e}")
        else:
            width = len(self.columns)
            model.set_data(self.columns, [(r + [None] * width)[:width] for r in self.sample[:50]])
            self.preview_view.fit_columns()
        self.completeChanged.emit()

    def isComplete(self):
        return bool(self.columns)


class ImportTargetPage(QWizardPage):
    def __init__(self, wizard_):
        super().__init__()
        self.wz = wizard_
        self.setTitle("Target table")
        self.setSubTitle("Import into an existing table or create a new one.")
        self.existing = QRadioButton("Existing table:")
        self.new = QRadioButton("New table:")
        self.table = QComboBox()
        self.new_name = QLineEdit()
        self.existing.toggled.connect(self._toggle)
        self.new_name.textChanged.connect(lambda *_: self.completeChanged.emit())
        grid = QGridLayout(self)
        grid.addWidget(self.existing, 0, 0)
        grid.addWidget(self.table, 0, 1)
        grid.addWidget(self.new, 1, 0)
        grid.addWidget(self.new_name, 1, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(2, 1)

    def initializePage(self):
        if self.table.count() == 0:
            for name, ttype in self.wz.tables:
                if ttype != "VIEW":
                    self.table.addItem(icons.icon("table"), name)
        base = os.path.splitext(os.path.basename(self.wz.source_page.path.text()))[0]
        if not self.new_name.text():
            self.new_name.setText("".join(ch if ch.isalnum() or ch == "_" else "_" for ch in base) or "imported")
        if self.wz.preselect and self.table.findText(self.wz.preselect) >= 0:
            self.table.setCurrentText(self.wz.preselect)
            self.existing.setChecked(True)
        elif self.table.findText(self.new_name.text()) >= 0:
            self.table.setCurrentText(self.new_name.text())
            self.existing.setChecked(True)
        else:
            self.new.setChecked(True)
        self.existing.setEnabled(self.table.count() > 0)
        self._toggle()

    def _toggle(self, *_):
        self.table.setEnabled(self.existing.isChecked())
        self.new_name.setEnabled(self.new.isChecked())
        self.completeChanged.emit()

    def is_new(self):
        return self.new.isChecked()

    def target(self):
        return self.new_name.text().strip() if self.is_new() else self.table.currentText()

    def isComplete(self):
        return bool(self.target())

    def validatePage(self):
        if self.is_new() and self.table.findText(self.target()) >= 0:
            QMessageBox.warning(self, "Import", f"A table named {self.target()} already exists. "
                                "Choose Existing table to import into it.")
            return False
        return True


SKIP = "(skip)"


class ImportMappingPage(QWizardPage):
    def __init__(self, wizard_):
        super().__init__()
        self.wz = wizard_
        self.setTitle("Field mapping")
        self.grid = QTableWidget(0, 4)
        self.grid.setHorizontalHeaderLabels(["Source Field", "Target Field", "Type", "Primary Key"])
        self.grid.verticalHeader().hide()
        self.grid.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.grid.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.grid.setColumnWidth(3, 100)
        layout = QVBoxLayout(self)
        layout.addWidget(self.grid)
        self.table_columns = []
        self.table_pk = []
        self._key = None

    def initializePage(self):
        key = (self.wz.target_page.target(), self.wz.target_page.is_new(), tuple(self.wz.source_page.columns))
        if key == self._key:
            return
        self._key = key
        new = self.wz.target_page.is_new()
        self.setSubTitle("Name the new table's fields and choose their types." if new else
                         "Match each source field to a column of the target table, or skip it.")
        source = self.wz.source_page.columns
        if not new:
            conn = db.connect(self.wz.cfg, self.wz.database)
            try:
                rs = db.execute(conn, f"SHOW COLUMNS FROM {db.quote_ident(self.wz.target_page.target())}")
                self.table_columns = [r[0] for r in rs.rows]
                types = {r[0]: r[1] for r in rs.rows}
                self.table_pk = db.primary_key(conn, self.wz.database, self.wz.target_page.target())
            finally:
                conn.close()
        else:
            self.table_columns, self.table_pk = [], []
            sample = self.wz.source_page.sample
            types = {}
        self.grid.setRowCount(0)
        lower = {c.lower(): c for c in self.table_columns}
        for i, src in enumerate(source):
            self.grid.insertRow(i)
            item = QTableWidgetItem(src)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.grid.setItem(i, 0, item)
            target = QComboBox()
            pk_box = QCheckBox()
            type_item = QComboBox()
            if new:
                target.setEditable(True)
                target.addItem(src)
                type_item.setEditable(True)
                guess = transfer.infer_type([row[i] if i < len(row) else None for row in sample])
                for t in dict.fromkeys([guess, "INT", "BIGINT", "DECIMAL(12,2)", "DOUBLE", "VARCHAR(255)", "TEXT",
                                        "DATE", "DATETIME", "TINYINT(1)", "JSON"]):
                    type_item.addItem(t)
            else:
                target.addItem(SKIP)
                target.addItems(self.table_columns)
                match = lower.get(src.lower())
                if match is None and i < len(self.table_columns) and not any(
                        s.lower() in lower for s in source):
                    match = self.table_columns[i]  # no names match: map by position
                target.setCurrentText(match or SKIP)
                type_item.setEnabled(False)
                pk_box.setEnabled(False)
                target.currentTextChanged.connect(
                    lambda t, combo=type_item, box=pk_box: self._show_target(t, combo, box, types))
                self._show_target(target.currentText(), type_item, pk_box, types)
            self.grid.setCellWidget(i, 1, target)
            self.grid.setCellWidget(i, 2, type_item)
            holder = QWidget()
            row = QHBoxLayout(holder)
            row.setContentsMargins(0, 0, 0, 0)
            row.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(pk_box)
            self.grid.setCellWidget(i, 3, holder)

    def _show_target(self, column, type_combo, pk_box, types):
        """Existing table: show the chosen column's type and whether it is part of the primary key."""
        type_combo.clear()
        type_combo.addItem(types.get(column, ""))
        pk_box.setChecked(column in self.table_pk)

    def mapping(self):
        """[(source index, target column, type, is_key)] for mapped fields."""
        out = []
        for i in range(self.grid.rowCount()):
            target = self.grid.cellWidget(i, 1).currentText().strip()
            if not target or target == SKIP:
                continue
            type_ = self.grid.cellWidget(i, 2).currentText().strip()
            key = self.grid.cellWidget(i, 3).findChild(QCheckBox).isChecked()
            out.append((i, target, type_, key))
        return out

    def validatePage(self):
        mapping = self.mapping()
        if not mapping:
            QMessageBox.warning(self, "Import", "Map at least one field.")
            return False
        targets = [t for _, t, _, _ in mapping]
        dupes = {t for t in targets if targets.count(t) > 1}
        if dupes:
            QMessageBox.warning(self, "Import", "Each target field can be used once: " + ", ".join(sorted(dupes)))
            return False
        return True


class ImportModePage(QWizardPage):
    def __init__(self, wizard_):
        super().__init__()
        self.wz = wizard_
        self.setTitle("Import mode")
        self.setSubTitle("Choose how the source records are written to the target table.")
        self.group = QButtonGroup(self)
        layout = QVBoxLayout(self)
        self.radios = {}
        for i, (key, label) in enumerate(transfer.IMPORT_MODES.items()):
            radio = QRadioButton(label)
            radio.setProperty("mode", key)
            radio.setChecked(i == 0)
            self.group.addButton(radio)
            self.radios[key] = radio
            layout.addWidget(radio)
        self.key_note = _hint("")
        layout.addWidget(self.key_note)
        layout.addSpacing(10)
        self.empty_null = QCheckBox("Import empty values as NULL")
        self.empty_null.setChecked(True)
        self.continue_on_error = QCheckBox("Continue on error (skip bad records)")
        self.transaction = QCheckBox("Use a transaction (roll everything back on error)")
        self.transaction.setChecked(True)
        self.continue_on_error.toggled.connect(lambda on: on and self.transaction.setChecked(False))
        self.transaction.toggled.connect(lambda on: on and self.continue_on_error.setChecked(False))
        for w in (self.empty_null, self.continue_on_error, self.transaction):
            layout.addWidget(w)
        layout.addStretch(1)

    def initializePage(self):
        new = self.wz.target_page.is_new()
        keys = [t for _, t, _, k in self.wz.mapping_page.mapping() if k]
        for key in ("update", "append_update", "delete"):
            self.radios[key].setEnabled(not new and bool(keys))
        self.radios["copy"].setEnabled(not new)
        if not self.group.checkedButton().isEnabled():
            self.radios["append"].setChecked(True)
        if new:
            self.key_note.setText("A new table is created, so records are appended.")
        elif keys:
            self.key_note.setText("Records are matched on the primary key: " + ", ".join(keys))
        else:
            self.key_note.setText("Update and Delete need the table's primary key to be mapped.")

    def mode(self):
        return self.group.checkedButton().property("mode")


class ImportWizard(_Wizard):
    def __init__(self, cfg, database, tables, preselect=None, on_finished=None, parent=None):
        super().__init__("Import Wizard", parent)
        self.cfg, self.database = cfg, database
        self.tables = list(tables)  # [(name, type)]
        self.preselect = preselect
        self.on_finished = on_finished
        self.format_page = FormatPage("Import format", transfer.IMPORT_FORMATS,
                                      "Choose the format of the file to import.")
        self.source_page = ImportSourcePage(self)
        self.target_page = ImportTargetPage(self)
        self.mapping_page = ImportMappingPage(self)
        self.mode_page = ImportModePage(self)
        self.run_page = RunPage("Import")
        self.run_page.on_start = self._task
        self.run_page.panel.finished.connect(self._finished)
        for page in (self.format_page, self.source_page, self.target_page, self.mapping_page, self.mode_page,
                     self.run_page):
            self.addPage(page)

    def fmt(self):
        return self.format_page.fmt()

    def _task(self):
        fmt = self.fmt()
        path, options = self.source_page.path.text().strip(), self.source_page.options()
        table, new = self.target_page.target(), self.target_page.is_new()
        mapping = self.mapping_page.mapping()
        mode = self.mode_page.mode()
        empty_null = self.mode_page.empty_null.isChecked()
        cont = self.mode_page.continue_on_error.isChecked()
        use_tx = self.mode_page.transaction.isChecked()
        cfg, database = self.cfg, self.database

        def run(progress, log, cancelled):
            conn = db.connect(cfg, database)
            try:
                if new:
                    keys = [t for _, t, _, k in mapping if k]
                    sql = transfer.create_table_sql(database, table, [t for _, t, _, _ in mapping],
                                                    [ty or "TEXT" for _, _, ty, _ in mapping], keys)
                    log(f"[MSG] Creating table {table}")
                    db.execute(conn, sql)
                    key_columns = keys
                else:
                    key_columns = db.primary_key(conn, database, table)
                _, rows = transfer.read_source(fmt, path, options)
                processed, errors = transfer.import_rows(
                    conn, database, table, [(i, t) for i, t, _, _ in mapping], rows, mode, key_columns,
                    empty_null, cont, use_tx, progress, cancelled, log)
                log(f"[MSG] Processed: {processed:,}, Errors: {errors:,}")
                if errors and not cont:
                    raise RuntimeError(f"{errors} errors")
                return processed, errors
            finally:
                conn.close()
        return run

    def _finished(self, ok, _result):
        if self.on_finished:
            self.on_finished()


# --- simple dialogs: dump database / execute SQL file ----------------------------------------
class TaskDialog(QDialog):
    def __init__(self, title, fn, on_finished=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640, 420)
        self.panel = RunPanel()
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.buttons.rejected.connect(self.reject)
        self.close_btn = self.buttons.button(QDialogButtonBox.StandardButton.Close)
        self.close_btn.setText("Cancel")
        self.on_finished = on_finished
        layout = QVBoxLayout(self)
        layout.addWidget(self.panel, 1)
        layout.addWidget(self.buttons)
        self.panel.finished.connect(self._finished)
        self.panel.start(fn)

    def _finished(self, ok, result):
        self.close_btn.setText("Close")
        if self.on_finished:
            self.on_finished()

    def reject(self):
        if self.panel.running:
            self.panel.cancel()
        super().reject()


def dump_sql_file(parent, cfg, database, with_data=True):
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path, _ = QFileDialog.getSaveFileName(parent, "Dump SQL File", os.path.expanduser(f"~/{database}_{stamp}.sql"),
                                          "SQL files (*.sql)")
    if not path:
        return

    def run(progress, log, cancelled):
        conn = db.connect(cfg, database)
        try:
            log(f"[MSG] Dumping {database} {'(structure and data)' if with_data else '(structure only)'} → {path}")
            return transfer.dump_database(conn, database, path, with_data, progress, cancelled)
        finally:
            conn.close()
    TaskDialog(f"Dump SQL File — {database}", run, parent=parent).exec()


def execute_sql_file(parent, cfg, database=None, on_finished=None):
    path, _ = QFileDialog.getOpenFileName(parent, "Execute SQL File", os.path.expanduser("~"),
                                          "SQL files (*.sql);;All files (*)")
    if not path:
        return
    box = QMessageBox(QMessageBox.Icon.Question, "Execute SQL File",
                      f"Run all statements in\n{path}\n\non {cfg.name}{' / ' + database if database else ''}?",
                      parent=parent)
    stop = box.addButton("Run, stop on error", QMessageBox.ButtonRole.AcceptRole)
    cont_btn = box.addButton("Run, continue on error", QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(stop)
    box.exec()
    if box.clickedButton() not in (stop, cont_btn):
        return
    cont = box.clickedButton() is cont_btn

    def run(progress, log, cancelled):
        conn = db.connect(cfg, database)
        try:
            ok, errors = transfer.execute_sql_file(conn, path, cont, progress, cancelled, log)
            log(f"[MSG] {ok:,} statements executed, {errors:,} errors")
            return ok, errors
        finally:
            conn.close()
    TaskDialog("Execute SQL File", run, on_finished, parent).exec()

