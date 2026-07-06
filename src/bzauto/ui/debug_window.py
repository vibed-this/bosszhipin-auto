from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from bzauto.config import get_config

if TYPE_CHECKING:
    from bzauto.ui import BzAutoApp

log = logging.getLogger("boss.debug")


class DebugWindow(QWidget):
    """Debug window for manually triggering scheduled tasks with dual-path execution."""

    def __init__(self, app: BzAutoApp, parent=None):
        super().__init__(parent)
        self._app = app
        self.setWindowTitle("调试窗口")
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        )
        self.resize(640, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ── 账号 + 执行路径 + 超时 ──
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("账号:"))
        self._account_combo = QComboBox()
        for a in get_config().accounts:
            self._account_combo.addItem(a.id)
        top_row.addWidget(self._account_combo)

        top_row.addSpacing(12)
        self._path_runner = QRadioButton("TaskRunner")
        self._path_runner.setChecked(True)
        self._path_direct = QRadioButton("直接执行")
        top_row.addWidget(self._path_runner)
        top_row.addWidget(self._path_direct)

        top_row.addSpacing(12)
        top_row.addWidget(QLabel("超时:"))
        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(10, 600)
        self._timeout_spin.setValue(120)
        self._timeout_spin.setSuffix(" 秒")
        top_row.addWidget(self._timeout_spin)
        top_row.addStretch()
        layout.addLayout(top_row)

        # ── 单账号任务按钮 ──
        task_box = QGroupBox("单账号任务 (使用上方选中的账号)")
        task_layout = QHBoxLayout(task_box)
        self._task_buttons: dict[str, QPushButton] = {}
        for name in ("采集", "投递", "扫描", "聊天爬取", "删拒", "抓取沟通"):
            btn = QPushButton(name)
            btn.setFixedHeight(28)
            btn.clicked.connect(lambda _, n=name: self._on_single_task(n))
            task_layout.addWidget(btn)
            self._task_buttons[name] = btn
        layout.addWidget(task_box)

        # ── 完整定时触发按钮 ──
        trigger_box = QGroupBox("完整定时触发 (全部账号 + 合并通知, 走 TaskRunner)")
        trigger_layout = QHBoxLayout(trigger_box)
        for name in ("触发采集", "触发投递", "触发扫描"):
            btn = QPushButton(name)
            btn.setFixedHeight(28)
            trigger_name = name[2:]
            btn.clicked.connect(lambda _, n=trigger_name: self._on_full_trigger(n))
            trigger_layout.addWidget(btn)
        layout.addWidget(trigger_box)

        # ── 调度器状态 ──
        status_box = QGroupBox("调度器状态")
        status_layout = QVBoxLayout(status_box)
        self._status_text = QTextEdit()
        self._status_text.setReadOnly(True)
        self._status_text.setFixedHeight(120)
        status_layout.addWidget(self._status_text)

        self._btn_refresh = QPushButton("刷新状态")
        self._btn_refresh.setFixedHeight(28)
        self._btn_refresh.clicked.connect(self._refresh_status)
        status_layout.addWidget(self._btn_refresh)
        layout.addWidget(status_box)

        # ── 结果 ──
        result_box = QGroupBox("结果")
        result_layout = QVBoxLayout(result_box)
        self._result_text = QTextEdit()
        self._result_text.setReadOnly(True)
        result_layout.addWidget(self._result_text)

        self._btn_clear = QPushButton("清空")
        self._btn_clear.setFixedHeight(28)
        self._btn_clear.clicked.connect(self._result_text.clear)
        result_layout.addWidget(self._btn_clear)
        layout.addWidget(result_box)

    # ── Qt slots (called from BzAutoApp via _TaskBridge signals) ──

    def on_result(self, task_name: str, result_text: str, elapsed: float) -> None:
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._result_text.append(f"[{ts}] {task_name} (耗时 {elapsed:.1f}s)")
        self._result_text.append(result_text)
        self._result_text.append("")

    def on_error(self, task_name: str, error_text: str) -> None:
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._result_text.append(f"[{ts}] {task_name} 错误:")
        self._result_text.append(error_text)
        self._result_text.append("")

    def on_running(self, running: bool) -> None:
        for btn in self._task_buttons.values():
            btn.setEnabled(not running)
        self._btn_refresh.setEnabled(not running)

    # ── 按钮事件 ──

    def _refresh_status(self) -> None:
        self._status_text.setText(self._app.get_debug_status())

    def _on_single_task(self, task_name: str) -> None:
        account = self._account_combo.currentText()
        via_runner = self._path_runner.isChecked()
        timeout = self._timeout_spin.value()
        self._app.run_debug_task(task_name, account, via_runner, timeout)

    def _on_full_trigger(self, trigger_name: str) -> None:
        timeout = self._timeout_spin.value() * 2
        self._app.run_debug_trigger(trigger_name, timeout)
