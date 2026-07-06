from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ControlPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("控制台")
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setFont(QFont("Microsoft YaHei", 9))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(0)

        # Button: 聊天爬取
        layout.addSpacing(2)
        self.btn_scrape_chat = QPushButton("聊天爬取")
        self.btn_scrape_chat.setFixedHeight(28)
        layout.addWidget(self.btn_scrape_chat)

        # Button: 聊天删拒
        layout.addSpacing(2)
        self.btn_delete_chat = QPushButton("聊天删拒")
        self.btn_delete_chat.setFixedHeight(28)
        layout.addWidget(self.btn_delete_chat)

        # Separator
        layout.addSpacing(4)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep)

        # Button: 职位爬取
        layout.addSpacing(2)
        self.btn_dump = QPushButton("职位爬取")
        self.btn_dump.setFixedHeight(28)
        layout.addWidget(self.btn_dump)

        # Button: 批量沟通
        layout.addSpacing(2)
        self.btn_batch = QPushButton("批量沟通")
        self.btn_batch.setFixedHeight(28)
        layout.addWidget(self.btn_batch)

        # Separator
        layout.addSpacing(4)
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep2)

        # Button: 配置
        layout.addSpacing(2)
        self.btn_config = QPushButton("配置")
        self.btn_config.setFixedHeight(28)
        layout.addWidget(self.btn_config)

        # Button: 数据
        layout.addSpacing(2)
        self.btn_data = QPushButton("数据")
        self.btn_data.setFixedHeight(28)
        layout.addWidget(self.btn_data)

        # Button: DEBUG
        layout.addSpacing(2)
        self.btn_debug = QPushButton("DEBUG")
        self.btn_debug.setFixedHeight(28)
        layout.addWidget(self.btn_debug)

        # Separator
        layout.addSpacing(4)
        sep_stop = QFrame()
        sep_stop.setFrameShape(QFrame.Shape.HLine)
        sep_stop.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep_stop)

        # Button: 停止 (Ctrl+W)
        layout.addSpacing(2)
        self.btn_stop = QPushButton("停止 (Ctrl+W)")
        self.btn_stop.setFixedHeight(28)
        layout.addWidget(self.btn_stop)

        # Separator
        layout.addSpacing(4)
        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep3)

        # Button: 退出 (Ctrl+E)
        layout.addSpacing(2)
        self.btn_exit = QPushButton("退出 (Ctrl+E)")
        self.btn_exit.setFixedHeight(28)
        self.btn_exit.clicked.connect(QApplication.quit)
        layout.addWidget(self.btn_exit)

        self.adjustSize()
        self.setFixedSize(self.width(), self.height())

        # 所有任务按钮（退出除外），用于任务执行时禁用/启用
        self.task_buttons = [
            self.btn_scrape_chat,
            self.btn_delete_chat,
            self.btn_dump,
            self.btn_batch,
        ]

    def set_buttons_enabled(self, enabled: bool) -> None:
        """启用/禁用所有任务按钮。"""
        for btn in self.task_buttons:
            btn.setEnabled(enabled)
