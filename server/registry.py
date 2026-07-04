from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from collections.abc import Callable
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.websockets import WebSocket

logger = logging.getLogger("boss.registry")


class TabRegistry:
    """Shared state: tab metadata, WebSocket connections, pending execution futures."""

    def __init__(self) -> None:
        self._tabs: dict[str, dict[str, Any]] = {}
        self._connections: dict[str, WebSocket] = {}
        self._pending: dict[str, asyncio.Future] = {}
        self._pending_scripts: dict[str, str] = {}
        self._control_clients: list[WebSocket] = []
        self._event_handlers: dict[str, list[Callable]] = {}

    # ── event subscription ───────────────────────────────────────

    def on(self, event: str, callback: Callable) -> None:
        """Register a local callback for an event.

        Events:
        - ``tab_connected``     - received ``dict`` with key ``"tab"``
        - ``tab_disconnected``  - received ``dict`` with key ``"tabId"``
        - ``execution_result``  - received ``dict`` with keys
                                  ``"tabId"``, ``"id"``, ``"data"``, ``"error"``
        """
        self._event_handlers.setdefault(event, []).append(callback)

    def off(self, event: str, callback: Callable | None = None) -> None:
        """Unregister a callback.  If *callback* is ``None``, clears all for the event."""
        if callback is None:
            self._event_handlers.pop(event, None)
        else:
            try:
                self._event_handlers[event].remove(callback)
            except (KeyError, ValueError):
                pass

    def _broadcast(self, msg: dict) -> None:
        # Local callbacks
        for cb in self._event_handlers.get(msg.get("type", ""), []):
            try:
                result = cb(msg)
                if asyncio.iscoroutine(result):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(result)
                    except RuntimeError:
                        logger.warning(
                            "跳过异步回调（无运行中的事件循环）: %s",
                            msg.get("type", ""),
                        )
            except Exception as e:
                logger.error("事件回调异常 (%s): %s", msg.get("type", ""), e)
        # WS control clients
        for ws in self._control_clients[:]:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(ws.send_text(json.dumps(msg)))
            except RuntimeError:
                pass
            except Exception:
                self.remove_control_client(ws)

    # ── tab lifecycle ────────────────────────────────────────────

    def register(self, tab_id: str, url: str, title: str, ws: WebSocket) -> None:
        self._tabs[tab_id] = {
            "tab_id": tab_id,
            "url": url,
            "title": title,
            "connected_at": datetime.now(timezone.utc).isoformat(),
        }
        self._connections[tab_id] = ws
        logger.info("[+] 标签注册: %s - %s", tab_id[:8], title)
        self._broadcast({"type": "tab_connected", "tab": self._tabs[tab_id]})

    def unregister(self, tab_id: str) -> None:
        info = self._tabs.pop(tab_id, None)
        self._connections.pop(tab_id, None)
        for cid, fut in list(self._pending.items()):
            if not fut.done():
                fut.set_exception(ConnectionError(f"标签 {tab_id[:8]} 已断开"))
            self._pending.pop(cid, None)
            self._pending_scripts.pop(cid, None)
        self._broadcast({"type": "tab_disconnected", "tabId": tab_id})
        if info:
            logger.info("[-] 标签注销: %s - %s", tab_id[:8], info.get("title", ""))

    def is_connected(self, tab_id: str) -> bool:
        return tab_id in self._connections

    @property
    def tabs(self) -> list[dict[str, Any]]:
        return list(self._tabs.values())

    def get_tab(self, tab_id: str) -> dict[str, Any] | None:
        return self._tabs.get(tab_id)

    # ── execution ────────────────────────────────────────────────

    async def send_execute(
        self,
        tab_id: str,
        code: str,
        context: str = "page",
        timeout: float = 30.0,
    ) -> Any:
        ws = self._connections.get(tab_id)
        if ws is None:
            raise ValueError(f"标签 {tab_id[:8]} 未连接")

        cmd_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._pending[cmd_id] = fut
        self._pending_scripts[cmd_id] = code

        payload = {
            "type": "execute",
            "id": cmd_id,
            "context": context,
            "code": code,
        }
        await ws.send_text(json.dumps(payload))

        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(cmd_id, None)
            self._pending_scripts.pop(cmd_id, None)
            raise TimeoutError(f"执行超时 ({timeout}s)")

    async def send_simple(
        self,
        tab_id: str,
        msg_type: str,
        timeout: float = 10.0,
        **extra: Any,
    ) -> Any:
        ws = self._connections.get(tab_id)
        if ws is None:
            raise ValueError(f"标签 {tab_id[:8]} 未连接")

        cmd_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._pending[cmd_id] = fut

        payload = {"type": msg_type, "id": cmd_id, **extra}
        await ws.send_text(json.dumps(payload))

        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(cmd_id, None)
            raise TimeoutError(f"{msg_type} 超时 ({timeout}s)")

    async def send_get_coordinates(
        self,
        tab_id: str,
        selector: str,
        timeout: float = 30.0,
    ) -> Any:
        return await self.send_simple(
            tab_id, "get_coordinates", timeout=timeout, selector=selector
        )

    async def send_activate(
        self,
        tab_id: str,
        timeout: float = 10.0,
    ) -> Any:
        return await self.send_simple(tab_id, "activate", timeout=timeout)

    def resolve_result(self, cmd_id: str, data: Any, error: str | None) -> None:
        self._pending_scripts.pop(cmd_id, None)
        fut = self._pending.pop(cmd_id, None)
        if fut is not None and not fut.done():
            if error:
                fut.set_exception(Exception(error))
            else:
                fut.set_result(data)

    def get_pending_script(self, cmd_id: str) -> str | None:
        code = self._pending_scripts.get(cmd_id)
        if code is None:
            return None
        # 清空避免重复使用
        self._pending_scripts.pop(cmd_id, None)
        # 构造绕过 CSP 的包装脚本
        escaped_id = json.dumps(cmd_id)
        return f"""
(async function() {{
  const __boss_id__ = {escaped_id};
  try {{
    const result = await (async function() {{ {code} }})();
    window.dispatchEvent(new CustomEvent('__boss_result', {{
      detail: {{
        id: __boss_id__,
        data: JSON.parse(JSON.stringify(result)),
        error: null
      }}
    }}));
  }} catch(e) {{
    window.dispatchEvent(new CustomEvent('__boss_result', {{
      detail: {{
        id: __boss_id__,
        data: null,
        error: e.toString() + '\\\\n' + (e.stack || '')
      }}
    }}));
  }}
}})();
"""

    # ── control clients ─────────────────────────────────────────

    def add_control_client(self, ws: WebSocket) -> None:
        self._control_clients.append(ws)

    def remove_control_client(self, ws: WebSocket) -> None:
        if ws in self._control_clients:
            self._control_clients.remove(ws)

    # ── cleanup ─────────────────────────────────────────────────

    async def close_all(self) -> None:
        for ws in list(self._connections.values()):
            try:
                await ws.close()
            except Exception:
                pass
        for ws in list(self._control_clients):
            try:
                await ws.close()
            except Exception:
                pass
