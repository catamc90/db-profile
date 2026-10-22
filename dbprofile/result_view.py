"""Grid model and view for query results, with optional row editing."""
import csv
import datetime
import decimal

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QPointF, QRect, QRectF, QSize, Qt
from PyQt6.QtGui import QAction, QBrush, QColor, QFont, QFontMetrics, QKeySequence, QPalette, QPen
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QHeaderView, QMenu, QMessageBox, QStyle, QStyledItemDelegate, QStyleOptionViewItem,
    QTableView,
)

from . import theme

NULL_TEXT = "(NULL)"
TYPE_ROLE = Qt.ItemDataRole.UserRole + 1  # headerData: the column's type name, e.g. "int"

# Navicat-style grid: white headers, the current row tinted, the current cell solid blue.
HEADER_BG = QColor("#ffffff")
HEADER_LINE = QColor("#e3e3e3")
CURRENT_TINT = QColor("#dcebfd")
SELECTED_CELL = QColor("#3d8af7")
TYPE_COLOR = QColor("#8a8a8a")
NUMBER_TYPES = {"tinyint", "smallint", "mediumint", "int", "bigint", "decimal", "float", "double", "year", "bit"}
DATE_TYPES = {"date", "time", "datetime", "timestamp"}
BINARY_TYPES = {"blob", "binary", "varbinary", "geometry"}
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
    def __init__(self, columns=None, rows=None, parent=None, types=None):
        super().__init__(parent)
        self.columns = list(columns or [])
        self.rows = [list(r) for r in rows or []]
        self.types = list(types) if types else []
        self._italic = QFont()
        self._italic.setItalic(True)

    def set_data(self, columns, rows, types=None):
        self.beginResetModel()
        self.columns = list(columns)
        self.rows = [list(r) for r in rows]
        self.types = list(types) if types else []
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
        if role == TYPE_ROLE and orientation == Qt.Orientation.Horizontal:
            return self.types[section] if section < len(self.types) else None
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

    def set_data(self, columns, rows, types=None):
        super().set_data(columns, rows, types)
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


def _draw_type_glyph(p, rect, type_name):
    """Small glyph before a column's type: # numbers, linked rings enum/set, calendar dates, T text..."""
    p.save()
    p.setRenderHint(p.RenderHint.Antialiasing)
    pen = QPen(TYPE_COLOR, 1.1)
    p.setPen(pen)
    x, y, s = rect.x(), rect.y(), rect.height()
    if type_name in ("enum", "set"):
        r = s * 0.2
        for cx in (x + s * 0.3, x + s * 0.7):
            p.drawEllipse(QPointF(cx, y + s * 0.5), r, r)
    elif type_name in DATE_TYPES:
        box = QRectF(x + s * 0.12, y + s * 0.2, s * 0.76, s * 0.68)
        p.drawRoundedRect(box, 1.2, 1.2)
        p.drawLine(QPointF(box.left(), box.top() + s * 0.22), QPointF(box.right(), box.top() + s * 0.22))
    else:
        glyph = "#" if type_name in NUMBER_TYPES else "{}" if type_name == "json" \
            else "01" if type_name in BINARY_TYPES else "T"
        font = QFont(p.font())
        font.setBold(glyph == "T")
        font.setPixelSize(max(8, round(s * (0.72 if len(glyph) > 1 else 0.9))))
        p.setFont(font)
        p.drawText(QRectF(x, y, s, s), Qt.AlignmentFlag.AlignCenter, glyph)
    p.restore()


