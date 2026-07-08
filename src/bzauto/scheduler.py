"""APScheduler 定时调度 — 采集 / 投递 / 扫描。"""
from __future__ import annotations

import asyncio
import datetime
import logging
import re
import traceback
from typing import Any

from pydantic import BaseModel

from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_MISSED
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.schedulers import SchedulerNotRunningError

from bzauto.config import get_config
from bzauto.browser import get_browser_manager
from bzauto.flows.delete_chat import BossDeleteChatFlow
from bzauto.flows.dispatch import DispatchFlow
from bzauto.flows.scan import ChatScanFlow
from bzauto.flows.scrape_chat import BossScrapeChatFlow
from bzauto.flows.scrape_scheduled import BossScrapeScheduledFlow
from bzauto.notify import NotificationAggregator, get_notifier
from bzauto.pages.chat_list import BossChatListPage
from bzauto.pages.job_list import BossJobListPage
from bzauto.models_doc import AccountDoc, RunDoc
from bzauto.results import DispatchResult, ScrapeChatResult, ScrapeResult
from bzauto.storage import Storage
from bzauto.task_runner import ScheduledTask, TaskRunner

log = logging.getLogger("boss.scheduler")

_MISFIRE_GRACE = 86400  # 24h，重启后补执行窗口


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

    async def execute(self) -> ScrapeResult:
        bm = get_browser_manager()
        session = bm.get_session(self._account_id)
        page = BossJobListPage(session)
        flow = BossScrapeScheduledFlow(page, session, self._account_id, self._storage)
        return await flow.run()

    def format_result(self, result: ScrapeResult) -> list[str]:
        return [f"采集 {result.scraped} 个"]


class ScrapeManualTask(ScheduledTask):
    name = "采集"

    def __init__(self, account_id: str, storage: Storage) -> None:
        self._account_id = account_id
        self._storage = storage

    async def execute(self) -> dict[str, Any]:
        from bzauto.flows.scrape_manual import BossScrapeManualFlow
        bm = get_browser_manager()
        session = bm.get_session(self._account_id)
        page = BossJobListPage(session)
        flow = BossScrapeManualFlow(page, session, self._account_id, self._storage)
        jobs = await flow.run(max_scrolls=50, max_jobs=999)
        return {"scraped": len(jobs), "skipped": False}

    def format_result(self, result: dict[str, Any]) -> list[str]:
        return [f"采集 {result.get('scraped', 0)} 个"]


class DispatchTask(ScheduledTask):
    name = "投递"

    def __init__(self, account_id: str, storage: Storage, batch_size: int) -> None:
        self._account_id = account_id
        self._storage = storage
        self._batch_size = batch_size

    async def execute(self) -> DispatchResult:
        cfg = get_config()
        sched_cfg = cfg.schedule
        self._storage.jobs.release_stale_claims(sched_cfg.claim_timeout_minutes)
        remaining = self._storage.accounts.get_remaining_quota(self._account_id)
        if remaining <= 0:
            return DispatchResult(success=0, failed=0, skipped=True, skip_reason="配额已满")

        bm = get_browser_manager()
        session = bm.get_session(self._account_id)
        page = BossJobListPage(session)
        flow = DispatchFlow(page, session, self._account_id, self._storage)
        return await flow.run(batch_size=min(remaining, self._batch_size))

    def format_result(self, result: DispatchResult) -> list[str]:
        if result.skipped:
            reason = result.skip_reason or ""
            return [f"跳过: {reason}" if reason else "跳过"]
        return [f"投递 {result.success + result.failed} 个 (成功 {result.success}, 失败 {result.failed})"]


class ScrapeChatTask(ScheduledTask):
    name = "消息扫描"

    def __init__(self, account_id: str, storage: Storage) -> None:
        self._account_id = account_id
        self._storage = storage

    async def execute(self) -> ScrapeChatResult:
        bm = get_browser_manager()
        session = bm.get_session(self._account_id)
        page = BossChatListPage(session)
        flow = BossScrapeChatFlow(page, session, self._account_id, self._storage)
        return await flow.run()

    def format_result(self, result: ScrapeChatResult) -> list[str] | None:
        if not result.unread:
            return None

        updates = result.new + result.updated
        lines = [f"更新 {updates} 条。未读 {len(result.unread)}，拒信 {len(result.rejections)}"]

        lines.append("")
        lines.append(f"📩 未读消息 ({len(result.unread)})")
        for item in result.unread:
            msg = (item.lastMsg[:60] + "...") if len(item.lastMsg) > 60 else item.lastMsg
            lines.append(f"  {item.name}·{item.company}: {msg}")

        return lines


