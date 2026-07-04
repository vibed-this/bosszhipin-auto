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
from typing import Any

import pyautogui
import uvicorn

from server import TabRegistry, RemoteSession, create_app

__all__ = ["BossJobsAuto"]

log = logging.getLogger("boss.jobs_auto")

# ── 关键词过滤 ────────────────────────────────────────────

_WHITELIST = ["前端", "全栈", "Web"]
_BLACKLIST = ["出差"]

# ── JS 片段 ────────────────────────────────────────────────

_SCRAPE_JOBS = r"""
function decodeSalary(text) {
  const map = {
    '\u{E031}': '0', '\u{E032}': '1', '\u{E033}': '2', '\u{E034}': '3',
    '\u{E035}': '4', '\u{E036}': '5', '\u{E037}': '6', '\u{E038}': '7',
    '\u{E039}': '8', '\u{E03A}': '9',
  };
  return text.replace(/[\u{E031}-\u{E03A}]/g, ch => map[ch] || ch);
}
const cards = document.querySelectorAll('li.job-card-box');
const jobs = Array.from(cards).map(card => {
  const title = card.querySelector('.job-name')?.textContent?.replace(/\s+/g, ' ').trim() || '';
  const raw = card.querySelector('.job-salary')?.textContent?.replace(/\s+/g, ' ').trim() || '';
  const salary = raw ? decodeSalary(raw) : '';
  const company = card.querySelector('.boss-name')?.textContent?.replace(/\s+/g, ' ').trim() || '';
  const area = card.querySelector('.company-location')?.textContent?.replace(/\s+/g, ' ').trim() || '';
  const tagItems = Array.from(card.querySelectorAll('.tag-list > li'));
  const experience = tagItems[0]?.textContent?.replace(/\s+/g, ' ').trim() || '';
  const education = tagItems[1]?.textContent?.replace(/\s+/g, ' ').trim() || '';
  const techTags = tagItems.slice(2).map(el => el.textContent?.replace(/\s+/g, ' ').trim()).filter(Boolean);
  const link = card.querySelector('a.job-name')?.href || '';
  return { title, company, area, experience, education, tags: techTags, salary, link };
});
return {
  url: location.href,
  title: document.title,
  total: jobs.length,
  jobs,
  noMore: document.body.innerText.includes('没有更多了'),
};
"""

_LOCATE_FRONTEND_TAB = r"""
const tabs = document.querySelectorAll('a.expect-item');
for (const tab of tabs) {
  if (tab.textContent.includes('前端')) {
    const rect = tab.getBoundingClientRect();
    const border = (window.outerWidth - window.innerWidth) / 2;
    const topUI = window.outerHeight - window.innerHeight - border;
    const cssX = window.screenX + border + rect.left;
    const cssY = window.screenY + topUI + rect.top;
    const ratio = window.devicePixelRatio || 1;
    return {
      css: { x: Math.round(cssX), y: Math.round(cssY) },
      physical: { x: Math.round(cssX * ratio), y: Math.round(cssY * ratio) },
      width: Math.round(rect.width),
      height: Math.round(rect.height),
    };
  }
}
return null;
"""

_GET_MATCHING_CARDS = r"""
const cards = document.querySelectorAll('li.job-card-box');
const whitelist = ['前端', '全栈', 'Web'];
const blacklist = ['出差'];
const result = [];
for (let i = 0; i < cards.length; i++) {
  const card = cards[i];
  const title = card.querySelector('.job-name')?.textContent?.trim() || '';
  const link = card.querySelector('a.job-name')?.href || '';
  const matchWhite = whitelist.some(kw => title.includes(kw));
  const matchBlack = blacklist.some(kw => title.includes(kw));
  if (!matchWhite || matchBlack) continue;
  result.push({ title, link, index: i });
}
return result;
"""

_SELECT_CARD_BY_INDEX = r"""
const card = document.querySelectorAll('li.job-card-box')[INDEX];
if (!card) return 'no card';
card.click();
return 'ok';
"""

_CHECK_CHAT_BTN = r"""
const btn = document.querySelector('a.op-btn-chat');
if (!btn) return { exists: false };
const rect = btn.getBoundingClientRect();
const border = (window.outerWidth - window.innerWidth) / 2;
const topUI = window.outerHeight - window.innerHeight - border;
const ratio = window.devicePixelRatio || 1;
return {
  exists: true,
  disabled: btn.classList.contains('is-disabled'),
  text: btn.textContent.trim(),
  physical: {
    x: Math.round((window.screenX + border + rect.left + rect.width / 2) * ratio),
    y: Math.round((window.screenY + topUI + rect.top + rect.height / 2) * ratio),
  },
};
"""

_CLICK_CHAT_BTN = r"""
const btn = document.querySelector('a.op-btn-chat');
if (!btn) return 'no btn';
if (btn.classList.contains('is-disabled')) return 'disabled';
btn.click();
return 'clicked';
"""


