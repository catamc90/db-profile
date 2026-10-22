"""Flat vector icons drawn with QPainter (no gradients, no shadows).

Every icon is drawn on a 16x16 grid and scaled, so it stays sharp at any size.
"""
import math

from PyQt6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QIcon, QIconEngine, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

BLUE = QColor("#2d7ff9")
GREEN = QColor("#2fa55a")
LIGHT_GREEN = QColor("#7ccf98")
ORANGE = QColor("#f29d38")
RED = QColor("#e5484d")
PURPLE = QColor("#8e5bd8")
DARK = QColor("#59606b")
GRAY = QColor("#9aa0a8")
LIGHT_GRAY = QColor("#c9cdd3")
LINE = QColor("#b9c0ca")
WHITE = QColor("#ffffff")


def _pen(color, width=1.2, cap=Qt.PenCapStyle.RoundCap):
    return QPen(color, width, Qt.PenStyle.SolidLine, cap, Qt.PenJoinStyle.RoundJoin)


def _fill(p, color):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(color))


def _poly(*pts):
    return QPolygonF([QPointF(x, y) for x, y in pts])


# --- building blocks ------------------------------------------------------
def _grid(p, header, x=1.5, y=2.5, w=13, h=11):
    """A small spreadsheet: coloured header row and light grid lines."""
    p.setPen(_pen(LINE, 1))
    p.setBrush(QBrush(WHITE))
    p.drawRoundedRect(QRectF(x, y, w, h), 1.2, 1.2)
    _fill(p, header)
    path = QPainterPath()
    path.addRoundedRect(QRectF(x, y, w, 3.4), 1.2, 1.2)
    path.addRect(QRectF(x, y + 2, w, 1.4))
    p.drawPath(path.simplified())
    p.setPen(_pen(LINE, 0.9))
    for gx in (x + w * 0.36, x + w * 0.68):
        p.drawLine(QPointF(gx, y + 3.4), QPointF(gx, y + h - 0.5))
    for gy in (y + 3.4 + (h - 3.4) / 3, y + 3.4 + 2 * (h - 3.4) / 3):
        p.drawLine(QPointF(x + 0.5, gy), QPointF(x + w - 0.5, gy))


def _badge(p, color, symbol):
    """Small round badge in the bottom-right corner with +, x or a pencil."""
    _fill(p, WHITE)
    p.drawEllipse(QPointF(12, 12), 4.2, 4.2)
    _fill(p, color)
    p.drawEllipse(QPointF(12, 12), 3.4, 3.4)
    p.setPen(_pen(WHITE, 1.3))
    if symbol == "+":
        p.drawLine(QPointF(10.2, 12), QPointF(13.8, 12))
        p.drawLine(QPointF(12, 10.2), QPointF(12, 13.8))
    elif symbol == "x":
        p.drawLine(QPointF(10.6, 10.6), QPointF(13.4, 13.4))
        p.drawLine(QPointF(13.4, 10.6), QPointF(10.6, 13.4))
    elif symbol == "pencil":
        p.drawLine(QPointF(10.5, 13.5), QPointF(13.5, 10.5))


# --- icons ----------------------------------------------------------------
def connection(p, active=True):
    body = BLUE if active else GRAY
    for y in (2, 8.6):
        _fill(p, body)
        p.drawRoundedRect(QRectF(2, y, 12, 5.4), 1.4, 1.4)
        _fill(p, LIGHT_GREEN if active else LIGHT_GRAY)
        p.drawEllipse(QPointF(11.3, y + 2.7), 1.1, 1.1)
        p.setPen(_pen(WHITE, 1.1))
        p.drawLine(QPointF(4, y + 2.7), QPointF(8, y + 2.7))


def database(p, open_=True):
    body = GREEN if open_ else GRAY
    top = LIGHT_GREEN if open_ else LIGHT_GRAY
    _fill(p, body)
    p.drawRect(QRectF(2.5, 4, 11, 8))
    p.drawEllipse(QRectF(2.5, 9.6, 11, 4.8))
    p.setPen(_pen(top, 0.9))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(2.5, 5.2, 11, 4.8), 180 * 16, 180 * 16)
    _fill(p, top)
    p.drawEllipse(QRectF(2.5, 1.6, 11, 4.8))


