from __future__ import annotations

import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import QTextEdit, QVBoxLayout, QWidget


class LogWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Boss直聘 - 日志")
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
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
        layout.addWidget(self._text)

        self._log_file: str | None = None

    def _ensure_log_file(self) -> None:
        if self._log_file is not None:
            return
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        now = datetime.datetime.now()
        self._log_file = str(
            log_dir / f"{now:%Y-%m-%d-%H-%M-%S}.log"
        )

    def log(self, text: str) -> None:
        self._ensure_log_file()
        line = f"[{datetime.datetime.now():%H:%M:%S}] {text}\n"

        self._text.moveCursor(QTextCursor.MoveOperation.End)
        self._text.insertPlainText(line)
        scrollbar = self._text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

        if self._log_file:
            try:
                with open(self._log_file, "a", encoding="utf-8") as f:
                    f.write(line)
            except OSError:
                pass
