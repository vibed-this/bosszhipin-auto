"""右侧面板状态区：调度状态 + 账号投递进度。"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from bzauto.storage import Storage

if TYPE_CHECKING:
    from bzauto.scheduler import BzScheduler
    from bzauto.task_runner import TaskRunner


class SideStatusPanel(QWidget):
    """控制面板与日志之间的状态区。"""

    def __init__(self, storage: Storage, parent=None) -> None:
        super().__init__(parent)
        self._storage = storage
        self._get_runner: Callable[[], TaskRunner | None] | None = None
        self._get_scheduler: Callable[[], BzScheduler | None] | None = None
        self._next_run_dt: datetime.datetime | None = None

        self.setFont(QFont("Microsoft YaHei", 9))
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(4)

        schedule_box = QGroupBox("调度状态")
        schedule_layout = QVBoxLayout(schedule_box)
        schedule_layout.setContentsMargins(6, 4, 6, 4)
        schedule_layout.setSpacing(2)
        self._lbl_schedule_primary = QLabel("—")
        self._lbl_schedule_primary.setWordWrap(True)
        self._lbl_schedule_secondary = QLabel("")
        self._lbl_schedule_secondary.setWordWrap(True)
        self._lbl_schedule_secondary.setStyleSheet("color: #666;")
        schedule_layout.addWidget(self._lbl_schedule_primary)
        schedule_layout.addWidget(self._lbl_schedule_secondary)
        layout.addWidget(schedule_box)

        progress_box = QGroupBox("投递进度")
        self._progress_layout = QVBoxLayout(progress_box)
        self._progress_layout.setContentsMargins(6, 4, 6, 4)
        self._progress_layout.setSpacing(3)
        self._progress_rows: dict[str, _AccountProgressRow] = {}
        layout.addWidget(progress_box)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)

    def bind(
        self,
        get_runner: Callable[[], TaskRunner | None],
        get_scheduler: Callable[[], BzScheduler | None],
    ) -> None:
        self._get_runner = get_runner
        self._get_scheduler = get_scheduler
        self._timer.start()
        self.refresh()

    def refresh(self) -> None:
        self._refresh_schedule()
        self._refresh_progress()

    def _refresh_schedule(self) -> None:
        runner = self._get_runner() if self._get_runner else None
        scheduler = self._get_scheduler() if self._get_scheduler else None

        if runner and runner.current_task_name:
            primary = f"执行中: {runner.current_task_name}"
            pending = runner.pending_count
            secondary = f"队列等待: {pending}" if pending else ""
            self._next_run_dt = None
            self._lbl_schedule_primary.setText(primary)
            self._lbl_schedule_secondary.setText(secondary)
            return

        if not scheduler or not scheduler.running:
            self._next_run_dt = None
            self._lbl_schedule_primary.setText("调度器已停止")
            self._lbl_schedule_secondary.setText("")
            return

        snapshots = scheduler.snapshot()
        upcoming = [
            job for job in snapshots
            if job.get("next_run_time")
        ]
        if not upcoming:
            self._next_run_dt = None
            self._lbl_schedule_primary.setText("空闲")
            self._lbl_schedule_secondary.setText("暂无计划任务")
            return

        upcoming.sort(key=lambda j: j["next_run_time"])
        job = upcoming[0]
        label = job.get("label", job.get("id", "—"))
        trigger = _short_trigger(job.get("trigger_repr", ""))
        try:
            dt = datetime.datetime.fromisoformat(job["next_run_time"])
            self._next_run_dt = dt
            local_dt = dt.astimezone()
            countdown = _fmt_countdown(dt)
            self._lbl_schedule_primary.setText(f"下一个: {label}")
            self._lbl_schedule_secondary.setText(
                f"触发: {trigger}\n"
                f"时间: {local_dt:%m-%d %H:%M:%S} ({countdown})"
            )
        except (ValueError, TypeError):
            self._next_run_dt = None
            self._lbl_schedule_primary.setText(f"下一个: {label}")
            self._lbl_schedule_secondary.setText(f"触发: {trigger}")

    def _refresh_progress(self) -> None:
        accounts = self._storage.accounts.list(enabled_only=True)
        active_ids = {acc.account_id for acc in accounts}

        for account_id in list(self._progress_rows):
            if account_id not in active_ids:
                row = self._progress_rows.pop(account_id)
                self._progress_layout.removeWidget(row)
                row.deleteLater()

        for acc in accounts:
            name = acc.name or acc.account_id
            count = acc.daily_count
            limit = max(acc.daily_limit, 1)
            if acc.account_id in self._progress_rows:
                self._progress_rows[acc.account_id].update(name, count, limit)
            else:
                row = _AccountProgressRow(name, count, limit)
                self._progress_rows[acc.account_id] = row
                self._progress_layout.addWidget(row)

        if not accounts:
            if not hasattr(self, "_empty_progress_label"):
                self._empty_progress_label = QLabel("无启用账号")
                self._empty_progress_label.setStyleSheet("color: #888;")
                self._progress_layout.addWidget(self._empty_progress_label)
            self._empty_progress_label.show()
        elif hasattr(self, "_empty_progress_label"):
            self._empty_progress_label.hide()


class _AccountProgressRow(QWidget):
    def __init__(self, name: str, count: int, limit: int, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self._name_label = QLabel(name)
        self._count_label = QLabel()
        self._count_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self._name_label)
        header.addStretch()
        header.addWidget(self._count_label)
        layout.addLayout(header)

        self._bar = QProgressBar()
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(8)
        layout.addWidget(self._bar)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Plain)
        sep.setStyleSheet("color: #e0e0e0;")
        layout.addWidget(sep)

        self.update(name, count, limit)

    def update(self, name: str, count: int, limit: int) -> None:
        self._name_label.setText(name)
        self._count_label.setText(f"{count}/{limit}")
        self._bar.setMaximum(limit)
        self._bar.setValue(min(count, limit))
        if count >= limit:
            self._bar.setStyleSheet(
                "QProgressBar::chunk { background-color: #e74c3c; }"
            )
        else:
            self._bar.setStyleSheet(
                "QProgressBar::chunk { background-color: #3498db; }"
            )


def _short_trigger(trigger_repr: str) -> str:
    if not trigger_repr:
        return "—"
    text = trigger_repr
    for prefix in ("cron[", "interval["):
        if text.startswith(prefix):
            text = text[len(prefix):]
    if text.endswith("]"):
        text = text[:-1]
    return text.replace("'", "")


def _fmt_countdown(target: datetime.datetime) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    remaining = target - now
    total_sec = int(remaining.total_seconds())
    if total_sec <= 0:
        return "即将执行"
    hours, remainder = divmod(total_sec, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}时{minutes}分{seconds}秒后"
    if minutes > 0:
        return f"{minutes}分{seconds}秒后"
    return f"{seconds}秒后"