"""BOSS直聘自动化抓取

用法::

    import asyncio
    from bzauto.scrape_jobs import BossJobsAuto

    async def main():
        async with BossJobsAuto() as auto:
            jobs = await auto.run("https://www.zhipin.com/...")
            print(f"抓取到 {len(jobs)} 条职位")

    asyncio.run(main())
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Any

import keyboard

from bzauto.server.session import TabSession
from bzauto.server.lifecycle import get_registry, start_server, stop_server
from bzauto.pages.job_list import BossJobListPage
from bzauto.flows.scrape import BossScrapeFlow

log = logging.getLogger("boss.main")


class BossJobsAuto:
    """Boss直聘自动化入口（组合模式）。"""

    def __init__(
        self,
        session: TabSession | None = None,
        *,
        host: str = "127.0.0.1",
        port: int = 8765,
    ) -> None:
        self._host = host
        self._port = port
        self.session = session or TabSession()
        self.page = BossJobListPage(self.session)
        self.flow = BossScrapeFlow(self.page, self.session)

    async def run(
        self,
        url: str | None = None,
        max_scrolls: int = 10,
        reuse_existing: bool = False,
    ) -> list[dict[str, Any]]:
        return await self.flow.run(url, max_scrolls=max_scrolls, reuse_existing=reuse_existing)

    async def __aenter__(self) -> BossJobsAuto:
        await start_server(self._host, self._port)
        return self

    async def __aexit__(self, *args: object) -> None:
        pass


def cli_main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    log.info("按 Ctrl+E 强制退出")

    keyboard.add_hotkey("ctrl+e", lambda: os._exit(0))

    async def _main():
        url = sys.argv[1] if len(sys.argv) > 1 else "https://www.zhipin.com/web/geek/jobs"
        async with BossJobsAuto() as auto:
            jobs = await auto.run(url, reuse_existing=True)
            print(f"抓取到 {len(jobs)} 条职位")

    asyncio.run(_main())


if __name__ == "__main__":
    cli_main()
