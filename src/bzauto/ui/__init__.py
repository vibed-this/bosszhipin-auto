"""Qt 桌面 UI：主窗口(QTabWidget 多账号浏览器) + 浮动面板 + qasync 引导。"""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
import sys
import traceback

import keyboard
import qasync

from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtWidgets import QApplication

from bzauto.browser import BrowserManager, get_browser_manager
from bzauto.browser.manager import _set_browser_manager
from bzauto.config import get_config
from bzauto.notify import get_notifier
from bzauto.storage import Storage
from bzauto.task_runner import ScheduledTask, TaskRunner
from bzauto.scheduler import (
    BzScheduler,
    DeleteChatTask,
    DispatchTask,
    ScrapeChatTask,
    ScrapeManualTask,
    ScrapeTask,
)
from bzauto.ui.control_panel import ControlPanel
from bzauto.ui.log_window import LogWindow
from bzauto.ui.config_dialog import ConfigDialog
from bzauto.ui.data_window import DataWindow
from bzauto.ui.schedule_window import ScheduleWindow

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

# 抑制第三方库调试日志
for _log_name in ("httpcore", "httpx", "qasync", "apscheduler", "asyncio"):
    logging.getLogger(_log_name).setLevel(logging.WARNING)

log = logging.getLogger("boss.ui")


class _TaskBridge(QObject):
    """信号桥（同一线程内，保留以防后续需要跨组件通知）。"""

    buttons_enabled = Signal(bool)
    data_updated = Signal()
    stop_requested = Signal()

    # debug 窗口信号
    debug_result = Signal(str, str, float)
    debug_error = Signal(str, str)
    debug_running = Signal(bool)


