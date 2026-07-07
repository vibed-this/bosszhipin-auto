from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from bzauto.storage import Storage

if TYPE_CHECKING:
    from bzauto.ui import BzAutoApp

_ROLE_NEXT_RUN = Qt.ItemDataRole.UserRole + 10


class ScheduleWindow(QWidget):
    """调度面板 — 只读展示调度器状态、规划任务、账号配额、积压维护。"""

    def __init__(self, app: BzAutoApp, parent=None):
        super().__init__(parent)
        self._app = app
        self._storage = Storage()

        self.setWindowTitle("调度面板")
        self.setWindowFlags(Qt.WindowType.Window)
        self.setFont(QFont("Microsoft YaHei", 9))
        self.resize(640, 560)

        self._build_ui()

        self._btn_reset_all.clicked.connect(self._on_reset_all)
        self._btn_run_selected.clicked.connect(self._on_run_selected)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(5000)
        self._refresh_timer.timeout.connect(self._refresh_all)

        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._update_countdown)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ── 1. 调度器概览 ──
        overview_box = QGroupBox("调度器概览")
        overview_layout = QHBoxLayout(overview_box)
        self._lbl_scheduler_status = QLabel("运行状态: —")
        self._lbl_start_time = QLabel("启动时间: —")
        self._lbl_current_task = QLabel("当前任务: —")
        self._lbl_pending_count = QLabel("队列等待: —")
        for w in (self._lbl_scheduler_status, self._lbl_start_time,
                  self._lbl_current_task, self._lbl_pending_count):
            overview_layout.addWidget(w)
        overview_layout.addStretch()
        layout.addWidget(overview_box)

        # ── 2. 后续规划任务表 ──
        task_box = QGroupBox("后续规划任务")
        task_layout = QVBoxLayout(task_box)
        self._task_table = QTableWidget(0, 4)
        self._task_table.setHorizontalHeaderLabels(["触发类型", "触发规则", "下次执行时间", "倒计时"])
        header = self._task_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._task_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._task_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        task_layout.addWidget(self._task_table)

        btn_layout = QHBoxLayout()
        self._btn_reset_all = QPushButton("重置所有")
        self._btn_run_selected = QPushButton("运行选中")
        btn_layout.addWidget(self._btn_reset_all)
        btn_layout.addWidget(self._btn_run_selected)
        btn_layout.addStretch()
        task_layout.addLayout(btn_layout)

        layout.addWidget(task_box)

        # ── 3. 积压与维护状态 ──
        backlog_box = QGroupBox("积压与维护状态")
        backlog_layout = QHBoxLayout(backlog_box)
        self._lbl_pending = QLabel("待处理投递: —")
        self._lbl_stale = QLabel("超时 Claim: —")
        self._lbl_today_jobs = QLabel("今日更新: —")
        self._lbl_dispatched = QLabel("今日投递: —")
        for w in (self._lbl_pending, self._lbl_stale, self._lbl_today_jobs, self._lbl_dispatched):
            backlog_layout.addWidget(w)
        backlog_layout.addStretch()
        layout.addWidget(backlog_box)

        # ── 5. 最近执行记录 ──
        runs_box = QGroupBox("最近执行记录")
        runs_layout = QVBoxLayout(runs_box)
        self._runs_table = QTableWidget(0, 6)
        self._runs_table.setHorizontalHeaderLabels(["时间", "触发类型", "账号", "状态", "结果摘要", "耗时"])
        r_header = self._runs_table.horizontalHeader()
        r_header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._runs_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._runs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        runs_layout.addWidget(self._runs_table)
        layout.addWidget(runs_box)

    # ── 生命周期 ──

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_all()
        self._refresh_timer.start()
        self._countdown_timer.start()

    def closeEvent(self, event):
        self._refresh_timer.stop()
        self._countdown_timer.stop()
        self.hide()
        event.ignore()

    # ── 操作按钮 ──

    def _on_reset_all(self) -> None:
        sched = self._app._scheduler
        if sched:
            sched.reset_all_jobs()
        self._refresh_all()
        self._task_table.viewport().update()

    def _on_run_selected(self) -> None:
        table = self._task_table
        selected = table.selectedItems()
        if not selected:
            return
        rows = set(item.row() for item in selected)
        sched = self._app._scheduler
        if not sched:
            return
        snapshots = sched.snapshot()
        for row in rows:
            if row < len(snapshots):
                sched.run_job_now(snapshots[row]["id"])
        self._refresh_all()

    # ── 刷新 ──

    def _refresh_all(self) -> None:
        self._refresh_overview()
        self._refresh_task_table()
        self._refresh_backlog()
        self._refresh_recent_runs()
        self._update_countdown()

    def _refresh_overview(self) -> None:
        sched = self._app._scheduler
        if sched and sched.running:
            self._lbl_scheduler_status.setText("运行状态: 运行中")
            self._lbl_start_time.setText(f"启动时间: —")
        else:
            self._lbl_scheduler_status.setText("运行状态: 已停止")
            self._lbl_start_time.setText("启动时间: —")

        runner = self._app._task_runner
        if runner:
            current = runner.current_task_name
            self._lbl_current_task.setText(f"当前任务: {current or '空闲'}")
            self._lbl_pending_count.setText(f"队列等待: {runner.pending_count}")
        else:
            self._lbl_current_task.setText("当前任务: —")
            self._lbl_pending_count.setText("队列等待: —")

    def _refresh_task_table(self) -> None:
        table = self._task_table
        table.setRowCount(0)
        sched = self._app._scheduler
        if not sched or not sched.running:
            return
        snapshots = sched.snapshot()
        table.setRowCount(len(snapshots))
        for i, job in enumerate(snapshots):
            table.setItem(i, 0, QTableWidgetItem(job["label"]))
            table.setItem(i, 1, QTableWidgetItem(job["trigger_repr"]))
            nrt = job["next_run_time"]
            if nrt:
                try:
                    dt = datetime.datetime.fromisoformat(nrt)
                    local_dt = dt.astimezone()
                    table.setItem(i, 2, QTableWidgetItem(local_dt.strftime("%m-%d %H:%M:%S")))
                    countdown_item = QTableWidgetItem("")
                    countdown_item.setData(_ROLE_NEXT_RUN, dt)
                    table.setItem(i, 3, countdown_item)
                except (ValueError, TypeError):
                    table.setItem(i, 2, QTableWidgetItem(nrt))
                    table.setItem(i, 3, QTableWidgetItem("—"))
            else:
                table.setItem(i, 2, QTableWidgetItem("未调度"))
                table.setItem(i, 3, QTableWidgetItem("—"))

    def _update_countdown(self) -> None:
        table = self._task_table
        now = datetime.datetime.now(datetime.timezone.utc)
        for row in range(table.rowCount()):
            item = table.item(row, 3)
            if item is None:
                continue
            dt = item.data(_ROLE_NEXT_RUN)
            if dt is None:
                continue
            remaining = dt - now
            if remaining.total_seconds() <= 0:
                item.setText("即将执行")
            else:
                total_sec = int(remaining.total_seconds())
                hours, remainder = divmod(total_sec, 3600)
                minutes, seconds = divmod(remainder, 60)
                if hours > 0:
                    item.setText(f"{hours} 时 {minutes} 分 {seconds} 秒后")
                elif minutes > 0:
                    item.setText(f"{minutes} 分 {seconds} 秒后")
                else:
                    item.setText(f"{seconds} 秒后")

    def _refresh_backlog(self) -> None:
        self._lbl_pending.setText(f"待处理投递: {self._storage.count_pending_jobs()}")
        self._lbl_stale.setText(f"超时 Claim: {self._storage.count_stale_claims()}")
        self._lbl_today_jobs.setText(f"今日更新: {self._storage.count_jobs_today()}")
        self._lbl_dispatched.setText(f"今日投递: {self._storage.count_dispatched_today()}")

    def _refresh_recent_runs(self) -> None:
        table = self._runs_table
        table.setRowCount(0)
        runs = self._storage.get_recent_runs(limit=50)
        table.setRowCount(len(runs))
        for i, run in enumerate(runs):
            table.setItem(i, 0, QTableWidgetItem(_fmt_run_time(run.started_at)))
            table.setItem(i, 1, QTableWidgetItem(run.trigger))
            table.setItem(i, 2, QTableWidgetItem(run.account_name))
            table.setItem(i, 3, QTableWidgetItem(_fmt_run_status(run.status)))
            table.setItem(i, 4, QTableWidgetItem(_fmt_run_result(run.result)))
            table.setItem(i, 5, QTableWidgetItem(_fmt_duration(run.started_at, run.finished_at)))


def _fmt_run_time(iso_str: str) -> str:
    try:
        dt = datetime.datetime.fromisoformat(iso_str)
        return dt.strftime("%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return iso_str


def _fmt_run_status(status: str) -> str:
    mapping = {"success": "✓", "failed": "✗", "skipped": "⊘"}
    return mapping.get(status, status)


def _fmt_run_result(result: dict) -> str:
    parts = [f"{k}={v}" for k, v in result.items()]
    text = ", ".join(parts)
    return text[:40] + "…" if len(text) > 40 else text


def _fmt_duration(start: str, end: str) -> str:
    try:
        s = datetime.datetime.fromisoformat(start)
        e = datetime.datetime.fromisoformat(end)
        secs = (e - s).total_seconds()
        return f"{secs:.1f}s"
    except (ValueError, TypeError):
        return "—"
