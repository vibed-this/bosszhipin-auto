from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from bzauto.flows.scrape import BaseScrapeFlow

if TYPE_CHECKING:
    from bzauto.pages.job_list import BossJobListPage
    from bzauto.server.tab_session import TabSession

log = logging.getLogger("flow.scrape_only")


class BossScrapeOnlyFlow(BaseScrapeFlow):
    """纯爬取流程编排：只收集职位数据，不执行沟通。"""

    def __init__(self, page: "BossJobListPage", session: "TabSession") -> None:
        super().__init__(page, session)

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

        log.info("完成: 共 %d 条匹配职位", len(all_jobs))
        return all_jobs
