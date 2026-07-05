from __future__ import annotations

import asyncio
import json
import logging
import random
from pathlib import Path
from typing import Any

from bzauto.pages.chat_list import BossChatListPage

log = logging.getLogger("flow.scrape_chat")


class BossScrapeChatFlow:
    """聊天列表爬取流程编排。"""

    def __init__(self, page: BossChatListPage) -> None:
        self._page = page

    async def run(
        self,
        url: str | None = None,
        *,
        max_scrolls: int = 0,
        output: str | Path | None = None,
    ) -> list[dict[str, Any]]:
        session = self._page._session

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

        # 第一屏
        items = await self._page.get_chat_items_with_status()
        log.info("第 1 屏: %d 条", len(items))
        all_items.extend(items)

        # 滚动加载更多
        for scroll in range(max_scrolls):
            if not await self._page.has_more():
                log.info("没有更多数据")
                break

            log.info("翻页 #%d...", scroll + 1)
            await session.scroll_pagedown(presses=3)
            await asyncio.sleep(random.uniform(0.8, 1.5))

            items = await self._page.get_chat_items_with_status()
            # 去重：以 name+company 为 key
            seen = {(it["name"], it["company"]) for it in all_items}
            new_items = [
                it for it in items
                if (it["name"], it["company"]) not in seen
            ]

            if not new_items:
                log.info("无新增数据，停止滚动")
                break

            log.info("第 %d 屏新增: %d 条", scroll + 2, len(new_items))
            all_items.extend(new_items)

        log.info("爬取完成: 共 %d 条聊天记录", len(all_items))

        if output:
            path = Path(output)
            path.write_text(
                json.dumps(all_items, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            log.info("数据已保存到 %s", path)

        return all_items
