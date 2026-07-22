"""未读消息轮询 — tab 角标更新 + 边沿触发单账号消息扫描。"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from bzauto.browser import get_browser_manager
from bzauto.config import get_config
from bzauto.pages import BossHeader
from bzauto.task_runner import TaskRunner

log = logging.getLogger("boss.unread_watcher")

BadgeCallback = Callable[[str, int], None]
TriggerCallback = Callable[[str], Awaitable[None]]


class UnreadWatcher:
    """轮询导航栏未读角标，未读数上升时触发单账号消息扫描。"""

    def __init__(
        self,
        account_ids: list[str],
        task_runner: TaskRunner,
        on_badge_update: BadgeCallback,
        on_unread_detected: TriggerCallback,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._account_ids = account_ids
        self._task_runner = task_runner
        self._on_badge_update = on_badge_update
        self._on_unread_detected = on_unread_detected
        self._loop = loop
        self._last_counts: dict[str, int] = {}
        self._last_trigger_at: dict[str, float] = {}
        self._pending_scan: dict[str, bool] = {}
        self._scanning: set[str] = set()
        self._tasks: list[asyncio.Task[None]] = []
        self._stopped = False

    def start(self) -> None:
        for account_id in self._account_ids:
            self._tasks.append(self._loop.create_task(self._poll_account(account_id)))

    def stop(self) -> None:
        self._stopped = True
        for task in self._tasks:
            task.cancel()

    async def _poll_account(self, account_id: str) -> None:
        bm = get_browser_manager()
        if bm is None:
            log.warning("轮询未读: BrowserManager 未初始化")
            return

        session = bm.get_session(account_id)
        if session is None:
            log.warning("轮询未读: 账号 %s 无 session", account_id)
            return

        header = BossHeader(session)
        while not self._stopped:
            try:
                cfg = get_config().schedule
                count = await header.get_unread_count()
                if count is None:
                    await asyncio.sleep(cfg.unread_poll_seconds)
                    continue
                self._on_badge_update(account_id, count)
                await self._handle_count_change(account_id, count)
                await self._flush_pending(account_id)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.debug("轮询未读 [%s] 失败: %s", account_id, e)
            await asyncio.sleep(get_config().schedule.unread_poll_seconds)

    async def _handle_count_change(self, account_id: str, count: int) -> None:
        last = self._last_counts.get(account_id, 0)
        self._last_counts[account_id] = count
        if count <= last:
            return
        if not get_config().schedule.unread_trigger_enabled:
            return
        log.info("未读上升 [%s]: %d → %d", account_id, last, count)
        await self._request_scan(account_id)

    async def _request_scan(self, account_id: str) -> None:
        cfg = get_config().schedule
        now = time.monotonic()
        cooldown = cfg.unread_scan_cooldown_minutes * 60
        if now - self._last_trigger_at.get(account_id, 0) < cooldown:
            log.debug("未读触发冷却中 [%s]", account_id)
            return

        if self._task_runner.is_busy or account_id in self._scanning:
            self._pending_scan[account_id] = True
            log.debug("未读触发排队 [%s]", account_id)
            return

        self._loop.create_task(self._run_scan(account_id))

    async def _flush_pending(self, account_id: str) -> None:
        if not self._pending_scan.get(account_id):
            return
        if self._task_runner.is_busy or account_id in self._scanning:
            return
        self._pending_scan.pop(account_id, None)
        await self._request_scan(account_id)

    async def _run_scan(self, account_id: str) -> None:
        if account_id in self._scanning:
            return
        self._scanning.add(account_id)
        self._last_trigger_at[account_id] = time.monotonic()
        try:
            await self._on_unread_detected(account_id)
        except Exception:
            log.exception("未读触发扫描失败 [%s]", account_id)
        finally:
            self._scanning.discard(account_id)
            if self._pending_scan.pop(account_id, False):
                await self._request_scan(account_id)
