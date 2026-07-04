"""Python API: open / close / list browser tabs and execute JS remotely.

Usage::

    from server.registry import TabRegistry
    from server.api import RemoteSession
    from server.main import create_app, run_server

    registry = TabRegistry()
    session = RemoteSession(registry)
    app = create_app(registry)

    # Start the WebSocket server in a background task, then:
    tabs = session.list_tabs()
    result = await session.execute(tab_id, "document.title")
    tab_id = await session.open_url("https://www.zhipin.com/")
    await session.close_tab(tab_id)
"""

from __future__ import annotations

import asyncio
import json
import logging
import webbrowser
from typing import Any

logger = logging.getLogger("boss.api")


class RemoteSession:
    """High-level Python API for remote browser tab control.

    All methods are thread-safe when called from an async context.
    """

    def __init__(self, registry: "TabRegistry") -> None:
        self._registry = registry

    # ── query ─────────────────────────────────────────────────

    def list_tabs(self) -> list[dict[str, Any]]:
        """Return metadata for every connected tab."""
        return self._registry.tabs

    def get_tab(self, tab_id: str) -> dict[str, Any] | None:
        """Return metadata for a single tab, or *None*."""
        return self._registry.get_tab(tab_id)

    # ── open / close ──────────────────────────────────────────

    async def open_url(
        self,
        url: str,
        wait_timeout: float = 15.0,
    ) -> str | None:
        """Open *url* in the default browser and wait for connection.

        Returns the ``tab_id`` that the userscript registered with,
        or ``None`` if no tab connected within *wait_timeout* seconds.
        """
        webbrowser.open(url)
        logger.info("打开 URL: %s", url)

        deadline = asyncio.get_event_loop().time() + wait_timeout
        while asyncio.get_event_loop().time() < deadline:
            for tab in self._registry.tabs:
                # Match by URL — the userscript sends the full URL on registration
                if tab.get("url") == url:
                    logger.info(
                        "标签已连接: %s — %s", tab["tab_id"][:8], url
                    )
                    return tab["tab_id"]
            await asyncio.sleep(0.5)

        logger.warning("等待标签连接超时: %s", url)
        return None

    async def close_tab(self, tab_id: str) -> None:
        """Send a close signal to the userscript and unregister.

        The userscript will call ``window.close()`` in response.
        Falls back to simply unregistering if the WebSocket is gone.
        """
        if self._registry.is_connected(tab_id):
            ws = self._registry._connections.get(tab_id)
            if ws is not None:
                try:
                    await ws.send_text(json.dumps({"type": "close"}))
                    await asyncio.sleep(0.3)  # brief pause for delivery
                except Exception:
                    pass

        self._registry.unregister(tab_id)
        logger.info("关闭标签: %s", tab_id[:8])

    # ── execute ───────────────────────────────────────────────

    async def execute(
        self,
        tab_id: str,
        code: str,
        context: str = "page",
        timeout: float = 30.0,
    ) -> Any:
        """Execute JavaScript on a connected tab and return the result.

        Parameters
        ----------
        tab_id :
            Target tab identifier.
        code :
            JavaScript source code.
        context :
            ``"page"`` (browser window) or ``"gm"`` (userscript scope).
        timeout :
            Max seconds to wait for a result.
        """
        return await self._registry.send_execute(tab_id, code, context, timeout)
