"""纯爬取流程编排：只收集职位数据，不执行沟通（带 DB upsert）。"""
from __future__ import annotations

import asyncio
import logging

from bzauto.config import get_config
from bzauto.browser.session import BrowserSession
from bzauto.flows.base import BaseFlow
from bzauto.models import JobCard, make_job_id
from bzauto.pages.job_detail import BossJobDetailPage
from bzauto.pages.job_list import BossJobListPage
from bzauto.storage import Storage

log = logging.getLogger("flow.scrape_manual")


class BossScrapeManualFlow(BaseFlow[BossJobListPage]):
    """纯爬取流程编排：只收集职位数据，不执行沟通。"""

    def __init__(self, page: BossJobListPage, session: BrowserSession, account_id: str = "main", storage: Storage | None = None) -> None:
        super().__init__(page, session, account_id)
        self._storage = storage
        cfg = get_config()
        self._whitelist = cfg.scrape.filter.whitelist
        self._blacklist = cfg.scrape.filter.blacklist
        self._city_blacklist = cfg.scrape.filter.city_blacklist
        self._company_blacklist = cfg.scrape.filter.company_blacklist
        self._min_salary = cfg.scrape.filter.min_salary
        self._max_salary = cfg.scrape.filter.max_salary
        self._jobs_url = "https://www.zhipin.com/web/geek/jobs"
        self._detail_page: BossJobDetailPage | None = BossJobDetailPage(session) if session is not None else None

    def _iter_cards(
        self,
        *,
        max_scrolls: int = 10,
        whitelist: list[str] | None = None,
        blacklist: list[str] | None = None,
        city_blacklist: list[str] | None = None,
        company_blacklist: list[str] | None = None,
        min_salary: int | None = None,
        max_salary: int | None = None,
        max_jobs: int = 0,
    ):
        return self._page.iter_filtered_cards(
            whitelist=whitelist or self._whitelist,
            blacklist=blacklist or self._blacklist,
            city_blacklist=city_blacklist or self._city_blacklist,
            company_blacklist=company_blacklist or self._company_blacklist,
            min_salary=min_salary if min_salary is not None else self._min_salary,
            max_salary=max_salary if max_salary is not None else self._max_salary,
            max_scrolls=max_scrolls,
            max_jobs=max_jobs,
        )

    async def run(
        self,
        url: str | None = None,
        *,
        max_scrolls: int = 10,
        min_salary: int | None = None,
        max_salary: int | None = None,
        max_jobs: int = 0,
    ) -> list[JobCard]:
        await self._setup(url or self._jobs_url)

        log.info("切换到期望职位tab...")
        try:
            await self._page.click_expect_tab()
        except Exception:
            log.warning("未找到期望tab，使用默认列表")

        all_jobs: list[JobCard] = []

        seen_hrefs = self._storage.seen_hrefs.get_all() if self._storage else set()
        seen_duplicate: set[tuple[str, str]] = set()

        async for card, idx in self._iter_cards(max_scrolls=max_scrolls, min_salary=min_salary, max_salary=max_salary, max_jobs=max_jobs):
            key = (card.title, card.company)
            if key in seen_duplicate:
                continue
            seen_duplicate.add(key)

            if card.href in seen_hrefs:
                log.info("已在库中，标记不合适(重复推荐): %s — %s", card.title, card.company)
                try:
                    await self._page.click_card_at(idx)
                    await asyncio.sleep(1.5)
                    await self._page.click_unsuitable_for_current("重复推荐")
                except Exception as e:
                    log.warning("标记不合适失败: %s - %s", card.title, e)
                continue

            log.info("  [#%d] %s — %s", idx, card.title, card.salary)
            all_jobs.append(card)

            if self._storage:
                job_doc = card.to_doc(self._account_id)
                self._storage.jobs.upsert(job_doc)
                self._storage.seen_hrefs.add([card.href])

            if len(all_jobs) >= max_jobs:
                log.info("已达采集上限 %d 条，停止", max_jobs)
                break

        log.info("完成列表采集: 共 %d 条匹配职位", len(all_jobs))

        # 每次爬取后实时抓取详情页数据（tags、experience、degree、job_desc）并写回
        if self._storage and self._detail_page and all_jobs:
            log.info("开始实时抓取详情元数据并写回...")
            enriched = 0
            for i, card in enumerate(all_jobs, 1):
                try:
                    job_id = make_job_id(card.href)

                    # 已有 tags 则跳过详情抓取（支持已有数据的情况）
                    existing = self._storage.jobs.get(job_id)
                    if existing and existing.tags and any(str(t).strip() for t in existing.tags):
                        continue

                    full_url = card.href if card.href.startswith("http") else f"https://www.zhipin.com{card.href}"
                    await self._session.ensure_tab(full_url)

                    await self._detail_page.wait_jd_loaded(timeout=25)
                    await asyncio.sleep(1.0)

                    meta = await self._detail_page.get_job_meta()
                    jd = await self._detail_page.get_job_desc()

                    self._storage.jobs.update_meta(
                        job_id,
                        tags=meta.tags,
                        job_desc=jd,
                        experience=meta.experience,
                        degree=meta.degree,
                        is_headhunter=meta.is_headhunter,
                    )
                    enriched += 1

                    if i % 10 == 0 or i == len(all_jobs):
                        log.info("  详情写回进度: %d/%d (tags=%d)", i, len(all_jobs), len(meta.tags))

                    # 礼貌延迟，避免频繁访问详情页
                    await asyncio.sleep(1.8)
                except Exception as e:
                    log.warning("  详情元数据抓取失败: %s - %s", card.title, e)

            log.info("详情元数据实时写回完成: %d/%d", enriched, len(all_jobs))

        log.info("完成: 共 %d 条匹配职位", len(all_jobs))
        return all_jobs
