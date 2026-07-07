"""BOSS直聘自动化抓取 — QWebEngineView 模式。

用法::

    boss-scrape [url]
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
from bzauto.models import JobCard
from bzauto.pages.job_list import BossJobListPage
from bzauto.flows.scrape_manual import BossScrapeManualFlow
from bzauto.storage import Storage

log = logging.getLogger("boss.main")


class BossJobsAuto:
    """Boss直聘自动化入口（最小 Qt 引导，无控制面板）。"""

    def __init__(self, account_id: str = "main") -> None:
        self._account_id = account_id
        self._cfg = get_config()
        self._storage = Storage()

    async def run(
        self,
        url: str | None = None,
        max_scrolls: int = 10,
        reuse_existing: bool = False,
    ) -> list[JobCard]:
        accounts = [{"id": self._account_id, "name": self._account_id}]
        manager = BrowserManager(accounts)
        _set_browser_manager(manager)
        manager.show()

        session = manager.get_session(self._account_id)
        page = BossJobListPage(session)
        flow = BossScrapeManualFlow(page, session, self._account_id, self._storage)

        result = await flow.run(url, max_scrolls=max_scrolls, reuse_existing=reuse_existing)

        manager.close()
        return result


def cli_main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    log.info("按 Ctrl+E 强制退出")

    keyboard.add_hotkey("ctrl+e", lambda: os._exit(0))

    app = QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    async def _main():
        url = sys.argv[1] if len(sys.argv) > 1 else "https://www.zhipin.com/web/geek/jobs"
        auto = BossJobsAuto()
        jobs = await auto.run(url, reuse_existing=True)
        print(f"抓取到 {len(jobs)} 条职位")

    loop.create_task(_main())
    with loop:
        loop.run_forever()


if __name__ == "__main__":
    cli_main()
