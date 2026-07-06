"""聊天删除流程编排（DB 驱动）。"""
from __future__ import annotations

import asyncio
import logging
import random

from bzauto.config import get_config
from bzauto.enums import ConvStatus
from bzauto.flows.base import BaseFlow
from bzauto.models import ChatItem
from bzauto.pages.chat_list import BossChatListPage
from bzauto.server.tab_session import TabSession
from bzauto.storage import Storage

log = logging.getLogger("flow.delete_chat")


def _should_delete(status: str, last_msg: str, keywords: list[str]) -> bool:
    if status == "已读" and last_msg.startswith("您好"):
        return True
    for kw in keywords:
        if kw in last_msg:
            return True
    return False


class BossDeleteChatFlow(BaseFlow[BossChatListPage]):
    """遍历消息列表，删除符合条件的聊天记录。

    支持两种模式：
    1. DB 驱动（优先）：从 storage 获取拒信列表，按 name+company 匹配删除
    2. 关键词 fallback：页面上有新拒信时关键词匹配删除
    """

    def __init__(self, page: BossChatListPage, session: TabSession, account_id: str = "main", storage: Storage | None = None) -> None:
        super().__init__(page, session, account_id)
        self._storage = storage
        self._keywords = get_config().delete.keywords

    async def run(
        self,
        url: str | None = None,
        *,
        dry_run: bool = True,
    ) -> list[ChatItem]:
        from bzauto.pages.chat_list import _CHAT_URL

        await self._setup(url or _CHAT_URL, reuse_existing=True)

        processed: set[tuple[str, str]] = set()
        deleted: list[ChatItem] = []

        # 收集 DB 中待删对话
        db_targets: set[tuple[str, str]] = set()
        if self._storage:
            rejections = self._storage.get_conversations_by_status(ConvStatus.REJECTION, self._account_id)
            for conv in rejections:
                name = conv.get("name", "")
                company = conv.get("company", "")
                if name and company:
                    db_targets.add((name, company))

        async for item, idx in self._page.iter_chat_items():
            if item.name and item.company:
                key = (item.name, item.company)
            else:
                key = ("", "")

            if key in processed:
                continue

            should_del = key in db_targets or _should_delete(item.status, item.lastMsg, self._keywords)

            if should_del:
                processed.add(key)
                log.info("--- 处理 #%d: %s ---", idx, item.name)

                try:
                    await self._page.click_chat_item(idx)
                except Exception:
                    continue
                await asyncio.sleep(random.uniform(0.5, 1.0))

                try:
                    await self._page.click_more_button()
                except Exception:
                    continue
                await asyncio.sleep(random.uniform(0.3, 0.6))

                try:
                    await self._page.click_delete_in_menu()
                except Exception:
                    continue
                await asyncio.sleep(random.uniform(0.5, 1.0))

                try:
                    if dry_run:
                        log.info("[DRY RUN] 点击取消")
                        await self._page.click_cancel_in_dialog()
                    else:
                        log.info("点击确定")
                        await self._page.click_confirm_in_dialog()
                except Exception:
                    log.warning("对话框操作失败")

                await asyncio.sleep(random.uniform(0.5, 1.0))
                deleted.append(item)

                # DB 标记已删除
                if self._storage and key in db_targets and item.name and item.company:
                    from bzauto.storage import _conv_id
                    cid = _conv_id(self._account_id, item.name, item.company)
                    self._storage.mark_deleted(cid, self._account_id)

        log.info("完成: 共处理 %d 条", len(deleted))
        return deleted
