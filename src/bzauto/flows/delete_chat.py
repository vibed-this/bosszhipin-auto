from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, TYPE_CHECKING

from bzauto.pages.chat_list import BossChatListPage

if TYPE_CHECKING:
    from bzauto.server.tab_session import TabSession

log = logging.getLogger("flow.delete_chat")


class BossDeleteChatFlow:
    """遍历消息列表，删除符合条件的聊天记录。

    筛选条件：status == 已读 且 lastMsg 以"您好"开头。
    """

    def __init__(self, page: BossChatListPage, session: "TabSession") -> None:
        self._page = page
        self._session = session

    async def run(
        self,
        url: str | None = None,
        *,
        dry_run: bool = True,
    ) -> list[dict[str, Any]]:
        session = self._session

        from bzauto.server.lifecycle import ensure_tab
        await ensure_tab(session, url or "https://www.zhipin.com/web/geek/chat", reuse_existing=True)
        await session.activate()

        log.info("等待聊天页面加载...")
        loaded = await self._page.is_loaded()
        if not loaded:
            for _ in range(20):
                await asyncio.sleep(0.5)
                if await self._page.is_loaded():
                    loaded = True
                    break
        if not loaded:
            log.warning("聊天列表未加载")
            return []

        items = await self._page.get_chat_items_with_status()
        log.info("共 %d 条聊天记录", len(items))

        matched: list[dict[str, Any]] = []
        for i, item in enumerate(items):
            status = item.get("status", "")
            last_msg = item.get("lastMsg", "")
            if status == "已读" and last_msg.startswith("您好"):
                log.info(
                    "匹配 #%d: name=%s company=%s lastMsg=%s",
                    i, item.get("name"), item.get("company"), last_msg[:20],
                )
                matched.append({**item, "_index": i})

        if not matched:
            log.info("没有匹配的聊天记录")
            return []

        log.info("匹配 %d 条，开始删除流程", len(matched))

        deleted: list[dict[str, Any]] = []
        for m in matched:
            idx = m["_index"]
            name = m.get("name", "")
            log.info("--- 处理: %s ---", name)

            ok = await self._page.click_chat_item(idx)
            if not ok:
                log.warning("点击聊天项失败，跳过")
                continue
            await asyncio.sleep(random.uniform(0.5, 1.0))

            ok = await self._page.click_more_button()
            if not ok:
                log.warning("点击更多按钮失败，跳过")
                continue
            await asyncio.sleep(random.uniform(0.3, 0.6))

            ok = await self._page.click_delete_in_menu()
            if not ok:
                log.warning("点击删除失败，跳过")
                continue
            await asyncio.sleep(random.uniform(0.5, 1.0))

            if dry_run:
                log.info("[DRY RUN] 点击取消 (不实际删除)")
                ok = await self._page.click_cancel_in_dialog()
                if not ok:
                    log.warning("点击取消失败")
            else:
                log.info("点击确定 (实际删除)")
                ok = await self._page.click_confirm_in_dialog()
                if not ok:
                    log.warning("点击确定失败")

            await asyncio.sleep(random.uniform(0.5, 1.0))
            deleted.append(m)

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
        log.info("  %s - %s", r.get("name"), r.get("lastMsg"))


if __name__ == "__main__":
    asyncio.run(_main())
