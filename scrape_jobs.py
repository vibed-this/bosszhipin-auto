"""BOSS直聘自动化抓取

用法::

    import asyncio
    from scrape_jobs import BossJobsAuto

    async def main():
        async with BossJobsAuto() as auto:
            jobs = await auto.run("https://www.zhipin.com/...")
            print(f"抓取到 {len(jobs)} 条职位")

    asyncio.run(main())
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from typing import Any

import keyboard
import pyautogui
import uvicorn

from server import TabRegistry, RemoteSession, create_app

__all__ = ["BossJobsAuto"]

log = logging.getLogger("boss.jobs_auto")

# ── 关键词过滤 ────────────────────────────────────────────

_WHITELIST = ["前端", "全栈", "Web"]
_BLACKLIST = ["出差"]

# ── 薪资字符映射（BOSS 使用 PUA 区域字符编码数字） ───────

_SALARY_DECODE = {
    '\uE031': '0', '\uE032': '1', '\uE033': '2', '\uE034': '3',
    '\uE035': '4', '\uE036': '5', '\uE037': '6', '\uE038': '7',
    '\uE039': '8', '\uE03A': '9',
}


def _decode_salary(text: str) -> str:
    return ''.join(_SALARY_DECODE.get(ch, ch) for ch in text)


async def sleep(interval: tuple[float, float]) -> None:
    await asyncio.sleep(random.uniform(*interval))


class BossJobsAuto:
    """BOSS直聘自动化：启动服务 -> 打开页面 -> 点击前端 tab -> 循环爬取+滚动+沟通"""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.host = host
        self.port = port
        self.registry = TabRegistry()
        self.session = RemoteSession(self.registry)
        self.app = create_app(self.registry)
        self._server: uvicorn.Server | None = None
        self._server_task: asyncio.Task[None] | None = None
        self._tab_id: int | None = None

    def _tid(self) -> int:
        assert self._tab_id is not None
        return self._tab_id

    async def _activate(self) -> None:
        if self._tab_id is None:
            return
        try:
            await self.session.activate_tab(self._tab_id)
        except ConnectionError:
            log.warning("标签激活失败: chromeTabId=%s", self._tab_id)

    async def _click(self, x: int, y: int) -> None:
        await self._activate()
        pyautogui.click(x, y)

    async def __aenter__(self) -> BossJobsAuto:
        await self._start_server()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._stop_server()

    # ── 服务器生命周期 ─────────────────────────────────────

    async def _start_server(self) -> None:
        config = uvicorn.Config(self.app, host=self.host, port=self.port, log_level="warning")
        self._server = uvicorn.Server(config)
        self._server_task = asyncio.create_task(self._server.serve())

    async def _stop_server(self) -> None:
        if self._server:
            self._server.should_exit = True
            self._server = None
        if self._server_task:
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
            self._server_task = None

    # ── 主流程 ─────────────────────────────────────────────

    async def run(
        self,
        url: str | None = None,
        max_scrolls: int = 10,
        reuse_existing: bool = False,
    ) -> list[dict[str, Any]]:
        """打开页面 -> 点击前端 tab -> 循环爬取+滚动，返回职位列表"""
        tab_info = await self._connect(url, reuse_existing=reuse_existing)
        if tab_info:
            self._tab_id = tab_info["chromeTabId"]
        log.info("标签就绪: chromeTabId=%s", self._tab_id)

        await self._activate()

        await self.click_frontend_tab()

        all_jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        applied: set[str] = set()

        for scroll_i in range(max_scrolls + 1):
            if scroll_i > 0:
                log.info("滚动 (%d/%d)...", scroll_i, max_scrolls)
                await self.scroll_down()
                await asyncio.sleep(1.0)

            self._refresh_tab_id()

            jobs = await self._scrape_visible_jobs()

            new_jobs = [j for j in jobs if j["link"] not in seen]
            for j in new_jobs:
                seen.add(j["link"])
            all_jobs.extend(new_jobs)

            log.info(
                "第 %d 轮: %d 条, 新增 %d 条, 总计 %d 条",
                scroll_i + 1, len(jobs), len(new_jobs), len(all_jobs),
            )

            await self._apply_matches(new_jobs, applied)

            no_more = await self._check_no_more()
            if no_more:
                log.info("无更多数据，结束")
                break

        return all_jobs

    # ── 标签连接 ───────────────────────────────────────────

    async def _connect(
        self, url: str | None, timeout: float = 120.0, reuse_existing: bool = False
    ) -> dict[str, Any] | None:
        deadline = time.monotonic() + timeout
        while not self.registry.is_connected():
            if time.monotonic() > deadline:
                raise ConnectionError("扩展后台未连接")
            await asyncio.sleep(0.5)

        if url:
            if reuse_existing:
                for tab in self.registry.tabs:
                    if tab.get("url") == url:
                        log.info("复用已有标签: chromeTabId=%s", tab.get("chromeTabId"))
                        return tab
            result = await self.session.open_tab(url)
            if not result:
                raise TimeoutError(f"标签创建超时: {url}")
            log.info("标签已创建: chromeTabId=%s", result.get("chromeTabId"))
            return result

        # no url: use first existing tracked tab
        if self.registry.tabs:
            tab = self.registry.tabs[-1]
            log.info("使用已有标签: chromeTabId=%s", tab.get("chromeTabId"))
            return tab

        event = asyncio.Event()
        ready: list[dict] = []

        def on_ready(msg: dict) -> None:
            ready.append(msg)
            event.set()

        self.registry.on("tab_ready", on_ready)
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        finally:
            self.registry.off("tab_ready", on_ready)

        tab = ready[0]
        log.info("标签就绪: chromeTabId=%s", tab.get("chromeTabId"))
        return tab

    def _refresh_tab_id(self) -> None:
        if self._tab_id and self.registry.get_tab(self._tab_id):
            return
        tabs = self.registry.tabs
        if tabs:
            ctid = tabs[-1]["chromeTabId"]
            self._tab_id = ctid
            log.info("切换到标签 (最新): chromeTabId=%s", ctid)

    # ── 点击前端 tab ───────────────────────────────────────

    async def click_frontend_tab(self) -> bool:
        b = await self.session.bbox(
            self._tid(), "a.expect-item",
            filter={"textContains": "前端"},
        )
        if not b:
            log.warning("未找到「前端」tab")
            return False
        cx, cy = b["physical"]["cx"], b["physical"]["cy"]
        await self._click(cx, cy)
        log.info("已点击「前端」tab @ (%d, %d)", cx, cy)
        await asyncio.sleep(2.0)
        return True

    # ── 爬取可见职位 ───────────────────────────────────────

    async def _scrape_visible_jobs(self) -> list[dict[str, Any]]:
        res = await self.session.query(
            self._tid(),
            select="li.job-card-box",
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

    async def _check_no_more(self) -> bool:
        text = await self.session.execute(
            self._tid(), "return document.body.innerText", world="isolated",
        )
        return "没有更多了" in (text or "")

    # ── 滚动 ───────────────────────────────────────────────

    async def _get_job_list_center(self) -> tuple[int, int]:
        b = await self.session.bbox(
            self._tid(), "li.job-card-box",
            filter={"index": 0},
        )
        if not b:
            raise RuntimeError("无法定位职位列表区域")
        return (b["physical"]["cx"], b["physical"]["cy"])

    async def scroll_down(self, presses: int = 3) -> None:
        px, py = await self._get_job_list_center()
        await self._activate()
        pyautogui.moveTo(px, py)
        pyautogui.press('pagedown', presses=presses)

    # ── 匹配与沟通 ─────────────────────────────────────────

    async def _apply_matches(
        self,
        new_jobs: list[dict[str, Any]],
        applied: set[str],
    ) -> None:
        matches = [j for j in new_jobs if self._matches(j["title"])]
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

            # 点击卡片选中
            b = await self.session.bbox(
                self._tid(), "li.job-card-box",
                filter={"index": idx},
            )
            if not b:
                log.warning("定位卡片失败: %s", job["title"][:30])
                continue
            await self._click(b["physical"]["cx"], b["physical"]["cy"])
            await asyncio.sleep(1.0)

            # 检查沟通按钮
            btn = await self.session.query(
                self._tid(),
                select="a.op-btn-chat",
                project={"disabled": "@class~is-disabled", "text": "@text"},
                return_="first",
            )
            if not btn:
                log.info("无沟通按钮: %s", job["title"][:30])
                continue
            if btn.get("disabled"):
                log.info("已沟通过，跳过: %s", job["title"][:30])
                applied.add(job["link"])
                continue

            # 点击沟通
            b_btn = await self.session.bbox(self._tid(), "a.op-btn-chat")
            if not b_btn:
                log.warning("无法定位沟通按钮: %s", job["title"][:30])
                continue
            await self._click(b_btn["physical"]["cx"], b_btn["physical"]["cy"])
            log.info("已向「%s」发送沟通", job["title"][:40])
            applied.add(job["link"])

            # 处理成功弹窗：点击「留在本页」并等待消失
            await self._dismiss_greet_dialog()

            # 随机等待后继续
            await sleep((1.5, 4.0))

    async def _dismiss_greet_dialog(self, timeout: float = 10.0) -> bool:
        """等待沟通成功弹窗，点击「留在本页」，等待弹窗关闭。"""
        deadline = time.monotonic() + timeout

        # 等待弹窗出现
        while time.monotonic() < deadline:
            dialog = await self.session.query(
                self._tid(),
                select=".greet-boss-dialog",
                return_="raw",
            )
            if dialog:
                break
            await asyncio.sleep(0.3)
        else:
            log.warning("沟通成功弹窗未出现")
            return False

        await asyncio.sleep(0.5)

        # 点击「留在本页」
        b = await self.session.bbox(self._tid(), ".greet-boss-dialog .cancel-btn")
        if b:
            await self._click(b["physical"]["cx"], b["physical"]["cy"])
            log.info("已点击「留在本页」")
        else:
            log.warning("未找到「留在本页」按钮")

        # 等待弹窗消失
        while time.monotonic() < deadline:
            dialog = await self.session.query(
                self._tid(),
                select=".greet-boss-dialog",
                return_="raw",
            )
            if not dialog:
                log.info("沟通弹窗已关闭")
                return True
            await asyncio.sleep(0.3)

        log.warning("等待弹窗关闭超时")
        return False

    @staticmethod
    def _matches(title: str) -> bool:
        match_white = any(kw in title for kw in _WHITELIST)
        match_black = any(kw in title for kw in _BLACKLIST)
        return match_white and not match_black


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    log.info("按 Ctrl+E 强制退出")

    keyboard.add_hotkey("ctrl+e", lambda: os._exit(0))

    async def main():
        url = sys.argv[1] if len(sys.argv) > 1 else "https://www.zhipin.com/web/geek/jobs"
        async with BossJobsAuto() as auto:
            jobs = await auto.run(url, reuse_existing=True)
            print(f"抓取到 {len(jobs)} 条职位")

    asyncio.run(main())
