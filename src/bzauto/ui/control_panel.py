from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from bzauto.config import get_config


class ControlPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(QFont("Microsoft YaHei", 9))
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(0)

        # Account selector
        layout.addSpacing(2)
        account_row = QHBoxLayout()
        account_row.setContentsMargins(2, 2, 2, 2)
        account_row.addWidget(QLabel("账号:"))
        self._account_combo = QComboBox()
        self._account_combo.setFixedHeight(24)
        self._account_combo.setMinimumWidth(90)
        self._refresh_accounts()
        account_row.addWidget(self._account_combo)
        layout.addLayout(account_row)

        def _add_btn_row(btns: list[QPushButton]) -> QHBoxLayout:
            row = QHBoxLayout()
            row.setContentsMargins(2, 2, 2, 2)
            row.setSpacing(4)
            for b in btns:
                b.setFixedHeight(28)
                row.addWidget(b)
            layout.addLayout(row)
            return row

        layout.addSpacing(4)

        # Row: 消息扫描 + 消息删拒
        layout.addSpacing(2)
        self.btn_scrape_chat = QPushButton("消息扫描")
        self.btn_delete_chat = QPushButton("消息删拒")
        _add_btn_row([self.btn_scrape_chat, self.btn_delete_chat])

        # Separator
        layout.addSpacing(4)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep)

        # Row: 职位爬取 + 批量沟通
        layout.addSpacing(2)
        self.btn_dump = QPushButton("职位爬取")
        self.btn_batch = QPushButton("批量沟通")
        _add_btn_row([self.btn_dump, self.btn_batch])

        # Separator
        layout.addSpacing(4)
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep2)

        # Row: 配置 + 数据
        layout.addSpacing(2)
        self.btn_config = QPushButton("配置")
        self.btn_data = QPushButton("数据")
        _add_btn_row([self.btn_config, self.btn_data])

        # Row: 账号 + 调度
        layout.addSpacing(2)
        self.btn_account = QPushButton("账号")
        self.btn_schedule = QPushButton("调度")
        _add_btn_row([self.btn_account, self.btn_schedule])

        # DEBUG (full width)
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

        # Row: 启动调度 + 停止调度 (Ctrl+W)
        layout.addSpacing(2)
        self.btn_start_scheduler = QPushButton("启动调度")
        self.btn_stop_scheduler = QPushButton("停止调度 (Ctrl+W)")
        _add_btn_row([self.btn_start_scheduler, self.btn_stop_scheduler])

        # 取消任务 (full width)
        layout.addSpacing(2)
        self.btn_cancel = QPushButton("取消任务")
        self.btn_cancel.setFixedHeight(28)
        layout.addWidget(self.btn_cancel)

        # Separator
        layout.addSpacing(4)
        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep3)

        # 退出 (Ctrl+E) (full width)
        layout.addSpacing(2)
        self.btn_exit = QPushButton("退出 (Ctrl+E)")
        self.btn_exit.setFixedHeight(28)
        self.btn_exit.clicked.connect(QApplication.quit)
        layout.addWidget(self.btn_exit)

        # 所有任务按钮（退出除外），用于任务执行时禁用/启用
        self.task_buttons = [
            self.btn_scrape_chat,
            self.btn_delete_chat,
            self.btn_dump,
            self.btn_batch,
        ]

    def selected_account(self) -> str:
        return self._account_combo.currentText()

    def _refresh_accounts(self) -> None:
        self._account_combo.clear()
        for a in get_config().accounts:
            if a.enabled:
                label = f"{a.name or a.id}" if a.name else a.id
                self._account_combo.addItem(a.id, label)

    def set_buttons_enabled(self, enabled: bool) -> None:
        """启用/禁用所有任务按钮。"""
        for btn in self.task_buttons:
            btn.setEnabled(enabled)
