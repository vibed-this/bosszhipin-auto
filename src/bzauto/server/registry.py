"""Multi-account TabRegistry — 支持多个 Chrome profile 同时连接。"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import socketio

from bzauto.protocol.types import (
    EventName,
    QueryFilter,
    RemoteCallError,
    TabEvent,
    TabInfo,
)

logger = logging.getLogger("boss.registry")


@dataclass
class AccountConnection:
    account_id: str
    sid: str
    tabs: dict[int, TabInfo] = field(default_factory=dict)


class ElementNotFound(LookupError):
    """Raised when a bbox/query selector matches no elements."""

    def __init__(self, selector: str, filter: QueryFilter | None = None) -> None:
        self.selector = selector
        self.filter = filter
        ctx = f"selector={selector!r}"
        if filter:
            ctx += f" filter={filter!r}"
        super().__init__(f"未找到匹配元素: {ctx}")


class TabRegistry:
    """Shared state: multi-account tab metadata, Socket.IO server, exec store."""

    def __init__(self) -> None:
        self.sio = socketio.AsyncServer(
            async_mode="asgi",
            cors_allowed_origins="*",
            ping_interval=20,
            ping_timeout=25,
        )
        self._connections: dict[str, AccountConnection] = {}  # account_id -> conn
        self._sid_to_account: dict[str, str] = {}  # sid -> account_id
        self._event_handlers: dict[str, list[Callable[[TabEvent], Any]]] = {}
        self._exec_store: dict[str, str] = {}
        self._register_sio_events()

    def _register_sio_events(self) -> None:
        @self.sio.event
        async def connect(sid, environ):
            logger.info("扩展后台已连接: sid=%s", sid[:8])

        @self.sio.event
        async def disconnect(sid):
            account_id = self._sid_to_account.pop(sid, None)
            if account_id:
                self._connections.pop(account_id, None)
                logger.info("扩展后台已断开: account=%s sid=%s", account_id, sid[:8])
            else:
                logger.info("扩展后台已断开(未注册): sid=%s", sid[:8])

        @self.sio.on("register_account")
        async def on_register_account(sid: str, data: dict[str, Any]) -> None:
            account_id = data.get("account_id", "default")
            existing = self._sid_to_account.get(sid)
            if existing and existing != account_id:
                self._connections.pop(existing, None)
            self._connections[account_id] = AccountConnection(account_id=account_id, sid=sid)
            self._sid_to_account[sid] = account_id
            logger.info("账号已注册: account=%s sid=%s", account_id, sid[:8])

        @self.sio.on(EventName.SYNC_STATE)
        async def on_sync_state(sid: str, data: dict[str, Any]) -> None:
            self.handle_tab_event({"sid": sid, "type": EventName.SYNC_STATE, **data})

        @self.sio.on(EventName.TAB_CREATED)
        async def on_tab_created(sid: str, data: dict[str, Any]) -> None:
            self.handle_tab_event({"sid": sid, "type": EventName.TAB_CREATED, **data})

        @self.sio.on(EventName.TAB_UPDATED)
        async def on_tab_updated(sid: str, data: dict[str, Any]) -> None:
            self.handle_tab_event({"sid": sid, "type": EventName.TAB_UPDATED, **data})

        @self.sio.on(EventName.TAB_CLOSED)
        async def on_tab_closed(sid: str, data: dict[str, Any]) -> None:
            self.handle_tab_event({"sid": sid, "type": EventName.TAB_CLOSED, **data})

        @self.sio.on(EventName.TAB_ACTIVATED)
        async def on_tab_activated(sid: str, data: dict[str, Any]) -> None:
            self.handle_tab_event({"sid": sid, "type": EventName.TAB_ACTIVATED, **data})

    def on(self, event: str, callback: Callable[[TabEvent], Any]) -> None:
        logger.debug("注册事件监听: event=%s", event)
        self._event_handlers.setdefault(event, []).append(callback)

    def off(self, event: str, callback: Callable[[TabEvent], Any] | None = None) -> None:
        if callback is None:
            logger.debug("移除所有事件监听: event=%s", event)
            self._event_handlers.pop(event, None)
        else:
            try:
                self._event_handlers[event].remove(callback)
                logger.debug("移除事件监听: event=%s", event)
            except (KeyError, ValueError):
                pass

    def _broadcast(self, msg: Any) -> None:
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

    def is_connected(self, account_id: str | None = None) -> bool:
        if account_id is not None:
            return account_id in self._connections
        connected = len(self._connections) > 0
        logger.debug("检查连接状态: %s", connected)
        return connected

    def get_connected_accounts(self) -> list[str]:
        return list(self._connections.keys())

    async def call(self, event: str, data: dict, timeout: float = 10.0, account_id: str | None = None) -> Any:
        if account_id:
            conn = self._connections.get(account_id)
            if conn is None:
                raise ConnectionError(f"账号 {account_id} 未连接")
            sid = conn.sid
        else:
            if not self._connections:
                raise ConnectionError("扩展后台未连接")
            sid = next(iter(self._connections.values())).sid
        try:
            result = await self.sio.call(event, data, to=sid, timeout=int(timeout))
            if isinstance(result, dict) and "error" in result:
                raise RemoteCallError(event, result["error"])
            result_str = str(result) if result else "None"
            logger.debug("<< 命令完成: event=%s account=%s result=%s", event, account_id or "any", result_str[:200] if len(result_str) > 200 else result_str)
            return result
        except Exception as e:
            if "timeout" in str(type(e).__name__).lower() or "timeout" in str(e).lower():
                logger.debug("!! 命令超时: event=%s timeout=%s", event, timeout)
                raise TimeoutError(f"{event} 超时 ({timeout}s)") from None
            raise

    def handle_tab_event(self, msg: dict) -> None:
        t = msg.get("type")
        sid = msg.get("sid")
        account_id = self._sid_to_account.get(sid) if sid else None
        if account_id is None:
            return
        conn = self._connections.get(account_id)
        if conn is None:
            return
        tabs = conn.tabs

        logger.debug("处理标签事件: type=%s account=%s", t, account_id)

        if t == EventName.SYNC_STATE:
            new_tabs: dict[int, TabInfo] = {}
            for tb in msg.get("tabs", []):
                ctid = tb.get("chromeTabId")
                if ctid is not None:
                    new_tabs[ctid] = tb

            old_ids = set(tabs.keys())
            new_ids = set(new_tabs.keys())

            for ctid in old_ids - new_ids:
                tb = tabs[ctid]
                logger.info("[-] 标签从同步消失: account=%s chromeTabId=%s", account_id, ctid)
                self._broadcast({"type": EventName.TAB_GONE, "account_id": account_id, "chromeTabId": ctid, "source": "sync_removed", **tb})

            for ctid in new_ids - old_ids:
                tb = new_tabs[ctid]
                logger.info("[+] 标签同步: account=%s chromeTabId=%s", account_id, ctid)
                self._broadcast({"type": EventName.TAB_READY, "account_id": account_id, "chromeTabId": ctid, "source": "sync", **tb})

            for ctid in old_ids & new_ids:
                old = tabs[ctid]
                new = new_tabs[ctid]
                changes = {}
                for key in ("url", "title", "status", "active"):
                    if key in new and old.get(key) != new[key]:
                        changes[key] = new[key]
                if changes:
                    logger.debug("标签变更: account=%s chromeTabId=%s changes=%s", account_id, ctid, changes)
                    self._broadcast({"type": EventName.TAB_CHANGED, "account_id": account_id, "chromeTabId": ctid, "changes": changes, **new})

            conn.tabs = new_tabs
            logger.info("[同步] account=%s 全量标签状态: %d 个", account_id, len(tabs))

        elif t == EventName.TAB_CREATED:
            ctid = msg.get("chromeTabId")
            if ctid is not None:
                tb = self._build_tab_info(msg, ctid)
                tabs[ctid] = tb
                logger.info("[+] 标签创建: account=%s chromeTabId=%s", account_id, ctid)
                self._broadcast({"type": EventName.TAB_READY, "account_id": account_id, "chromeTabId": ctid, "source": "created", **tb})

        elif t == EventName.TAB_UPDATED:
            ctid = msg.get("chromeTabId")
            if ctid is not None:
                if ctid in tabs:
                    tb = tabs[ctid]
                    changes = {}
                    for key in ("url", "title", "status"):
                        if key in msg and msg[key] is not None and tb.get(key) != msg[key]:
                            changes[key] = msg[key]
                            tb[key] = msg[key]
                    if changes:
                        logger.debug("标签更新: account=%s chromeTabId=%s changes=%s", account_id, ctid, changes)
                        self._broadcast({"type": EventName.TAB_CHANGED, "account_id": account_id, "chromeTabId": ctid, "changes": changes, **tb})
                else:
                    tb = self._build_tab_info(msg, ctid)
                    tabs[ctid] = tb
                    logger.info("[+] 标签更新(竞态): account=%s chromeTabId=%s", account_id, ctid)
                    self._broadcast({"type": EventName.TAB_READY, "account_id": account_id, "chromeTabId": ctid, "source": "updated", **tb})

        elif t == EventName.TAB_CLOSED:
            ctid = msg.get("chromeTabId")
            if ctid is not None and ctid in tabs:
                tb = tabs.pop(ctid)
                logger.info("[-] 标签关闭: account=%s chromeTabId=%s", account_id, ctid)
                self._broadcast({"type": EventName.TAB_GONE, "account_id": account_id, "chromeTabId": ctid, "source": "closed", **tb})

        elif t == EventName.TAB_ACTIVATED:
            ctid = msg.get("chromeTabId")
            if ctid is not None:
                logger.debug("标签激活: account=%s chromeTabId=%s", account_id, ctid)
                for tid in tabs:
                    new_active = (tid == ctid)
                    if tabs[tid]["active"] != new_active:
                        tabs[tid]["active"] = new_active
                        self._broadcast({"type": EventName.TAB_CHANGED, "account_id": account_id, "chromeTabId": tid, "changes": {"active": new_active}, **tabs[tid]})

    def _build_tab_info(self, msg: dict[str, Any], chrome_tab_id: int) -> TabInfo:
        return TabInfo(
            chromeTabId=chrome_tab_id,
            url=msg.get("url", ""),
            title=msg.get("title", ""),
            status=msg.get("status", "loading"),
            active=msg.get("active", False),
            windowId=msg.get("windowId"),
        )

    @property
    def tabs(self) -> list[TabInfo]:
        result = []
        for conn in self._connections.values():
            result.extend(conn.tabs.values())
        return result

    def get_tabs(self, account_id: str) -> list[TabInfo]:
        conn = self._connections.get(account_id)
        if conn is None:
            return []
        return list(conn.tabs.values())

    def get_tab(self, chrome_tab_id: int) -> TabInfo | None:
        for conn in self._connections.values():
            if chrome_tab_id in conn.tabs:
                return conn.tabs[chrome_tab_id]
        return None

    def get_tab_by_account(self, chrome_tab_id: int, account_id: str) -> TabInfo | None:
        conn = self._connections.get(account_id)
        if conn is None:
            return None
        return conn.tabs.get(chrome_tab_id)

    async def close_all(self) -> None:
        self._exec_store.clear()
        self._connections.clear()
        self._sid_to_account.clear()
