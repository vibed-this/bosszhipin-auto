from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from server.session import TabSession

log = logging.getLogger("page.job_list")

_SALARY_DECODE = {
    '\uE031': '0', '\uE032': '1', '\uE033': '2', '\uE034': '3',
    '\uE035': '4', '\uE036': '5', '\uE037': '6', '\uE038': '7',
    '\uE039': '8', '\uE03A': '9',
}


def _decode_salary(text: str) -> str:
    return ''.join(_SALARY_DECODE.get(ch, ch) for ch in text)


class BossJobListPage:
    """Boss直聘职位列表页面对象。"""

    TAB_ITEM = "a.expect-item"
    JOB_CARD = "li.job-card-box"
    JOB_NAME = ".job-name"
    JOB_SALARY = ".job-salary"
    COMPANY_NAME = ".boss-name"
    AREA = ".company-location"
    TAGS = ".tag-list > li"
    LINK = "a.job-name"
    CHAT_BUTTON = "a.op-btn-chat"
    CHAT_DISABLED_CLASS = "is-disabled"
    GREET_DIALOG = ".greet-boss-dialog"
    CANCEL_BTN = ".cancel-btn"

    def __init__(self, session: TabSession) -> None:
        self.session = session

    # ── Tab 操作 ──────────────────────────────────────

    async def click_frontend_tab(self, label: str = "前端") -> bool:
        b = await self.session.bbox(self.TAB_ITEM, filter={"textContains": label})
        if not b:
            log.warning("未找到「%s」tab", label)
            return False
        cx, cy = b["physical"]["cx"], b["physical"]["cy"]
        await self.session.click(cx, cy)
        log.info("已点击「%s」tab @ (%d, %d)", label, cx, cy)
        await asyncio.sleep(2.0)
        return True

    # ── 数据爬取 ──────────────────────────────────────

    async def scrape_visible_jobs(self) -> list[dict[str, Any]]:
        res = await self.session.query(
            select=self.JOB_CARD,
            project={
                "title": ".job-name@text",
                "salary": ".job-salary@text",
                "company": ".boss-name@text",
                "area": ".company-location@text",
                "tags": [".tag-list > li@text"],
                "link": "a.job-name@href",
                "i": "@index",
            },
            return_="list",
        )
        for j in res:
            if j.get("salary"):
                j["salary"] = _decode_salary(j["salary"])
        return res

    async def has_no_more(self) -> bool:
        text = await self.session.execute("return document.body.innerText")
        return "没有更多了" in (text or "")

    # ── 交互坐标 ──────────────────────────────────────

    async def get_card_bbox(self, index: int) -> dict | None:
        return await self.session.bbox(self.JOB_CARD, filter={"index": index})

    async def get_card_center(self, index: int = 0) -> tuple[int, int]:
        b = await self.get_card_bbox(index)
        if not b:
            raise RuntimeError(f"未找到第 {index} 个职位卡片")
        return (b["physical"]["cx"], b["physical"]["cy"])

    # ── 沟通按钮 ──────────────────────────────────────

    async def get_chat_button_info(self) -> dict | None:
        return await self.session.query(
            self.CHAT_BUTTON,
            project={"disabled": "@class~is-disabled", "text": "@text"},
            return_="first",
        )

    async def get_chat_button_bbox(self) -> dict | None:
        return await self.session.bbox(self.CHAT_BUTTON)

    # ── 弹窗管理 ──────────────────────────────────────

    async def wait_for_greet_dialog(self, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            dialog = await self.session.query(self.GREET_DIALOG, return_="raw")
            if dialog:
                return True
            await asyncio.sleep(0.3)
        return False

    async def dismiss_greet_dialog(self, timeout: float = 10.0) -> bool:
        if not await self.wait_for_greet_dialog(timeout):
            log.warning("沟通成功弹窗未出现")
            return False

        await asyncio.sleep(0.5)

        b = await self.session.bbox(f"{self.GREET_DIALOG} {self.CANCEL_BTN}")
        if b:
            await self.session.click(b["physical"]["cx"], b["physical"]["cy"])
            log.info("已点击「留在本页」")
        else:
            log.warning("未找到「留在本页」按钮")

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            dialog = await self.session.query(self.GREET_DIALOG, return_="raw")
            if not dialog:
                log.info("沟通弹窗已关闭")
                return True
            await asyncio.sleep(0.3)

        log.warning("等待弹窗关闭超时")
        return False
