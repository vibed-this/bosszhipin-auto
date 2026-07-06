"""纯爬取流程编排：只收集职位数据，不执行沟通。"""
from __future__ import annotations

import logging
from typing import Any

from bzauto.flows.base import BaseFlow
from bzauto.pages.job_list import BossJobListPage
from bzauto.server.tab_session import TabSession

log = logging.getLogger("flow.scrape_only")


class BossScrapeOnlyFlow(BaseFlow[BossJobListPage]):
    """纯爬取流程编排：只收集职位数据，不执行沟通。"""

    def __init__(self, page: BossJobListPage, session: TabSession) -> None:
        super().__init__(page, session)

    def _iter_cards(
        self,
        *,
        max_scrolls: int = 10,
        whitelist: list[str] | None = None,
        blacklist: list[str] | None = None,
    ):
        from bzauto.flows.scrape import _WHITELIST, _BLACKLIST

        return self._page.iter_filtered_cards(
            whitelist=whitelist or _WHITELIST,
            blacklist=blacklist or _BLACKLIST,
            max_scrolls=max_scrolls,
        )

    async def run(
        self,
        url: str | None = None,
        *,
        max_scrolls: int = 10,
        reuse_existing: bool = False,
    ) -> list[dict[str, Any]]:
        await self._setup(url, reuse_existing=reuse_existing)

        log.info("切换到期望职位tab...")
        ok = await self._page.click_expect_tab()
        if not ok:
            log.warning("未找到期望tab，使用默认列表")

        all_jobs: list[dict[str, Any]] = []

        async for card, idx in self._iter_cards(max_scrolls=max_scrolls):
            log.info("  [#%d] %s — %s", idx, card.get("title"), card.get("salary_raw"))
            all_jobs.append(card)

        log.info("完成: 共 %d 条匹配职位", len(all_jobs))
        return all_jobs