"""所有 flow 的基类：page + session 持有 + 通用 setup。"""
from __future__ import annotations

import logging
from typing import Generic, Protocol, TypeVar

from bzauto.config import get_config
from bzauto.server.tab_session import TabSession

log = logging.getLogger("flow.base")


class _LoadablePage(Protocol):
    async def wait_loaded(self, timeout: float = ...) -> bool: ...


P = TypeVar("P", bound=_LoadablePage)


class BaseFlow(Generic[P]):
    """所有 flow 的基类：page + session 持有 + 通用 setup。"""

    def __init__(self, page: P, session: TabSession, account_id: str = "main") -> None:
        self._page = page
        self._session = session
        self._account_id = account_id

    async def _setup(
        self,
        url: str | None = None,
        *,
        reuse_existing: bool = False,
        timeout: float = 20.0,
    ) -> bool:
        from bzauto.server.lifecycle import ensure_tab

        await ensure_tab(self._session, url, reuse_existing=reuse_existing)
        await self._session.activate()
        loaded = await self._page.wait_loaded(timeout=timeout)
        if not loaded:
            log.warning("页面加载超时")
        return loaded