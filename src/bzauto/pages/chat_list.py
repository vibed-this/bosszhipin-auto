"""Boss直聘聊天列表页面对象（选择器 + 操作方法）。"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import AsyncIterator

from bzauto.models import ChatItem
from bzauto.pages.base import BasePage
from bzauto.server.tab_session import TabSession

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
}

_CHAT_PROJECT_WITH_STATUS = {
    **_CHAT_PROJECT,
    "status": f"{_STATUS}@text",
}


class BossChatListPage(BasePage):
    """Boss直聘聊天列表页面对象（选择器 + 操作方法）。"""

    _LOADED_SELECTOR = "li[role='listitem']"

    def __init__(self, session: TabSession) -> None:
        super().__init__(session)

    async def get_chat_items(
        self,
        limit: int = 50,
        *,
        include_status: bool = False,
    ) -> list[ChatItem]:
        project = _CHAT_PROJECT_WITH_STATUS if include_status else _CHAT_PROJECT
        raw = await self._session.query(
            select=_LIST_ITEM,
            project=project,
            return_="list",
        )
        if not raw:
            return []
        return [ChatItem.from_query_row(item) for item in raw[:limit]]

    async def get_chat_item_at(self, index: int) -> ChatItem | None:
        raw = await self._session.query(
            select=_LIST_ITEM,
            filter={"index": index},
            project=_CHAT_PROJECT_WITH_STATUS,
            return_="list",
        )
        if not raw:
            return None
        return ChatItem.from_query_row(raw[0])

    async def iter_chat_items(
        self, *, max_scrolls: int = 0
    ) -> AsyncIterator[tuple[ChatItem, int]]:
        index = 0
        scroll_count = 0

        while True:
            item = await self.get_chat_item_at(index)

            if item is None:
                if scroll_count < max_scrolls and await self.has_more():
                    scroll_count += 1
                    await self._session.scroll_pagedown(presses=3)
                    await asyncio.sleep(random.uniform(0.8, 1.5))
                    continue
                break

            yield item, index
            index += 1

    async def is_chat_page(self) -> bool:
        url = self._session.current_url
        return bool(url and "zhipin.com" in url and "chat" in url)

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