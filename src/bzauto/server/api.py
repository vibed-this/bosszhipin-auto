"""Python API: remote browser tab control via Chrome extension.

Usage::

    from bzauto import TabRegistry, RemoteSession, create_app

    registry = TabRegistry()
    session = RemoteSession(registry)
    app = create_app(registry)

    # Start the WebSocket server in a background task, then:
    tabs = await session.list_tabs()
    result = await session.execute(42, "document.title")
    tab = await session.open_tab("https://www.zhipin.com/")
    await session.close_tab(tab["chromeTabId"])
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("boss.api")


class RemoteSession:
    """High-level Python API for remote browser tab control.

    All operations go through the extension background WebSocket,
    which uses ``chrome.scripting.executeScript`` for JS execution
    and ``chrome.tabs.*`` for tab management.
    """

    def __init__(self, registry: "TabRegistry") -> None:
        self._registry = registry

    def on(self, event: str, callback: Callable) -> None:
        self._registry.on(event, callback)

    def off(self, event: str, callback: Callable | None = None) -> None:
        self._registry.off(event, callback)

    async def open_tab(
        self,
        url: str,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        if not self._registry.is_connected():
            raise ConnectionError("扩展后台未连接")
        result = await self._registry.send("open_tab", timeout=timeout, url=url)
        logger.info("打开标签: chromeTabId=%s url=%s", result.get("chromeTabId"), url)
        return result

    async def close_tab(
        self,
        chrome_tab_id: int,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        return await self._registry.send(
            "close_tab", timeout=timeout, chromeTabId=chrome_tab_id
        )

    async def activate_tab(
        self,
        chrome_tab_id: int,
        timeout: float = 10.0,
    ) -> bool:
        result = await self._registry.send(
            "activate_tab", timeout=timeout, chromeTabId=chrome_tab_id
        )
        if isinstance(result, dict):
            return result.get("success", False)
        return bool(result)

    async def reload_tab(
        self,
        chrome_tab_id: int,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        return await self._registry.send(
            "reload_tab", timeout=timeout, chromeTabId=chrome_tab_id
        )

    async def list_tabs(self) -> list[dict[str, Any]]:
        return await self._registry.send("list_tabs", timeout=10.0)

    def list_tracked_tabs(self) -> list[dict[str, Any]]:
        return self._registry.tabs

    list_connected_tabs = list_tracked_tabs

    def get_tab(self, chrome_tab_id: int) -> dict[str, Any] | None:
        return self._registry.get_tab(chrome_tab_id)

    async def execute(
        self,
        chrome_tab_id: int,
        code: str,
        timeout: float = 30.0,
    ) -> Any:
        exec_id = str(uuid.uuid4())
        wrapped = (
            f'(async function(){{\n'
            f'{code}\n'
            f'}})().then(function(r){{\n'
            f'  window.postMessage({{type:"boss_exec_result",id:"{exec_id}",data:JSON.parse(JSON.stringify(r!==undefined?r:null))}},"*");\n'
            f'}},function(e){{\n'
            f'  window.postMessage({{type:"boss_exec_result",id:"{exec_id}",error:e&&e.message?e.message:String(e)}},"*");\n'
            f'}});'
        )
        self._registry._exec_store[exec_id] = wrapped
        return await self._registry.send(
            "execute", timeout=timeout,
            chromeTabId=chrome_tab_id, execId=exec_id,
        )

    async def query(
        self,
        chrome_tab_id: int,
        select: str,
        filter: dict | None = None,
        project: dict | None = None,
        return_: str = "list",
        timeout: float = 30.0,
    ) -> Any:
        result = await self._registry.send(
            "query", timeout=timeout,
            chromeTabId=chrome_tab_id, select=select,
            filter=filter, project=project, **{"return": return_},
        )
        if isinstance(result, dict) and "data" in result:
            return result["data"]
        return result

    async def bbox(
        self,
        chrome_tab_id: int,
        select: str,
        filter: dict | None = None,
        timeout: float = 30.0,
    ) -> dict | None:
        return await self._registry.send(
            "query", timeout=timeout,
            chromeTabId=chrome_tab_id, select=select,
            filter=filter, **{"return": "bbox"},
        )

    async def dump_html(
        self,
        chrome_tab_id: int,
        timeout: float = 30.0,
    ) -> str | None:
        """Dump 页面完整 HTML（document.documentElement.outerHTML）。"""
        return await self._registry.send(
            "dump_html", timeout=timeout,
            chromeTabId=chrome_tab_id,
        )