def table(p):
    _grid(p, BLUE)


def view(p):
    _grid(p, PURPLE)


def objects(p):
    for i, y in enumerate((3, 7, 11)):
        _fill(p, BLUE if i == 0 else GRAY)
        p.drawRoundedRect(QRectF(2, y - 1, 2.6, 2.6), 0.6, 0.6)
        p.setPen(_pen(DARK, 1.3))
        p.drawLine(QPointF(6.5, y + 0.3), QPointF(14, y + 0.3))


def query(p):
    p.setPen(_pen(LINE, 1))
    p.setBrush(QBrush(WHITE))
    p.drawPolygon(_poly((3, 1.5), (10, 1.5), (13, 4.5), (13, 14.5), (3, 14.5)))
    _fill(p, LINE)
    p.drawPolygon(_poly((10, 1.5), (13, 4.5), (10, 4.5)))
    p.setPen(_pen(ORANGE, 1.3))
    p.drawLine(QPointF(5, 7), QPointF(11, 7))
    p.setPen(_pen(BLUE, 1.3))
    p.drawLine(QPointF(5, 9.5), QPointF(11, 9.5))
    p.drawLine(QPointF(5, 12), QPointF(9, 12))


def new_query(p):
    query(p)
    _badge(p, GREEN, "+")


def beautify(p):
    """Indented code lines with a small sparkle."""
    p.setPen(_pen(DARK, 1.4))
    for x, y, w in ((2, 3, 7), (4.5, 6.5, 6), (4.5, 10, 4.5), (2, 13.5, 6)):
        p.drawLine(QPointF(x, y), QPointF(x + w, y))
    _fill(p, ORANGE)
    star = QPainterPath()
    cx, cy, r = 12.3, 4.2, 3.4
    for k in range(8):
        rad = r if k % 2 == 0 else r * 0.32
        ang = math.pi / 4 * k - math.pi / 2
        pt = QPointF(cx + rad * math.cos(ang), cy + rad * math.sin(ang))
        star.moveTo(pt) if k == 0 else star.lineTo(pt)
    star.closeSubpath()
    p.drawPath(star)


def drop_query(p):
    query(p)
    _badge(p, RED, "x")


def open_table(p):
    table(p)


def design_table(p):
    table(p)
    _badge(p, ORANGE, "pencil")


def new_table(p):
    table(p)
    _badge(p, GREEN, "+")


def drop_table(p):
    table(p)
    _badge(p, RED, "x")


def _tile(p, color, text):
    """Rounded square with a short white label, e.g. "fx"."""
    _fill(p, color)
    p.drawRoundedRect(QRectF(1.5, 1.5, 13, 13), 2.5, 2.5)
    font = QFont("DejaVu Sans")
    font.setPixelSize(8)
    font.setBold(True)
    font.setItalic(text == "fx")
    p.setFont(font)
    p.setPen(_pen(WHITE, 1))
    p.drawText(QRectF(1.5, 1.5, 13, 12.5), Qt.AlignmentFlag.AlignCenter, text)


def function(p):
    _tile(p, ORANGE, "fx")


def procedure(p):
    _tile(p, QColor("#d9822b"), "P")


def new_function(p):
    function(p)
    _badge(p, GREEN, "+")


def design_function(p):
    function(p)
    _badge(p, BLUE, "pencil")


def drop_function(p):
    function(p)
    _badge(p, RED, "x")


def user(p, color=BLUE):
    _fill(p, color)
    p.drawEllipse(QPointF(8, 5), 3, 3)
    path = QPainterPath()
    path.moveTo(2.5, 14.5)
    path.cubicTo(2.5, 9, 13.5, 9, 13.5, 14.5)
    path.closeSubpath()
    p.drawPath(path)


def users(p):
    user(p)


def new_user(p):
    user(p)
    _badge(p, GREEN, "+")


def edit_user(p):
    user(p)
    _badge(p, ORANGE, "pencil")


def drop_user(p):
    user(p)
    _badge(p, RED, "x")


def save(p):
    _fill(p, BLUE)
    p.drawRoundedRect(QRectF(2, 2, 12, 12), 1.6, 1.6)
    _fill(p, WHITE)
    p.drawRect(QRectF(4.5, 2, 7, 4.2))
    p.drawRoundedRect(QRectF(4, 8.5, 8, 5.5), 0.8, 0.8)
    _fill(p, BLUE)
    p.drawRect(QRectF(9, 2.8, 1.5, 2.6))


