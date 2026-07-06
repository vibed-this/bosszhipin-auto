"""BOSS直聘聊天列表抓取

用法::

    import asyncio
    from bzauto.scrape_chat_auto import BossChatAuto

    async def main():
        async with BossChatAuto() as auto:
            data = await auto.run(max_scrolls=2)
            print(f"抓取到 {len(data)} 条聊天记录")

    asyncio.run(main())
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Any

import keyboard

from bzauto.server.tab_session import TabSession
from bzauto.server.lifecycle import start_server, stop_server
from bzauto.pages.chat_list import BossChatListPage
from bzauto.flows.scrape_chat import BossScrapeChatFlow

log = logging.getLogger("boss.chat")


class BossChatAuto:
    """Boss直聘聊天列表抓取入口（组合模式）。"""

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
        self.page = BossChatListPage(self.session)
        self.flow = BossScrapeChatFlow(self.page, self.session)

    async def run(
        self,
        url: str | None = None,
        *,
        max_scrolls: int = 0,
        output: str | None = None,
    ) -> list[dict[str, Any]]:
        return await self.flow.run(url, max_scrolls=max_scrolls, output=output)

    async def __aenter__(self) -> BossChatAuto:
        await start_server(self._host, self._port)
        return self

    async def __aexit__(self, *args: object) -> None:
        await stop_server()


def cli_main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    log.info("按 Ctrl+E 强制退出")

    keyboard.add_hotkey("ctrl+e", lambda: os._exit(0))

    async def _main():
        url = sys.argv[1] if len(sys.argv) > 1 else "https://www.zhipin.com/web/geek/chat"
        output = sys.argv[2] if len(sys.argv) > 2 else None
        async with BossChatAuto() as auto:
            data = await auto.run(url, max_scrolls=2, output=output)
            print(f"抓取到 {len(data)} 条聊天记录")

    asyncio.run(_main())


if __name__ == "__main__":
    cli_main()
