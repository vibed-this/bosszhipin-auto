"""APScheduler 定时调度 — 采集 / 投递 / 扫描。"""
from __future__ import annotations

import asyncio
import datetime
import logging
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bzauto.config import get_config
from bzauto.flows.dispatch import DispatchFlow
from bzauto.flows.scan import ScanFlow
from bzauto.flows.scrape_only import BossScrapeOnlyFlow
from bzauto.notify import NotificationAggregator, get_notifier
from bzauto.pages.job_list import BossJobListPage
from bzauto.server.tab_session import TabSession
from bzauto.storage import Storage
from bzauto.task_runner import ScheduledTask, TaskRunner

log = logging.getLogger("boss.scheduler")


def parse_cron_time(time_str: str) -> dict[str, int]:
    parts = time_str.split(":")
    return {"hour": int(parts[0]), "minute": int(parts[1])}


class ScrapeTask(ScheduledTask):
    name = "采集"

    def __init__(self, account_id: str, storage: Storage) -> None:
        self._account_id = account_id
        self._storage = storage

    async def execute(self) -> dict[str, Any]:
        session = TabSession(account_id=self._account_id)
        page = BossJobListPage(session)
        flow = BossScrapeOnlyFlow(page, session, self._account_id, self._storage)
        cfg = get_config()
        jobs = await flow.run(max_scrolls=10)
        return {"scraped": len(jobs)}


class DispatchTask(ScheduledTask):
    name = "投递"

    def __init__(self, account_id: str, storage: Storage, batch_size: int) -> None:
        self._account_id = account_id
        self._storage = storage
        self._batch_size = batch_size

    async def execute(self) -> dict[str, Any]:
        cfg = get_config()
        self._storage.release_stale_claims(cfg.schedule.claim_timeout_minutes)
        remaining = self._storage.get_remaining_quota(self._account_id)
        if remaining <= 0:
            return {"skipped": "配额已满", "success": 0, "failed": 0}

        pending_count = self._storage.count_pending_jobs()
        account_cfg = None
        for a in cfg.accounts:
            if a.id == self._account_id:
                account_cfg = a
                break
        is_scraper = account_cfg and account_cfg.role == "scraper"

        if pending_count < self._batch_size and is_scraper:
            await ScrapeTask(self._account_id, self._storage).execute()

        session = TabSession(account_id=self._account_id)
        page = BossJobListPage(session)
        flow = DispatchFlow(page, session, self._account_id, self._storage)
        result = await flow.run(batch_size=min(remaining, self._batch_size))
        return result


class ScanTask(ScheduledTask):
    name = "扫描"

    def __init__(self, account_id: str, storage: Storage) -> None:
        self._account_id = account_id
        self._storage = storage

    async def execute(self) -> dict[str, Any]:
        session = TabSession(account_id=self._account_id)
        flow = ScanFlow(session, self._account_id, self._storage)
        return await flow.run()


class BzScheduler:
    """定时调度器。"""

    def __init__(self, task_runner: TaskRunner, loop: asyncio.AbstractEventLoop, storage: Storage) -> None:
        self._scheduler = AsyncIOScheduler(event_loop=loop)
        self._runner = task_runner
        self._storage = storage

    def start(self) -> None:
        cfg = get_config().schedule

        self._scheduler.add_job(self._trigger_scrape, 'cron', **parse_cron_time(cfg.scrape_time))

        for t in cfg.dispatch_times:
            self._scheduler.add_job(self._trigger_dispatch, 'cron', **parse_cron_time(t))

        self._scheduler.add_job(
            self._trigger_scan, 'interval', minutes=cfg.scan_interval_minutes,
        )

        self._scheduler.start()
        log.info("调度器已启动")

    def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
        log.info("调度器已停止")

    async def _trigger_scrape(self) -> None:
        cfg = get_config()
        accounts = self._get_scraper_accounts()
        agg = NotificationAggregator(get_notifier(), f"采集报告 {datetime.date.today().isoformat()}")
        for acc in accounts:
            task = ScrapeTask(acc["account_id"], self._storage)
            result = await self._runner.submit_and_wait(task)
            agg.add_section(acc["name"], [f"采集 {result.get('scraped', 0)} 个"])
        await agg.flush()

    async def _trigger_dispatch(self) -> None:
        accounts = self._storage.get_enabled_accounts()
        agg = NotificationAggregator(get_notifier(), f"投递报告 {datetime.datetime.now():%m-%d %H:%M}")
        for acc in accounts:
            task = DispatchTask(acc["account_id"], self._storage, get_config().schedule.dispatch_batch_size)
            result = await self._runner.submit_and_wait(task)
            if result.get("skipped"):
                agg.add_section(acc.get("name", acc["account_id"]), [f"跳过: {result['skipped']}"])
            else:
                account_data = self._storage.get_account(acc['account_id'])
                daily_count = account_data.get('daily_count', 0) if account_data else 0
                daily_limit = account_data.get('daily_limit', 150) if account_data else 150
                total = result.get('success', 0) + result.get('failed', 0)
                agg.add_section(acc.get("name", acc["account_id"]), [
                    f"投递 {total} 个 (成功 {result.get('success', 0)}, 失败 {result.get('failed', 0)})",
                    f"今日已投 {daily_count}/{daily_limit}",
                ])
        await agg.flush()

    async def _trigger_scan(self) -> None:
        accounts = self._storage.get_enabled_accounts()
        agg = NotificationAggregator(get_notifier(), f"消息扫描 {datetime.datetime.now():%m-%d %H:%M}")
        for acc in accounts:
            task = ScanTask(acc["account_id"], self._storage)
            result = await self._runner.submit_and_wait(task)
            lines = [
                f"删拒 {result.get('deleted', 0)} 条",
                f"新对话 {result.get('new', 0)} 条",
            ]
            for r in result.get("rejections", [])[:5]:
                lines.append(f"  {r}")
            agg.add_section(acc.get("name", acc["account_id"]), lines)
        await agg.flush()

    def _get_scraper_accounts(self) -> list[dict]:
        cfg = get_config()
        return [
            {"account_id": a.id, "name": a.name}
            for a in cfg.accounts if a.enabled and a.role == "scraper"
        ]
