"""Boss直聘聊天列表页面对象（选择器 + 操作方法）。"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import AsyncIterator

from bzauto.browser.session import BrowserSession, ElementNotFound
from bzauto.models import ChatItem, ChatMessage, ConversationBoss, ConversationMeta
from bzauto.pages.base import BasePage

log = logging.getLogger("page.chat_list")

_CHAT_URL = "https://www.zhipin.com/web/geek/chat"

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

_CHAT_NO_DATA_CONTAINER = ".chat-conversation .chat-no-data"
_CHAT_INPUT = "div.chat-input"
_CHAT_SEND = "button.btn-v2.btn-sure-v2.btn-send"
_CHAT_RECORD = ".chat-record"
_MESSAGE_ITEM = ".message-item"

# Vue dataSources 字段映射（列表侧）
_VUE_MAP_SOURCE_JS = """
function mapSource(s) {
    return {
        name: s.name,
        avatar: s.avatar || '',
        brandName: s.brandName,
        title: s.title,
        encryptBossId: s.encryptBossId || '',
        securityId: s.securityId || '',
        encryptJobId: s.encryptJobId || '',
        jobId: s.jobId || 0,
        friendSource: s.friendSource || 0,
        friendId: s.friendId || 0,
        uid: s.uid || 0,
        uniqueId: s.uniqueId || '',
        relationType: s.relationType || 0,
        sourceTitle: s.sourceTitle || '',
        lastText: s.lastText || '',
        lastMsgId: s.lastMsgId || 0,
        lastMsgStatus: s.lastMsgStatus,
        lastTS: s.lastTS,
        updateTime: s.updateTime,
        unreadCount: s.unreadCount,
        lastIsSelf: s.lastIsSelf,
        isTop: s.isTop || 0,
        note: s.note || '',
    };
}
"""

_VUE_EXTRACT_DATASOURCES_JS = f"""
JSON.stringify((function() {{
    {_VUE_MAP_SOURCE_JS}
    var el = document.querySelector('.user-list-content');
    if (!el || !el.__vue__) return [];
    var ds = el.__vue__.$props && el.__vue__.$props.dataSources;
    if (!Array.isArray(ds)) return [];
    return ds.map(mapSource);
}})())
"""

_VUE_EXTRACT_BOSS_JS = f"""
JSON.stringify((function() {{
    {_VUE_MAP_SOURCE_JS}
    function mapBoss(s) {{
        var base = mapSource(s);
        base.jobName = s.jobName || '';
        base.positionName = s.positionName || '';
        base.locationName = s.locationName || '';
        base.jobTypeDesc = s.jobTypeDesc || '';
        return base;
    }}
    var el = document.querySelector('{_CHAT_RECORD}');
    if (!el || !el.__vue__) return null;
    var boss = el.__vue__.$data && el.__vue__.$data.boss;
    if (!boss) return null;
    return mapBoss(boss);
}})())
"""

_VUE_EXTRACT_CONV_META_JS = f"""
JSON.stringify((function() {{
    var el = document.querySelector('{_CHAT_RECORD}');
    if (!el || !el.__vue__) return null;
    var d = el.__vue__.$data;
    if (!d) return null;
    return {{
        page: d.page || 0,
        pageSize: d.pageSize || 0,
        msgMinId: d.msgMinId || 0,
        history: !!d.history,
        isToTop: !!d.isToTop,
        loading: !!d.loading,
    }};
}})())
"""

_VUE_EXTRACT_LOADED_MESSAGES_JS = f"""
JSON.stringify((function() {{
    var items = document.querySelectorAll('{_MESSAGE_ITEM}');
    var out = [];
    items.forEach(function(el) {{
        var m = el.__vue__ && el.__vue__.$props && el.__vue__.$props.message;
        if (!m) return;
        var text = m.text || m.body || (m.extend && m.extend.text) || '';
        out.push({{
            mid: m.mid || 0,
            time: m.time || 0,
            formateTime: m.formateTime || '',
            isSelf: !!m.isSelf,
            type: m.type || 0,
            bodyType: m.bodyType || 0,
            fromName: m.fromName || '',
            text: text,
            status: m.status || 0,
            messageType: m.messageType || 0,
            securityId: m.securityId || '',
            uniqueId: m.uniqueId || '',
            friendId: m.friendId || 0,
            friendSource: m.friendSource || 0,
        }});
    }});
    return out;
}})())
"""


class BossChatListPage(BasePage):
    """Boss直聘聊天列表页面对象（选择器 + 操作方法）。"""

    _LOADED_SELECTOR = "li[role='listitem']"

    def __init__(self, session: BrowserSession) -> None:
        super().__init__(session)
        self._session: BrowserSession = session

    async def get_chat_items(
        self,
        limit: int = 999,
        *,
        include_status: bool = False,
    ) -> list[ChatItem]:
        """从 Vue dataSources 读取聊天列表项。

        :param limit: 返回上限
        :param include_status: 已弃用，保留兼容
        :returns: ChatItem 列表
        """
        raw = await self._session.eval_js(_VUE_EXTRACT_DATASOURCES_JS)
        if not raw:
            return []
        items = json.loads(raw) if isinstance(raw, str) else raw
        return [ChatItem.from_vue_row(item) for item in items[:limit]]

    async def get_chat_item_at(self, index: int) -> ChatItem | None:
        """按 dataSources 索引获取单项（兼容旧接口）。"""
        items = await self.get_chat_items(limit=index + 1)
        return items[index] if index < len(items) else None

    async def iter_chat_items(
        self,
        *,
        scroll_timeout: float = 30.0,
    ) -> AsyncIterator[ChatItem]:
        """JS 先滚动到底部（按高度无变化算），再一次性 dump 所有数据。"""
        await self._session.eval_js(f"""
