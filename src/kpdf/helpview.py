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
DIM = QColor(0, 0, 0, 185)  # over the whole window
PANEL_BG = QColor(22, 22, 22, 248)
BORDER = QPen(ACCENT, 1)
PAD_X, PAD_Y = 3, 1  # panel padding, in characters / lines
MARGIN = 12  # minimum gap between the panel and the window edge, in px
MAX_PX, MIN_PX = 16, 6  # font pixel sizes the panel may use


class Layout(NamedTuple):
    font: QFont
    cw: float  # width of one character
    lh: float  # height of one line
    ascent: float
    panel: QRectF


@lru_cache(maxsize=1)
def _content():
    return helptext.build()


@lru_cache(maxsize=None)
def _metrics(px: int):
    """(font, char width, line height, ascent) at a pixel size.

    Each new size makes Qt resolve "monospace" and load a font engine, which is by far the most
    expensive thing here, so every size is measured at most once (and as few sizes as possible).
    """
    f = QFont("monospace")
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPixelSize(px)
    fm = QFontMetricsF(f)
    return f, fm.horizontalAdvance("M"), fm.lineSpacing(), fm.ascent()


@lru_cache(maxsize=4)
def layout(width: int, height: int) -> Layout:
    """Largest font (MAX_PX down to MIN_PX) at which the whole panel fits the window."""
    _, cols, lines = _content()
    avail_w, avail_h = width - 2 * MARGIN, height - 2 * MARGIN

    def panel_size(px):
        _, cw, lh, _ = _metrics(px)
        return (cols + 2 * PAD_X) * cw, (lines + 2 * PAD_Y) * lh

    # Text scales ~linearly with the font size, so measure once at the biggest size and start
    # just above where the panel should fit, instead of walking down through every size.
    w, h = panel_size(MAX_PX)
    px = min(MAX_PX, int(MAX_PX * min(avail_w / w, avail_h / h)) + 1)
    px = max(px, MIN_PX)
    w, h = panel_size(px)
    while px > MIN_PX and (w > avail_w or h > avail_h):
        px -= 1
        w, h = panel_size(px)
    font, cw, lh, ascent = _metrics(px)
    panel = QRectF(max((width - w) / 2, 0), max((height - h) / 2, 0), w, h)
    return Layout(font, cw, lh, ascent, panel)


def draw_help(p: QPainter, rect: QRectF) -> None:
    lay = layout(int(rect.width()), int(rect.height()))
    segs, _, _ = _content()
    p.save()
    p.fillRect(rect, DIM)
    p.setPen(BORDER)
    p.setBrush(PANEL_BG)
    p.drawRoundedRect(lay.panel, 6, 6)
    p.setFont(lay.font)
    left, top = lay.panel.left() + PAD_X * lay.cw, lay.panel.top() + PAD_Y * lay.lh + lay.ascent
    for s in segs:
        p.setPen(COLORS[s.role])
        p.drawText(QPointF(left + s.col * lay.cw, top + s.line * lay.lh), s.text)
    p.restore()
