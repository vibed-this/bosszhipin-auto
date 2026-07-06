from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any

import keyboard

from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtWidgets import QApplication

from bzauto.ui.control_panel import ControlPanel
from bzauto.ui.log_window import LogWindow
from bzauto.ui.config_dialog import ConfigDialog
from bzauto.ui.data_window import DataWindow
from bzauto.pages.chat_list import BossChatListPage
from bzauto.pages.job_list import BossJobListPage
from bzauto.flows.scrape_chat import BossScrapeChatFlow
from bzauto.flows.scrape_only import BossScrapeOnlyFlow
from bzauto.flows.scrape import BossScrapeFlow
from bzauto.flows.delete_chat import BossDeleteChatFlow
from bzauto.server.tab_session import TabSession
from bzauto.server.lifecycle import start_server, get_registry
from bzauto.storage import Storage
from bzauto.task_runner import TaskRunner
from bzauto.scheduler import BzScheduler

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

log = logging.getLogger("boss.ui")


class _TaskBridge(QObject):
    """跨线程信号桥：后台线程 → Qt 主线程。"""

    buttons_enabled = Signal(bool)
    data_updated = Signal()


class BzAutoApp:
    """主应用控制器：单一后台线程 + event loop + 任务管理。"""

    def __init__(self) -> None:
        self._app = QApplication(sys.argv)
        self._app.setQuitOnLastWindowClosed(True)

        self._storage = Storage()
        self._control = ControlPanel()
        self._log_win = LogWindow()
        self._data_win: DataWindow | None = None
        self._bridge = _TaskBridge()

        # 后台线程 + event loop（所有异步操作在此执行）
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._start_bg_thread()

        # 任务状态
        self._current_task: asyncio.Future | None = None
        self._task_runner: TaskRunner | None = None
        self._scheduler: BzScheduler | None = None
        self._config_dlg: ConfigDialog | None = None

        self._setup_ui()

    def _start_bg_thread(self) -> None:
        """启动单一后台线程和 event loop。"""
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_bg_loop, daemon=True)
        self._thread.start()

    def _run_bg_loop(self) -> None:
        """后台线程入口：运行 event loop。"""
        asyncio.set_event_loop(self._loop)
        # 初始化 TaskRunner 和 Scheduler
        self._task_runner = TaskRunner(self._loop)
        self._scheduler = BzScheduler(self._task_runner, self._loop, self._storage)
        self._loop.call_soon(self._init_scheduler)
        self._loop.run_forever()

    async def _init_scheduler(self) -> None:
        """启动时恢复 + 启动调度器。"""
        await start_server()
        self._storage.release_stale_claims()
        self._storage.reset_daily_counts_if_new_day()
        self._scheduler.start()
        log.info("系统启动完成: 调度器已运行")

    def _setup_ui(self) -> None:
        """配置 UI 布局和信号。"""
        sg = QApplication.primaryScreen().availableGeometry()
        margin = 20
        gap = 50

        self._log_win.move(
            sg.width() - self._log_win.width() - margin,
            sg.height() - self._log_win.height() - margin,
        )
        self._control.move(
            sg.width() - self._control.width() - margin,
            self._log_win.y() - self._control.height() - gap,
        )

        # 跨线程信号连接
        self._bridge.buttons_enabled.connect(self._control.set_buttons_enabled)
        self._bridge.data_updated.connect(self._on_data_updated)

        # 全局退出快捷键
        keyboard.add_hotkey("ctrl+e", lambda: os._exit(0))
        log.info("按 Ctrl+E 强制退出")

        # 连接按钮信号
        self._control.btn_scrape_chat.clicked.connect(lambda: self._on_scrape_chat())
        self._control.btn_delete_chat.clicked.connect(lambda: self._on_delete_chat())
        self._control.btn_dump.clicked.connect(lambda: self._on_scrape_jobs())
        self._control.btn_batch.clicked.connect(lambda: self._on_batch_chat())
        self._control.btn_config.clicked.connect(self._on_open_config)
        self._control.btn_data.clicked.connect(self._on_open_data)

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

    def _on_scrape_chat(self) -> None:
        """聊天爬取。"""
        async def _task() -> None:
            session = TabSession()
            page = BossChatListPage(session)
            flow = BossScrapeChatFlow(page, session, "main", self._storage)
            result = await flow.run(max_scrolls=0)
            log.info("聊天爬取完成: %d 条", len(result.get("items", [])))

        self._run_task(_task)

    def _on_scrape_jobs(self) -> None:
        """职位爬取（纯抓取，不沟通）。"""
        async def _task() -> None:
            session = TabSession()
            page = BossJobListPage(session)
            flow = BossScrapeOnlyFlow(page, session, "main", self._storage)
            jobs = await flow.run(max_scrolls=10)
            log.info("职位爬取完成: %d 条 -> DB", len(jobs))
            self._bridge.data_updated.emit()

        self._run_task(_task)

    def _on_batch_chat(self) -> None:
        """批量沟通（抓取 + 自动沟通）。"""
        async def _task() -> None:
            session = TabSession()
            page = BossJobListPage(session)
            flow = BossScrapeFlow(page, session, "main", self._storage)
            jobs = await flow.run(max_scrolls=10)
            log.info("批量沟通完成: %d 条 -> DB", len(jobs))
            self._bridge.data_updated.emit()

        self._run_task(_task)

    def _on_delete_chat(self) -> None:
        """聊天删拒：遍历聊天列表，删除拒信。"""
        async def _task() -> None:
            session = TabSession()
            page = BossChatListPage(session)
            flow = BossDeleteChatFlow(page, session, "main", self._storage)
            result = await flow.run(dry_run=False)
            log.info("聊天删拒完成: 共删除 %d 条", len(result))
            self._bridge.data_updated.emit()

        self._run_task(_task)

    def _run_task(self, coro_func: Any, *args: Any, **kwargs: Any) -> None:
        """提交异步任务到后台 loop 执行。互斥：同时只允许一个任务。"""
        if self._current_task is not None and not self._current_task.done():
            log.warning("已有任务在运行，请等待完成")
            return

        self._bridge.buttons_enabled.emit(False)
        log.info("开始任务...")

        self._current_task = asyncio.run_coroutine_threadsafe(
            self._wrap_task(coro_func, *args, **kwargs),
            self._loop,
        )
        self._current_task.add_done_callback(self._on_task_done)

    async def _wrap_task(self, coro_func: Any, *args: Any, **kwargs: Any) -> Any:
        """包装任务：确保服务器已启动 + 异常处理。"""
        try:
            await start_server()
            return await coro_func(*args, **kwargs)
        except Exception as e:
            log.error("任务异常: %s", e)
            raise

    def _on_task_done(self, future: asyncio.Future) -> None:
        """任务完成回调：恢复按钮状态。"""
        if future.cancelled():
            log.info("任务已取消")
        elif future.exception():
            log.error("任务失败: %s", future.exception())
        self._bridge.buttons_enabled.emit(True)

    def run(self) -> None:
        """启动应用。"""
        self._log_win.show()
        self._control.show()
        sys.exit(self._app.exec())


def run_ui() -> None:
    app = BzAutoApp()
    app.run()
