"""DispatchFlow — 从 DB pending 池取 job 并按 href 直达详情页沟通。"""
from __future__ import annotations

import asyncio
import logging
import random

from bzauto.browser.session import BrowserSession
from bzauto.config import get_config
from bzauto.flows.base import BaseFlow
from bzauto.pages.chat_list import BossChatListPage
from bzauto.pages.job_list import BossJobListPage
from bzauto.storage import Storage

log = logging.getLogger("flow.dispatch")


class DispatchFlow(BaseFlow[BossJobListPage]):
    """从 DB pending 池取 job 并按 href 直达详情页沟通。"""

    def __init__(self, page: BossJobListPage, session: BrowserSession, account_id: str, storage: Storage) -> None:
        super().__init__(page, session, account_id)
        self._storage = storage
        self._chat_page = BossChatListPage(session)

    async def run(self, batch_size: int = 50) -> dict:
        remaining = self._storage.get_remaining_quota(self._account_id)
        if remaining <= 0:
            log.info("配额已满: account=%s", self._account_id)
            return {"success": 0, "failed": 0, "skipped": True}

        jobs = self._storage.get_pending_jobs(min(remaining, batch_size))
        if not jobs:
            log.info("无待办 job，跳过投递: account=%s", self._account_id)
            return {"success": 0, "failed": 0, "skipped": True}

        log.info("开始投递: account=%s batch=%d", self._account_id, len(jobs))

        success = 0
        failed = 0

        for job in jobs:
            job_id = job.job_id
            claimed = self._storage.claim_job(job_id, self._account_id)
            if not claimed:
                log.debug("job 已被领取: %s", job_id)
                continue

            try:
                href = job.href
                full_url = href if href.startswith("http") else f"https://www.zhipin.com{href}"
                await self._session.ensure_tab(full_url, reuse_existing=True)

                await self._page.click_chat_on_detail()

                greeting = get_config().scrape.greeting
                await self._chat_page.wait_conversation_selected(timeout=10)
                await self._chat_page.send_message(greeting)
                log.info("已发送招呼语: %s — %s", job.title, job.company)

                self._storage.mark_job_success(job_id)
                self._storage.increment_daily_count(self._account_id)
                success += 1
                log.info("投递成功: %s — %s", job.title, job.company)

                remaining = self._storage.get_remaining_quota(self._account_id)
                if remaining <= 0:
                    log.info("配额已满，终止投递")
                    break

                await asyncio.sleep(random.uniform(2.0, 4.0))

            except Exception as e:
                log.error("投递异常: job=%s error=%s", job_id, e)
                self._storage.mark_job_failed(job_id)
                failed += 1

        log.info("投递完成: account=%s success=%d failed=%d", self._account_id, success, failed)
        return {"success": success, "failed": failed}