def refresh(p):
    p.setPen(_pen(BLUE, 1.6))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(3, 3, 10, 10), 60 * 16, 270 * 16)
    a = math.radians(60)
    tip = QPointF(8 + 5 * math.cos(a), 8 - 5 * math.sin(a))
    _fill(p, BLUE)
    p.drawPolygon(_poly((tip.x() + 2.4, tip.y() - 1.6), (tip.x() + 0.6, tip.y() + 2.6), (tip.x() - 2.2, tip.y() - 0.6)))


def run(p):
    _fill(p, GREEN)
    path = QPainterPath()
    path.addPolygon(_poly((4.5, 2.5), (13.5, 8), (4.5, 13.5)))
    path.closeSubpath()
    p.setPen(_pen(GREEN, 1.2))
    p.setBrush(QBrush(GREEN))
    p.drawPath(path)


def stop(p):
    _fill(p, RED)
    p.drawRoundedRect(QRectF(3.5, 3.5, 9, 9), 1.5, 1.5)


def add(p):
    p.setPen(_pen(DARK, 1.5))
    p.drawLine(QPointF(3.5, 8), QPointF(12.5, 8))
    p.drawLine(QPointF(8, 3.5), QPointF(8, 12.5))


def remove(p):
    p.setPen(_pen(DARK, 1.5))
    p.drawLine(QPointF(3.5, 8), QPointF(12.5, 8))


def apply(p):
    p.setPen(_pen(GREEN, 1.7))
    p.drawPolyline(_poly((3.5, 8.5), (6.8, 11.8), (12.8, 4.5)))


def discard(p):
    p.setPen(_pen(RED, 1.6))
    p.drawLine(QPointF(4.5, 4.5), QPointF(11.5, 11.5))
    p.drawLine(QPointF(11.5, 4.5), QPointF(4.5, 11.5))


def close(p, color=GRAY):
    p.setPen(_pen(color, 1.3))
    p.drawLine(QPointF(5, 5), QPointF(11, 11))
    p.drawLine(QPointF(11, 5), QPointF(5, 11))


def filter(p):  # noqa: A001 - icon name
    p.setPen(_pen(DARK, 1.1))
    p.setBrush(QBrush(QColor("#e3ecfb")))
    p.drawPolygon(_poly((2.5, 3), (13.5, 3), (9.3, 8.2), (9.3, 13), (6.7, 11.8), (6.7, 8.2)))


def export(p):
    p.setPen(_pen(DARK, 1.3))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolyline(_poly((3, 8.5), (3, 13.5), (13, 13.5), (13, 8.5)))
    p.setPen(_pen(BLUE, 1.4))
    p.drawLine(QPointF(8, 2.5), QPointF(8, 10))
    p.drawPolyline(_poly((5, 5.5), (8, 2.5), (11, 5.5)))


def import_(p):
    p.setPen(_pen(DARK, 1.3))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolyline(_poly((3, 8.5), (3, 13.5), (13, 13.5), (13, 8.5)))
    p.setPen(_pen(GREEN, 1.4))
    p.drawLine(QPointF(8, 2.5), QPointF(8, 10))
    p.drawPolyline(_poly((5, 7), (8, 10), (11, 7)))


