"""Boss直聘职位列表爬取流程编排。"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from bzauto.flows.base import BaseFlow
from bzauto.pages.job_list import BossJobListPage
from bzauto.server.tab_session import TabSession

log = logging.getLogger("flow.scrape")

_WHITELIST = ["前端", "全栈", "Web"]
_BLACKLIST = ["出差"]
_MIN_SALARY = 5
_MAX_SALARY = 7


class BossScrapeFlow(BaseFlow[BossJobListPage]):
    """爬取 + 沟通流程编排。"""

    def __init__(self, page: BossJobListPage, session: TabSession) -> None:
        super().__init__(page, session)

    def _iter_cards(
        self,
        *,
        max_scrolls: int = 10,
        whitelist: list[str] | None = None,
        blacklist: list[str] | None = None,
        min_salary: int | None = None,
        max_salary: int | None = None,
    ):
        return self._page.iter_filtered_cards(
            whitelist=whitelist or _WHITELIST,
            blacklist=blacklist or _BLACKLIST,
            min_salary=min_salary if min_salary is not None else _MIN_SALARY,
            max_salary=max_salary if max_salary is not None else _MAX_SALARY,
            max_scrolls=max_scrolls,
        )

    async def run(
        self,
        url: str | None = None,
        *,
        max_scrolls: int = 10,
        min_salary: int | None = None,
        max_salary: int | None = None,
        reuse_existing: bool = False,
    ) -> list[dict[str, Any]]:
        await self._setup(url, reuse_existing=reuse_existing)

        log.info("切换到期望职位tab...")
        ok = await self._page.click_expect_tab()
        if not ok:
            log.warning("未找到期望tab，使用默认列表")

        all_jobs: list[dict[str, Any]] = []

        async for card, idx in self._iter_cards(max_scrolls=max_scrolls, min_salary=min_salary, max_salary=max_salary):
            log.info("  [#%d] %s — %s", idx, card.get("title"), card.get("salary"))
            all_jobs.append(card)

            await self._page.click_card_at(idx)

            await self._page.click_chat(idx)
            await asyncio.sleep(random.uniform(1.0, 2.0))

            result = await self._page.dismiss_dialogs()
            if not result:
                log.warning("每日沟通上限已达，终止抓取")
                break

            await asyncio.sleep(random.uniform(0.5, 1.0))

        log.info("完成: 共 %d 条匹配职位", len(all_jobs))
        return all_jobs