"""UrgeFlow — 催促：对未回复的对话重新发送打招呼语。"""
from __future__ import annotations

import asyncio
import logging
import random

from bzauto.browser.session import BrowserSession
from bzauto.config import get_config
from bzauto.pages.chat_list import BossChatListPage
from bzauto.results import UrgeResult
from bzauto.storage import Storage

log = logging.getLogger("flow.urge")


class UrgeFlow:
    """催促流程：查找 DB 中我方最后发送且无回复的对话，重新发送招呼语。"""

    def __init__(self, page: BossChatListPage, session: BrowserSession, account_id: str, storage: Storage) -> None:
        self._page = page
        self._session = session
        self._account_id = account_id
        self._storage = storage

    async def run(self) -> UrgeResult:
        convos = self._storage.conversations.list_unreplied(self._account_id)
        if not convos:
            log.info("无待催促对话: account=%s", self._account_id)
            return UrgeResult(skipped=True, total=0)

        log.info("开始催促: account=%s count=%d", self._account_id, len(convos))
        await self._session.ensure_tab("https://www.zhipin.com/web/geek/chat")
        await self._session.activate()

        # 等待 Vue 数据加载
        await asyncio.sleep(10)

        # 一次性获取页面所有对话项的 unique_id 映射
        all_items = await self._page.get_chat_items()
        by_uid = {item.uniqueId: item for item in all_items if item.uniqueId}
        by_name = {f"{item.name}:{item.company}": item for item in all_items}

        success = 0
        failed = 0

        for conv in convos:
            try:
                uid = None
                if conv.unique_id and conv.unique_id in by_uid:
                    uid = conv.unique_id
                else:
                    key = f"{conv.name}:{conv.company}"
                    match = by_name.get(key)
                    if match and match.uniqueId:
                        uid = match.uniqueId

                if not uid:
                    log.warning("未在页面找到对话: %s·%s", conv.name, conv.company)
                    failed += 1
                    continue

                await self._page.click_chat_item(uid)
                await self._page.wait_conversation_selected(timeout=10)

                greeting = get_config().scrape.greeting
                await self._page.send_message(greeting)
                log.info("已催促: %s·%s", conv.name, conv.company)
                success += 1

                await asyncio.sleep(random.uniform(2.0, 4.0))

            except Exception as e:
                log.error("催促异常: %s·%s - %s", conv.name, conv.company, e)
                failed += 1

        log.info("催促完成: account=%s success=%d failed=%d total=%d",
                 self._account_id, success, failed, len(convos))
        return UrgeResult(success=success, failed=failed, total=len(convos))