class DeleteChatTask(ScheduledTask):
    name = "消息删拒"

    def __init__(self, account_id: str, storage: Storage) -> None:
        self._account_id = account_id
        self._storage = storage

    async def execute(self) -> dict[str, Any]:
        bm = get_browser_manager()
        session = bm.get_session(self._account_id)
        page = BossChatListPage(session)
        flow = BossDeleteChatFlow(page, session, self._account_id, self._storage)
        return {"deleted": len(await flow.run(dry_run=False))}

    def format_result(self, result: dict[str, Any]) -> list[str]:
        return [f"删除 {result.get('deleted', 0)} 条"]


class BzScheduler:
    """定时调度器。"""

    def __init__(self, task_runner: TaskRunner, loop: asyncio.AbstractEventLoop, storage: Storage) -> None:
        self._scheduler = AsyncIOScheduler(event_loop=loop)
        self._runner = task_runner
        self._storage = storage

    def start(self) -> None:
        cfg = get_config().schedule

        for i, t in enumerate(cfg.dispatch_times):
            job_id = f"dispatch_{i}"
            nxt = self._load_next_run(job_id)
            kwargs: dict[str, Any] = dict(
                misfire_grace_time=_MISFIRE_GRACE,
                coalesce=True,
            )
            if nxt is not None:
                kwargs["next_run_time"] = nxt
            self._scheduler.add_job(
                self._trigger_dispatch, 'cron', id=job_id,
                **parse_cron_time(t), **kwargs,
            )

        nxt = self._load_next_run("scrape_chat")
        kwargs = dict(
            misfire_grace_time=_MISFIRE_GRACE,
            coalesce=True,
        )
        if nxt is not None:
            kwargs["next_run_time"] = nxt
        self._scheduler.add_job(
            self._trigger_scrape_chat, 'interval', id="scrape_chat",
            minutes=cfg.scan_interval_minutes, **kwargs,
        )

        nxt = self._load_next_run("delete_chat")
        kwargs = dict(
            misfire_grace_time=_MISFIRE_GRACE,
            coalesce=True,
        )
        if nxt is not None:
            kwargs["next_run_time"] = nxt
        self._scheduler.add_job(
            self._trigger_delete_chat, 'interval', id="delete_chat",
            hours=1, **kwargs,
        )

        self._scheduler.add_listener(
            self._on_job_event, EVENT_JOB_EXECUTED | EVENT_JOB_MISSED,
        )
        self._scheduler.start()

        # start() 后 APScheduler 才计算出 next_run_time，首次运行需要持久化
        for job in self._scheduler.get_jobs():
            self._persist_next_run(job)

        log.info("调度器已启动")

    def stop(self) -> None:
        try:
            self._scheduler.shutdown(wait=False)
            log.info("调度器已停止")
        except SchedulerNotRunningError:
            log.info("调度器已处于停止状态")

    _JOB_LABEL_MAP: dict[str, str] = {
        "_trigger_dispatch": "投递",
        "_trigger_scrape_chat": "消息扫描",
        "_trigger_delete_chat": "消息删拒",
        "_trigger_scrape": "采集",
    }

    def reset_all_jobs(self) -> None:
        """重置所有任务，重新根据当前时间计算 next_run_time（模拟初始启动）。"""
        if not self._scheduler.running:
            return
        for job in self._scheduler.get_jobs():
            self._scheduler.reschedule_job(job.id, trigger=job.trigger)
            self._persist_next_run(self._scheduler.get_job(job.id))

    def run_job_now(self, job_id: str) -> None:
        """将指定任务的 next_run_time 设为当前时间。"""
        if not self._scheduler.running:
            return
        job = self._scheduler.get_job(job_id)
        if job:
            self._scheduler.modify_job(job_id, next_run_time=datetime.datetime.now())
            self._persist_next_run(self._scheduler.get_job(job_id))

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

    def _load_next_run(self, job_id: str) -> datetime.datetime | None:
        val = self._storage.meta.get(f"next_run:{job_id}")
        try:
            return datetime.datetime.fromisoformat(val) if val else None
        except (ValueError, TypeError):
            return None

    def _persist_next_run(self, job) -> None:
        if job and job.next_run_time:
            self._storage.meta.set(f"next_run:{job.id}", job.next_run_time.isoformat())

    def _on_job_event(self, event) -> None:
        self._persist_next_run(self._scheduler.get_job(event.job_id))

    @staticmethod
    def _is_skipped(result: Any) -> bool:
        if isinstance(result, BaseModel):
            return bool(getattr(result, "skipped", False))
        return bool(result.get("skipped")) if isinstance(result, dict) else False

    @staticmethod
    def _to_result_dict(result: Any) -> dict:
        if isinstance(result, BaseModel):
            return result.model_dump()
        return result if isinstance(result, dict) else {}

    async def _run_and_record(self, trigger: str, acc: AccountDoc, task: ScheduledTask) -> Any:
        """执行任务并记录执行结果到 schedule_runs 表。

        :param trigger: 触发类型（采集 / 投递 / 扫描）
        :param acc: 账号文档
        :param task: ScheduledTask 实例
        :returns: task.execute() 的返回值
        """
        started = _now_iso()
        status = "success"
        result: Any = {}
        error = ""
        try:
            result = await self._runner.submit_and_wait(task)
            if self._is_skipped(result):
                status = "skipped"
            log.info("[%s] %s 完成 — %s", trigger, acc.name or acc.account_id, status)
            return result
        except Exception:
            status = "failed"
            error = traceback.format_exc()
            log.error("[%s] %s 异常: %s", trigger, acc.name or acc.account_id, error)
            raise
        finally:
                self._storage.runs.insert(RunDoc(
                trigger=trigger,
                account_id=acc.account_id,
                account_name=acc.name or acc.account_id,
                started_at=started,
                finished_at=_now_iso(),
                status=status,
                result=self._to_result_dict(result),
                error=error,
            ))

    async def _trigger_dispatch(self) -> None:
        cfg = get_config().schedule
        accounts = self._storage.accounts.list(enabled_only=True)
        agg = NotificationAggregator(get_notifier(), f"投递报告 {datetime.datetime.now():%m-%d %H:%M}")
        total_dispatched = 0
        for acc in accounts:
            if total_dispatched >= cfg.dispatch_total_limit:
                self._storage.runs.insert(RunDoc(
                    trigger="投递",
                    account_id=acc.account_id,
                    account_name=acc.name or acc.account_id,
                    started_at=_now_iso(),
                    finished_at=_now_iso(),
                    status="skipped",
                    result={"skipped": True, "skip_reason": "达到单次调度总沟通上限"},
                    error="",
                ))
                agg.add_section(acc.name or acc.account_id,
                                [f"跳过: 达到单次调度总沟通上限 ({cfg.dispatch_total_limit})"])
                continue

            task = DispatchTask(acc.account_id, self._storage, cfg.dispatch_batch_size)
            result = await self._run_and_record("投递", acc, task)
            lines = task.format_result(result)

            if isinstance(result, DispatchResult):
                dispatched_count = result.success
                skipped = result.skipped
            elif isinstance(result, dict):
                dispatched_count = result.get("success", 0)
                skipped = result.get("skipped", False)
            else:
                dispatched_count = 0
                skipped = True

            total_dispatched += dispatched_count

            if not skipped:
                lines.append(f"今日已投 {acc.daily_count}/{acc.daily_limit}")
            agg.add_section(acc.name or acc.account_id, lines)
        await agg.flush()

    async def _trigger_scrape(self) -> None:
        accounts = self._storage.accounts.list(enabled_only=True)
        agg = NotificationAggregator(get_notifier(), f"采集报告 {datetime.datetime.now():%m-%d %H:%M}")
        for acc in accounts:
            task = ScrapeTask(acc.account_id, self._storage)
            result = await self._run_and_record("采集", acc, task)
            agg.add_section(acc.name or acc.account_id, task.format_result(result))
        await agg.flush()

    async def _trigger_scrape_chat(self) -> None:
        accounts = self._storage.accounts.list(enabled_only=True)
        agg = NotificationAggregator(get_notifier(), f"消息扫描 {datetime.datetime.now():%m-%d %H:%M}")
        any_unread = False
        for acc in accounts:
            task = ScrapeChatTask(acc.account_id, self._storage)
            result = await self._run_and_record("消息扫描", acc, task)
            lines = task.format_result(result)
            if lines is not None:
                any_unread = True
                agg.add_section(acc.name or acc.account_id, lines)
            else:
                log.info("[消息扫描] %s 无未读消息", acc.name or acc.account_id)
        if any_unread:
            await agg.flush()
        else:
            log.info("[消息扫描] 全部账号无未读消息，跳过通知")

    async def _trigger_delete_chat(self) -> None:
        accounts = self._storage.accounts.list(enabled_only=True)
        agg = NotificationAggregator(get_notifier(), f"消息删拒 {datetime.datetime.now():%m-%d %H:%M}")
        for acc in accounts:
            task = DeleteChatTask(acc.account_id, self._storage)
            result = await self._run_and_record("消息删拒", acc, task)
            agg.add_section(acc.name or acc.account_id, task.format_result(result))
        await agg.flush()


