from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

import socketio

logger = logging.getLogger("boss.registry")


class ElementNotFound(LookupError):
    """Raised when a bbox/query selector matches no elements."""

    def __init__(self, selector: str, filter: dict | None = None) -> None:
        self.selector = selector
        self.filter = filter
        ctx = f"selector={selector!r}"
        if filter:
            ctx += f" filter={filter!r}"
        super().__init__(f"未找到匹配元素: {ctx}")


class TabRegistry:
    """Shared state: tab metadata (from bg events), Socket.IO server, exec store."""

    def __init__(self) -> None:
        self.sio = socketio.AsyncServer(
            async_mode="asgi",
            cors_allowed_origins="*",
            ping_interval=20,
            ping_timeout=25,
        )
        self._sid: str | None = None
        self._tabs: dict[int, dict[str, Any]] = {}
        self._event_handlers: dict[str, list[Callable]] = {}
        self._exec_store: dict[str, str] = {}
        self._register_sio_events()

    def _register_sio_events(self) -> None:
        @self.sio.event
        async def connect(sid, environ):
            logger.info("扩展后台已连接: sid=%s", sid[:8])
            self._sid = sid

        @self.sio.event
        async def disconnect(sid):
            logger.info("扩展后台已断开: sid=%s", sid[:8])
            if self._sid == sid:
                self._sid = None

        @self.sio.on("sync_state")
        async def on_sync_state(sid, data):
            self.handle_tab_event({"type": "sync_state", **data})

        @self.sio.on("tab_created")
        async def on_tab_created(sid, data):
            self.handle_tab_event({"type": "tab_created", **data})

        @self.sio.on("tab_updated")
        async def on_tab_updated(sid, data):
            self.handle_tab_event({"type": "tab_updated", **data})

        @self.sio.on("tab_closed")
        async def on_tab_closed(sid, data):
            self.handle_tab_event({"type": "tab_closed", **data})

        @self.sio.on("tab_activated")
        async def on_tab_activated(sid, data):
            self.handle_tab_event({"type": "tab_activated", **data})

    def on(self, event: str, callback: Callable) -> None:
        logger.debug("注册事件监听: event=%s", event)
        self._event_handlers.setdefault(event, []).append(callback)

    def off(self, event: str, callback: Callable | None = None) -> None:
        if callback is None:
            logger.debug("移除所有事件监听: event=%s", event)
            self._event_handlers.pop(event, None)
        else:
            try:
                self._event_handlers[event].remove(callback)
                logger.debug("移除事件监听: event=%s", event)
            except (KeyError, ValueError):
                pass

    def _broadcast(self, msg: dict) -> None:
        event_type = msg.get("type", "")
        handlers = self._event_handlers.get(event_type, [])
        if handlers:
            logger.debug("广播事件: type=%s handlers=%d", event_type, len(handlers))
        for cb in handlers:
            try:
                result = cb(msg)
                if asyncio.iscoroutine(result):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(result)
                    except RuntimeError:
                        logger.warning("跳过异步回调: %s", event_type)
            except Exception as e:
                logger.error("事件回调异常 (%s): %s", event_type, e)

    def is_connected(self) -> bool:
        connected = self._sid is not None
        logger.debug("检查连接状态: %s", connected)
        return connected

    async def call(self, event: str, data: dict, timeout: float = 10.0) -> Any:
        if self._sid is None:
            raise ConnectionError("扩展后台未连接")
        try:
            result = await self.sio.call(event, data, to=self._sid, timeout=timeout)
            if isinstance(result, dict) and "error" in result:
                raise Exception(result["error"])
            result_str = str(result) if result else "None"
            logger.debug("<< 命令完成: event=%s result=%s", event, result_str[:200] if len(result_str) > 200 else result_str)
            return result
        except socketio.exceptions.TimeoutError:
            logger.debug("!! 命令超时: event=%s timeout=%s", event, timeout)
            raise TimeoutError(f"{event} 超时 ({timeout}s)") from None

    def handle_tab_event(self, msg: dict) -> None:
        t = msg.get("type")
        logger.debug("处理标签事件: type=%s", t)

        if t == "sync_state":
            new_tabs: dict[int, dict] = {}
            for tb in msg.get("tabs", []):
                ctid = tb.get("chromeTabId")
                if ctid is not None:
                    new_tabs[ctid] = tb

            old_ids = set(self._tabs.keys())
            new_ids = set(new_tabs.keys())

            for ctid in old_ids - new_ids:
                tb = self._tabs[ctid]
                logger.info("[-] 标签从同步消失: chromeTabId=%s", ctid)
                self._broadcast({"type": "tab_gone", "chromeTabId": ctid, "source": "sync_removed", **tb})

            for ctid in new_ids - old_ids:
                tb = new_tabs[ctid]
                logger.info("[+] 标签同步: chromeTabId=%s url=%s", ctid, tb.get("url", "")[:60])
                self._broadcast({"type": "tab_ready", "chromeTabId": ctid, "source": "sync", **tb})

            for ctid in old_ids & new_ids:
                old = self._tabs[ctid]
                new = new_tabs[ctid]
                changes = {}
                for key in ("url", "title", "status", "active"):
                    if key in new and old.get(key) != new[key]:
                        changes[key] = new[key]
                if changes:
                    logger.debug("标签变更: chromeTabId=%s changes=%s", ctid, changes)
                    self._broadcast({"type": "tab_changed", "chromeTabId": ctid, "changes": changes, **new})

            self._tabs = new_tabs
            logger.info("[同步] 全量标签状态: %d 个标签", len(self._tabs))

        elif t == "tab_created":
            ctid = msg.get("chromeTabId")
            if ctid is not None:
                tb = {
                    "chromeTabId": ctid,
                    "url": msg.get("url", ""),
                    "title": msg.get("title", ""),
                    "status": msg.get("status", "loading"),
                    "active": msg.get("active", False),
                    "windowId": msg.get("windowId"),
                }
                self._tabs[ctid] = tb
                logger.info("[+] 标签创建: chromeTabId=%s url=%s", ctid, msg.get("url", "")[:60])
                self._broadcast({"type": "tab_ready", "chromeTabId": ctid, "source": "created", **tb})

        elif t == "tab_updated":
            ctid = msg.get("chromeTabId")
            if ctid is not None:
                if ctid in self._tabs:
                    tb = self._tabs[ctid]
                    changes = {}
                    for key in ("url", "title", "status"):
                        if key in msg and msg[key] is not None and tb.get(key) != msg[key]:
                            changes[key] = msg[key]
                            tb[key] = msg[key]
                    if changes:
                        logger.debug("标签更新: chromeTabId=%s changes=%s", ctid, changes)
                        self._broadcast({"type": "tab_changed", "chromeTabId": ctid, "changes": changes, **tb})
                else:
                    tb = {
                        "chromeTabId": ctid,
                        "url": msg.get("url", ""),
                        "title": msg.get("title", ""),
                        "status": msg.get("status", "loading"),
                        "active": msg.get("active", False),
                        "windowId": msg.get("windowId"),
                    }
                    self._tabs[ctid] = tb
                    logger.info("[+] 标签更新(竞态): chromeTabId=%s url=%s", ctid, tb.get("url", "")[:60])
                    self._broadcast({"type": "tab_ready", "chromeTabId": ctid, "source": "updated", **tb})

        elif t == "tab_closed":
            ctid = msg.get("chromeTabId")
            if ctid is not None and ctid in self._tabs:
                tb = self._tabs.pop(ctid)
                logger.info("[-] 标签关闭: chromeTabId=%s", ctid)
                self._broadcast({"type": "tab_gone", "chromeTabId": ctid, "source": "closed", **tb})

        elif t == "tab_activated":
            ctid = msg.get("chromeTabId")
            if ctid is not None:
                logger.debug("标签激活: chromeTabId=%s", ctid)
                for tid in self._tabs:
                    new_active = (tid == ctid)
                    if self._tabs[tid]["active"] != new_active:
                        self._tabs[tid]["active"] = new_active
                        self._broadcast({"type": "tab_changed", "chromeTabId": tid, "changes": {"active": new_active}, **self._tabs[tid]})

    @property
    def tabs(self) -> list[dict[str, Any]]:
        return list(self._tabs.values())

    def get_tab(self, chrome_tab_id: int) -> dict[str, Any] | None:
        return self._tabs.get(chrome_tab_id)

    async def close_all(self) -> None:
        self._exec_store.clear()
        if self._sid is not None:
            # 连接将由 Socket.IO 自动管理
            self._sid = None