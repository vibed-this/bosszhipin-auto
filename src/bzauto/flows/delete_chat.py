"""聊天删除流程编排。"""
from __future__ import annotations

import asyncio
import logging
import random

from bzauto.flows.base import BaseFlow
from bzauto.models import ChatItem
from bzauto.pages.chat_list import BossChatListPage
from bzauto.server.tab_session import TabSession

log = logging.getLogger("flow.delete_chat")

_DELETE_KEYWORDS = ["抱歉", "不好意思", "对不起", "不合适", "不太合适"]


def _should_delete(status: str, last_msg: str) -> bool:
    if status == "已读" and last_msg.startswith("您好"):
        return True
    for kw in _DELETE_KEYWORDS:
        if kw in last_msg:
            return True
    return False


class BossDeleteChatFlow(BaseFlow[BossChatListPage]):
    """遍历消息列表，删除符合条件的聊天记录。

    条件（任一满足）：
    - status == 已读 且 lastMsg 以"您好"开头
    - lastMsg 包含关键词：抱歉、不好意思、对不起、不合适、不太合适
    """

    def __init__(self, page: BossChatListPage, session: TabSession) -> None:
        super().__init__(page, session)

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

        async for item, idx in self._page.iter_chat_items():
            if item.name and item.company:
                key = (item.name, item.company)
            else:
                key = ("", "")

            if key not in processed and _should_delete(item.status, item.lastMsg):
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

        log.info("完成: 共处理 %d 条", len(deleted))
        return deleted


async def _main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
    from bzauto.server.lifecycle import start_server, get_registry
    from bzauto.server.tab_session import TabSession

    await start_server()
    registry = get_registry()
    import time
    deadline = time.monotonic() + 10.0
    while not registry.is_connected():
        if time.monotonic() > deadline:
            log.error("扩展未连接")
            return
        await asyncio.sleep(0.5)

    session = TabSession(registry)

    page = BossChatListPage(session)
    flow = BossDeleteChatFlow(page, session)
    result = await flow.run(dry_run=True)
    log.info("dry run 结果: %d 条", len(result))
    for r in result:
        log.info("  %s - %s", r.name, r.lastMsg)


if __name__ == "__main__":
    asyncio.run(_main())