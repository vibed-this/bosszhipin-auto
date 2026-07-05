from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any, AsyncIterator

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

# --- 右侧聊天详情面板 ---
_MORE_LABEL = ".chat-conversation .ui-dropmenu-label"
_TOP_INFO = ".top-info-content"
_DROPDOWN_LIST = ".chat-conversation .ui-dropmenu-list"
_DROPDOWN_ITEM_SPAN = ".chat-conversation .ui-dropmenu-list li span"
_DIALOG_WRAPPER = ".boss-dialog__wrapper"
_DIALOG_CANCEL = ".boss-dialog__button.button-outline"
_DIALOG_CONFIRM = ".boss-dialog__button:not(.button-outline)"


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
            project={
                "name": f"{_NAME}@text",
                "company": f"{_NAME_BOX} span:nth-child(2)@text",
                "position": f"{_NAME_BOX} span:nth-child(4)@text",
                "time": f"{_TIME}@text",
                "lastMsg": f"{_MSG}@text",
                "status": f"{_STATUS}@text",
            },
            return_="list",
        )
        if not raw:
            return []
        for item in raw:
            item["status"] = (item.get("status") or "").strip(" []")
        return raw

    async def get_chat_item_at(self, index: int) -> dict[str, Any] | None:
        raw = await self._session.query(
            select=_LIST_ITEM,
            filter={"index": index},
            project={
                "name": f"{_NAME}@text",
                "company": f"{_NAME_BOX} span:nth-child(2)@text",
                "position": f"{_NAME_BOX} span:nth-child(4)@text",
                "time": f"{_TIME}@text",
                "lastMsg": f"{_MSG}@text",
                "status": f"{_STATUS}@text",
            },
            return_="list",
        )
        if not raw:
            return None
        item = raw[0]
        item["status"] = (item.get("status") or "").strip(" []")
        return item

    async def iter_chat_items(self, *, max_scrolls: int = 0) -> AsyncIterator[tuple[dict[str, Any], int]]:
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

    # --- 等待元素辅助 ---

    async def _wait_visible(self, select: str, *, filter: dict | None = None, timeout: float = 10.0) -> dict | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            bbox = await self._session.bbox(select=select, filter=filter)
            if bbox is not None:
                return bbox
            await asyncio.sleep(0.3)
        return None

    async def _wait_hidden(self, select: str, *, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            bbox = await self._session.bbox(select=select)
            if bbox is None:
                return True
            await asyncio.sleep(0.3)
        return False

    # --- 右侧聊天详情操作 ---

    async def click_chat_item(self, index: int = 0) -> bool:
        bbox = await self._session.bbox(select=_LIST_ITEM, filter={"index": index})
        if bbox is None:
            log.warning("未找到聊天项 #%d", index)
            return False
        log.info("点击聊天项 #%d  (%d,%d)", index, bbox["physical"]["cx"], bbox["physical"]["cy"])
        await self._session.click(bbox["physical"]["cx"], bbox["physical"]["cy"])
        loaded = await self._wait_visible(_TOP_INFO)
        if not loaded:
            log.warning("点击聊天项后右侧面板未加载")
            return False
        return True

    async def click_more_button(self) -> bool:
        bbox = await self._session.bbox(select=_MORE_LABEL)
        if bbox is None:
            log.warning("未找到更多按钮")
            return False
        log.info("点击更多按钮  (%d,%d)", bbox["physical"]["cx"], bbox["physical"]["cy"])
        await self._session.click(bbox["physical"]["cx"], bbox["physical"]["cy"])
        opened = await self._wait_visible(_DROPDOWN_LIST)
        if not opened:
            log.warning("点击更多后下拉菜单未展开")
            return False
        return True

    async def click_delete_in_menu(self) -> bool:
        bbox = await self._session.bbox(
            select=_DROPDOWN_ITEM_SPAN,
            filter={"textContains": "删除"},
        )
        if bbox is None:
            log.warning("未找到删除菜单项")
            return False
        log.info("点击删除  (%d,%d)", bbox["physical"]["cx"], bbox["physical"]["cy"])
        await self._session.click(bbox["physical"]["cx"], bbox["physical"]["cy"])
        opened = await self._wait_visible(_DIALOG_WRAPPER)
        if not opened:
            log.warning("点击删除后弹窗未出现")
            return False
        return True

    async def click_cancel_in_dialog(self) -> bool:
        bbox = await self._session.bbox(select=_DIALOG_CANCEL)
        if bbox is None:
            log.warning("未找到取消按钮")
            return False
        log.info("点击取消  (%d,%d)", bbox["physical"]["cx"], bbox["physical"]["cy"])
        await self._session.click(bbox["physical"]["cx"], bbox["physical"]["cy"])
        hidden = await self._wait_hidden(_DIALOG_WRAPPER)
        if not hidden:
            log.warning("弹窗未关闭")
        return True

    async def click_confirm_in_dialog(self) -> bool:
        bbox = await self._session.bbox(select=_DIALOG_CONFIRM)
        if bbox is None:
            log.warning("未找到确定按钮")
            return False
        log.info("点击确定  (%d,%d)", bbox["physical"]["cx"], bbox["physical"]["cy"])
        await self._session.click(bbox["physical"]["cx"], bbox["physical"]["cy"])
        hidden = await self._wait_hidden(_DIALOG_WRAPPER)
        if not hidden:
            log.warning("弹窗未关闭")
        return True
