"""DotOverlay — 调试时在点击位置显示红点。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QPainter
from PySide6.QtWidgets import QWidget


class DotOverlay(QWidget):
    """Transparent overlay that draws a red dot for debugging."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dot: tuple[float, float] | None = None
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def show_dot(self, cx: float, cy: float) -> None:
        self._dot = (cx, cy)
        self.update()

    def clear_dot(self) -> None:
        self._dot = None
        self.update()

    def paintEvent(self, event: object) -> None:
        if self._dot:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(QBrush(QColor("red")))
            painter.setPen(Qt.PenStyle.NoPen)
            cx, cy = self._dot
            painter.drawEllipse(int(cx) - 5, int(cy) - 5, 10, 10)
            painter.end()