class GridHeader(QHeaderView):
    """Column header with the column name and, below it, its type (like Navicat). The current column is tinted."""

    PAD = 8

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setObjectName("gridHeader")
        self.setSectionsClickable(True)
        self.setHighlightSections(False)

    def _type_font(self):
        font = QFont(self.font())
        font.setPointSizeF(max(7.0, font.pointSizeF() - 1))
        return font

    def _has_types(self):
        model = self.model()
        return bool(model is not None and getattr(model, "types", None))

    def sizeHint(self):
        hint = super().sizeHint()
        height = QFontMetrics(self.font()).height() + 14
        if self._has_types():
            height += QFontMetrics(self._type_font()).height() + 1
        return QSize(hint.width(), height)

    def sectionSizeFromContents(self, logical):
        model = self.model()
        name = str(model.headerData(logical, Qt.Orientation.Horizontal) or "") if model else ""
        type_name = model.headerData(logical, Qt.Orientation.Horizontal, TYPE_ROLE) if model else None
        width = QFontMetrics(self.font()).horizontalAdvance(name)
        if type_name:
            fm = QFontMetrics(self._type_font())
            width = max(width, fm.height() + 3 + fm.horizontalAdvance(type_name))
        return QSize(width + 2 * self.PAD, self.sizeHint().height())

    def paintSection(self, painter, rect, logical):
        model = self.model()
        if model is None:
            return
        view = self.parent()
        current = view.currentIndex() if isinstance(view, QTableView) else QModelIndex()
        is_current = current.isValid() and current.column() == logical
        painter.save()
        painter.fillRect(rect, CURRENT_TINT if is_current else HEADER_BG)
        painter.setPen(HEADER_LINE)
        painter.drawLine(rect.topRight(), rect.bottomRight())
        if is_current:
            painter.fillRect(QRect(rect.left(), rect.bottom() - 1, rect.width(), 2), QColor(theme.ACCENT))
        else:
            painter.drawLine(rect.bottomLeft(), rect.bottomRight())

        name = str(model.headerData(logical, Qt.Orientation.Horizontal) or "")
        type_name = model.headerData(logical, Qt.Orientation.Horizontal, TYPE_ROLE)
        inner = rect.adjusted(self.PAD, 0, -self.PAD, 0)
        fm = QFontMetrics(self.font())
        painter.setPen(QColor(theme.TEXT))
        painter.setFont(self.font())
        if type_name:
            tfont = self._type_font()
            tfm = QFontMetrics(tfont)
            top = rect.top() + (rect.height() - fm.height() - tfm.height() - 1) // 2
            painter.drawText(QRect(inner.left(), top, inner.width(), fm.height()),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             fm.elidedText(name, Qt.TextElideMode.ElideRight, inner.width()))
            line = QRect(inner.left(), top + fm.height() + 1, inner.width(), tfm.height())
            glyph = tfm.height()
            _draw_type_glyph(painter, QRect(line.left(), line.top(), glyph, glyph), type_name)
            painter.setFont(tfont)
            painter.setPen(TYPE_COLOR)
            text_rect = line.adjusted(glyph + 3, 0, 0, 0)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             tfm.elidedText(type_name, Qt.TextElideMode.ElideRight, text_rect.width()))
        else:
            painter.drawText(inner, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             fm.elidedText(name, Qt.TextElideMode.ElideRight, inner.width()))
        painter.restore()


class RowHeader(QHeaderView):
    """Narrow row header without numbers; the current row is tinted, unsaved new rows show a +."""

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Vertical, parent)
        self.setObjectName("rowHeader")
        self.setSectionsClickable(True)
        self.setHighlightSections(False)

    def sizeHint(self):
        return QSize(18, super().sizeHint().height())

    def paintSection(self, painter, rect, logical):
        view = self.parent()
        current = view.currentIndex() if isinstance(view, QTableView) else QModelIndex()
        model = self.model()
        painter.save()
        painter.fillRect(rect, CURRENT_TINT if current.isValid() and current.row() == logical else HEADER_BG)
        painter.setPen(HEADER_LINE)
        painter.drawLine(rect.topRight(), rect.bottomRight())
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        if logical in getattr(model, "new_rows", ()):
            painter.setPen(QColor(theme.ACCENT))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "+")
        painter.restore()


class GridDelegate(QStyledItemDelegate):
    """Paints the current row tinted and selected cells solid blue with white text."""

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        view = self.parent()
        current = view.currentIndex()
        # Like Navicat, the current cell is always shown solid blue, with or without a selection.
        selected = bool(opt.state & QStyle.StateFlag.State_Selected) or index == current
        background = index.data(Qt.ItemDataRole.BackgroundRole)  # unsaved edit / new / deleted rows
        if selected:
            painter.fillRect(opt.rect, SELECTED_CELL)
        elif background is not None:
            painter.fillRect(opt.rect, background)
        elif current.isValid() and current.row() == index.row():
            painter.fillRect(opt.rect, CURRENT_TINT)
        opt.state &= ~QStyle.StateFlag.State_Selected
        opt.state &= ~QStyle.StateFlag.State_HasFocus
        opt.backgroundBrush = QBrush()
        if selected:
            for role in (QPalette.ColorRole.Text, QPalette.ColorRole.HighlightedText):
                opt.palette.setColor(role, QColor("#ffffff"))
        widget = opt.widget
        (widget.style() if widget else QApplication.style()).drawControl(
            QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)


class ResultView(QTableView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalHeader(GridHeader(self))
        self.setVerticalHeader(RowHeader(self))
        self.setItemDelegate(GridDelegate(self))
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableView.SelectionBehavior.SelectItems)
        self.setSortingEnabled(False)
        self.horizontalHeader().setDefaultSectionSize(140)
        # Size columns from the visible rows plus a sample, not every row: measuring 1,000 rows takes ~0.3 s.
        self.horizontalHeader().setResizeContentsPrecision(100)
        self.verticalHeader().setDefaultSectionSize(26)
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.extra_actions: list[QAction] = []
        copy = QAction("Copy", self)
        copy.setShortcut(QKeySequence.StandardKey.Copy)
        copy.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        copy.triggered.connect(self.copy_selection)
        self.addAction(copy)
        self._copy_action = copy

    def currentChanged(self, current, previous):
        super().currentChanged(current, previous)
        # The whole current row and the current column's header are highlighted, not just the cell.
        self.viewport().update()
        self.horizontalHeader().viewport().update()
        self.verticalHeader().viewport().update()

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
