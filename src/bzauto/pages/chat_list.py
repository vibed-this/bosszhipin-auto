"""Boss直聘聊天列表页面对象（选择器 + 操作方法）。"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

from bzauto.browser.session import BrowserSession
from bzauto.models import ChatItem
from bzauto.pages.base import BasePage

log = logging.getLogger("page.chat_list")

_CHAT_URL = "https://www.zhipin.com/web/geek/chat"

_LIST_ITEM = "li[role='listitem']"
_NAME = ".name-text"
_NAME_BOX = ".name-box"
_TIME = ".text .time"
_MSG = ".last-msg-text"
_STATUS = ".message-status"
_LABEL_LIST = ".label-list li .label-name"
_FOOTER = ".boss-list-footer .finished"
_CHAT_NO_DATA = ".chat-no-data .no-data-text"

_MORE_LABEL = ".chat-conversation .ui-dropmenu-label"
_TOP_INFO = ".top-info-content"
_DROPDOWN_LIST = ".chat-conversation .ui-dropmenu-list"
_DROPDOWN_ITEM_SPAN = ".chat-conversation .ui-dropmenu-list li span"
_DIALOG_WRAPPER = ".boss-dialog__wrapper"
_DIALOG_CANCEL = ".boss-dialog__button.button-outline"
_DIALOG_CONFIRM = ".boss-dialog__button:not(.button-outline)"

_CHAT_PROJECT = {
    "name": f"{_NAME}@text",
    "company": f"{_NAME_BOX} span:nth-child(2)@text",
    "position": f"{_NAME_BOX} span:nth-child(4)@text",
    "time": f"{_TIME}@text",
    "lastMsg": f"{_MSG}@text",
    "firstChildClass": ".gray.last-msg > :first-child@class",
    "unreadCount": ".notice-badge@text",
}

_CHAT_PROJECT_WITH_STATUS = {
    **_CHAT_PROJECT,
    "status": f"{_STATUS}@text",
}


class BossChatListPage(BasePage):
    """Boss直聘聊天列表页面对象（选择器 + 操作方法）。"""

    _LOADED_SELECTOR = "li[role='listitem']"

    def __init__(self, session: BrowserSession) -> None:
        super().__init__(session)
        self._session: BrowserSession = session

    async def get_chat_items(
        self,
        limit: int = 50,
        *,
        include_status: bool = False,
    ) -> list[ChatItem]:
        project = _CHAT_PROJECT_WITH_STATUS if include_status else _CHAT_PROJECT
        raw = await self._session.find_all(
            select=_LIST_ITEM,
            project=project,
        )
        if not raw:
            return []
        return [ChatItem.from_query_row(item) for item in raw[:limit]]

    async def get_chat_item_at(self, index: int) -> ChatItem | None:
        raw = await self._session.find_one(
            select=_LIST_ITEM,
            filter={"index": index},
            project=_CHAT_PROJECT_WITH_STATUS,
        )
        if not raw:
            return None
        return ChatItem.from_query_row(raw)

    async def iter_chat_items(
        self,
        *,
        scroll_timeout: float = 5.0,
    ) -> AsyncIterator[tuple[ChatItem, int]]:
        """全量捞取当前可见聊天项，滚动后捞取新项，按 (name, company) 去重。"""
        max_scrolls = 3
        seen: set[tuple[str, str]] = set()
        scroll_count = 0

        while True:
            items = await self.get_chat_items(limit=999, include_status=True)

            new_found = False
            for item in items:
                key = (item.name, item.company)
                if key not in seen:
                    seen.add(key)
                    new_found = True
                    yield item, len(seen) - 1

            if new_found:
                scroll_count = 0
                continue

            if scroll_count >= max_scrolls:
                log.info("已达最大滚动次数 %d", max_scrolls)
                break

            scroll_count += 1
            log.info("无新数据，尝试智能滚动 #%d...", scroll_count)

            # JS 多次滚至最底部触发懒加载
            await self._session.eval_js("""
(function () {
    var c = document.querySelector('.user-list-content');
    if (!c) return;

    var count = 0;
    var scroll = function () {
        c.scrollTop = c.scrollHeight;
        if (count++ < 5) {
            window.setTimeout(scroll, 300);
        }
    }
    scroll();
})()
            """
            )
            await asyncio.sleep(scroll_timeout)

    async def is_chat_page(self) -> bool:
        url = self._session.current_url
        return bool(url and "zhipin.com" in url and "chat" in url)

    async def get_labels(self) -> list[str]:
        items = await self._session.find_all(
            select=_LABEL_LIST,
            project={"text": "@text"},
        )
        return [item["text"].strip() for item in items]

    async def has_more(self) -> bool:
        return await self._session.count(_FOOTER) > 0

    async def get_no_data_text(self) -> str | None:
        items = await self._session.find_all(
            select=_CHAT_NO_DATA,
            project={"text": "@text"},
        )
        if items:
            return items[0].get("text")
        return None

    async def click_chat_item(self, index: int = 0) -> None:
        await self._session.click_element(
            _LIST_ITEM,
            filter={"index": index},
            wait_visible=_TOP_INFO,
            post_sleep=0.5,
        )

    async def click_more_button(self) -> None:
        await self._session.click_element(
            _MORE_LABEL,
            wait_visible=_DROPDOWN_LIST,
            post_sleep=0.5,
        )

    async def click_delete_in_menu(self) -> None:
        await self._session.click_element(
            _DROPDOWN_ITEM_SPAN,
            filter={"textContains": "删除"},
            wait_visible=_DIALOG_WRAPPER,
            post_sleep=0.5,
        )

    async def click_cancel_in_dialog(self) -> None:
        await self._session.click_element(
            _DIALOG_CANCEL,
            wait_hidden=_DIALOG_WRAPPER,
            post_sleep=0.5,
        )

    async def click_confirm_in_dialog(self) -> None:
        await self._session.click_element(
            _DIALOG_CONFIRM,
            wait_hidden=_DIALOG_WRAPPER,
            post_sleep=0.5,
        )