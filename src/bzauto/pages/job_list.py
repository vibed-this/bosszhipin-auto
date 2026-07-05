from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

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
_SALARY = ".salary"
_COMPANY = ".company-name"
_JOB_LINK = "a.job-card-left"


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

    async def scroll_next_page(self) -> bool:
        bbox = await self._session.bbox(
            select="div.job-list-box",
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