(function() {{
    window.__bz_chat_data = null;
    window.__bz_chat_scroll_done = false;
    {_VUE_MAP_SOURCE_JS}

    var container = document.querySelector('.user-list-content');
    if (!container) {{
        window.__bz_chat_scroll_done = true;
        return;
    }}

    var lastHeight = -1;
    var maxAttempts = 40;
    var attempt = 0;

    function doScroll() {{
        if (attempt >= maxAttempts) {{
            finish();
            return;
        }}
        attempt++;
        container.scrollTop = container.scrollHeight;
        var currentHeight = container.scrollHeight;
        if (currentHeight === lastHeight) {{
            finish();
        }} else {{
            lastHeight = currentHeight;
            setTimeout(doScroll, 800);
        }}
    }}

    function finish() {{
        var el = document.querySelector('.user-list-content');
        if (el && el.__vue__) {{
            var ds = el.__vue__.$props && el.__vue__.$props.dataSources;
            if (Array.isArray(ds)) {{
                window.__bz_chat_data = ds.map(mapSource);
            }}
        }}
        window.__bz_chat_scroll_done = true;
    }}

    doScroll();
}})()
        """)

        deadline = time.monotonic() + scroll_timeout
        while time.monotonic() < deadline:
            done = await self._session.eval_js("window.__bz_chat_scroll_done === true")
            if done:
                break
            await asyncio.sleep(0.3)
        else:
            log.warning("聊天列表滚动超时 (%s 秒)", scroll_timeout)

        raw = await self._session.eval_js("window.__bz_chat_data ? JSON.stringify(window.__bz_chat_data) : '[]'")
        items = json.loads(raw) if isinstance(raw, str) else (raw or [])
        seen: set[str] = set()
        for item in items:
            uid = item.get("uniqueId", "")
            if uid and uid not in seen:
                seen.add(uid)
                yield ChatItem.from_vue_row(item)

    async def get_conversation_boss(self) -> ConversationBoss | None:
        """读取当前选中会话的 Boss/职位详情（message-list.$data.boss）。

        须先 click_chat_item 选中对话。
        """
        raw = await self._session.eval_js(_VUE_EXTRACT_BOSS_JS)
        if not raw:
            return None
        row = json.loads(raw) if isinstance(raw, str) else raw
        if not row:
            return None
        return ConversationBoss.from_vue_boss(row)

    async def get_conversation_meta(self) -> ConversationMeta | None:
        """读取当前会话 message-list 分页/加载状态。

        须先 click_chat_item 选中对话。
        """
        raw = await self._session.eval_js(_VUE_EXTRACT_CONV_META_JS)
        if not raw:
            return None
        row = json.loads(raw) if isinstance(raw, str) else raw
        if not row:
            return None
        return ConversationMeta(**row)

    async def get_loaded_messages(self) -> list[ChatMessage]:
        """读取当前会话已载入 DOM 的聊天消息（不滚动加载历史）。

        须先 click_chat_item 选中对话。
        """
        raw = await self._session.eval_js(_VUE_EXTRACT_LOADED_MESSAGES_JS)
        if not raw:
            return []
        rows = json.loads(raw) if isinstance(raw, str) else raw
        return [ChatMessage.from_vue_message(row) for row in (rows or [])]

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

    async def click_chat_item(self, unique_id: str) -> None:
        """通过 uniqueId 定位并点击聊天项。

        先通过 dataSources 找到索引，用虚拟滚动组件 scrollToIndex 滚动到该位置，
        等待渲染后从 DOM 中查找并点击。

        :param unique_id: Vue 侧的 uniqueId（{uid}-{friendSource}）
        """
        idx_raw = await self._session.eval_js(f"""
