from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, TYPE_CHECKING

from bzauto.pages.job_list import BossJobListPage

if TYPE_CHECKING:
    from bzauto.server.tab_session import TabSession

log = logging.getLogger("flow.scrape")

_WHITELIST = ["前端", "全栈", "Web"]
_BLACKLIST = ["出差"]


class BaseScrapeFlow:
    """爬取流程基类：共享初始化 + 过滤迭代器。"""

    def __init__(self, page: BossJobListPage, session: "TabSession") -> None:
        self._page = page
        self._session = session

    async def _setup(
        self,
        url: str | None = None,
        *,
        reuse_existing: bool = False,
    ) -> None:
        from bzauto.server.lifecycle import ensure_tab
        await ensure_tab(self._session, url, reuse_existing=reuse_existing)
        await self._session.activate()

        log.info("等待页面加载...")
        loaded = await self._page.wait_loaded(timeout=20.0)
        if not loaded:
            log.warning("页面加载超时，继续尝试...")

        log.info("切换到期望职位tab...")
        ok = await self._page.click_expect_tab()
        if not ok:
            log.warning("未找到期望tab，使用默认列表")

    def _iter_cards(
        self,
        *,
        max_scrolls: int = 10,
        whitelist: list[str] | None = None,
        blacklist: list[str] | None = None,
    ):
        return self._page.iter_filtered_cards(
            whitelist=whitelist or _WHITELIST,
            blacklist=blacklist or _BLACKLIST,
            max_scrolls=max_scrolls,
        )


class BossScrapeFlow(BaseScrapeFlow):
    """爬取 + 沟通流程编排。"""

    async def run(
        self,
        url: str | None = None,
        *,
        max_scrolls: int = 10,
        reuse_existing: bool = False,
    ) -> list[dict[str, Any]]:
        await self._setup(url, reuse_existing=reuse_existing)

        all_jobs: list[dict[str, Any]] = []

        async for card, idx in self._iter_cards(max_scrolls=max_scrolls):
            log.info("  [#%d] %s — %s", idx, card.get("title"), card.get("salary_raw"))
            all_jobs.append(card)

            await self._session.execute(
                "(function(){"
                f"  var cards = document.querySelectorAll('li.job-card-box');"
                f"  var c = cards[{idx}];"
                "  if (c) { c.scrollIntoView({block:'center'}); c.click(); }"
                "})()"
            )
            await asyncio.sleep(0.5)

            bbox = await self._session.bbox(select="a.op-btn-chat")
            if bbox:
                log.info(
                    "  点击沟通按钮 #%d  css=(%d,%d)  physical=(%d,%d)",
                    idx,
                    bbox["css"]["cx"], bbox["css"]["cy"],
                    bbox["physical"]["cx"], bbox["physical"]["cy"],
                )
                await self._session.click(bbox["physical"]["cx"], bbox["physical"]["cy"])
                await asyncio.sleep(random.uniform(1.0, 2.0))

                sent = await self._send_greeting()
                if sent:
                    log.info("  打招呼成功")
                else:
                    log.warning("  打招呼可能失败")

                result = await self._dismiss_dialogs()
                if not result:
                    log.warning("每日沟通上限已达，终止抓取")
                    break

            await asyncio.sleep(random.uniform(0.5, 1.0))

        log.info("完成: 共 %d 条匹配职位", len(all_jobs))
        return all_jobs

    async def _send_greeting(self) -> bool:
        try:
            chat_btn = await self._session.bbox("a.op-btn-chat")
            if chat_btn:
                log.info(
                    "  点击打招呼按钮  css=(%d,%d)  physical=(%d,%d)",
                    chat_btn["css"]["cx"], chat_btn["css"]["cy"],
                    chat_btn["physical"]["cx"], chat_btn["physical"]["cy"],
                )
                await self._session.click(chat_btn["physical"]["cx"], chat_btn["physical"]["cy"])
                await asyncio.sleep(1.0)
                return True
        except Exception as e:
            log.debug("打招呼异常: %s", e)
        return False

    async def _check_chat_block_dialog(self) -> bool:
        """检查沟通上限弹窗。返回 True 继续，False 终止。无弹窗返回 True。"""
        raw = await self._session.query(
            select=".chat-block-dialog .chat-block-body",
            return_="raw",
        )
        if not raw:
            return True
        text = raw[0].get("text", "")
        log.info("  沟通上限弹窗: %s", text)

        bbox = await self._session.bbox(select=".chat-block-dialog .sure-btn")
        if bbox and bbox["css"]["cx"] > 0:
            log.info(
                "  点击关闭  css=(%d,%d)  physical=(%d,%d)",
                bbox["css"]["cx"], bbox["css"]["cy"],
                bbox["physical"]["cx"], bbox["physical"]["cy"],
            )
            await self._session.click(bbox["physical"]["cx"], bbox["physical"]["cy"])
            await asyncio.sleep(0.5)

        if "150" in text or "消息已满" in text or "明日再试" in text:
            return False
        return True

    async def _dismiss_dialogs(self) -> bool:
        """关闭弹窗。返回 True 继续，False 终止。"""
        if not await self._check_chat_block_dialog():
            return False

        for selector in [
            ".greet-boss-dialog .cancel-btn",
            ".dialog-close",
            ".dialog-wrap .close",
            ".boss-dialog .close",
            ".tips-success .close",
        ]:
            try:
                bbox = await self._session.bbox(selector)
                if bbox and bbox["css"]["cx"] > 0:
                    log.info(
                        "  关闭弹窗 %s  css=(%d,%d)  physical=(%d,%d)",
                        selector,
                        bbox["css"]["cx"], bbox["css"]["cy"],
                        bbox["physical"]["cx"], bbox["physical"]["cy"],
                    )
                    await self._session.click(bbox["physical"]["cx"], bbox["physical"]["cy"])
                    await asyncio.sleep(0.5)
            except Exception:
                pass
        return True