def set_null(p):
    p.setPen(_pen(DARK, 1.2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(8, 8), 4.5, 4.5)
    p.drawLine(QPointF(4.8, 11.2), QPointF(11.2, 4.8))


def _chevron(p, direction, bar=False):
    p.setPen(_pen(DARK, 1.5))
    if direction < 0:
        p.drawPolyline(_poly((10, 3.5), (5.5, 8), (10, 12.5)))
        if bar:
            p.drawLine(QPointF(3.5, 3.5), QPointF(3.5, 12.5))
    else:
        p.drawPolyline(_poly((6, 3.5), (10.5, 8), (6, 12.5)))
        if bar:
            p.drawLine(QPointF(12.5, 3.5), QPointF(12.5, 12.5))


def first(p):
    _chevron(p, -1, True)


def prev(p):
    _chevron(p, -1)


def next(p):  # noqa: A001 - icon name
    _chevron(p, 1)


def last(p):
    _chevron(p, 1, True)


# Small glyphs used by the stylesheet (combo arrows, check marks, ...)
def arrow_down(p, color=DARK):
    _fill(p, color)
    p.drawPolygon(_poly((4, 6), (12, 6), (8, 10.5)))


def arrow_up(p, color=DARK):
    _fill(p, color)
    p.drawPolygon(_poly((4, 10), (12, 10), (8, 5.5)))


def check(p, color=WHITE):
    p.setPen(_pen(color, 2))
    p.drawPolyline(_poly((3.5, 8.5), (6.8, 11.5), (12.5, 4.8)))


def dash(p, color=WHITE):
    p.setPen(_pen(color, 2))
    p.drawLine(QPointF(4.5, 8), QPointF(11.5, 8))


# --- application icon --------------------------------------------------------
def app(p):
    """DB Profile's own icon: a white database on a blue tile, with an orange profile badge."""
    _fill(p, BLUE)
    p.drawRoundedRect(QRectF(0.5, 0.5, 15, 15), 3.4, 3.4)
    # database cylinder: body, three disk lines and the top ellipse
    _fill(p, WHITE)
    body = QPainterPath()
    body.moveTo(3.2, 4.4)
    body.lineTo(3.2, 11.4)
    body.arcTo(QRectF(3.2, 9.8, 8.6, 3.2), 180, 180)
    body.lineTo(11.8, 4.4)
    body.closeSubpath()
    p.drawPath(body)
    p.setPen(_pen(BLUE, 0.7))
    for y in (6.8, 9.2):
        p.drawArc(QRectF(3.2, y - 1.6, 8.6, 3.2), 180 * 16, 180 * 16)
    p.setPen(_pen(BLUE, 0.7))
    p.setBrush(QBrush(WHITE))
    p.drawEllipse(QRectF(3.2, 2.8, 8.6, 3.2))
    # profile badge: orange circle with a white head and shoulders
    cx = cy = 11.8
    _fill(p, BLUE)
    p.drawEllipse(QPointF(cx, cy), 3.4, 3.4)
    _fill(p, ORANGE)
    p.drawEllipse(QPointF(cx, cy), 2.75, 2.75)
    _fill(p, WHITE)
    p.drawEllipse(QPointF(cx, cy - 0.95), 0.9, 0.9)
    shoulders = QPainterPath()
    shoulders.moveTo(cx - 1.65, cy + 1.75)
    shoulders.cubicTo(cx - 1.45, cy + 0.1, cx + 1.45, cy + 0.1, cx + 1.65, cy + 1.75)
    shoulders.closeSubpath()
    p.drawPath(shoulders)


# --- QIcon plumbing ---------------------------------------------------------
class _Engine(QIconEngine):
    def __init__(self, draw):
        super().__init__()
        self.draw = draw

    def paint(self, painter, rect, mode, state):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if mode == QIcon.Mode.Disabled:
            painter.setOpacity(0.35)
        side = min(rect.width(), rect.height())
        painter.translate(rect.x() + (rect.width() - side) / 2, rect.y() + (rect.height() - side) / 2)
        painter.scale(side / 16, side / 16)
        self.draw(painter)
        painter.restore()

    def pixmap(self, size, mode, state):
        pm = QPixmap(size)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        self.paint(painter, QRect(0, 0, size.width(), size.height()), mode, state)
        painter.end()
        return pm

    def scaledPixmap(self, size, mode, state, scale):
        pm = self.pixmap(QSize(round(size.width() * scale), round(size.height() * scale)), mode, state)
        pm.setDevicePixelRatio(scale)
        return pm

    def clone(self):
        return _Engine(self.draw)


_cache: dict[str, QIcon] = {}
_VARIANTS = {
    "connection_closed": lambda p: connection(p, active=False),
    "database_closed": lambda p: database(p, open_=False),
    "import": import_,
}


def icon(name: str) -> QIcon:
    if name not in _cache:
        draw = _VARIANTS.get(name) or globals()[name]
        _cache[name] = QIcon(_Engine(draw))
    return _cache[name]


def save_png(draw, path: str, size: int) -> None:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 16, size / 16)
    draw(painter)
    painter.end()
    pm.save(path, "PNG")