JSON.stringify((function() {{
    var uid = {json.dumps(unique_id)};
    var el = document.querySelector('.user-list-content');
    if (!el || !el.__vue__) return null;
    var ds = el.__vue__.$props && el.__vue__.$props.dataSources;
    if (!Array.isArray(ds)) return null;
    for (var i = 0; i < ds.length; i++) {{
        if (ds[i].uniqueId === uid) {{
            if (typeof el.__vue__.scrollToIndex === 'function') {{
                el.__vue__.scrollToIndex(i);
            }} else {{
                var avgH = el.scrollHeight / ds.length;
                el.scrollTop = i * avgH;
            }}
            return {{index: i}};
        }}
    }}
    return null;
}})())
        """)
        if not idx_raw:
            raise ElementNotFound(f"uniqueId={unique_id} not in dataSources")
        await asyncio.sleep(1.0)

        bbox_raw = await self._session.eval_js(f"""
JSON.stringify((function() {{
    var uid = {json.dumps(unique_id)};
    var items = document.querySelectorAll('li[role="listitem"]');
    for (var i = 0; i < items.length; i++) {{
        var src = items[i].__vue__ && items[i].__vue__.$props && items[i].__vue__.$props.source;
        if (src && src.uniqueId === uid) {{
            items[i].scrollIntoView({{block: 'nearest', behavior: 'instant'}});
            var rect = items[i].getBoundingClientRect();
            return {{x: rect.x, y: rect.y, w: rect.width, h: rect.height, cx: Math.round(rect.x + rect.width / 2), cy: Math.round(rect.y + rect.height / 2)}};
        }}
    }}
    return null;
}})())
        """)
        bbox = bbox_raw if isinstance(bbox_raw, dict) else (json.loads(bbox_raw) if bbox_raw else None)
        if not bbox or bbox.get("cx", 0) <= 0:
            raise ElementNotFound(f"li[uniqueId={unique_id}]")
        await self._session.click(int(bbox["cx"]), int(bbox["cy"]))
        await asyncio.sleep(0.5)
        # 等待右侧对话面板出现
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            check = await self._session.bbox(_TOP_INFO, timeout=3.0)
            if check is not None:
                break
            await asyncio.sleep(0.3)

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

    async def is_conversation_selected(self) -> bool:
        """检查右侧是否已选中对话（.chat-no-data 消失 = 已选中）。"""
        return await self._session.count(_CHAT_NO_DATA_CONTAINER) == 0

    async def wait_conversation_selected(self, timeout: float = 10.0) -> bool:
        """等待右侧选中一个对话。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if await self.is_conversation_selected():
                return True
            await asyncio.sleep(0.3)
        return False

    async def type_message(self, text: str) -> None:
        """在聊天输入框中输入文本。

        必须先选中任意对话（is_conversation_selected() 为 True），
        否则输入框不存在。

        通过 eval_js 设置 contentEditable div 的 innerText 并派发 input 事件
        以触发 Vue 响应式更新。
        """
        await self._session.click_element(_CHAT_INPUT, post_sleep=0.3)
        js = json.dumps({
            "selector": _CHAT_INPUT,
            "text": text,
        })
        await self._session.eval_js(f"""
(function() {{
    var o = {js};
    var el = document.querySelector(o.selector);
    if (!el) return;
    el.focus();
    el.innerText = o.text;
    el.dispatchEvent(new Event('input', {{bubbles: true}}));
}})()
        """)
        await asyncio.sleep(0.3)

    async def click_send(self) -> None:
        """点击发送按钮。

        必须先选中任意对话且输入框内有内容，否则按钮为 .disabled 状态无法点击。
        """
        await self._session.click_element(_CHAT_SEND, post_sleep=4.0)

    async def send_message(self, text: str) -> None:
        """输入并发送消息。

        必须先选中任意对话（is_conversation_selected() 为 True），
        否则输入框不存在且发送按钮为 .disabled 状态。
        """
        await self.type_message(text)
        await self.click_send()