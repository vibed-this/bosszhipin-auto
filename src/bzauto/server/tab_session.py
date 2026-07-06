"""TabSession：当前 tab 的操作代理。"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import pyautogui

from bzauto.server.registry import TabRegistry
from bzauto.server.remote_session import RemoteSession

log = logging.getLogger("boss.session")


class TabSession:
    """当前 tab 的操作代理。

    不管理服务器生命周期，不决定使用哪个 tab。
    外部通过 ``set_current()`` 设置当前标签。
    """

    def __init__(self, registry: TabRegistry | None = None) -> None:
        if registry is None:
            from bzauto.server.lifecycle import get_registry
            registry = get_registry()
        self._registry = registry
        self._rsession = RemoteSession(registry)
        self._tab_id: int | None = None

    def set_current(self, chrome_tab_id: int) -> None:
        self._tab_id = chrome_tab_id
        log.debug("当前标签设为: chromeTabId=%s", chrome_tab_id)

    @property
    def tab_id(self) -> int | None:
        return self._tab_id

    @property
    def remote_session(self) -> RemoteSession:
        return self._rsession

    @property
    def registry(self) -> TabRegistry:
        return self._registry

    def _require_tab(self) -> int:
        if self._tab_id is None:
            raise RuntimeError("未设置当前标签，请先调用 set_current()")
        return self._tab_id

    async def activate(self) -> None:
        if self._tab_id is None:
            return
        try:
            await self._rsession.activate_tab(self._tab_id)
        except ConnectionError:
            log.warning("标签激活失败: chromeTabId=%s", self._tab_id)

    def refresh_tab(self) -> int | None:
        if self._tab_id is not None and self._registry.get_tab(self._tab_id):
            return self._tab_id
        tabs = self._registry.tabs
        if tabs:
            self._tab_id = tabs[-1]["chromeTabId"]
            log.info("切换到标签: chromeTabId=%s", self._tab_id)
            return self._tab_id
        self._tab_id = None
        return None

    async def click(self, x: int, y: int) -> None:
        await self.activate()
        pyautogui.click(x, y)

    async def scroll_pagedown(
        self,
        at_x: int | None = None,
        at_y: int | None = None,
        presses: int = 3,
    ) -> None:
        await self.activate()
        if at_x is not None and at_y is not None:
            pyautogui.moveTo(at_x, at_y)
        pyautogui.press("pagedown", presses=presses)

    async def execute(
        self,
        code: str,
        *,
        timeout: float = 30.0,
    ) -> Any:
        return await self._rsession.execute(self._require_tab(), code, timeout=timeout)

    async def query(
        self,
        select: str,
        *,
        filter: dict | None = None,
        project: dict | None = None,
        return_: str = "list",
        timeout: float = 30.0,
    ) -> Any:
        return await self._rsession.query(
            self._require_tab(), select,
            filter=filter, project=project, return_=return_, timeout=timeout,
        )

    async def bbox(
        self,
        select: str,
        *,
        filter: dict | None = None,
        timeout: float = 30.0,
    ) -> dict | None:
        return await self._rsession.bbox(self._require_tab(), select, filter=filter, timeout=timeout)

    async def dump_html(self, timeout: float = 30.0) -> str | None:
        return await self._rsession.dump_html(self._require_tab(), timeout=timeout)

    def on(self, event: str, callback: Any) -> None:
        self._registry.on(event, callback)

    def off(self, event: str, callback: Any | None = None) -> None:
        self._registry.off(event, callback)

    async def click_element(
        self,
        select: str,
        *,
        filter: dict | None = None,
        wait_visible: str | None = None,
        wait_hidden: str | None = None,
        timeout: float = 30.0,
        post_sleep: float = 0.5,
    ) -> bool:
        """bbox → 激活 → 点击 → 可选等待。返回是否成功。"""
        bbox = await self.bbox(select, filter=filter, timeout=timeout)
        if bbox is None or bbox.get("css", {}).get("cx", 0) <= 0:
            return False
        await self.click(bbox["physical"]["cx"], bbox["physical"]["cy"])
        await asyncio.sleep(post_sleep)
        if wait_visible:
            deadline = asyncio.get_event_loop().time() + timeout
            while asyncio.get_event_loop().time() < deadline:
                check = await self.bbox(wait_visible, timeout=5.0)
                if check is not None:
                    break
                await asyncio.sleep(0.3)
        if wait_hidden:
            deadline = asyncio.get_event_loop().time() + timeout
            while asyncio.get_event_loop().time() < deadline:
                check = await self.bbox(wait_hidden, timeout=5.0)
                if check is None:
                    break
                await asyncio.sleep(0.3)
        return True

    async def scroll_wheel(
        self,
        dy: int,
        *,
        at_x: int | None = None,
        at_y: int | None = None,
        presses: int = 1,
    ) -> None:
        """细粒度滚轮，补 scroll_pagedown 的不足。"""
        await self.activate()
        if at_x is not None and at_y is not None:
            pyautogui.moveTo(at_x, at_y)
        for _ in range(presses):
            pyautogui.scroll(dy, at_x, at_y, _pause=False)
            await asyncio.sleep(0.05)

    @property
    def current_url(self) -> str | None:
        """获取当前标签页的 URL。"""
        if self._tab_id is None:
            return None
        tab = self._registry.get_tab(self._tab_id)
        return tab.get("url") if tab else None