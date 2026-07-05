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

from bzauto.server.session import TabSession
from bzauto.pages.chat_list import BossChatListPage
from bzauto.flows.scrape_chat import BossScrapeChatFlow

log = logging.getLogger("boss.chat")


class BossChatAuto:
    """Boss直聘聊天列表抓取入口（组合模式）。"""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.session = TabSession(host, port)
        self.page = BossChatListPage(self.session)
        self.flow = BossScrapeChatFlow(self.page)

    async def run(
        self,
        *,
        max_scrolls: int = 0,
        output: str | None = None,
    ) -> list[dict[str, Any]]:
        return await self.flow.run(max_scrolls=max_scrolls, output=output)

    async def __aenter__(self) -> BossChatAuto:
        await self.session.start()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.session.stop()


def cli_main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    log.info("按 Ctrl+E 强制退出")

    keyboard.add_hotkey("ctrl+e", lambda: os._exit(0))

    async def _main():
        async with BossChatAuto() as auto:
            data = await auto.run(max_scrolls=2)
            print(f"抓取到 {len(data)} 条聊天记录")

    asyncio.run(_main())


if __name__ == "__main__":
    cli_main()
