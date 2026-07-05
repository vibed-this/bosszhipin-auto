"""Python API: remote browser tab control via Chrome extension.

Usage::

    from server import TabRegistry, RemoteSession, create_app

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

import logging
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

    # ── event subscription ───────────────────────────────────────

    def on(self, event: str, callback: Callable) -> None:
        self._registry.on(event, callback)

    def off(self, event: str, callback: Callable | None = None) -> None:
        self._registry.off(event, callback)

    # ── tab lifecycle ─────────────────────────────────────────

    async def open_tab(
        self,
        url: str,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        """Open *url* in a new Chrome tab.

        Returns ``{chromeTabId, url}`` immediately after tab creation.
        """
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
        """Close a Chrome tab by its ``chromeTabId``."""
        return await self._registry.send(
            "close_tab", timeout=timeout, chromeTabId=chrome_tab_id
        )

    async def activate_tab(
        self,
        chrome_tab_id: int,
        timeout: float = 10.0,
    ) -> bool:
        """Activate a Chrome tab: bring its window to front and focus.

        Returns ``True`` on success.
        """
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
        """Reload a Chrome tab, returns ``{chromeTabId}``."""
        return await self._registry.send(
            "reload_tab", timeout=timeout, chromeTabId=chrome_tab_id
        )

    async def list_tabs(self) -> list[dict[str, Any]]:
        """List all Chrome tabs via extension API.

        Each entry contains ``chromeTabId``, ``url``, ``title``, ``active``,
        ``windowId``.
        """
        return await self._registry.send("list_tabs", timeout=10.0)

    # ── local state access (no WS roundtrip) ──────────────────

    def list_tracked_tabs(self) -> list[dict[str, Any]]:
        """Return all tracked tabs (synced from background events).

        Each entry contains ``chromeTabId``, ``url``, ``title``, ``status``,
        ``active``, ``windowId``.
        """
        return self._registry.tabs

    list_connected_tabs = list_tracked_tabs  # backward compat

    def get_tab(self, chrome_tab_id: int) -> dict[str, Any] | None:
        """Return tracked info for a single tab by its ``chromeTabId``."""
        return self._registry.get_tab(chrome_tab_id)

    # ── execute (raw JS via chrome.scripting) ─────────────────

    async def execute(
        self,
        chrome_tab_id: int,
        code: str,
        world: str = "isolated",
        timeout: float = 30.0,
    ) -> Any:
        """Execute JavaScript on a tab via ``chrome.scripting.executeScript``.

        Parameters
        ----------
        chrome_tab_id :
            Target tab ID.
        code :
            JavaScript source code.
        world :
            ``"isolated"`` (default, eval works regardless of page CSP) or
            ``"main"`` (subject to page CSP).
        timeout :
            Max seconds to wait for a result.
        """
        return await self._registry.send(
            "execute", timeout=timeout,
            chromeTabId=chrome_tab_id, code=code, world=world,
        )

    # ── declarative DOM query ─────────────────────────────────

    async def query(
        self,
        chrome_tab_id: int,
        select: str,
        filter: dict | None = None,
        project: dict | None = None,
        return_: str = "list",
        timeout: float = 30.0,
    ) -> Any:
        """Declarative DOM query on a tab (via ``chrome.scripting``).

        Parameters
        ----------
        chrome_tab_id :
            Target tab ID.
        select :
            CSS selector for ``querySelectorAll``.
        filter :
            Optional filter dict with ``textContains``, ``textAny``,
            ``textNone``, ``index``, ``nth``.
        project :
            Dict mapping output keys to ``subSelector@attr`` specs.
        return_ :
            One of ``"bbox"``, ``"bboxList"``, ``"list"``, ``"first"``,
            ``"count"``, ``"raw"``.
        timeout :
            Max seconds to wait.
        """
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
        """Convenience: query bbox of first matching element.

        Returns ``{css: {x,y,w,h,cx,cy}, physical: {x,y,w,h,cx,cy}}``
        or ``None`` if no match.
        """
        return await self.query(
            chrome_tab_id, select=select, filter=filter,
            return_="bbox", timeout=timeout,
        )
