"""DispatchFlow — 从 DB pending 池取 job 并按 href 定位卡片进行沟通。"""
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
    """从 DB pending 池取 job 并按 href 定位卡片进行沟通。"""

    def __init__(self, page: BossJobListPage, session: BrowserSession, account_id: str, storage: Storage) -> None:
        super().__init__(page, session, account_id)
        self._storage = storage
        self._chat_page = BossChatListPage(session)
        self._jobs_url = "https://www.zhipin.com/web/geek/jobs"

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
                await self._session.ensure_tab(self._jobs_url, reuse_existing=True)

                idx = await self._page.find_card_by_href(job.href)
                if idx < 0:
                    log.warning("未找到卡片: job=%s href=%s", job_id, job.href)
                    self._storage.mark_job_failed(job_id)
                    failed += 1
                    continue

                await self._page.click_card_at(idx)
                await self._page.click_chat(idx)

                # === 新流程：自动跳转聊天页 → 发送招呼语 ===
                greeting = get_config().scrape.greeting
                await self._chat_page.wait_conversation_selected(timeout=10)
                await self._chat_page.send_message(greeting)
                log.info("已发送招呼语: %s — %s", job.title, job.company)

                # === 旧流程：有打招呼语（平台侧已设置）→ 弹窗确认 ===
                # await asyncio.sleep(random.uniform(1.0, 2.0))
                # result = await self._page.dismiss_dialogs()
                # if not result:
                #     log.warning("沟通上限已达，终止投递")
                #     self._storage.mark_job_failed(job_id)
                #     failed += 1
                #     break

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
