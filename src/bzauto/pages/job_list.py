"""Boss直聘职位列表页面对象（选择器 + 操作方法）。"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, AsyncIterator

from bzauto.pages.base import BasePage
from bzauto.server.tab_session import TabSession

log = logging.getLogger("page.job_list")

_SALARY_DECODE = {
    '\uE031': '0', '\uE032': '1', '\uE033': '2', '\uE034': '3',
    '\uE035': '4', '\uE036': '5', '\uE037': '6', '\uE038': '7',
    '\uE039': '8', '\uE03A': '9',
}

_SALARY_RE = re.compile('|'.join(re.escape(c) for c in _SALARY_DECODE))

_JOB_ITEM = "li.job-card-box"
_JOB_TITLE = ".job-name"
_SALARY = ".job-salary"
_COMPANY = ".boss-name"
_JOB_LINK = "a.job-name"
_EXPECT_TAB = "a.expect-item"

_JOB_PROJECT = {
    "title": f"{_JOB_TITLE}@text",
    "salary_raw": f"{_SALARY}@text",
    "company": f"{_COMPANY}@text",
    "href": f"{_JOB_LINK}@href",
}

_DIALOG_SELECTORS = [
    ".greet-boss-dialog .cancel-btn",
    ".dialog-close",
    ".dialog-wrap .close",
    ".boss-dialog .close",
    ".tips-success .close",
]


def _decode_salary_icon(text: str) -> str:
    for k, v in _SALARY_DECODE.items():
        text = text.replace(k, v)
    return text


class BossJobListPage(BasePage):
    """Boss直聘职位列表页面对象（选择器 + 操作方法）。"""

    _LOADED_SELECTOR = "li.job-card-box"

    def __init__(self, session: TabSession) -> None:
        super().__init__(session)

    async def get_job_cards(self) -> list[dict[str, Any]]:
        return await self._session.query(
            select=_JOB_ITEM,
            project=_JOB_PROJECT,
            return_="list",
        )

    async def get_job_card_at(self, index: int) -> dict[str, Any] | None:
        raw = await self._session.query(
            select=_JOB_ITEM,
            filter={"index": index},
            project=_JOB_PROJECT,
            return_="list",
        )
        return raw[0] if raw else None

    async def click_card_at(self, index: int) -> bool:
        """点击指定索引的职位卡片。"""
        await self._session.execute(
            f"(function(){{"
            f"  var cards = document.querySelectorAll('{_JOB_ITEM}');"
            f"  var c = cards[{index}];"
            "  if (c) { c.scrollIntoView({block:'center'}); c.click(); }"
            "})()"
        )
        await asyncio.sleep(0.5)
        return True

    async def click_chat(self, index: int = 0) -> bool:
        """点击沟通按钮。"""
        return await self._session.click_element(
            "a.op-btn-chat",
            filter={"nth": index},
            post_sleep=1.5,
        )

    async def click_expect_tab(self) -> bool:
        """点击期望 tab。"""
        return await self._session.click_element(
            _EXPECT_TAB,
            post_sleep=1.5,
        )

    async def dismiss_dialogs(self) -> bool:
        """关闭弹窗。返回 True 继续，False 终止。无弹窗返回 True。"""
        for selector in _DIALOG_SELECTORS:
            try:
                bbox = await self._session.bbox(selector)
                if bbox and bbox["css"]["cx"] > 0:
                    log.info(
                        "  关闭弹窗 %s  css=(%d,%d)  physical=(%d,%d)",
                        selector,
                        bbox["css"]["cx"], bbox["css"]["cy"],
                        bbox["physical"]["cx"], bbox["physical"]["cy"],
                    )
                    await self._session.click(
                        bbox["physical"]["cx"], bbox["physical"]["cy"]
                    )
                    await asyncio.sleep(0.5)
            except Exception:
                pass

        raw = await self._session.query(
            select=".chat-block-dialog .chat-block-body",
            return_="raw",
        )
        if raw:
            text = raw[0].get("text", "")
            log.info("  沟通上限弹窗: %s", text)
            bbox = await self._session.bbox(select=".chat-block-dialog .sure-btn")
            if bbox and bbox["css"]["cx"] > 0:
                await self._session.click(
                    bbox["physical"]["cx"], bbox["physical"]["cy"]
                )
                await asyncio.sleep(0.5)
            if "150" in text or "消息已满" in text or "明日再试" in text:
                return False
        return True

    async def get_salary_texts(self) -> list[str]:
        raw = await self._session.query(
            select=_SALARY, return_="raw",
        )
        return [r.get("text", "") for r in raw] if raw else []

    async def get_salary_info(self) -> dict[str, Any] | None:
        texts = await self.get_salary_texts()
        if not texts:
            return None
        decoded = []
        for t in texts:
            d = _SALARY_RE.sub(lambda m: _SALARY_DECODE.get(m.group(0), m.group(0)), t)
            decoded.append(d)
        return {"raw": texts, "decoded": decoded}

    async def iter_job_cards(
        self,
        *,
        max_scrolls: int = 10,
        scroll_timeout: float = 5.0,
    ) -> AsyncIterator[tuple[dict[str, Any], int]]:
        """异步迭代器：逐个产出职位卡片，自动处理翻页和智能滚动。"""
        index = 0
        scroll_count = 0
        stale_rounds = 0
        max_stale = 3

        while True:
            card = await self.get_job_card_at(index)

            if card is None:
                if scroll_count >= max_scrolls:
                    log.info("已达最大滚动次数 %d", max_scrolls)
                    break

                if stale_rounds >= max_stale:
                    log.info("连续 %d 轮无新数据，停止", max_stale)
                    break

                scroll_count += 1
                stale_rounds += 1

                log.info("数据耗尽，尝试智能滚动 #%d...", scroll_count)

                await self._session.execute(
                    "(function(){"
                    "  var c = document.querySelector('.job-list-container');"
                    "  if (c) c.scrollTop = c.scrollHeight;"
                    "  window.scrollTo(0, document.body.scrollHeight);"
                    "})()"
                )
                await asyncio.sleep(0.5)

                bbox = await self._session.bbox(select="div.job-list-container")
                if bbox:
                    cx = bbox["css"]["cx"]
                    cy = bbox["css"]["cy"]
                    await self._session.scroll_wheel(50, at_x=cx, at_y=cy, presses=3)
                    await asyncio.sleep(0.3)
                    await self._session.scroll_wheel(-50, at_x=cx, at_y=cy, presses=6)
                    await asyncio.sleep(scroll_timeout)
                else:
                    await asyncio.sleep(scroll_timeout)

                continue

            stale_rounds = 0
            yield card, index
            index += 1

    async def iter_filtered_cards(
        self,
        *,
        whitelist: list[str] | None = None,
        blacklist: list[str] | None = None,
        max_scrolls: int = 10,
        scroll_timeout: float = 5.0,
    ) -> AsyncIterator[tuple[dict[str, Any], int]]:
        """包装 iter_job_cards，按白名单/黑名单过滤并去重。"""
        seen: set[tuple[str, str]] = set()
        async for card, idx in self.iter_job_cards(
            max_scrolls=max_scrolls,
            scroll_timeout=scroll_timeout,
        ):
            title = (card.get("title") or "").strip().lower()
            if whitelist and not any(kw in title for kw in whitelist):
                continue
            if blacklist and any(kw in title for kw in blacklist):
                continue
            key = (card.get("title") or "", card.get("company") or "")
            if key in seen:
                continue
            seen.add(key)
            yield card, idx