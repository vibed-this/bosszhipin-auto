"""聊天列表爬取流程编排（带 DB upsert + 状态推断）。"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from bzauto.browser.session import BrowserSession
from bzauto.enums import MsgType
from bzauto.flows.base import BaseFlow
from bzauto.models import ChatItem, classify_msg_type
from bzauto.pages.chat_list import BossChatListPage, _CHAT_URL
from bzauto.results import ScrapeChatResult
from bzauto.storage import Storage

log = logging.getLogger("flow.scrape_chat")


class BossScrapeChatFlow(BaseFlow[BossChatListPage]):
    """聊天列表爬取流程编排。"""

    def __init__(self, page: BossChatListPage, session: BrowserSession, account_id: str = "main", storage: Storage | None = None) -> None:
        super().__init__(page, session, account_id)
        self._storage = storage
        self._chat_url = _CHAT_URL

    async def run(
        self,
        url: str | None = None,
        *,
        output: str | Path | None = None,
    ) -> ScrapeChatResult:
        await self._setup(url or self._chat_url)

        # 等待消息列表未读红点载入
        log.info("等待消息列表未读红点载入...")
        await asyncio.sleep(10)

        all_items: list[ChatItem] = []
        new_count = 0
        updated_count = 0
        rejections: list[ChatItem] = []
        unread: list[ChatItem] = []
        invite_resume: list[ChatItem] = []
        invite_interview: list[ChatItem] = []

        storage = self._storage

        async for item in self._page.iter_chat_items():
            all_items.append(item)
            log.info("消息：%s·%s %s", item.name, item.company, item.time)

            msg_type = classify_msg_type(item.lastMsg, item.sender, item.status)
            if msg_type is MsgType.REJECTION:
                rejections.append(item)
            elif msg_type is MsgType.INVITE_RESUME:
                invite_resume.append(item)
            elif msg_type is MsgType.INVITE_INTERVIEW:
                invite_interview.append(item)
            if item.sender == "other" and item.unread_count > 0:
                unread.append(item)

        log.info("爬取完成: 共 %d 条聊天记录", len(all_items))

        # 一次性批量写入 DB
        if storage and all_items:
            new_count, updated_count = storage.conversations.batch_upsert(
                self._account_id, all_items,
            )
            log.info("DB 写入完成: 新增 %d, 更新 %d", new_count, updated_count)

        if output:
            path = Path(output)
            path.write_text(
                json.dumps([i.model_dump() for i in all_items], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        return ScrapeChatResult(
            items=all_items,
            new=new_count,
            updated=updated_count,
            rejections=rejections,
            unread=unread,
            invite_resume=invite_resume,
            invite_interview=invite_interview,
        )
