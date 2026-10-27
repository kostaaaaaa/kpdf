"""Bottom hotbar for keyboard navigation between PDFs in the current directory."""

import os
from pathlib import Path

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget


class PdfTreeSitter(QWidget):
    """A bottom-docked PDF picker controlled entirely from the keyboard."""

    PANEL_HEIGHT = 118
    TILE_WIDTH = 220
    TILE_GAP = 8

    ACCENT = QColor(140, 100, 167)
    LIGHT = QColor(240, 240, 240)
    BACKGROUND = QColor(34, 32, 38, 248)
    TILE_BACKGROUND = QColor(48, 44, 53)
    TILE_BORDER = QColor(91, 84, 99)
    SELECTED_BACKGROUND = QColor(69, 54, 79)

    def __init__(self, viewer):
        super().__init__(viewer)
        self.viewer = viewer
        self.files = []
        self.selected = 0
        self.offset = 0
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.hide()
        self.refresh()
        self.resize_to_parent()

    def resize_to_parent(self):
        parent = self.parentWidget()
        if parent is not None:
            h = min(self.PANEL_HEIGHT, parent.height())
            self.setGeometry(0, parent.height() - h, parent.width(), h)

    def refresh(self):
        current = os.path.abspath(self.viewer.path)
        folder = os.path.dirname(current)
        try:
            self.files = sorted(
                (str(p.resolve()) for p in Path(folder).iterdir()
                 if p.is_file() and p.suffix.lower() == ".pdf"),
                key=lambda p: os.path.basename(p).casefold(),
            )
        except OSError:
            self.files = [current]
        if current not in self.files:
            self.files.append(current)
            self.files.sort(key=lambda p: os.path.basename(p).casefold())
        self.selected = self.files.index(current) if current in self.files else 0
        self._keep_selected_visible()
        self.update()

    def toggle(self):
        if self.isVisible():
            self.hide()
            self.viewer.setFocus()
            return
        self.refresh()
        self.resize_to_parent()
        self.show()
        self.raise_()
        self.setFocus()
        self.update()

    def _keep_selected_visible(self):
        if not self.files:
            self.offset = 0
            return
        visible = max(1, (max(1, self.width()) - 24) // (self.TILE_WIDTH + self.TILE_GAP))
        if self.selected < self.offset:
            self.offset = self.selected
        elif self.selected >= self.offset + visible:
            self.offset = self.selected - visible + 1
        self.offset = max(0, min(self.offset, max(0, len(self.files) - visible)))

    def move_selection(self, delta):
        if not self.files:
            return
        self.selected = (self.selected + delta) % len(self.files)
        self._keep_selected_visible()
        self.update()

    def open_selected(self):
        if self.files and 0 <= self.selected < len(self.files):
            path = self.files[self.selected]
            self.hide()
            self.viewer.setFocus()
            if os.path.abspath(path) != os.path.abspath(self.viewer.path):
                self.viewer.open_pdf(path)

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_Backslash:
            self.toggle()
        elif key in (Qt.Key.Key_Escape,):
            self.toggle()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_H) or event.text() == "h":
            self.move_selection(-1)
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_L) or event.text() == "l":
            self.move_selection(1)
        elif event.text() == "k" or key == Qt.Key.Key_Up:
            self.move_selection(-1)
        elif event.text() == "j" or key == Qt.Key.Key_Down:
            self.move_selection(1)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.open_selected()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.BACKGROUND)
        painter.setFont(QFont("monospace", 9))
        painter.setPen(self.LIGHT)
        painter.drawText(12, 18, "PDFs in this directory  ·  h/j/k/l navigate  ·  Enter open  ·  Esc close")

        if not self.files:
            painter.setPen(self.LIGHT)
            painter.drawText(14, 54, "No PDF files found in this directory.")
            return

        y, tile_h = 28, self.height() - 38
        x = 12
        visible_count = max(1, (self.width() - 24) // (self.TILE_WIDTH + self.TILE_GAP))
        end = min(len(self.files), self.offset + visible_count)
        for index in range(self.offset, end):
            rect = QRectF(x, y, self.TILE_WIDTH, tile_h)
            selected = index == self.selected
            painter.setPen(QPen(self.ACCENT if selected else self.TILE_BORDER, 2 if selected else 1))
            painter.setBrush(self.SELECTED_BACKGROUND if selected else self.TILE_BACKGROUND)
            painter.drawRoundedRect(rect, 5, 5)
            name = os.path.basename(self.files[index])
            metrics = painter.fontMetrics()
            if metrics.horizontalAdvance(name) > self.TILE_WIDTH - 20:
                while name and metrics.horizontalAdvance(name + "…") > self.TILE_WIDTH - 20:
                    name = name[:-1]
                name += "…"
            painter.setPen(self.LIGHT)
            painter.drawText(rect.adjusted(10, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter, name)
            x += self.TILE_WIDTH + self.TILE_GAP
        if self.offset > 0:
            painter.setPen(self.LIGHT)
            painter.drawText(1, self.height() - 8, "‹")
        if end < len(self.files):
            painter.setPen(self.LIGHT)
            painter.drawText(self.width() - 12, self.height() - 8, "›")

