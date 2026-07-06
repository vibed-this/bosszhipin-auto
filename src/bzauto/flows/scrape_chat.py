"""聊天列表爬取流程编排（带 DB upsert + 状态推断）。"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from bzauto.config import get_config
from bzauto.enums import ConvStatus
from bzauto.flows.base import BaseFlow
from bzauto.models import ChatItem
from bzauto.pages.chat_list import BossChatListPage, _CHAT_URL
from bzauto.server.tab_session import TabSession
from bzauto.storage import Storage

log = logging.getLogger("flow.scrape_chat")


def infer_status(last_msg: str, platform_status: str, old_status: str) -> str:
    cfg = get_config()
    keywords = cfg.delete.keywords
    if any(kw in last_msg for kw in keywords):
        return ConvStatus.REJECTION
    invitation_keywords = ["面试", "邀约", "到面", "面试邀请"]
    if any(kw in last_msg for kw in invitation_keywords):
        return ConvStatus.INVITATION
    if old_status not in (ConvStatus.REPLIED, ConvStatus.CLOSED, ConvStatus.DELETED, ConvStatus.REJECTION):
        return ConvStatus.PENDING_REPLY
    return old_status


class BossScrapeChatFlow(BaseFlow[BossChatListPage]):
    """聊天列表爬取流程编排。"""

    def __init__(self, page: BossChatListPage, session: TabSession, account_id: str = "main", storage: Storage | None = None) -> None:
        super().__init__(page, session, account_id)
        self._storage = storage
        self._chat_url = _CHAT_URL

    async def run(
        self,
        url: str | None = None,
        *,
        max_scrolls: int = 0,
        output: str | Path | None = None,
    ) -> dict[str, Any]:
        await self._setup(url or self._chat_url, reuse_existing=True)

        all_items: list[ChatItem] = []
        seen: set[tuple[str, str]] = set()

        async for item, _idx in self._page.iter_chat_items(max_scrolls=max_scrolls):
            key = (item.name, item.company)
            if key not in seen:
                seen.add(key)
                all_items.append(item)

        log.info("爬取完成: 共 %d 条聊天记录", len(all_items))

        if self._storage is None:
            return {"items": all_items, "new": 0, "updated": 0, "rejections": [], "unread": []}

        storage = self._storage
        new_count = 0
        updated_count = 0
        rejections: list[str] = []
        unread: list[str] = []

        # 构建已有对话查找表 (conv_id, account) → status
        existing_all = storage.get_conversations("", "")
        existing_map: dict[tuple[str, str], str] = {
            (c.get("conv_id", ""), c.get("account", "")): c.get("status", ConvStatus.NEW)
            for c in existing_all
        }

        for item in all_items:
            conv_dict = item.to_db_dict(self._account_id)
            conv_id = conv_dict["conv_id"]

            is_new = storage.upsert_conversation(conv_dict)
            if is_new:
                new_count += 1
                old_status = ConvStatus.NEW
            else:
                old_status = existing_map.get((conv_id, self._account_id), ConvStatus.NEW)

            status = infer_status(item.lastMsg, item.status, old_status)
            storage.update_conv_status(conv_id, self._account_id, status)

            if status == ConvStatus.REJECTION:
                rejections.append(f"{item.name}·{item.company}: {item.lastMsg}")
            if item.status == "未读":
                unread.append(f"{item.name}·{item.company}")

        if output:
            path = Path(output)
            path.write_text(
                json.dumps([asdict(i) for i in all_items], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        return {
            "items": all_items,
            "new": new_count,
            "updated": updated_count,
            "rejections": rejections,
            "unread": unread,
        }
