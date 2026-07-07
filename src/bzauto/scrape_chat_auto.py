"""BOSS直聘聊天列表抓取 — QWebEngineView 模式。

用法::

    boss-scrape-chat [url]
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

import keyboard
import qasync

from PySide6.QtWidgets import QApplication

from bzauto.browser import BrowserManager
from bzauto.browser.manager import _set_browser_manager
from bzauto.config import get_config
from bzauto.pages.chat_list import BossChatListPage
from bzauto.flows.scrape_chat import BossScrapeChatFlow

log = logging.getLogger("boss.chat")


class BossChatAuto:
    """Boss直聘聊天列表抓取入口（最小 Qt 引导，无控制面板）。"""

    def __init__(self, account_id: str = "main") -> None:
        self._account_id = account_id
        self._cfg = get_config()

    async def run(
        self,
        url: str | None = None,
        *,
        output: str | None = None,
    ):
        from bzauto.results import ScrapeChatResult

        accounts = [{"id": self._account_id, "name": self._account_id}]
        manager = BrowserManager(accounts)
        _set_browser_manager(manager)
        manager.show()

        session = manager.get_session(self._account_id)
        page = BossChatListPage(session)
        flow = BossScrapeChatFlow(page, session, self._account_id)

        result = await flow.run(url, output=output)

        manager.close()
        return result


def cli_main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    for _log_name in ("httpcore", "httpx", "qasync", "apscheduler", "asyncio"):
        logging.getLogger(_log_name).setLevel(logging.WARNING)
    log.info("按 Ctrl+E 强制退出")

    keyboard.add_hotkey("ctrl+e", lambda: os._exit(0))

    app = QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    async def _main():
        url = sys.argv[1] if len(sys.argv) > 1 else "https://www.zhipin.com/web/geek/chat"
        output = sys.argv[2] if len(sys.argv) > 2 else None
        auto = BossChatAuto()
        data = await auto.run(url, output=output)
        print(f"抓取到 {len(data.items)} 条聊天记录 (新增 {data.new}, 拒信 {len(data.rejections)})")

    loop.create_task(_main())
    with loop:
        loop.run_forever()


if __name__ == "__main__":
    cli_main()
