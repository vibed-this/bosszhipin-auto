"""Boss直聘页面顶部导航栏对象 — 未读消息角标等。"""
from __future__ import annotations

import logging

from bzauto.pages.base import BasePage

log = logging.getLogger("page.header")

_UNREAD_JS = """
(function() {
    var el = document.querySelector('span.nav-chat-num');
    if (!el) return null;
    var count = parseInt(el.textContent && el.textContent.trim(), 10);
    return Number.isFinite(count) ? count : 0;
})()
"""


class BossHeader(BasePage):
    """Boss直聘页面顶部导航栏对象 — 未读消息角标等。"""

    _LOADED_SELECTOR = ".nav-chat-num"

    async def get_unread_count(self) -> int | None:
        """返回右上角消息未读数；导航栏尚未加载时返回 None。"""
        value = await self._session.eval_js(_UNREAD_JS)
        if value is None or isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            log.debug("无法解析未读角标: %r", value)
            return None
