"""串行任务队列 — 确保同一时间只有一个任务在执行。"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger("boss.task_runner")


class ScheduledTask:
    """任务基类。"""
    name: str = ""

    async def execute(self) -> dict[str, Any]:
        raise NotImplementedError


class TaskRunner:
    """串行任务队列，挂在现有后台 asyncio event loop 上。"""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._queue: asyncio.Queue[ScheduledTask] = asyncio.Queue()
        self._current: ScheduledTask | None = None
        self._current_exec: asyncio.Task | None = None
        self._loop.create_task(self._worker())

    async def submit(self, task: ScheduledTask) -> None:
        await self._queue.put(task)

    async def submit_and_wait(self, task: ScheduledTask) -> dict[str, Any]:
        future: asyncio.Future[dict[str, Any]] = asyncio.Future()
        wrapped = _FutureTask(task, future)
        await self._queue.put(wrapped)
        return await future

    def cancel_current(self) -> None:
        if self._current_exec is not None and not self._current_exec.done():
            self._current_exec.cancel()

    async def _worker(self) -> None:
        while True:
            try:
                task = await self._queue.get()
            except asyncio.CancelledError:
                break
            self._current = task
            try:
                self._current_exec = asyncio.create_task(task.execute())
                result = await self._current_exec
                if isinstance(task, _FutureTask):
                    try:
                        task.future.set_result(result)
                    except asyncio.InvalidStateError:
                        log.warning("future 已处于终态，忽略 set_result: %s", task.name)
            except asyncio.CancelledError:
                if isinstance(task, _FutureTask):
                    try:
                        task.future.set_exception(asyncio.CancelledError())
                    except asyncio.InvalidStateError:
                        pass
            except Exception as e:
                log.error("任务异常 (%s): %s", task.name, e)
                if isinstance(task, _FutureTask):
                    try:
                        task.future.set_exception(e)
                    except asyncio.InvalidStateError:
                        log.warning("future 已处于终态，忽略 set_exception: %s", task.name)
            finally:
                self._current = None
                self._current_exec = None

    @property
    def is_busy(self) -> bool:
        return self._current is not None

    @property
    def current_task_name(self) -> str | None:
        return self._current.name if self._current else None

    @property
    def pending_count(self) -> int:
        return self._queue.qsize()


class _FutureTask(ScheduledTask):
    def __init__(self, inner: ScheduledTask, future: asyncio.Future[dict[str, Any]]) -> None:
        self._inner = inner
        self.future = future
        self.name = inner.name

    async def execute(self) -> dict[str, Any]:
        return await self._inner.execute()
