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


class BossScrapeFlow:
    """爬取 + 沟通流程编排。"""

    def __init__(self, page: BossJobListPage, session: "TabSession") -> None:
        self._page = page
        self._session = session

    async def run(
        self,
        url: str | None = None,
        *,
        max_scrolls: int = 10,
        reuse_existing: bool = False,
    ) -> list[dict[str, Any]]:
        session = self._session

        from bzauto.server.lifecycle import ensure_tab
        await ensure_tab(session, url, reuse_existing=reuse_existing)
        await session.activate()

        log.info("等待页面加载...")
        loaded = await self._page.wait_loaded(timeout=20.0)
        if not loaded:
            log.warning("页面加载超时，继续尝试...")

        all_jobs: list[dict[str, Any]] = []

        for scroll in range(max_scrolls):
            if scroll > 0:
                log.info("翻页 #%d...", scroll)
                ok = await self._page.scroll_next_page()
                if not ok:
                    break
                await asyncio.sleep(random.uniform(0.5, 1.5))

            cards = await self._page.get_job_cards(limit=30)
            if not cards:
                log.info("没有更多职位")
                break

            log.info("第 %d 页: %d 个职位", scroll + 1, len(cards))

            for i, card in enumerate(cards):
                title = (card.get("title") or "").strip().lower()
                if not any(kw in title for kw in _WHITELIST):
                    continue
                if any(kw in title for kw in _BLACKLIST):
                    continue

                log.info("  [#%d] %s — %s", i, card.get("title"), card.get("salary_raw"))
                all_jobs.append(card)

                bbox = await self._session.bbox(
                    select="a.op-btn-chat",
                    filter={"nth": len(all_jobs) - 1},
                )
                if bbox:
                    await self._session.click(bbox["physical"]["cx"], bbox["physical"]["cy"])
                    await asyncio.sleep(random.uniform(1.0, 2.0))

                    sent = await self._send_greeting()
                    if sent:
                        log.info("  打招呼成功")
                    else:
                        log.warning("  打招呼可能失败")

                    await self._dismiss_dialogs()

            await asyncio.sleep(random.uniform(0.5, 1.0))

        log.info("完成: 共 %d 条匹配职位", len(all_jobs))
        return all_jobs

    async def _send_greeting(self) -> bool:
        try:
            chat_btn = await self._session.bbox("a.op-btn-chat")
            if chat_btn:
                await self._session.click(chat_btn["physical"]["cx"], chat_btn["physical"]["cy"])
                await asyncio.sleep(1.0)
                return True
        except Exception as e:
            log.debug("打招呼异常: %s", e)
        return False

    async def _dismiss_dialogs(self) -> None:
        for selector in [
            ".greet-boss-dialog .cancel-btn",
            ".dialog-close",
            "[class*='dialog'] .close",
            ".tips-success .close",
        ]:
            try:
                bbox = await self._session.bbox(selector)
                if bbox:
                    log.info("关闭弹窗: %s", selector)
                    await self._session.click(bbox["physical"]["cx"], bbox["physical"]["cy"])
                    await asyncio.sleep(0.5)
            except Exception:
                pass
