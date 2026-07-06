"""所有 page object 的基类：提供 is_loaded / wait_loaded 通用实现。"""
from __future__ import annotations

import asyncio
import time

from bzauto.browser.session import BrowserSession


class BasePage:
    """所有 page object 的基类：提供 is_loaded / wait_loaded 通用实现。"""

    _LOADED_SELECTOR: str  # 子类覆盖，用于 count 判断

    def __init__(self, session: BrowserSession) -> None:
        self._session = session

    async def _count(self, selector: str) -> int:
        return await self._session.count(select=selector)

    async def is_loaded(self) -> bool:
        return await self._count(self._LOADED_SELECTOR) > 0

    async def wait_loaded(self, timeout: float = 20.0, interval: float = 0.5) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if await self.is_loaded():
                return True
            await asyncio.sleep(interval)
        return False

    async def _wait_visible(
        self,
        select: str,
        *,
        filter: dict | None = None,
        timeout: float = 10.0,
        interval: float = 0.3,
    ) -> dict | None:
        """等待元素可见（bbox 返回非 None）。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            bbox = await self._session.bbox(select=select, filter=filter)
            if bbox is not None:
                return bbox
            await asyncio.sleep(interval)
        return None

    async def _wait_hidden(
        self,
        select: str,
        *,
        timeout: float = 5.0,
        interval: float = 0.3,
    ) -> bool:
        """等待元素消失（bbox 返回 None）。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            bbox = await self._session.bbox(select=select)
            if bbox is None:
                return True
            await asyncio.sleep(interval)
        return False