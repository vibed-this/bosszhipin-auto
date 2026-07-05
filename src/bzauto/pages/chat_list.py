from __future__ import annotations

import logging
import re
from typing import Any

from bzauto.server.session import TabSession

log = logging.getLogger("page.chat_list")

_CHAT_URL = "https://www.zhipin.com/web/geek/chat"

_LIST_ITEM = "li[role='listitem']"
_NAME = ".name-text"
_NAME_BOX = ".name-box"
_TIME = ".text .time"
_MSG = ".last-msg-text"
_STATUS = ".message-status"
_FIGURE = ".figure .image-circle"
_FRIEND_CONTENT = ".friend-content"

_LABEL_LIST = ".label-list li .label-name"
_SEARCH_INPUT = ".boss-search-input"
_FOOTER = ".boss-list-footer .finished"
_CHAT_NO_DATA = ".chat-no-data .no-data-text"


class BossChatListPage:
    """Boss直聘聊天列表页面对象（选择器 + 操作方法）。"""

    def __init__(self, session: TabSession) -> None:
        self._session = session

    async def get_chat_items(self, limit: int = 50) -> list[dict[str, Any]]:
        raw = await self._session.query(
            select=_LIST_ITEM,
            project={
                "name": f"{_NAME}@text",
                "company": f"{_NAME_BOX} span:nth-child(2)@text",
                "position": f"{_NAME_BOX} span:nth-child(4)@text",
                "time": f"{_TIME}@text",
                "lastMsg": f"{_MSG}@text",
            },
            return_="list",
        )
        if not raw:
            return []
        return raw[:limit]

    async def get_chat_items_with_status(self) -> list[dict[str, Any]]:
        raw = await self._session.query(
            select=_LIST_ITEM,
            return_="raw",
        )
        if not raw:
            return []

        results = []
        for item in raw:
            html = item.get("html", "")
            name = re.search(r'class="name-text">(.*?)</span>', html)
            spans = re.findall(
                r'<span>(.*?)</span>',
                html.split("name-box")[1].split("last-msg")[0],
            ) if "name-box" in html else []
            time_m = re.search(r'class="time">(.*?)</span>', html)
            msg = re.search(r'class="last-msg-text">(.*?)</span>', html)
            status_m = re.search(
                r'class="message-status\s+(status-[^"]+)"', html
            )

            status = ""
            if status_m:
                s = status_m.group(1)
                status = "已读" if "read" in s else "送达" if "delivery" in s else ""

            results.append({
                "name": name.group(1) if name else "",
                "company": spans[0] if len(spans) > 0 else "",
                "position": spans[1] if len(spans) > 1 else "",
                "time": time_m.group(1) if time_m else "",
                "status": status,
                "lastMsg": msg.group(1).strip()[:200] if msg else "",
            })
        return results

    async def get_chat_item_count(self) -> int:
        result = await self._session.query(
            select=_LIST_ITEM, return_="count",
        )
        return int(result) if result is not None else 0

    async def is_loaded(self) -> bool:
        count = await self.get_chat_item_count()
        return count > 0

    async def is_chat_page(self) -> bool:
        tabs = self._session.registry.tabs
        for tab in tabs:
            url = tab.get("url", "")
            if "zhipin.com" in url and "chat" in url:
                return True
        return False

    async def get_labels(self) -> list[str]:
        raw = await self._session.query(
            select=_LABEL_LIST, return_="raw",
        )
        if not raw:
            return []
        return [r.get("text", "").strip() for r in raw]

    async def has_more(self) -> bool:
        raw = await self._session.query(
            select=_FOOTER, return_="raw",
        )
        return bool(raw)

    async def get_no_data_text(self) -> str | None:
        raw = await self._session.query(
            select=_CHAT_NO_DATA, return_="raw",
        )
        if raw:
            return raw[0].get("text", "")
        return None
