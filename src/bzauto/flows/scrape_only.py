"""纯爬取流程编排：只收集职位数据，不执行沟通（带 DB upsert）。"""
from __future__ import annotations

import logging

from bzauto.config import get_config
from bzauto.flows.base import BaseFlow
from bzauto.models import JobCard
from bzauto.pages.job_list import BossJobListPage
from bzauto.server.tab_session import TabSession
from bzauto.storage import Storage

log = logging.getLogger("flow.scrape_only")


class BossScrapeOnlyFlow(BaseFlow[BossJobListPage]):
    """纯爬取流程编排：只收集职位数据，不执行沟通。"""

    def __init__(self, page: BossJobListPage, session: TabSession, account_id: str = "main", storage: Storage | None = None) -> None:
        super().__init__(page, session, account_id)
        self._storage = storage
        cfg = get_config()
        self._whitelist = cfg.scrape.filter.whitelist
        self._blacklist = cfg.scrape.filter.blacklist
        self._min_salary = cfg.scrape.filter.min_salary
        self._max_salary = cfg.scrape.filter.max_salary
        self._jobs_url = "https://www.zhipin.com/web/geek/jobs"

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
            whitelist=whitelist or self._whitelist,
            blacklist=blacklist or self._blacklist,
            min_salary=min_salary if min_salary is not None else self._min_salary,
            max_salary=max_salary if max_salary is not None else self._max_salary,
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
    ) -> list[JobCard]:
        await self._setup(url or self._jobs_url, reuse_existing=reuse_existing)

        log.info("切换到期望职位tab...")
        try:
            await self._page.click_expect_tab()
        except Exception:
            log.warning("未找到期望tab，使用默认列表")

        all_jobs: list[JobCard] = []

        seen_hrefs = self._storage.get_seen_job_hrefs() if self._storage else set()
        seen_duplicate: set[tuple[str, str]] = set()

        async for card, idx in self._iter_cards(max_scrolls=max_scrolls, min_salary=min_salary, max_salary=max_salary):
            key = (card.title, card.company)
            if key in seen_duplicate:
                continue
            seen_duplicate.add(key)

            if card.href in seen_hrefs:
                log.debug("跳过已采集: %s", card.href)
                continue

            log.info("  [#%d] %s — %s", idx, card.title, card.salary)
            all_jobs.append(card)

            if self._storage:
                db_dict = card.to_db_dict(self._account_id)
                self._storage.upsert_job(db_dict)
                self._storage.add_seen_job_hrefs([card.href])

        log.info("完成: 共 %d 条匹配职位", len(all_jobs))
        return all_jobs
