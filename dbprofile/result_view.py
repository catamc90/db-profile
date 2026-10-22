"""Grid model and view for query results, with optional row editing."""
import csv
import datetime
import decimal

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtGui import QAction, QBrush, QColor, QFont, QKeySequence
from PyQt6.QtWidgets import QApplication, QFileDialog, QMenu, QMessageBox, QTableView

NULL_TEXT = "(NULL)"
NEW_ROW_COLOR = QColor(200, 255, 200, 90)
DELETED_ROW_COLOR = QColor(255, 180, 180, 110)
CHANGED_CELL_COLOR = QColor(255, 230, 150, 140)


def display_value(value) -> str:
    if value is None:
        return NULL_TEXT
    if isinstance(value, (bytes, bytearray)):
        return f"(BLOB {len(value)} bytes)"
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time, datetime.timedelta)):
        return str(value)
    if isinstance(value, decimal.Decimal):
        return format(value, "f")
    return str(value)


class ResultModel(QAbstractTableModel):
    def __init__(self, columns=None, rows=None, parent=None):
        super().__init__(parent)
        self.columns = list(columns or [])
        self.rows = [list(r) for r in rows or []]
        self._italic = QFont()
        self._italic.setItalic(True)

    def set_data(self, columns, rows):
        self.beginResetModel()
        self.columns = list(columns)
        self.rows = [list(r) for r in rows]
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def value(self, row, col):
        return self.rows[row][col]

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        value = self.value(index.row(), index.column())
        if role == Qt.ItemDataRole.DisplayRole:
            text = display_value(value)
            return text if len(text) <= 300 else text[:300] + "…"
        if role == Qt.ItemDataRole.EditRole:
            return "" if value is None else display_value(value)
        if role == Qt.ItemDataRole.ToolTipRole and isinstance(value, str) and len(value) > 80:
            return value[:2000]
        if value is None:
            if role == Qt.ItemDataRole.ForegroundRole:
                return QBrush(QColor(140, 140, 140))
            if role == Qt.ItemDataRole.FontRole:
                return self._italic
        if role == Qt.ItemDataRole.TextAlignmentRole and isinstance(value, (int, float, decimal.Decimal)):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self.columns[section] if section < len(self.columns) else None
        return str(section + 1)


class EditableResultModel(ResultModel):
    """Tracks edits, inserted rows and deleted rows until they are saved or discarded."""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.editable = False
        self.reset_changes()

    def set_data(self, columns, rows):
        super().set_data(columns, rows)
        self.reset_changes()

    def reset_changes(self):
        self.original = [list(r) for r in self.rows]
        self.new_rows: set[int] = set()
        self.deleted_rows: set[int] = set()
        self.changed: set[tuple[int, int]] = set()

    def has_changes(self):
        return bool(self.new_rows or self.deleted_rows or self.changed)

    def flags(self, index):
        f = super().flags(index)
        if self.editable and index.isValid() and index.row() not in self.deleted_rows:
            if not isinstance(self.value(index.row(), index.column()), (bytes, bytearray)):
                f |= Qt.ItemFlag.ItemIsEditable
        return f

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.BackgroundRole and index.isValid():
            r = index.row()
            if r in self.deleted_rows:
                return QBrush(DELETED_ROW_COLOR)
            if r in self.new_rows:
                return QBrush(NEW_ROW_COLOR)
            if (r, index.column()) in self.changed:
                return QBrush(CHANGED_CELL_COLOR)
        if role == Qt.ItemDataRole.FontRole and index.isValid() and index.row() in self.deleted_rows:
            font = QFont()
            font.setStrikeOut(True)
            return font
        return super().data(index, role)

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        if value == "" and self.rows[index.row()][index.column()] is None:
            return False  # editor opened on a NULL cell and left empty: keep NULL
        self.set_cell(index.row(), index.column(), value)
        return True

    def set_cell(self, row, col, value):
        if display_value(self.rows[row][col]) == display_value(value) and (self.rows[row][col] is None) == (value is None):
            return
        self.rows[row][col] = value
        if row not in self.new_rows:
            if display_value(self.original[row][col]) == display_value(value) and (self.original[row][col] is None) == (value is None):
                self.changed.discard((row, col))
            else:
                self.changed.add((row, col))
        idx = self.index(row, col)
        self.dataChanged.emit(idx, idx)

    def add_row(self):
        row = len(self.rows)
        self.beginInsertRows(QModelIndex(), row, row)
        self.rows.append([None] * len(self.columns))
        self.original.append([None] * len(self.columns))
        self.new_rows.add(row)
        self.endInsertRows()
        return row

    def toggle_delete(self, rows):
        """Mark existing rows for deletion (or unmark them); unsaved new rows are dropped."""
        for r in rows:
            if r in self.new_rows:
                continue
            if r in self.deleted_rows:
                self.deleted_rows.discard(r)
            else:
                self.deleted_rows.add(r)
        self.layoutChanged.emit()
        self.remove_new_rows(rows)

    def remove_new_rows(self, rows):
        for r in sorted((r for r in rows if r in self.new_rows), reverse=True):
            self.beginRemoveRows(QModelIndex(), r, r)
            del self.rows[r]
            del self.original[r]
            self.endRemoveRows()
            self.new_rows = {x - 1 if x > r else x for x in self.new_rows if x != r}
            self.deleted_rows = {x - 1 if x > r else x for x in self.deleted_rows}
            self.changed = {(x - 1 if x > r else x, c) for x, c in self.changed if x != r}


class ResultView(QTableView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableView.SelectionBehavior.SelectItems)
        self.setSortingEnabled(False)
        self.horizontalHeader().setDefaultSectionSize(140)
        self.verticalHeader().setDefaultSectionSize(24)
        self.verticalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.extra_actions: list[QAction] = []
        copy = QAction("Copy", self)
        copy.setShortcut(QKeySequence.StandardKey.Copy)
        copy.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        copy.triggered.connect(self.copy_selection)
        self.addAction(copy)
        self._copy_action = copy

    def fit_columns(self):
        self.resizeColumnsToContents()
        header = self.horizontalHeader()
        for i in range(header.count()):
            # +16 leaves room for the stylesheet's header padding and sort arrow
            header.resizeSection(i, max(60, min(header.sectionSize(i) + 16, 340)))

    def copy_selection(self):
        indexes = self.selectedIndexes()
        if not indexes:
            return
        rows = sorted({i.row() for i in indexes})
        cols = sorted({i.column() for i in indexes})
        selected = {(i.row(), i.column()) for i in indexes}
        model = self.model()
        lines = []
        for r in rows:
            cells = []
            for c in cols:
                v = model.value(r, c) if (r, c) in selected else ""
                cells.append("NULL" if v is None else display_value(v))
            lines.append("\t".join(cells))
        QApplication.clipboard().setText("\n".join(lines))

    def export_csv(self):
        model = self.model()
        if model is None or not model.columns:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export to CSV", "export.csv", "CSV files (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(model.columns)
                for r in range(model.rowCount()):
                    w.writerow(["" if v is None else display_value(v) for v in model.rows[r]])
        except OSError as e:
            QMessageBox.critical(self, "Export failed", str(e))

    def _context_menu(self, pos):
        menu = QMenu(self)
        menu.addAction(self._copy_action)
        for a in self.extra_actions:
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction("Export to CSV…", self.export_csv)
        menu.exec(self.viewport().mapToGlobal(pos))
