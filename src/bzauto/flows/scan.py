"""ScanFlow — 扫描任务编排（爬取 + 删拒 + 状态推断）。"""
from __future__ import annotations

import logging

from bzauto.browser.session import BrowserSession
from bzauto.flows.delete_chat import BossDeleteChatFlow
from bzauto.flows.scrape_chat import BossScrapeChatFlow
from bzauto.pages.chat_list import BossChatListPage
from bzauto.storage import Storage

log = logging.getLogger("flow.scan")


class ScanFlow:
    """编排扫描任务的完整流程。"""

    def __init__(self, page: BossChatListPage, session: BrowserSession, account_id: str, storage: Storage) -> None:
        self.session = session
        self._account_id = account_id
        self._storage = storage
        self.chat_page = page
        self.scrape_flow = BossScrapeChatFlow(page, session, account_id, storage)
        self.delete_flow = BossDeleteChatFlow(page, session, account_id, storage)

    async def run(self) -> dict:
        url = "https://www.zhipin.com/web/geek/chat"

        await self.session.ensure_tab(url, reuse_existing=True)

        result = await self.scrape_flow.run()
        deleted = await self.delete_flow.run(dry_run=False)

        return {
            "new": result.get("new", 0),
            "updated": result.get("updated", 0),
            "deleted": len(deleted),
            "rejections": result.get("rejections", []),
            "unread": result.get("unread", []),
            "followed_up": 0,
        }