class BossJobsAuto:
    """BOSS直聘自动化：启动服务 → 打开页面 → 点击前端 tab → 循环爬取+滚动+沟通"""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.host = host
        self.port = port
        self.registry = TabRegistry()
        self.session = RemoteSession(self.registry)
        self.app = create_app(self.registry)
        self._server: uvicorn.Server | None = None
        self._server_task: asyncio.Task[None] | None = None
        self._tab_id: str | None = None

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
    ) -> list[dict[str, Any]]:
        """打开页面 → 点击前端 tab → 循环爬取+滚动，返回职位列表"""
        self._tab_id = await self._connect(url)
        log.info("标签就绪: %s", self._tab_id[:8])

        await self.session.activate_tab(self._tab_id)
        await asyncio.sleep(0.5)

        # 清除旧标签，取最新注册的标签
        self._refresh_tab_id()

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
            data = await self.session.execute(self._tab_id, _SCRAPE_JOBS)
            jobs = data.get("jobs", [])

            new_jobs = [j for j in jobs if j["link"] not in seen]
            for j in new_jobs:
                seen.add(j["link"])
            all_jobs.extend(new_jobs)

            log.info(
                "第 %d 轮: %d 条, 新增 %d 条, 总计 %d 条",
                scroll_i + 1, len(jobs), len(new_jobs), len(all_jobs),
            )

            # 对新增的匹配岗位发起沟通
            await self._apply_matches(new_jobs, applied)

            if data.get("noMore", True):
                log.info("无更多数据，结束")
                break

        return all_jobs

    # ── 标签连接 ────────────────────────────────────────────

    async def _connect(self, url: str | None, timeout: float = 120.0) -> str:
        if url:
            tab_id = await self.session.open_url(url)
            if not tab_id:
                raise TimeoutError(f"标签连接超时: {url}")
            return tab_id

        event = asyncio.Event()
        self.registry.on("tab_connected", lambda m: event.set())
        await asyncio.wait_for(event.wait(), timeout=timeout)
        return self.registry.tabs[0]["tab_id"]

    def _refresh_tab_id(self) -> None:
        if self._tab_id and self.registry.is_connected(self._tab_id):
            return
        connected = [
            t['tab_id'] for t in self.registry.tabs
            if self.registry.is_connected(t['tab_id'])
        ]
        if connected:
            self._tab_id = connected[-1]
            log.info("切换到标签: %s", self._tab_id[:8])

    # ── 点击前端 tab ────────────────────────────────────────

    async def click_frontend_tab(self) -> bool:
        coords = await self.session.execute(self._tab_id, _LOCATE_FRONTEND_TAB)
        if not coords:
            log.warning("未找到「前端」tab")
            return False
        cx = coords["physical"]["x"] + coords["width"] // 2
        cy = coords["physical"]["y"] + coords["height"] // 2
        pyautogui.click(cx, cy)
        log.info("已点击「前端」tab @ (%d, %d)", cx, cy)
        await asyncio.sleep(2.0)
        return True

    # ── 滚动 ────────────────────────────────────────────────

    async def _get_job_list_center(self) -> tuple[int, int]:
        js = r"""
const card = document.querySelector('li.job-card-box');
if (!card) return null;
const rect = card.getBoundingClientRect();
const border = (window.outerWidth - window.innerWidth) / 2;
const topUI = window.outerHeight - window.innerHeight - border;
const centerX = rect.left + rect.width / 2;
const centerY = rect.top + rect.height / 2;
const cssX = window.screenX + border + centerX;
const cssY = window.screenY + topUI + centerY;
const ratio = window.devicePixelRatio || 1;
return { x: Math.round(cssX * ratio), y: Math.round(cssY * ratio) };
"""
        result = await self.session.execute(self._tab_id, js)
        if not result:
            raise RuntimeError("无法定位职位列表区域")
        return (result["x"], result["y"])

    async def scroll_down(self, presses: int = 3) -> None:
        px, py = await self._get_job_list_center()
        pyautogui.moveTo(px, py)
        pyautogui.press('pagedown', presses=presses)

    # ── 匹配与沟通 ──────────────────────────────────────────

    async def _apply_matches(
        self,
        new_jobs: list[dict[str, Any]],
        applied: set[str],
    ) -> None:
        """遍历新增岗位，对白名单匹配且未沟通的发起沟通"""
        matches = [j for j in new_jobs if self._matches(j["title"])]
        if not matches:
            return

        log.info("本轮 %d 个匹配岗位，准备发起沟通", len(matches))

        # 获取当前可见匹配卡片的索引
        card_map = await self.session.execute(self._tab_id, _GET_MATCHING_CARDS)
        if not isinstance(card_map, list):
            log.warning("无法获取卡片列表: %s", card_map)
            return

        for job in matches:
            if job["link"] in applied:
                continue
            # 找到对应卡片在 DOM 中的索引
            entry = next(
                (c for c in card_map if c.get("link") == job["link"]),
                None,
            )
            if entry is None:
                log.info("卡片 %s 已不在可见区域，跳过", job["title"][:30])
                continue

            # 点击卡片选中（始终用搜索页 tab，不切换）
            sel_js = _SELECT_CARD_BY_INDEX.replace("INDEX", str(entry["index"]))
            result = await self.session.execute(self._tab_id, sel_js)
            if result != "ok":
                log.warning("选中卡片失败: %s", job["title"][:30])
                continue
            await asyncio.sleep(1.0)

            # 检查沟通按钮
            btn = await self.session.execute(self._tab_id, _CHECK_CHAT_BTN)
            if not btn or not btn.get("exists"):
                log.info("无沟通按钮: %s", job["title"][:30])
                continue
            if btn.get("disabled"):
                log.info("已沟通过，跳过: %s", job["title"][:30])
                applied.add(job["link"])
                continue

            # 点击沟通
            click_result = await self.session.execute(self._tab_id, _CLICK_CHAT_BTN)
            if click_result == "clicked":
                log.info("✅ 已向「%s」发送沟通", job["title"][:40])
                applied.add(job["link"])
                await asyncio.sleep(2.0)
            else:
                log.warning("沟通失败: %s", click_result)

    @staticmethod
    def _matches(title: str) -> bool:
        match_white = any(kw in title for kw in _WHITELIST)
        match_black = any(kw in title for kw in _BLACKLIST)
        return match_white and not match_black
