from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
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
        self._control_clients: list[WebSocket] = []

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
            raise TimeoutError(f"执行超时 ({timeout}s)")

    def resolve_result(self, cmd_id: str, data: Any, error: str | None) -> None:
        fut = self._pending.pop(cmd_id, None)
        if fut is not None and not fut.done():
            if error:
                fut.set_exception(Exception(error))
            else:
                fut.set_result(data)

    # ── control clients ─────────────────────────────────────────

    def add_control_client(self, ws: WebSocket) -> None:
        self._control_clients.append(ws)

    def remove_control_client(self, ws: WebSocket) -> None:
        if ws in self._control_clients:
            self._control_clients.remove(ws)

    def _broadcast(self, msg: dict) -> None:
        for ws in self._control_clients[:]:
            try:
                asyncio.create_task(ws.send_text(json.dumps(msg)))
            except Exception:
                self.remove_control_client(ws)

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
