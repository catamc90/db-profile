"""Plain-text SQL editor with line numbers and syntax highlighting."""
import re

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPainter, QSyntaxHighlighter, QTextCharFormat
from PyQt6.QtWidgets import QPlainTextEdit, QWidget

KEYWORDS = """
ADD ALL ALTER AND AS ASC AUTO_INCREMENT BETWEEN BY CASE CHANGE CHECK COLUMN CONSTRAINT CREATE
CROSS DATABASE DATABASES DEFAULT DELETE DESC DESCRIBE DISTINCT DROP ELSE END ENGINE EXISTS EXPLAIN
FOREIGN FROM FULL GRANT GROUP HAVING IF IN INDEX INNER INSERT INTO IS JOIN KEY KEYS LEFT LIKE LIMIT
MODIFY NOT NULL OFFSET ON OR ORDER OUTER PRIMARY PROCEDURE REFERENCES RENAME REPLACE REVOKE RIGHT
SELECT SET SHOW TABLE TABLES THEN TO TRUNCATE UNION UNIQUE UNSIGNED UPDATE USE USING VALUES VIEW
WHEN WHERE WITH BEGIN COMMIT ROLLBACK TRANSACTION START TRIGGER FUNCTION RETURNS CALL REGEXP
INT INTEGER TINYINT SMALLINT MEDIUMINT BIGINT DECIMAL FLOAT DOUBLE CHAR VARCHAR TEXT MEDIUMTEXT
LONGTEXT BLOB DATE DATETIME TIMESTAMP TIME YEAR JSON ENUM BOOLEAN COLLATE CHARSET CHARACTER
""".split()

FUNCTIONS = """
COUNT SUM AVG MIN MAX CONCAT COALESCE IFNULL NOW CURDATE CURRENT_TIMESTAMP DATE_FORMAT LENGTH
LOWER UPPER SUBSTRING TRIM ROUND CAST CONVERT GROUP_CONCAT IFNULL NULLIF UUID
""".split()


def _fmt(color, bold=False, italic=False):
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Weight.Bold)
    f.setFontItalic(italic)
    return f


class SqlHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        kw = r"\b(?:" + "|".join(KEYWORDS) + r")\b"
        fn = r"\b(?:" + "|".join(FUNCTIONS) + r")(?=\s*\()"
        self.rules = [
            (re.compile(r"\b\d+(?:\.\d+)?\b"), _fmt("#b5651d")),
            (re.compile(kw, re.IGNORECASE), _fmt("#2a62c9", bold=True)),
            (re.compile(fn, re.IGNORECASE), _fmt("#8a3fb8")),
            (re.compile(r"`[^`]*`"), _fmt("#0f7b7b")),
            (re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\""), _fmt("#2e8b2e")),
            (re.compile(r"(?:--\s|#).*$"), _fmt("#8c8c8c", italic=True)),
        ]
        self.comment_fmt = _fmt("#8c8c8c", italic=True)

    def highlightBlock(self, text):
        for pattern, fmt in self.rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)
        # /* ... */ block comments, possibly spanning lines
        self.setCurrentBlockState(0)
        if self.previousBlockState() == 1:
            start, search_from = 0, 0
        else:
            start = text.find("/*")
            search_from = start + 2
        while start >= 0:
            end = text.find("*/", search_from)
            if end == -1:
                self.setCurrentBlockState(1)
                length = len(text) - start
            else:
                length = end - start + 2
            self.setFormat(start, length, self.comment_fmt)
            start = text.find("/*", start + length)
            search_from = start + 2


class _LineNumbers(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.line_number_width(), 0)

    def paintEvent(self, event):
        self.editor.paint_line_numbers(event)


class SqlEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPointSize(max(font.pointSize(), 11))
        self.setFont(font)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.highlighter = SqlHighlighter(self.document())
        self._numbers = _LineNumbers(self)
        self.blockCountChanged.connect(lambda _: self.setViewportMargins(self.line_number_width(), 0, 0, 0))
        self.updateRequest.connect(self._update_numbers)
        self.setViewportMargins(self.line_number_width(), 0, 0, 0)

    def line_number_width(self):
        digits = max(3, len(str(self.blockCount())))
        return 12 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_numbers(self, rect, dy):
        if dy:
            self._numbers.scroll(0, dy)
        else:
            self._numbers.update(0, rect.y(), self._numbers.width(), rect.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._numbers.setGeometry(QRect(cr.left(), cr.top(), self.line_number_width(), cr.height()))

    def paint_line_numbers(self, event):
        painter = QPainter(self._numbers)
        pal = self.palette()
        painter.fillRect(event.rect(), pal.alternateBase())
        painter.setPen(pal.placeholderText().color())
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        height = self.fontMetrics().height()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible():
                painter.drawText(0, top, self._numbers.width() - 6, height,
                                 Qt.AlignmentFlag.AlignRight, str(block.blockNumber() + 1))
            top += round(self.blockBoundingRect(block).height())
            block = block.next()

    def sql_to_run(self) -> str:
        cursor = self.textCursor()
        if cursor.hasSelection():
            # Qt uses U+2029 as paragraph separator in selections
            return cursor.selectedText().replace(" ", "\n")
        return self.toPlainText()
