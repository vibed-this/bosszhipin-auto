from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import QTextEdit, QVBoxLayout, QWidget


class LogWindow(QWidget):
    """日志窗口，作为标准 logging.Handler 接入日志体系。"""

    log_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.log_message.connect(self._append)
        self.setWindowTitle("Boss直聘 - 日志")
        self.setWindowFlags(Qt.WindowType.Tool)
        self.resize(400, 300)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setFont(QFont("Consolas", 10))
        self._text.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        )
        self._text.setStyleSheet("QTextEdit { border: 0px; }")
        self._text.document().setMaximumBlockCount(3000)
        layout.addWidget(self._text)

        # 日志文件 Handler
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        now = datetime.now()
        self._file_handler = logging.FileHandler(
            log_dir / f"{now:%Y-%m-%d-%H-%M-%S}.log",
            encoding="utf-8",
        )
        self._file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        )

        # 窗口 Handler
        self._gui_handler = _GuiHandler(self)
        self._gui_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        )

        # 挂到 root logger
        root = logging.getLogger()
        root.addHandler(self._file_handler)
        root.addHandler(self._gui_handler)

    def _append(self, text: str) -> None:
        """向窗口追加一行日志文本。由 log_message signal 触发。"""
        self._text.moveCursor(QTextCursor.MoveOperation.End)
        self._text.insertPlainText(text + "\n")
        scrollbar = self._text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def closeEvent(self, event) -> None:
        root = logging.getLogger()
        root.removeHandler(self._file_handler)
        root.removeHandler(self._gui_handler)
        self._file_handler.close()
        super().closeEvent(event)


class _GuiHandler(logging.Handler):
    """将 logging 记录通过 LogWindow.log_message signal 投递到 GUI 线程。"""

    def __init__(self, window: LogWindow) -> None:
        super().__init__()
        self._window = window

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._window.log_message.emit(msg)
        except Exception:
            self.handleError(record)
