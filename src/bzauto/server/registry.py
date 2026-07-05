from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Callable
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.websockets import WebSocket

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
    """Shared state: tab metadata (from bg events), WS connection, pending futures."""

    def __init__(self) -> None:
        self._ws: WebSocket | None = None
        self._tabs: dict[int, dict[str, Any]] = {}
        self._pending: dict[str, asyncio.Future] = {}
        self._event_handlers: dict[str, list[Callable]] = {}
        self._exec_store: dict[str, str] = {}

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

    def set_ws(self, ws: WebSocket) -> None:
        logger.debug("设置 WebSocket 连接")
        self._ws = ws

    def remove_ws(self) -> None:
        logger.debug("移除 WebSocket 连接")
        self._ws = None

    def is_connected(self) -> bool:
        connected = self._ws is not None
        logger.debug("检查连接状态: %s", connected)
        return connected

    async def send(
        self,
        msg_type: str,
        timeout: float = 10.0,
        **extra: Any,
    ) -> Any:
        ws = self._ws
        if ws is None:
            raise ConnectionError("扩展后台未连接")

        cmd_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._pending[cmd_id] = fut

        payload = {"type": msg_type, "id": cmd_id, **extra}
        payload_str = json.dumps(payload)
        logger.debug(">> 发送命令: type=%s id=%s timeout=%s", msg_type, cmd_id, timeout)
        logger.debug(">> 命令内容: %s", payload_str[:500] if len(payload_str) > 500 else payload_str)
        await ws.send_text(payload_str)

        try:
            result = await asyncio.wait_for(fut, timeout=timeout)
            result_str = str(result) if result else "None"
            logger.debug("<< 命令完成: id=%s result=%s", cmd_id, result_str[:200] if len(result_str) > 200 else result_str)
            return result
        except asyncio.TimeoutError:
            self._pending.pop(cmd_id, None)
            logger.debug("!! 命令超时: id=%s type=%s timeout=%s", cmd_id, msg_type, timeout)
            raise TimeoutError(f"{msg_type} 超时 ({timeout}s)") from None

    def resolve_result(self, cmd_id: str, data: Any, error: str | None) -> None:
        fut = self._pending.pop(cmd_id, None)
        if fut is not None and not fut.done():
            if error:
                logger.debug("解析结果(错误): cmd_id=%s error=%s", cmd_id, error)
                fut.set_exception(Exception(error))
            else:
                data_str = str(data) if data else "None"
                logger.debug("解析结果(成功): cmd_id=%s data=%s", cmd_id, data_str[:100] if len(data_str) > 100 else data_str)
                fut.set_result(data)
        else:
            logger.debug("解析结果(忽略): cmd_id=%s (Future不存在或已完成)", cmd_id)

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
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
