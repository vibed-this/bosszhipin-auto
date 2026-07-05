"""Python API: remote browser tab control via Chrome extension.

Usage::

    from bzauto import TabRegistry, RemoteSession, create_app

    registry = TabRegistry()
    session = RemoteSession(registry)
    app = create_app(registry)

    # Start the Socket.IO server in a background task, then:
    tabs = await session.list_tabs()
    result = await session.execute(42, "document.title")
    tab = await session.open_tab("https://www.zhipin.com/")
    await session.close_tab(tab["chromeTabId"])
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("boss.api")


class RemoteSession:
    """High-level Python API for remote browser tab control.

    All operations go through the extension background Socket.IO,
    which uses ``chrome.scripting.executeScript`` for JS execution
    and ``chrome.tabs.*`` for tab management.
    """

    def __init__(self, registry: "TabRegistry") -> None:
        self._registry = registry

    def on(self, event: str, callback: Callable) -> None:
        logger.debug("注册事件监听: event=%s", event)
        self._registry.on(event, callback)

    def off(self, event: str, callback: Callable | None = None) -> None:
        logger.debug("移除事件监听: event=%s", event)
        self._registry.off(event, callback)

    async def open_tab(
        self,
        url: str,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        logger.debug("打开标签: url=%s timeout=%s", url, timeout)
        if not self._registry.is_connected():
            raise ConnectionError("扩展后台未连接")
        result = await self._registry.call("open_tab", {"url": url}, timeout=timeout)
        logger.info("打开标签: chromeTabId=%s url=%s", result.get("chromeTabId"), url)
        return result

    async def close_tab(
        self,
        chrome_tab_id: int,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        logger.debug("关闭标签: chromeTabId=%s timeout=%s", chrome_tab_id, timeout)
        return await self._registry.call(
            "close_tab", {"chromeTabId": chrome_tab_id}, timeout=timeout
        )

    async def activate_tab(
        self,
        chrome_tab_id: int,
        timeout: float = 10.0,
    ) -> bool:
        logger.debug("激活标签: chromeTabId=%s timeout=%s", chrome_tab_id, timeout)
        result = await self._registry.call(
            "activate_tab", {"chromeTabId": chrome_tab_id}, timeout=timeout
        )
        if isinstance(result, dict):
            return result.get("success", False)
        return bool(result)

    async def reload_tab(
        self,
        chrome_tab_id: int,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        logger.debug("刷新标签: chromeTabId=%s timeout=%s", chrome_tab_id, timeout)
        return await self._registry.call(
            "reload_tab", {"chromeTabId": chrome_tab_id}, timeout=timeout
        )

    async def list_tabs(self) -> list[dict[str, Any]]:
        logger.debug("列出所有标签")
        return await self._registry.call("list_tabs", {}, timeout=10.0)

    def list_tracked_tabs(self) -> list[dict[str, Any]]:
        tabs = self._registry.tabs
        logger.debug("获取已跟踪标签: %d 个", len(tabs))
        return tabs

    list_connected_tabs = list_tracked_tabs

    def get_tab(self, chrome_tab_id: int) -> dict[str, Any] | None:
        tab = self._registry.get_tab(chrome_tab_id)
        logger.debug("获取标签: chromeTabId=%s found=%s", chrome_tab_id, tab is not None)
        return tab

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
        logger.debug("执行JS: chromeTabId=%s execId=%s timeout=%s", chrome_tab_id, exec_id, timeout)
        logger.debug("JS代码长度: %d 字符", len(code))
        return await self._registry.call(
            "execute", {"chromeTabId": chrome_tab_id, "execId": exec_id}, timeout=timeout
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
        logger.debug("DOM查询: chromeTabId=%s select=%s return=%s", chrome_tab_id, select, return_)
        if filter:
            logger.debug("查询过滤器: %s", filter)
        if project:
            logger.debug("查询投影: %s", project)
        data: dict[str, Any] = {
            "chromeTabId": chrome_tab_id,
            "select": select,
            "filter": filter,
            "project": project,
            "return": return_,
        }
        result = await self._registry.call("query", data, timeout=timeout)
        if isinstance(result, dict) and "data" in result:
            data = result["data"]
            data_str = str(data) if data else "None"
            logger.debug("查询结果: %s", data_str[:200] if len(data_str) > 200 else data_str)
            return data
        return result

    async def bbox(
        self,
        chrome_tab_id: int,
        select: str,
        filter: dict | None = None,
        timeout: float = 30.0,
    ) -> dict | None:
        logger.debug("获取元素坐标: chromeTabId=%s select=%s", chrome_tab_id, select)
        if filter:
            logger.debug("坐标过滤器: %s", filter)
        data: dict[str, Any] = {
            "chromeTabId": chrome_tab_id,
            "select": select,
            "filter": filter,
            "return": "bbox",
        }
        return await self._registry.call("query", data, timeout=timeout)

    async def dump_html(
        self,
        chrome_tab_id: int,
        timeout: float = 30.0,
    ) -> str | None:
        """Dump 页面完整 HTML（document.documentElement.outerHTML）。"""
        logger.debug("Dump HTML: chromeTabId=%s timeout=%s", chrome_tab_id, timeout)
        return await self._registry.call(
            "dump_html", {"chromeTabId": chrome_tab_id}, timeout=timeout
        )