class BzAutoApp:
    """主应用控制器：qasync 单线程 + BrowserManager + TaskRunner + Scheduler。"""

    def __init__(self) -> None:
        self._app = QApplication(sys.argv)
        self._app.setQuitOnLastWindowClosed(True)

        self._loop: asyncio.AbstractEventLoop | None = None
        self._storage = Storage()
        self._cfg = get_config()

        # 主窗口 — BrowserManager（QTabWidget 多账号浏览器）
        accounts_list = [
            {"id": a.id, "name": a.name} for a in self._cfg.accounts if a.enabled
        ]
        self._manager = BrowserManager(
            accounts_list, profiles_dir=self._cfg.browser.profiles_dir,
        )
        _set_browser_manager(self._manager)

        self._control = ControlPanel(self._manager)
        self._log_win = LogWindow(self._manager)
        self._data_win: DataWindow | None = None
        self._schedule_win: ScheduleWindow | None = None
        self._account_win: AccountWindow | None = None
        self._debug_win: DebugWindow | None = None

        self._bridge = _TaskBridge()

        # 任务状态
        self._task_runner: TaskRunner | None = None
        self._scheduler: BzScheduler | None = None
        self._current_task: asyncio.Task | None = None
        self._config_dlg: ConfigDialog | None = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        """配置 UI 布局和信号。"""
        sg = QApplication.primaryScreen().availableGeometry()
        margin = 20
        gap = 50

        self._manager.show()
        self._manager.move(0, 0)

        self._control.move(
            sg.width() - self._control.width() - margin,
            margin,
        )
        self._log_win.move(
            sg.width() - self._log_win.width() - margin,
            margin + self._control.height() + gap,
        )

        # 跨线程信号连接（实际同线程，保留 Signal 接口）
        self._bridge.buttons_enabled.connect(self._control.set_buttons_enabled)
        self._bridge.data_updated.connect(self._on_data_updated)
        self._bridge.stop_requested.connect(self._on_stop)

        # 全局快捷键 — 通过 run_coroutine_threadsafe 投递到 qasync 循环
        keyboard.add_hotkey("ctrl+e", lambda: os._exit(0))
        def _stop_threadsafe():
            f = asyncio.run_coroutine_threadsafe(self._async_stop(), self._loop)
            try:
                f.result(timeout=5)
            except Exception:
                pass
        keyboard.add_hotkey("ctrl+w", _stop_threadsafe)

        # 连接按钮信号
        self._control.btn_scrape_chat.clicked.connect(lambda: self._on_scrape_chat())
        self._control.btn_delete_chat.clicked.connect(lambda: self._on_delete_chat())
        self._control.btn_dump.clicked.connect(lambda: self._on_scrape_jobs())
        self._control.btn_batch.clicked.connect(lambda: self._on_batch_chat())
        self._control.btn_start_scheduler.clicked.connect(self._on_start_scheduler)
        self._control.btn_stop_scheduler.clicked.connect(self._on_stop)
        self._control.btn_cancel.clicked.connect(self._on_cancel_task)
        self._control.btn_config.clicked.connect(self._on_open_config)
        self._control.btn_data.clicked.connect(self._on_open_data)
        self._control.btn_account.clicked.connect(self._on_open_account)
        self._control.btn_schedule.clicked.connect(self._on_open_schedule)
        self._control.btn_debug.clicked.connect(self._on_open_debug)

        # 控制台/日志窗口随浏览器窗口最小化/恢复
        self._manager.windowStateChanged.connect(self._on_manager_window_state_changed)
        # 控制台/日志窗口随浏览器窗口激活/失焦
        self._manager.windowActivated.connect(self._on_manager_window_activated)

    def _on_manager_window_state_changed(self, state: Qt.WindowState) -> None:
        if state & Qt.WindowState.WindowMinimized:
            self._control.hide()
            self._log_win.hide()
        else:
            self._control.show()
            self._log_win.show()

    def _on_manager_window_activated(self, active: bool) -> None:
        if active:
            self._control.raise_()
            self._control.activateWindow()
            self._log_win.raise_()
            self._log_win.activateWindow()

    async def _async_stop(self) -> None:
        """协程版停止（被 keyboard 线程调用）。"""
        self._on_stop()

    def _on_open_config(self) -> None:
        self._config_dlg = ConfigDialog(self._control)
        self._config_dlg.finished.connect(self._config_dlg.deleteLater)
        self._config_dlg.finished.connect(self._on_config_closed)
        self._config_dlg.open()

    def _on_config_closed(self) -> None:
        self._config_dlg = None

    def _on_open_data(self) -> None:
        if self._data_win is None:
            self._data_win = DataWindow(self._storage)
        self._data_win.show()
        self._data_win.raise_()
        self._data_win.refresh_all()

    def _on_data_updated(self) -> None:
        if self._data_win is not None and self._data_win.isVisible():
            self._data_win.refresh_all()

    # ── 账号窗口管理 ──

    def _on_open_account(self) -> None:
        if self._account_win is None:
            from bzauto.ui.account_window import AccountWindow
            self._account_win = AccountWindow(self._storage)
        self._account_win.show()
        self._account_win.raise_()
        self._account_win.refresh()

    # ── 调度面板管理 ──

    def _on_open_schedule(self) -> None:
        if self._schedule_win is None:
            self._schedule_win = ScheduleWindow(self)
        self._schedule_win.show()
        self._schedule_win.raise_()

    # ── Debug 窗口管理 ──

    def _on_open_debug(self) -> None:
        if self._debug_win is None:
            from bzauto.ui.debug_window import DebugWindow
            self._debug_win = DebugWindow(self)
            self._bridge.debug_result.connect(self._debug_win.on_result)
            self._bridge.debug_error.connect(self._debug_win.on_error)
            self._bridge.debug_running.connect(self._debug_win.on_running)
        self._debug_win.show()
        self._debug_win.raise_()
        self._debug_win._refresh_status()

    # ── UI 按钮 → ScheduledTask ──

    def _get_selected_account(self) -> str:
        return self._control.selected_account()

    def _on_scrape_chat(self) -> None:
        self._submit(ScrapeChatTask(self._get_selected_account(), self._storage))

    def _on_scrape_jobs(self) -> None:
        self._submit(ScrapeTask(self._get_selected_account(), self._storage))

    def _on_batch_chat(self) -> None:
        self._submit(DispatchTask(self._get_selected_account(), self._storage, get_config().schedule.dispatch_batch_size))

    def _on_delete_chat(self) -> None:
        self._submit(DeleteChatTask(self._get_selected_account(), self._storage))

    def _on_cancel_task(self) -> None:
        """仅取消当前运行任务，不碰调度器。"""
        log.info("取消当前任务")
        if self._task_runner is not None:
            self._task_runner.cancel_current()
        if self._current_task is not None and not self._current_task.done():
            self._current_task.cancel()
            log.info("当前任务已取消")
        self._bridge.buttons_enabled.emit(True)

    def _on_start_scheduler(self) -> None:
        """启动定时调度器。"""
        if self._scheduler is not None and self._scheduler.running:
            log.info("调度器已在运行")
            return
        log.info("启动调度器")
        self._scheduler = BzScheduler(self._task_runner, self._loop, self._storage)
        self._scheduler.start()

    def _on_stop(self) -> None:
        """停止定时调度器，取消当前及队列中所有待执行任务。"""
        log.info("停止信号触发")
        if self._scheduler:
            self._scheduler.stop()
        if self._task_runner is not None:
            self._task_runner.cancel_pending()
        if self._current_task is not None and not self._current_task.done():
            self._current_task.cancel()
            log.info("当前任务已取消")
        self._bridge.buttons_enabled.emit(True)

    # ── 任务管理 ──

    def _submit(self, task: ScheduledTask) -> None:
        if self._current_task is not None and not self._current_task.done():
            log.warning("已有任务在运行，请等待完成")
            return

        self._bridge.buttons_enabled.emit(False)
        self._bridge.debug_running.emit(True)
        log.info("开始 %s...", task.name)

        assert self._loop is not None
        t = self._loop.create_task(self._run_and_notify(task))
        self._current_task = t
        t.add_done_callback(self._on_task_done)

    async def _run_and_notify(self, task: ScheduledTask) -> dict:
        """执行 ScheduledTask 并通过 TaskRunner 排队，完成后通知。"""
        try:
            while self._task_runner is None:
                await asyncio.sleep(0.05)
            result = await self._task_runner.submit_and_wait(task)
            lines = task.format_result(result)
            if lines:
                await get_notifier().send(
                    f"{task.name}完成 {datetime.datetime.now():%m-%d %H:%M}",
                    "\n".join(lines),
                )
            self._bridge.data_updated.emit()
            return result
        except Exception:
            log.error("任务异常 (%s):\n%s", task.name, traceback.format_exc())
            raise

    def _on_task_done(self, future: asyncio.Future) -> None:
        if future.cancelled():
            log.info("任务已取消")
        elif future.exception():
            exc = future.exception()
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            log.error("任务失败:\n%s", tb)
        self._bridge.buttons_enabled.emit(True)
        self._bridge.debug_running.emit(False)

    # ── 公共 Debug 方法 ──

    def run_debug_task(self, task_name: str, account_id: str,
                       timeout: float = 120) -> None:
        if self._current_task is not None and not self._current_task.done():
            log.warning("已有任务在运行，请等待完成")
            return
        self._bridge.debug_running.emit(True)
        self._bridge.buttons_enabled.emit(False)
        log.info("开始 Debug %s (account=%s, timeout=%s)",
                 task_name, account_id, timeout)
        assert self._loop is not None
        t = self._loop.create_task(
            self._run_debug_async(task_name, account_id, timeout),
        )
        self._current_task = t
        t.add_done_callback(self._on_debug_done)

    def run_debug_trigger(self, trigger_name: str, timeout: float = 300) -> None:
        if self._current_task is not None and not self._current_task.done():
            log.warning("已有任务在运行，请等待完成")
            return
        self._bridge.debug_running.emit(True)
        self._bridge.buttons_enabled.emit(False)
        log.info("开始 Debug 触发%s (timeout=%s)", trigger_name, timeout)
        assert self._loop is not None
        t = self._loop.create_task(
            self._run_debug_trigger_async(trigger_name, timeout),
        )
        self._current_task = t
        t.add_done_callback(self._on_debug_done)

    def get_debug_status(self) -> str:
        """返回调度器状态文本（jobs + 连接账号 + 配额）。"""
        lines: list[str] = []
        if self._scheduler and self._scheduler._scheduler.running:
            for job in self._scheduler._scheduler.get_jobs():
                nr = job.next_run_time
                if nr:
                    lines.append(f"{job.id}: {nr:%Y-%m-%d %H:%M:%S}")
                else:
                    lines.append(f"{job.id}: 未调度")
        else:
            lines.append("调度器未运行")
        try:
            bm = get_browser_manager()
            if bm:
                connected = bm.connected_accounts()
                if connected:
                    lines.append(f"\n已加载账号: {', '.join(connected)}")
                else:
                    lines.append("\n已加载账号: 无")
        except Exception:
            lines.append("\n已加载账号: 获取失败")
        for acc in self._storage.accounts.list(enabled_only=True):
            remaining = self._storage.accounts.get_remaining_quota(acc.account_id)
            lines.append(f"  {acc.name or acc.account_id}: 剩余 {remaining}")
        return "\n".join(lines)

    # ── Debug 后台协程 ──

    @staticmethod
    def _create_debug_task(task_name: str, account_id: str, storage: Storage) -> ScheduledTask:
        from bzauto.config import get_config
        mapping = {
            "采集": ScrapeManualTask(account_id, storage),
            "投递": DispatchTask(account_id, storage, get_config().schedule.dispatch_batch_size),
            "消息扫描": ScrapeChatTask(account_id, storage),
            "消息删拒": DeleteChatTask(account_id, storage),
        }
        return mapping[task_name]

    async def _run_debug_async(self, task_name: str, account_id: str,
                               timeout: float) -> None:
        import time
        start = time.monotonic()
        try:
            task = self._create_debug_task(task_name, account_id, self._storage)

            while self._task_runner is None:
                await asyncio.sleep(0.05)
            result = await asyncio.wait_for(
                self._task_runner.submit_and_wait(task), timeout=timeout)

            elapsed = time.monotonic() - start
            lines = task.format_result(result)
            text = f"result = {result}\n\n通知预览:\n" + "\n".join(lines) if lines else f"result = {result}"
            if lines:
                await get_notifier().send(
                    f"[DEBUG] {task.name}完成", "\n".join(lines))
            self._bridge.debug_result.emit(task.name, text, elapsed)

        except asyncio.TimeoutError:
            elapsed = time.monotonic() - start
            self._bridge.debug_error.emit(
                task_name, f"超时 ({elapsed:.1f}s)")
        except Exception:
            self._bridge.debug_error.emit(task_name, traceback.format_exc())

    async def _run_debug_trigger_async(self, trigger_name: str, timeout: float) -> None:
        import time
        start = time.monotonic()
        try:
            trigger_map = {
                "采集": self._scheduler._trigger_scrape,
                "投递": self._scheduler._trigger_dispatch,
                "消息扫描": self._scheduler._trigger_scrape_chat,
                "消息删拒": self._scheduler._trigger_delete_chat,
            }
            await asyncio.wait_for(trigger_map[trigger_name](), timeout=timeout)
            elapsed = time.monotonic() - start
            self._bridge.debug_result.emit(
                f"触发{trigger_name}", "完整触发完成 (通知已发送)", elapsed)
        except asyncio.TimeoutError:
            elapsed = time.monotonic() - start
            self._bridge.debug_error.emit(
                trigger_name, f"超时 ({elapsed:.1f}s, 完整触发)")
        except Exception:
            self._bridge.debug_error.emit(trigger_name, traceback.format_exc())

    def _on_debug_done(self, future: asyncio.Future) -> None:
        self._bridge.debug_running.emit(False)
        self._bridge.buttons_enabled.emit(True)
        # 自动刷新 debug 状态
        if self._debug_win is not None and self._debug_win.isVisible():
            self._debug_win._refresh_status()

    # ── 异步初始化 ──

    async def _init_async(self) -> None:
        """qasync 循环启动后回调：初始化 TaskRunner、Scheduler。"""
        self._task_runner = TaskRunner(self._loop)
        self._scheduler = BzScheduler(self._task_runner, self._loop, self._storage)

        # 启动时维护
        self._storage.jobs.release_stale_claims()
        self._storage.accounts.reset_daily_counts_if_new_day()
        self._storage.runs.purge_old(30)
        self._scheduler.start()
        log.info("系统启动完成: 调度器已运行")

    def run(self) -> None:
        """启动应用（阻塞直至退出）。"""
        self._log_win.show()
        self._control.show()

        loop = qasync.QEventLoop(self._app)
        self._loop = loop
        asyncio.set_event_loop(loop)

        loop.create_task(self._init_async())

        with loop:
            loop.run_forever()


def run_ui() -> None:
    app = BzAutoApp()
    app.run()
