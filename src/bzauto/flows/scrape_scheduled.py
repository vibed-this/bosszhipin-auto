"""定时采集流程编排：检查 DB 中待投递数量，不足时自动补采。"""
from __future__ import annotations

import logging
from typing import Any

from bzauto.config import get_config
from bzauto.browser.session import BrowserSession
from bzauto.flows.scrape_manual import BossScrapeManualFlow
from bzauto.pages.job_list import BossJobListPage
from bzauto.storage import Storage

log = logging.getLogger("flow.scrape_scheduled")


class BossScrapeScheduledFlow:
    """定时采集流程编排。

    每次执行前检查库中 pending job 数量，若已达 enabled 账号数×150 则跳过；
    否则采集至补齐目标数量。
    """

    def __init__(self, page: BossJobListPage, session: BrowserSession, account_id: str, storage: Storage) -> None:
        self._page = page
        self._session = session
        self._account_id = account_id
        self._storage = storage

    async def run(self) -> dict[str, Any]:
        cfg = get_config()
        enabled_count = sum(1 for a in cfg.accounts if a.enabled)
        target = enabled_count * 150

        pending = self._storage.count_pending_jobs()
        log.info("定时采集检查: pending=%d target=%d", pending, target)

        if pending >= target:
            log.info("跳过定时采集: pending=%d >= target=%d", pending, target)
            return {"scraped": 0, "skipped": True}

        need = target - pending
        log.info("定时采集启动: need=%d", need)

        flow = BossScrapeManualFlow(self._page, self._session, self._account_id, self._storage)
        jobs = await flow.run(max_jobs=need, max_scrolls=999)

        return {"scraped": len(jobs), "skipped": False}
