from __future__ import annotations

import asyncio
import datetime
import logging
import sys
import threading
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QApplication

from bzauto.ui.control_panel import ControlPanel
from bzauto.ui.log_window import LogWindow
from bzauto.pages.chat_list import BossChatListPage
from bzauto.flows.scrape_chat import BossScrapeChatFlow
from bzauto.server.session import TabSession
from bzauto.server.lifecycle import get_registry, start_server, ensure_tab

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

log = logging.getLogger("boss.ui")


def _run_async_in_thread(coro_func, *args: Any, **kwargs: Any) -> None:
    """在后台线程中运行异步函数。"""

    def _thread_target():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(coro_func(*args, **kwargs))
        except Exception as e:
            log.error("后台任务异常: %s", e)
        finally:
            loop.close()

    t = threading.Thread(target=_thread_target, daemon=True)
    t.start()


def run_ui() -> None:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    control = ControlPanel()
    log_win = LogWindow()  # 自动挂载 logging Handler

    sg = QApplication.primaryScreen().availableGeometry()
    margin = 20
    gap = 50

    log_win.move(sg.width() - log_win.width() - margin, sg.height() - log_win.height() - margin)
    control.move(sg.width() - control.width() - margin, log_win.y() - control.height() - gap)

    # 连接「聊天爬取」按钮
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    async def _do_scrape_chat():
        await start_server()
        session = TabSession()
        try:
            page = BossChatListPage(session)
            flow = BossScrapeChatFlow(page)
            out_file = output_dir / f"chat_{datetime.datetime.now():%Y%m%d_%H%M%S}.json"
            data = await flow.run(max_scrolls=0, output=out_file)
            log.info("聊天爬取完成: %d 条记录 -> %s", len(data), out_file)
        finally:
            pass

    def on_scrape_chat():
        log.info("开始聊天爬取...")
        _run_async_in_thread(_do_scrape_chat)

    control.btn_scrape_chat.clicked.connect(on_scrape_chat)

    log_win.show()
    control.show()

    sys.exit(app.exec())
