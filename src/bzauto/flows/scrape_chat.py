from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, TYPE_CHECKING

from bzauto.pages.chat_list import BossChatListPage

if TYPE_CHECKING:
    from bzauto.server.tab_session import TabSession

log = logging.getLogger("flow.scrape_chat")


class BossScrapeChatFlow:
    """聊天列表爬取流程编排。"""

    def __init__(self, page: BossChatListPage, session: "TabSession") -> None:
        self._page = page
        self._session = session

    async def run(
        self,
        url: str | None = None,
        *,
        max_scrolls: int = 0,
        output: str | Path | None = None,
    ) -> list[dict[str, Any]]:
        session = self._session

        from bzauto.server.lifecycle import ensure_tab
        await ensure_tab(session, url or 'https://www.zhipin.com/web/geek/chat')
        await session.activate()

        log.info("等待聊天页面加载...")
        loaded = await self._page.is_loaded()
        log.debug("聊天页面加载状态: %s", loaded)
        if not loaded:
            for _ in range(20):
                await asyncio.sleep(0.5)
                if await self._page.is_loaded():
                    loaded = True
                    break

        if not loaded:
            log.warning("聊天列表未加载")
            return []

        all_items: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        async for item, _idx in self._page.iter_chat_items(max_scrolls=max_scrolls):
            key = (item.get("name", ""), item.get("company", ""))
            if key not in seen:
                seen.add(key)
                all_items.append(item)

        log.info("爬取完成: 共 %d 条聊天记录", len(all_items))

        if output:
            path = Path(output)
            path.write_text(
                json.dumps(all_items, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            log.info("数据已保存到 %s", path)

        return all_items
