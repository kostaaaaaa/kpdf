"""Draws the help screen (see helptext.py for what it says) over the viewer."""

from functools import lru_cache
from typing import NamedTuple

from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen

from . import helptext

ACCENT = QColor(140, 100, 167)
COLORS = {
    "logo": ACCENT,
    "title": ACCENT,
    "user": ACCENT,
    "key": QColor(240, 240, 240),
    "desc": QColor(200, 200, 240),
    "tagline": QColor(200, 200, 240),
    "muted": QColor(200, 200, 240),
}
PAD_X, PAD_Y = 3, 1  # panel padding, in characters / lines
MARGIN = 12  # minimum gap between the panel and the window edge, in px


class Layout(NamedTuple):
    px: int  # font pixel size
    cw: float  # width of one character
    lh: float  # height of one line
    panel: QRectF


def _font(px: int) -> QFont:
    f = QFont("monospace")
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPixelSize(px)
    return f


@lru_cache(maxsize=1)
def _content():
    return helptext.build()


def layout(width: float, height: float) -> Layout:
    """Largest font (16 px down to 6 px) at which the whole panel fits the window."""
    _, cols, lines = _content()
    for px in range(16, 5, -1):
        fm = QFontMetricsF(_font(px))
        cw, lh = fm.horizontalAdvance("M"), fm.lineSpacing()
        w, h = (cols + 2 * PAD_X) * cw, (lines + 2 * PAD_Y) * lh
        if w <= width - 2 * MARGIN and h <= height - 2 * MARGIN:
            break
    return Layout(px, cw, lh, QRectF(max((width - w) / 2, 0), max((height - h) / 2, 0), w, h))


def draw_help(p: QPainter, rect: QRectF) -> None:
    lay = layout(rect.width(), rect.height())
    segs, _, _ = _content()
    p.save()
    p.fillRect(rect, QColor(0, 0, 0, 185))
    p.setPen(QPen(ACCENT, 1))
    p.setBrush(QColor(22, 22, 22, 248))
    p.drawRoundedRect(lay.panel, 6, 6)
    p.setFont(_font(lay.px))
    ascent = QFontMetricsF(p.font()).ascent()
    for s in segs:
        p.setPen(COLORS[s.role])
        x = lay.panel.left() + (PAD_X + s.col) * lay.cw
        y = lay.panel.top() + (PAD_Y + s.line) * lay.lh + ascent
        p.drawText(QPointF(x, y), s.text)
    p.restore()
