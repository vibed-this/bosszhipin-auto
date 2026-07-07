"""ChatScanFlow — 消息扫描（仅爬取聊天，不含删拒）。"""
from __future__ import annotations

import logging

from bzauto.browser.session import BrowserSession
from bzauto.flows.scrape_chat import BossScrapeChatFlow
from bzauto.pages.chat_list import BossChatListPage
from bzauto.storage import Storage

log = logging.getLogger("flow.chat_scan")


class ChatScanFlow:
    """消息扫描 — 仅爬取聊天列表。"""

    def __init__(self, page: BossChatListPage, session: BrowserSession, account_id: str, storage: Storage) -> None:
        self.session = session
        self._account_id = account_id
        self._storage = storage
        self.chat_page = page
        self.scrape_flow = BossScrapeChatFlow(page, session, account_id, storage)

    async def run(self) -> dict:
        url = "https://www.zhipin.com/web/geek/chat"

        await self.session.ensure_tab(url, reuse_existing=True)

        result = await self.scrape_flow.run()

        return {
            "new": result.get("new", 0),
            "updated": result.get("updated", 0),
            "rejections": result.get("rejections", []),
            "unread": result.get("unread", []),
            "followed_up": 0,
        }
