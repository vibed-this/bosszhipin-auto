"""聊天列表爬取流程编排。"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path

from bzauto.flows.base import BaseFlow
from bzauto.models import ChatItem
from bzauto.pages.chat_list import BossChatListPage
from bzauto.server.tab_session import TabSession

log = logging.getLogger("flow.scrape_chat")

_CHAT_URL = "https://www.zhipin.com/web/geek/chat"


class BossScrapeChatFlow(BaseFlow[BossChatListPage]):
    """聊天列表爬取流程编排。"""

    def __init__(self, page: BossChatListPage, session: TabSession) -> None:
        super().__init__(page, session)

    async def run(
        self,
        url: str | None = None,
        *,
        max_scrolls: int = 0,
        output: str | Path | None = None,
    ) -> list[ChatItem]:
        await self._setup(url or _CHAT_URL, reuse_existing=True)

        all_items: list[ChatItem] = []
        seen: set[tuple[str, str]] = set()

        async for item, _idx in self._page.iter_chat_items(max_scrolls=max_scrolls):
            key = (item.name, item.company)
            if key not in seen:
                seen.add(key)
                all_items.append(item)

        log.info("爬取完成: 共 %d 条聊天记录", len(all_items))

        if output:
            path = Path(output)
            path.write_text(
                json.dumps([asdict(i) for i in all_items], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            log.info("数据已保存到 %s", path)

        return all_items