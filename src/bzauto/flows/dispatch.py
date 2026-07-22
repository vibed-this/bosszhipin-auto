"""DispatchFlow — 从 DB pending 池取 job 并按 href 直达详情页沟通。"""
from __future__ import annotations

import asyncio
import logging
import random

from bzauto.browser.session import BrowserSession
from bzauto.config import get_config
from bzauto.filter import match_blacklist, match_city_blacklist
from bzauto.flows.base import BaseFlow
from bzauto.pages.chat_list import BossChatListPage
from bzauto.pages.job_detail import BossJobDetailPage
from bzauto.pages.job_list import BossJobListPage
from bzauto.results import DispatchResult
from bzauto.storage import Storage

log = logging.getLogger("flow.dispatch")


class DispatchFlow(BaseFlow[BossJobListPage]):
    """从 DB pending 池取 job 并按 href 直达详情页沟通。"""

    def __init__(self, page: BossJobListPage, session: BrowserSession, account_id: str, storage: Storage) -> None:
        super().__init__(page, session, account_id)
        self._storage = storage
        self._chat_page = BossChatListPage(session)
        self._detail_page = BossJobDetailPage(session)
        cfg_filter = get_config().scrape.filter
        self._blacklist = cfg_filter.blacklist
        self._city_blacklist = cfg_filter.city_blacklist
        self._company_blacklist = cfg_filter.company_blacklist

    async def run(self, batch_size: int = 50) -> DispatchResult:
        remaining = self._storage.accounts.get_remaining_quota(self._account_id)
        if remaining <= 0:
            log.info("配额已满: account=%s", self._account_id)
            return DispatchResult(success=0, failed=0, skipped=True)

        jobs = self._storage.jobs.list(dispatch_status="pending", limit=min(remaining, batch_size))
        if not jobs:
            log.info("无待办 job，跳过投递: account=%s", self._account_id)
            return DispatchResult(success=0, failed=0, skipped=True)

        log.info("开始投递: account=%s batch=%d", self._account_id, len(jobs))

        await self._session.activate()

        success = 0
        failed = 0
        filtered = 0

        for job in jobs:
            job_id = job.job_id
            claimed = self._storage.jobs.claim(job_id, self._account_id)
            if not claimed:
                log.debug("job 已被领取: %s", job_id)
                continue

            # 投递前再次用城市/公司黑名单防御过滤（使用 DB 中已存数据）
            city = (job.location[0] if job.location else "") if isinstance(job.location, list) else ""
            matched_city = match_city_blacklist(city or job.location, self._city_blacklist)
            matched_company = match_blacklist(job.company, self._company_blacklist)
            if matched_city or matched_company:
                reason = f"城市黑名单: {matched_city}" if matched_city else f"公司黑名单: {matched_company}"
                log.info("%s，跳过投递: %s — %s", reason, job.title, job.company)
                self._storage.jobs.mark_filtered(job_id, note=reason)
                filtered += 1
                continue

            try:
                href = job.href
                full_url = href if href.startswith("http") else f"https://www.zhipin.com{href}"
                await self._session.ensure_tab(full_url)

                await self._detail_page.wait_jd_loaded()

                # 抓取详情页元数据（包含 tags）和职位描述
                meta = await self._detail_page.get_job_meta()
                jd = await self._detail_page.get_job_desc()

                # 持久化 tags / experience / degree / job_desc / is_headhunter（无论是否过滤）
                self._storage.jobs.update_meta(
                    job_id,
                    tags=meta.tags,
                    job_desc=jd,
                    experience=meta.experience,
                    degree=meta.degree,
                    is_headhunter=meta.is_headhunter,
                )

                if meta.is_headhunter and get_config().scrape.skip_headhunter:
                    log.info("猎头职位，跳过投递: %s — %s", job.title, job.company)
                    self._storage.jobs.mark_filtered(
                        job_id,
                        note="猎头职位",
                    )
                    filtered += 1
                    continue

                matched_kw = match_blacklist(jd, self._blacklist)
                if matched_kw:
                    log.info(
                        "JD 命中黑名单「%s」，跳过投递: %s — %s",
                        matched_kw,
                        job.title,
                        job.company,
                    )
                    self._storage.jobs.mark_filtered(
                        job_id,
                        note=f"黑名单: {matched_kw}",
                    )
                    filtered += 1
                    continue

                await self._page.click_chat_on_detail()

                await asyncio.sleep(random.uniform(1.0, 2.0))
                dialog_result = await self._page.dismiss_dialogs()
                if not dialog_result:
                    log.warning("沟通上限已达，终止投递")
                    self._storage.jobs.mark_failed(job_id)
                    self._storage.accounts.set_daily_count_maxed(self._account_id)
                    failed += 1
                    break

                greeting = get_config().scrape.greeting
                await self._chat_page.wait_conversation_selected(timeout=10)
                await self._chat_page.send_message(greeting)
                log.info("已发送招呼语: %s — %s", job.title, job.company)

                self._storage.jobs.mark_success(job_id)
                self._storage.accounts.increment_daily_count(self._account_id)
                success += 1
                log.info("投递成功: %s — %s", job.title, job.company)

                remaining = self._storage.accounts.get_remaining_quota(self._account_id)
                if remaining <= 0:
                    log.info("配额已满，终止投递")
                    break

                await asyncio.sleep(random.uniform(2.0, 4.0))

            except Exception as e:
                log.error("投递异常: job=%s error=%s", job_id, e)
                self._storage.jobs.mark_failed(job_id)
                failed += 1

        log.info(
            "投递完成: account=%s success=%d failed=%d filtered=%d",
            self._account_id,
            success,
            failed,
            filtered,
        )
        return DispatchResult(success=success, failed=failed, filtered=filtered)
