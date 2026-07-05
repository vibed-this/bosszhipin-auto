from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import pyautogui
import uvicorn

from bzauto.server import TabRegistry, RemoteSession, create_app

log = logging.getLogger("boss.session")


class TabNotConnectedError(RuntimeError):
    pass


class TabSession:
    """浏览器会话层：服务生命周期 + 标签管理 + 设备输入 + RemoteSession 代理。"""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        self._host = host
        self._port = port
        self._registry = TabRegistry()
        self._rsession = RemoteSession(self._registry)
        self._app = create_app(self._registry)
        self._server: uvicorn.Server | None = None
        self._server_task: asyncio.Task | None = None
        self._tab_id: int | None = None

    async def start(self) -> None:
        config = uvicorn.Config(self._app, host=self._host, port=self._port, log_level="warning")
        self._server = uvicorn.Server(config)
        self._server_task = asyncio.create_task(self._server.serve())

    async def stop(self) -> None:
        if self._server:
            self._server.should_exit = True
            self._server = None
        if self._server_task:
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
            self._server_task = None

    async def __aenter__(self) -> TabSession:
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.stop()

    async def ensure_tab(
        self,
        url: str | None = None,
        *,
        reuse_existing: bool = False,
        wait_for_tab: bool = False,
        timeout: float = 120.0,
    ) -> int:
        deadline = time.monotonic() + 60.0
        while not self._registry.is_connected():
            if time.monotonic() > deadline:
                raise ConnectionError("扩展后台未连接")
            await asyncio.sleep(0.5)

        if url:
            if reuse_existing:
                for tab in self._registry.tabs:
                    if tab.get("url") == url:
                        self._tab_id = tab["chromeTabId"]
                        log.info("复用标签: chromeTabId=%s", self._tab_id)
                        return self._tab_id
            result = await self._rsession.open_tab(url)
            self._tab_id = result["chromeTabId"]
            log.info("标签已创建: chromeTabId=%s", self._tab_id)
            return self._tab_id

        if self._registry.tabs:
            tab = self._registry.tabs[-1]
            self._tab_id = tab["chromeTabId"]
            log.info("使用已有标签: chromeTabId=%s", self._tab_id)
            return self._tab_id

        if not wait_for_tab:
            raise RuntimeError("没有可用标签，请指定 url 或设置 wait_for_tab=True")

        event = asyncio.Event()
        ready: list[dict] = []

        def on_ready(msg: dict) -> None:
            ready.append(msg)
            event.set()

        self._registry.on("tab_ready", on_ready)
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        finally:
            self._registry.off("tab_ready", on_ready)

        self._tab_id = ready[0]["chromeTabId"]
        log.info("标签就绪: chromeTabId=%s", self._tab_id)
        return self._tab_id

    async def activate(self) -> None:
        if self._tab_id is None:
            return
        try:
            await self._rsession.activate_tab(self._tab_id)
        except ConnectionError:
            log.warning("标签激活失败: chromeTabId=%s", self._tab_id)

    async def close(self) -> None:
        if self._tab_id is not None:
            await self._rsession.close_tab(self._tab_id)
            self._tab_id = None

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

    def _require_tab(self) -> int:
        if self._tab_id is None:
            raise TabNotConnectedError("未设置当前标签，请先调用 ensure_tab()")
        return self._tab_id

    async def execute(
        self,
        code: str,
        *,
        world: str = "main",
        timeout: float = 30.0,
    ) -> Any:
        return await self._rsession.execute(self._require_tab(), code, world=world, timeout=timeout)

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

    def on(self, event: str, callback: Any) -> None:
        self._registry.on(event, callback)

    def off(self, event: str, callback: Any | None = None) -> None:
        self._registry.off(event, callback)

    @property
    def remote_session(self) -> RemoteSession:
        return self._rsession

    @property
    def tab_id(self) -> int | None:
        return self._tab_id
