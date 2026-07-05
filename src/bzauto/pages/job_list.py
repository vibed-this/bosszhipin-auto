from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, AsyncIterator

from bzauto.server.session import TabSession

log = logging.getLogger("page.job_list")

_SALARY_DECODE = {
    '\uE031': '0', '\uE032': '1', '\uE033': '2', '\uE034': '3',
    '\uE035': '4', '\uE036': '5', '\uE037': '6', '\uE038': '7',
    '\uE039': '8', '\uE03A': '9',
}


def _decode_salary_icon(text: str) -> str:
    for k, v in _SALARY_DECODE.items():
        text = text.replace(k, v)
    return text


_SALARY_RE = None
_RE_COMPILED = False


def _compile_patterns():
    global _SALARY_RE, _RE_COMPILED
    if not _RE_COMPILED:
        import re
        pat = '|'.join(re.escape(c) for c in _SALARY_DECODE)
        _SALARY_RE = re.compile(pat)
        _RE_COMPILED = True


_JOB_ITEM = "li.job-card-box"
_JOB_TITLE = ".job-name"
_SALARY = ".job-salary"
_COMPANY = ".boss-name"
_JOB_LINK = "a.job-name"
_EXPECT_TAB = "a.expect-item"


class BossJobListPage:
    """Boss直聘职位列表页面对象（选择器 + 操作方法）。"""

    def __init__(self, session: TabSession) -> None:
        self._session = session

    async def get_job_card_count(self) -> int:
        result = await self._session.query(
            select=_JOB_ITEM, return_="count",
        )
        return int(result) if result is not None else 0

    async def get_job_cards(self, limit: int = 30) -> list[dict[str, Any]]:
        return await self._session.query(
            select=_JOB_ITEM,
            project={
                "title": f"{_JOB_TITLE}@text",
                "salary_raw": f"{_SALARY}@text",
                "company": f"{_COMPANY}@text",
                "href": f"{_JOB_LINK}@href",
            },
            return_="list",
        )

    async def get_salary_texts(self) -> list[str]:
        raw = await self._session.query(
            select=_SALARY, return_="raw",
        )
        return [r.get("text", "") for r in raw] if raw else []

    async def click_chat(self, index: int = 0) -> bool:
        bbox = await self._session.bbox(
            select="a.op-btn-chat",
            filter={"nth": index},
        )
        if bbox is None:
            log.warning("未找到沟通按钮 #%d", index)
            return False

        log.info(
            "点击沟通按钮 #%d  css=(%d,%d)  physical=(%d,%d)",
            index,
            bbox["css"]["cx"], bbox["css"]["cy"],
            bbox["physical"]["cx"], bbox["physical"]["cy"],
        )
        await self._session.click(bbox["physical"]["cx"], bbox["physical"]["cy"])
        await asyncio.sleep(1.5)
        return True

    async def is_loaded(self) -> bool:
        count = await self.get_job_card_count()
        return count > 0

    async def wait_loaded(self, timeout: float = 20.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if await self.is_loaded():
                return True
            await asyncio.sleep(0.5)
        return False

    async def click_expect_tab(self) -> bool:
        bbox = await self._session.bbox(select=_EXPECT_TAB)
        if bbox is None:
            log.warning("未找到期望tab")
            return False
        log.info(
            "点击期望tab  css=(%d,%d)  physical=(%d,%d)",
            bbox["css"]["cx"], bbox["css"]["cy"],
            bbox["physical"]["cx"], bbox["physical"]["cy"],
        )
        await self._session.click(bbox["physical"]["cx"], bbox["physical"]["cy"])
        await asyncio.sleep(1.5)
        return True

    async def scroll_next_page(self) -> bool:
        bbox = await self._session.bbox(
            select="div.job-list-container",
        )
        if bbox is None:
            log.warning("未找到职位列表容器")
            return False
        y = bbox["css"]["y"] + bbox["css"]["h"] - 50
        px = bbox["css"]["cx"]
        log.info("翻页: 滚动到 y=%d", y)
        await self._session.scroll_pagedown(at_x=px, at_y=y, presses=3)
        await asyncio.sleep(1.0)
        return True

    async def get_job_card_at(self, index: int) -> dict[str, Any] | None:
        raw = await self._session.query(
            select=_JOB_ITEM,
            filter={"index": index},
            project={
                "title": f"{_JOB_TITLE}@text",
                "salary_raw": f"{_SALARY}@text",
                "company": f"{_COMPANY}@text",
                "href": f"{_JOB_LINK}@href",
            },
            return_="list",
        )
        return raw[0] if raw else None

    async def iter_job_cards(
        self,
        *,
        max_scrolls: int = 10,
        scroll_timeout: float = 5.0,
    ) -> AsyncIterator[tuple[dict[str, Any], int]]:
        """异步迭代器：逐个产出职位卡片，自动处理翻页和智能滚动。

        当列表数据耗尽时，先用 JS 滚动到底部，再用 pyautogui 反复上下滚动
        尝试触发懒加载，直到出现新数据或超时。
        """
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
                    await self._session.activate()
                    import pyautogui
                    pyautogui.moveTo(cx, cy)
                    for _ in range(3):
                        pyautogui.scroll(50, cx, cy)
                        await asyncio.sleep(0.15)
                    await asyncio.sleep(0.3)
                    for _ in range(6):
                        pyautogui.scroll(-50, cx, cy)
                        await asyncio.sleep(0.15)
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

    async def get_salary_info(self) -> dict[str, Any] | None:
        texts = await self.get_salary_texts()
        if not texts:
            return None
        _compile_patterns()
        decoded = []
        for t in texts:
            if _SALARY_RE:
                d = _SALARY_RE.sub(lambda m: _SALARY_DECODE.get(m.group(0), m.group(0)), t)
                decoded.append(d)
            else:
                decoded.append(t)
        return {"raw": texts, "decoded": decoded}
