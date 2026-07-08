"""Boss直聘页面顶部导航栏对象 — 未读消息角标等。"""
from __future__ import annotations

import logging

from bzauto.pages.base import BasePage

log = logging.getLogger("page.header")

_UNREAD_JS = "parseInt(document.querySelector('span.nav-chat-num')?.textContent?.trim()) || 0"


class BossHeader(BasePage):
    """Boss直聘页面顶部导航栏对象 — 未读消息角标等。"""

    _LOADED_SELECTOR = ".nav-chat-num"

    async def get_unread_count(self) -> int:
        """返回右上角消息未读数。"""
        return await self._session.eval_js(_UNREAD_JS)
