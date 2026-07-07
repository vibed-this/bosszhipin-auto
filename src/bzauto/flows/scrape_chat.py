"""聊天列表爬取流程编排（带 DB upsert + 状态推断）。"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from pathlib import Path

from bzauto.browser.session import BrowserSession
from bzauto.enums import ConvStatus, MsgType
from bzauto.flows.base import BaseFlow
from bzauto.models import ChatItem, classify_msg_type, is_older_than_week
from bzauto.pages.chat_list import BossChatListPage, _CHAT_URL
from bzauto.results import ScrapeChatResult
from bzauto.storage import Storage

log = logging.getLogger("flow.scrape_chat")


def infer_status(sender: str, unread_count: int, old_status: str, last_msg_time: str = "") -> str:
    """推断行动性状态，不涉及消息内容分类。"""
    if old_status == ConvStatus.CLOSED:
        return ConvStatus.CLOSED
    if sender == "self":
        return ConvStatus.NONE
    if unread_count > 0:
        if is_older_than_week(last_msg_time):
            return ConvStatus.FOLLOW_UP
        return ConvStatus.PENDING
    return ConvStatus.NONE


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
        await self._setup(url or self._chat_url, reuse_existing=True)

        # 等待消息列表未读红点载入
        log.info("等待消息列表未读红点载入...")
        await asyncio.sleep(10)

        all_items: list[ChatItem] = []
        new_count = 0
        updated_count = 0
        rejections: list[ChatItem] = []
        unread: list[ChatItem] = []

        storage = self._storage

        async for item, _idx in self._page.iter_chat_items():
            all_items.append(item)
            log.info("消息：%s·%s %s", item.name, item.company, item.time)

            if storage:
                conv_doc = item.to_doc(self._account_id)
                conv_id = conv_doc.conv_id

                # 查旧状态（upsert 会覆写 status，必须提前查）
                existing = storage.get_conversation(conv_id, self._account_id)
                old_status = existing.status or ConvStatus.NONE if existing else ConvStatus.NONE

                result = storage.upsert_conversation(conv_doc)
                if result is True:
                    new_count += 1
                elif result is False:
                    updated_count += 1

                status = infer_status(item.sender, item.unread_count, old_status, conv_doc.last_msg_time)
                storage.update_conv_status(conv_id, self._account_id, status)

                if classify_msg_type(item.lastMsg, item.sender, item.status) is MsgType.REJECTION:
                    rejections.append(item)
                if item.sender == "other" and item.unread_count > 0:
                    unread.append(item)

        log.info("爬取完成: 共 %d 条聊天记录", len(all_items))

        if output:
            path = Path(output)
            path.write_text(
                json.dumps([asdict(i) for i in all_items], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        return ScrapeChatResult(
            items=all_items,
            new=new_count,
            updated=updated_count,
            rejections=rejections,
            unread=unread,
        )
