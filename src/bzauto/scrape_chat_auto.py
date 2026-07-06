"""BOSS直聘聊天列表抓取

用法::

    import asyncio
    from bzauto.scrape_chat_auto import BossChatAuto

    async def main():
        async with BossChatAuto() as auto:
            data = await auto.run(max_scrolls=2)
            print(f"抓取到 {len(data.get('items', []))} 条聊天记录")

    asyncio.run(main())
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Any

import keyboard

from bzauto.config import get_config
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
        host: str | None = None,
        port: int | None = None,
        account_id: str = "main",
    ) -> None:
        cfg = get_config()
        self._host = host or cfg.server.host
        self._port = port or cfg.server.port
        self.session = session or TabSession(account_id=account_id)
        self.page = BossChatListPage(self.session)
        self.flow = BossScrapeChatFlow(self.page, self.session, account_id)

    async def run(
        self,
        url: str | None = None,
        *,
        max_scrolls: int = 0,
        output: str | None = None,
    ) -> dict[str, Any]:
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
            items = data.get("items", [])
            print(f"抓取到 {len(items)} 条聊天记录 (新增 {data.get('new', 0)}, 拒信 {len(data.get('rejections', []))})")

    asyncio.run(_main())


if __name__ == "__main__":
    cli_main()
