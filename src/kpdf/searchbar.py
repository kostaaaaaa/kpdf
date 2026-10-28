"""The small search box shown at the top right of the viewer."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QWidget

_STYLE = """
SearchBar { background: rgb(28, 28, 28); border: 1px solid #ffbe00; border-radius: 4px; }
QLineEdit { background: transparent; border: none; color: #eeeeee;
            selection-background-color: #ffbe00; selection-color: #000000; }
QLabel { color: #aaaaaa; }
"""


class _Edit(QLineEdit):
    cancelled = pyqtSignal()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            e.accept()
            self.cancelled.emit()
            return
        super().keyPressEvent(e)


class SearchBar(QWidget):
    submitted = pyqtSignal(str)  # Enter pressed
    cancelled = pyqtSignal()  # Esc pressed while typing

    WIDTH = 320

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(_STYLE)
        self.edit = _Edit()
        self.edit.setPlaceholderText("search")
        self.edit.returnPressed.connect(lambda: self.submitted.emit(self.edit.text()))
        self.edit.cancelled.connect(self.cancelled)
        self.info = QLabel()
        self.info.setMinimumWidth(80)
        self.info.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 8, 4)
        row.addWidget(self.edit, 1)
        row.addWidget(self.info)
        self.setFixedSize(self.WIDTH, 30)
        self.hide()

    def place(self):
        self.move(max(self.parentWidget().width() - self.width() - 10, 0), 10)

    def open(self):
        self.place()
        self.show()
        self.raise_()
        self.edit.setFocus()
        self.edit.selectAll()

    def set_info(self, text: str, ok: bool = True):
        self.info.setText(text)
        self.info.setStyleSheet("" if ok else "color: #ff6b6b;")
