"""APScheduler 定时调度 — 采集 / 投递 / 扫描。"""
from __future__ import annotations

import asyncio
import datetime
import logging
import re
import traceback
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.schedulers import SchedulerNotRunningError

from bzauto.config import get_config
from bzauto.browser import get_browser_manager
from bzauto.flows.delete_chat import BossDeleteChatFlow
from bzauto.flows.dispatch import DispatchFlow
from bzauto.flows.scan import ScanFlow
from bzauto.flows.scrape_chat import BossScrapeChatFlow
from bzauto.flows.scrape_scheduled import BossScrapeScheduledFlow
from bzauto.notify import NotificationAggregator, format_task_lines, get_notifier
from bzauto.pages.chat_list import BossChatListPage
from bzauto.pages.job_list import BossJobListPage
from bzauto.models_doc import AccountDoc, RunDoc
from bzauto.storage import Storage
from bzauto.task_runner import ScheduledTask, TaskRunner

log = logging.getLogger("boss.scheduler")


def _now_iso() -> str:
    return datetime.datetime.now().isoformat()


def parse_cron_time(time_str: str) -> dict[str, int]:
    """解析 HH:MM 格式时间为 APScheduler cron 参数。

    :param time_str: 时间字符串，格式 "HH:MM"
    :returns: {"hour": h, "minute": m}
    """
    parts = time_str.split(":")
    return {"hour": int(parts[0]), "minute": int(parts[1])}


class ScrapeTask(ScheduledTask):
    name = "采集"

    def __init__(self, account_id: str, storage: Storage) -> None:
        self._account_id = account_id
        self._storage = storage

    async def execute(self) -> dict[str, Any]:
        bm = get_browser_manager()
        session = bm.get_session(self._account_id)
        page = BossJobListPage(session)
        flow = BossScrapeScheduledFlow(page, session, self._account_id, self._storage)
        return await flow.run()


class DispatchTask(ScheduledTask):
    name = "投递"

    def __init__(self, account_id: str, storage: Storage, batch_size: int) -> None:
        self._account_id = account_id
        self._storage = storage
        self._batch_size = batch_size

    async def execute(self) -> dict[str, Any]:
        cfg = get_config()
        sched_cfg = cfg.schedule
        self._storage.release_stale_claims(sched_cfg.claim_timeout_minutes)
        remaining = self._storage.get_remaining_quota(self._account_id)
        if remaining <= 0:
            return {"skipped": "配额已满", "success": 0, "failed": 0}

        bm = get_browser_manager()
        session = bm.get_session(self._account_id)
        page = BossJobListPage(session)
        flow = DispatchFlow(page, session, self._account_id, self._storage)
        result = await flow.run(batch_size=min(remaining, self._batch_size))
        return result


class ScrapeChatTask(ScheduledTask):
    name = "聊天爬取"

    def __init__(self, account_id: str, storage: Storage) -> None:
        self._account_id = account_id
        self._storage = storage

    async def execute(self) -> dict[str, Any]:
        bm = get_browser_manager()
        session = bm.get_session(self._account_id)
        page = BossChatListPage(session)
        flow = BossScrapeChatFlow(page, session, self._account_id, self._storage)
        return await flow.run()


class DeleteChatTask(ScheduledTask):
    name = "删拒"

    def __init__(self, account_id: str, storage: Storage) -> None:
        self._account_id = account_id
        self._storage = storage

    async def execute(self) -> dict[str, Any]:
        bm = get_browser_manager()
        session = bm.get_session(self._account_id)
        page = BossChatListPage(session)
        flow = BossDeleteChatFlow(page, session, self._account_id, self._storage)
        return {"deleted": len(await flow.run(dry_run=False))}


class ScanTask(ScheduledTask):
    name = "扫描"

    def __init__(self, account_id: str, storage: Storage) -> None:
        self._account_id = account_id
        self._storage = storage

    async def execute(self) -> dict[str, Any]:
        bm = get_browser_manager()
        session = bm.get_session(self._account_id)
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

        for t in cfg.dispatch_times:
            self._scheduler.add_job(self._trigger_dispatch, 'cron', **parse_cron_time(t))  # type: ignore[arg-type]

        self._scheduler.add_job(
            self._trigger_scan, 'interval', minutes=cfg.scan_interval_minutes,
        )

        self._scheduler.start()
        log.info("调度器已启动")

    def stop(self) -> None:
        try:
            self._scheduler.shutdown(wait=False)
            log.info("调度器已停止")
        except SchedulerNotRunningError:
            log.info("调度器已处于停止状态")

    _JOB_LABEL_MAP: dict[str, str] = {
        "_trigger_dispatch": "投递",
        "_trigger_scan": "扫描",
    }

    @property
    def running(self) -> bool:
        return self._scheduler.running

    def snapshot(self) -> list[dict[str, Any]]:
        """返回各注册 job 的结构化快照。

        :returns: [{id, label, trigger_kind, trigger_repr, next_run_time}, ...]
        """
        if not self._scheduler.running:
            return []
        results: list[dict[str, Any]] = []
        for job in self._scheduler.get_jobs():
            func_ref = job.func_ref or ""
            m = re.search(r'_trigger_(\w+)', func_ref)
            key = m.group(0) if m else ""
            label = self._JOB_LABEL_MAP.get(key, job.id)

            trigger_repr = str(job.trigger)
            trigger_kind = str(type(job.trigger).__name__).removesuffix("Trigger").lower()

            results.append({
                "id": job.id,
                "label": label,
                "trigger_kind": trigger_kind,
                "trigger_repr": trigger_repr,
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            })
        return results

    async def _run_and_record(self, trigger: str, acc: AccountDoc, task) -> dict:
        """执行任务并记录执行结果到 schedule_runs 表。

        :param trigger: 触发类型（采集 / 投递 / 扫描）
        :param acc: 账号文档
        :param task: ScheduledTask 实例
        :returns: task.execute() 的返回值
        """
        started = _now_iso()
        status = "success"
        result: dict = {}
        error = ""
        try:
            result = await self._runner.submit_and_wait(task)
            if isinstance(result, dict) and result.get("skipped"):
                status = "skipped"
            return result
        except Exception:
            status = "failed"
            error = traceback.format_exc()
            raise
        finally:
            self._storage.insert_run(RunDoc(
                trigger=trigger,
                account_id=acc.account_id,
                account_name=acc.name or acc.account_id,
                started_at=started,
                finished_at=_now_iso(),
                status=status,
                result=result,
                error=error,
            ))

    async def _trigger_dispatch(self) -> None:
        accounts = self._storage.get_enabled_accounts()
        agg = NotificationAggregator(get_notifier(), f"投递报告 {datetime.datetime.now():%m-%d %H:%M}")
        for acc in accounts:
            task = DispatchTask(acc.account_id, self._storage, get_config().schedule.dispatch_batch_size)
            result = await self._run_and_record("投递", acc, task)
            lines = format_task_lines("投递", result)
            if not result.get("skipped"):
                lines.append(f"今日已投 {acc.daily_count}/{acc.daily_limit}")
            agg.add_section(acc.name or acc.account_id, lines)
        await agg.flush()

    async def _trigger_scan(self) -> None:
        accounts = self._storage.get_enabled_accounts()
        agg = NotificationAggregator(get_notifier(), f"消息扫描 {datetime.datetime.now():%m-%d %H:%M}")
        for acc in accounts:
            task = ScanTask(acc.account_id, self._storage)
            result = await self._run_and_record("扫描", acc, task)
            agg.add_section(acc.name or acc.account_id, format_task_lines("扫描", result))
        await agg.flush()


