"""进程级单例服务器生命周期 + ensure_tab 工具。"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

import uvicorn

from bzauto.server.registry import TabRegistry
from bzauto.server.app import create_app

if TYPE_CHECKING:
    from bzauto.server.session import TabSession

log = logging.getLogger("boss.lifecycle")

_registry: TabRegistry | None = None
_server: uvicorn.Server | None = None
_server_task: asyncio.Task | None = None


def get_registry() -> TabRegistry:
    global _registry
    if _registry is None:
        _registry = TabRegistry()
    return _registry


async def start_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    """启动全局 WebSocket 服务器（幂等）。"""
    global _server, _server_task
    if _server is not None:
        return
    app = create_app(get_registry())
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    _server = uvicorn.Server(config)
    _server_task = asyncio.create_task(_server.serve())
    log.info("服务器已启动: http://%s:%s/socket.io/", host, port)


async def stop_server() -> None:
    """停止全局 WebSocket 服务器。"""
    global _server, _server_task
    if _server is not None:
        _server.should_exit = True
        _server = None
    if _server_task is not None:
        _server_task.cancel()
        try:
            await _server_task
        except asyncio.CancelledError:
            pass
        _server_task = None
    log.info("服务器已停止")


def is_server_running() -> bool:
    return _server is not None


async def ensure_tab(
    session: TabSession,
    url: str | None = None,
    *,
    reuse_existing: bool = False,
) -> int:
    """等待扩展连接就绪，打开或复用标签，设为当前。返回 chromeTabId。"""
    registry = session.registry

    deadline = time.monotonic() + 60.0
    while not registry.is_connected():
        if time.monotonic() > deadline:
            raise ConnectionError("扩展后台未连接")
        await asyncio.sleep(0.5)

    remote = session.remote_session

    if url:
        if reuse_existing:
            for tab in registry.tabs:
                if tab.get("url") == url:
                    session.set_current(tab["chromeTabId"])
                    log.info("复用标签: chromeTabId=%s", tab["chromeTabId"])
                    return tab["chromeTabId"]
        result = await remote.open_tab(url)
        session.set_current(result["chromeTabId"])
        log.info("标签已创建: chromeTabId=%s", result["chromeTabId"])
        return result["chromeTabId"]

    if registry.tabs:
        tab = registry.tabs[-1]
        session.set_current(tab["chromeTabId"])
        log.info("使用已有标签: chromeTabId=%s", tab["chromeTabId"])
        return tab["chromeTabId"]

    raise RuntimeError("没有可用标签，请指定 url")
