"""聊天删除流程编排（DB 驱动）。"""
from __future__ import annotations

import asyncio
import logging
import random

from bzauto.browser.session import BrowserSession
from bzauto.flows.base import BaseFlow
from bzauto.enums import MsgType
from bzauto.models import ChatItem, classify_msg_type
from bzauto.pages.chat_list import BossChatListPage
from bzauto.storage import Storage

log = logging.getLogger("flow.delete_chat")


def _should_delete(msg_type: MsgType) -> bool:
    """判断聊天是否应被删除（委托给 classify_msg_type 判断拒信）。"""
    return msg_type is MsgType.REJECTION


class BossDeleteChatFlow(BaseFlow[BossChatListPage]):
    """遍历消息列表，删除符合条件的聊天记录。

    支持两种模式：
    1. DB 驱动（优先）：从 storage 获取拒信列表，按 unique_id 或 name+company 匹配
    2. 关键词 fallback：页面上有新拒信时关键词匹配删除
    """

    def __init__(self, page: BossChatListPage, session: BrowserSession, account_id: str = "main", storage: Storage | None = None) -> None:
        super().__init__(page, session, account_id)
        self._storage = storage

    async def run(
        self,
        url: str | None = None,
        *,
        dry_run: bool = True,
    ) -> list[ChatItem]:
        from bzauto.pages.chat_list import _CHAT_URL

        await self._setup(url or _CHAT_URL)

        processed: set[str] = set()
        deleted: list[ChatItem] = []

        # 收集 DB 中待删对话（按 msg_type 筛选），优先用 unique_id
        db_targets: dict[str, str] = {}  # unique_id -> conv_id
        db_fallback_keys: set[tuple[str, str]] = set()  # (name, company) fallback
        if self._storage:
            for conv in self._storage.conversations.list(account=self._account_id):
                if classify_msg_type(conv.last_msg, conv.sender, conv.platform_status) is MsgType.REJECTION:
                    if conv.unique_id:
                        db_targets[conv.unique_id] = conv.conv_id
                    elif conv.name and conv.company:
                        db_fallback_keys.add((conv.name, conv.company))

        async for item in self._page.iter_chat_items():
            uid = item.uniqueId
            if not uid or uid in processed:
                continue

            key = (item.name, item.company)
            msg_type = classify_msg_type(item.lastMsg, item.sender, item.status)
            should_del = uid in db_targets or key in db_fallback_keys or _should_delete(msg_type)

            if should_del:
                processed.add(uid)
                log.info("--- 处理: %s %s/%s ---", uid, item.name, item.company)

                try:
                    await self._page.click_chat_item(uid)
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
                if self._storage:
                    cid = db_targets.get(uid)
                    if not cid and item.name and item.company:
                        from bzauto.models import make_conv_id
                        cid = make_conv_id(self._account_id, item.name, item.company)
                    if cid:
                        self._storage.conversations.mark_deleted(cid, self._account_id)

        log.info("完成: 共处理 %d 条", len(deleted))
        return deleted
