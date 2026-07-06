from __future__ import annotations

import asyncio
import datetime
import logging
import sys
import threading
from pathlib import Path
from typing import Any

from PySide6.QtCore import Signal, QObject
from PySide6.QtWidgets import QApplication

from bzauto.ui.control_panel import ControlPanel
from bzauto.ui.log_window import LogWindow
from bzauto.pages.chat_list import BossChatListPage
from bzauto.flows.scrape_chat import BossScrapeChatFlow
from bzauto.server.tab_session import TabSession
from bzauto.server.lifecycle import start_server

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

log = logging.getLogger("boss.ui")


class _TaskBridge(QObject):
    """跨线程信号桥：后台线程 → Qt 主线程。"""

    buttons_enabled = Signal(bool)
    log_msg = Signal(str)


class BzAutoApp:
    """主应用控制器：单一后台线程 + event loop + 任务管理。"""

    def __init__(self) -> None:
        self._app = QApplication(sys.argv)
        self._app.setQuitOnLastWindowClosed(True)

        self._control = ControlPanel()
        self._log_win = LogWindow()
        self._bridge = _TaskBridge()

        # 后台线程 + event loop（所有异步操作在此执行）
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._start_bg_thread()

        # 任务状态
        self._current_task: asyncio.Future | None = None

        self._setup_ui()

    def _start_bg_thread(self) -> None:
        """启动单一后台线程和 event loop。"""
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_bg_loop, daemon=True)
        self._thread.start()

    def _run_bg_loop(self) -> None:
        """后台线程入口：运行 event loop。"""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

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

        # 连接按钮信号
        self._control.btn_scrape_chat.clicked.connect(
            lambda: self._on_scrape_chat()
        )

    def _on_scrape_chat(self) -> None:
        """聊天爬取按钮点击。"""
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)

        async def _task() -> None:
            session = TabSession()
            try:
                page = BossChatListPage(session)
                flow = BossScrapeChatFlow(page, session)
                out_file = output_dir / f"chat_{datetime.datetime.now():%Y%m%d_%H%M%S}.json"
                data = await flow.run(max_scrolls=0, output=out_file)
                log.info("聊天爬取完成: %d 条记录 -> %s", len(data), out_file)
            finally:
                pass

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
        # 通过信号在 Qt 线程恢复按钮
        self._bridge.buttons_enabled.emit(True)

    def run(self) -> None:
        """启动应用。"""
        self._log_win.show()
        self._control.show()
        sys.exit(self._app.exec())


def run_ui() -> None:
    app = BzAutoApp()
    app.run()
