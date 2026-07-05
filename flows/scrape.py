from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from pages.job_list import BossJobListPage

log = logging.getLogger("flow.scrape")

_WHITELIST = ["前端", "全栈", "Web"]
_BLACKLIST = ["出差"]


def _matches(title: str) -> bool:
    return any(kw in title for kw in _WHITELIST) and not any(kw in title for kw in _BLACKLIST)


class BossScrapeFlow:
    """Boss直聘爬取 + 沟通流程。"""

    def __init__(self, page: BossJobListPage) -> None:
        self.page = page

    async def run(
        self,
        url: str | None = None,
        *,
        max_scrolls: int = 10,
        reuse_existing: bool = False,
    ) -> list[dict[str, Any]]:
        session = self.page.session
        await session.ensure_tab(url, reuse_existing=reuse_existing)
        await session.activate()

        await self.page.click_frontend_tab()

        all_jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        applied: set[str] = set()

        for scroll_i in range(max_scrolls + 1):
            if scroll_i > 0:
                log.info("滚动 (%d/%d)...", scroll_i, max_scrolls)
                await session.scroll_pagedown()
                await asyncio.sleep(1.0)

            session.refresh_tab()

            jobs = await self.page.scrape_visible_jobs()

            new_jobs = [j for j in jobs if j["link"] not in seen]
            for j in new_jobs:
                seen.add(j["link"])
            all_jobs.extend(new_jobs)

            log.info(
                "第 %d 轮: %d 条, 新增 %d 条, 总计 %d 条",
                scroll_i + 1, len(jobs), len(new_jobs), len(all_jobs),
            )

            await self._apply_matches(new_jobs, applied)

            if await self.page.has_no_more():
                log.info("无更多数据，结束")
                break

        return all_jobs

    async def _apply_matches(
        self,
        new_jobs: list[dict[str, Any]],
        applied: set[str],
    ) -> None:
        session = self.page.session
        matches = [j for j in new_jobs if _matches(j["title"])]
        if not matches:
            return

        log.info("本轮 %d 个匹配岗位，准备发起沟通", len(matches))

        for job in matches:
            if job["link"] in applied:
                continue

            idx = job.get("i")
            if idx is None:
                log.info("卡片 %s 缺少索引，跳过", job["title"][:30])
                continue

            b = await self.page.get_card_bbox(idx)
            if not b:
                log.warning("定位卡片失败: %s", job["title"][:30])
                continue
            await session.click(b["physical"]["cx"], b["physical"]["cy"])
            await asyncio.sleep(1.0)

            btn = await self.page.get_chat_button_info()
            if not btn:
                log.info("无沟通按钮: %s", job["title"][:30])
                continue
            if btn.get("disabled"):
                log.info("已沟通过，跳过: %s", job["title"][:30])
                applied.add(job["link"])
                continue

            b_btn = await self.page.get_chat_button_bbox()
            if not b_btn:
                log.warning("无法定位沟通按钮: %s", job["title"][:30])
                continue
            await session.click(b_btn["physical"]["cx"], b_btn["physical"]["cy"])
            log.info("已向「%s」发送沟通", job["title"][:40])
            applied.add(job["link"])

            await self.page.dismiss_greet_dialog()

            await asyncio.sleep(random.uniform(1.5, 4.0))
