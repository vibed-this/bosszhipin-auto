"""Boss直聘职位列表页面对象（选择器 + 操作方法）。"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, AsyncIterator

from bzauto.browser.session import BrowserSession
from bzauto.filter import match_blacklist
from bzauto.models import JobCard
from bzauto.pages.base import BasePage

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
_LOCATION = ".company-location"
_EXPECT_TAB = "a.expect-item"

_JOB_PROJECT = {
    "title": f"{_JOB_TITLE}@text",
    "salary": f"{_SALARY}@text",
    "company": f"{_COMPANY}@text",
    "href": f"{_JOB_LINK}@href",
    "location": f"{_LOCATION}@text",
    # 尝试抓取列表卡片上可见的标签（如果有），不保证所有卡片都有
    "tags": [".job-tag@text", ".tag-item@text", ".job-label@text", "span[class*='tag']@text"],
}

_VUE_EXTRACT_JS = """
JSON.stringify((function() {
    var el = document.querySelector('.page-jobs-main');
    if (!el || !el.__vue__) return null;
    var list = el.__vue__.jobList;
    if (!Array.isArray(list)) return null;
    return list.map(function(j) {
        var tags = [];
        if (Array.isArray(j.welfareList)) tags = tags.concat(j.welfareList);
        if (Array.isArray(j.tags)) tags = tags.concat(j.tags);
        // 去重并保留字符串
        var seen = {};
        tags = tags.filter(function(t){ return t && !seen[t] && (seen[t]=1); });
        return {
            jobName: j.jobName,
            salaryDesc: j.salaryDesc,
            brandName: j.brandName,
            encryptJobId: j.encryptJobId,
            cityName: j.cityName,
            areaDistrict: j.areaDistrict,
            businessDistrict: j.businessDistrict,
            tags: tags,
        };
    });
})())
"""

_CHAT_DETAIL_SELECTOR = "a.btn-startchat"

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


def _parse_salary(text: str) -> tuple[int, int] | None:
    """解析薪资字符串，返回 (min_k, max_k) 或 None。"""
    m = re.search(r'(\d+)-(\d+)', text)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r'(\d+)K', text)
    if m:
        v = int(m.group(1))
        return v, v
    return None


class BossJobListPage(BasePage):
    """Boss直聘职位列表页面对象（选择器 + 操作方法）。"""

    _LOADED_SELECTOR = "li.job-card-box"

    def __init__(self, session: BrowserSession) -> None:
        super().__init__(session)
        self._session: BrowserSession = session

    async def get_job_cards_from_vue(self) -> list[JobCard]:
        """从 Vue page-jobs-main.jobList 读取所有职位卡片。"""
        raw = await self._session.eval_js(_VUE_EXTRACT_JS)
        if not raw:
            return []
        items = json.loads(raw) if isinstance(raw, str) else raw
        return [JobCard.from_vue_row(item) for item in items]

    async def get_job_cards(self) -> list[JobCard]:
        cards = await self._session.find_all(
            select=_JOB_ITEM,
            project=_JOB_PROJECT,
        )
        result: list[JobCard] = []
        for card in cards:
            if "salary" in card:
                card["salary"] = _decode_salary_icon(card["salary"])
            result.append(JobCard.from_query_row(card))
        return result

    async def get_job_card_at(self, index: int) -> JobCard | None:
        raw = await self._session.find_one(
            select=_JOB_ITEM,
            filter={"index": index},
            project=_JOB_PROJECT,
        )
        if not raw:
            return None
        if "salary" in raw:
            raw["salary"] = _decode_salary_icon(raw["salary"])
        return JobCard.from_query_row(raw)

    async def click_card_at(self, index: int) -> bool:
        """点击指定索引的职位卡片 — 通过 bbox → Qt 事件。"""
        await self._session.click_element(
            _JOB_ITEM,
            filter={"index": index},
            post_sleep=0.5,
        )
        return True

    async def click_chat_on_detail(self) -> None:
        """在独立职位详情页点击「立即沟通」按钮。"""
        await self._session.click_element(
            _CHAT_DETAIL_SELECTOR,
            post_sleep=2.0,
        )

    async def click_chat(self, index: int = 0) -> None:
        """等待沟通按钮出现后点击。"""
        from bzauto.browser.session import ElementNotFound

        deadline = asyncio.get_event_loop().time() + 30.0
        last_error: Exception | None = None
        while asyncio.get_event_loop().time() < deadline:
            try:
                await self._session.click_element(
                    "a.op-btn-chat",
                    filter={"nth": index},
                    post_sleep=1.5,
                )
                return
            except ElementNotFound as e:
                last_error = e
                await asyncio.sleep(0.5)
        if last_error:
            raise last_error

    async def click_expect_tab(self) -> None:
        """点击期望 tab。"""
        await self._session.click_element(
            _EXPECT_TAB,
            post_sleep=1.5,
        )

    async def dismiss_dialogs(self) -> bool:
        """关闭弹窗。返回 True 继续，False 终止。无弹窗返回 True。"""
        from bzauto.browser.session import ElementNotFound

        for selector in _DIALOG_SELECTORS:
            try:
                bbox = await self._session.bbox(selector)
                if bbox and bbox.get("cx", 0) > 0:
                    log.info("  关闭弹窗 %s  cx=%d cy=%d", selector, bbox["cx"], bbox["cy"])
                    await self._session.click(int(bbox["cx"]), int(bbox["cy"]))
                    await asyncio.sleep(0.5)
            except (ElementNotFound, TimeoutError, ConnectionError) as e:
                log.debug("关闭弹窗失败 %s: %s", selector, e)

        items = await self._session.find_all(
            select=".chat-block-dialog .chat-block-body",
            project={"text": "@text"},
        )
        if items:
            text = items[0].get("text", "")
            log.info("  沟通上限弹窗: %s", text)
            bbox = await self._session.bbox(select=".chat-block-dialog .sure-btn")
            if bbox and bbox.get("cx", 0) > 0:
                await self._session.click(int(bbox["cx"]), int(bbox["cy"]))
                await asyncio.sleep(0.5)
            if "今日已投递" in text or "150" in text or "消息已满" in text or "明日再试" in text:
                return False

        greet = await self._session.find_all(
            select=".dialog-wrap.greet-pop .dialog-con p",
            project={"text": "@text"},
        )
        if greet:
            text = greet[0].get("text", "")
            log.info("  温馨提示弹窗: %s", text)
            btn = await self._session.bbox(select=".dialog-wrap.greet-pop .btn.btn-sure")
            if btn and btn.get("cx", 0) > 0:
                await self._session.click(int(btn["cx"]), int(btn["cy"]))
                await asyncio.sleep(2.0)
            if "今日" in text or "已累计" in text or "150" in text:
                return False

        still_on_detail = await self._session.eval_js("""(function(){
            var el = document.querySelector('a.btn-startchat');
            if (!el) return false;
            var rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
        })()""")
        if still_on_detail:
            log.info("  弹窗已关闭，仍在详情页，点击沟通按钮继续")
            await self._session.click_element(
                _CHAT_DETAIL_SELECTOR,
                post_sleep=2.0,
            )

        return True

    async def find_card_by_href(self, href: str) -> int:
        """通过 href 查找卡片索引。未找到返回 -1。"""
        href_suffix = json.dumps(href.split("/").pop())
        result = await self._session.eval_js(
            f"(function(){{"
            f"  var cards = document.querySelectorAll('{_JOB_ITEM}');"
            f"  for (var i = 0; i < cards.length; i++) {{"
            f"    var link = cards[i].querySelector('{_JOB_LINK}');"
            f"    if (link && link.href.includes({href_suffix})) {{"
            f"      return i;"
            f"    }}"
            f"  }}"
            f"  return -1;"
            f"}})()"
        )
        return int(result) if result is not None else -1

    async def get_salary_texts(self) -> list[str]:
        items = await self._session.find_all(
            select=_SALARY,
            project={"text": "@text"},
        )
        return [item["text"] for item in items]

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
        max_jobs: int = 0,
    ) -> AsyncIterator[tuple[JobCard, int]]:
        """异步迭代器：逐个产出职位卡片，自动处理翻页和智能滚动。

        基于 Vue __vue__.jobList 数据源（优先），回退到 DOM 查询。
        """
        emitted = 0
        index = 0
        scroll_count = 0
        stale_rounds = 0
        max_stale = 3

        vue_items: list[JobCard] = await self.get_job_cards_from_vue()

        while True:
            if max_jobs > 0 and emitted >= max_jobs:
                log.info("已达采集上限 %d", max_jobs)
                break

            if index >= len(vue_items):
                if scroll_count >= max_scrolls:
                    log.info("已达最大滚动次数 %d", max_scrolls)
                    break
                if stale_rounds >= max_stale:
                    log.info("连续 %d 轮无新数据，停止", max_stale)
                    break

                scroll_count += 1
                stale_rounds += 1

                log.info("数据耗尽，尝试智能滚动 #%d...", scroll_count)

                await self._session.eval_js(
                    "(function(){"
                    "  var c = document.querySelector('.job-list-container');"
                    "  if (c) c.scrollTop = c.scrollHeight;"
                    "  window.scrollTo(0, document.body.scrollHeight);"
                    "})()"
                )
                await asyncio.sleep(10)

                vue_items = await self.get_job_cards_from_vue()
                if index < len(vue_items):
                    stale_rounds = 0
                continue

            card = vue_items[index]
            stale_rounds = 0
            scroll_count = 0
            emitted += 1
            yield card, index
            index += 1

    async def iter_filtered_cards(
        self,
        *,
        whitelist: list[str] | None = None,
        blacklist: list[str] | None = None,
        min_salary: int | None = None,
        max_salary: int | None = None,
        max_scrolls: int = 10,
        scroll_timeout: float = 5.0,
        max_jobs: int = 0,
    ) -> AsyncIterator[tuple[JobCard, int]]:
        """包装 iter_job_cards，按白名单/黑名单/薪资过滤并去重。"""
        seen: set[tuple[str, str]] = set()
        async for card, idx in self.iter_job_cards(
            max_scrolls=max_scrolls,
            scroll_timeout=scroll_timeout,
            max_jobs=max_jobs,
        ):
            title = card.title.strip().lower()
            if whitelist and not any(kw in title for kw in whitelist):
                continue
            if match_blacklist(card.title, blacklist or []):
                continue

            salary = _parse_salary(card.salary)
            if min_salary is not None:
                if salary is None or salary[0] < min_salary:
                    continue
            if max_salary is not None:
                if salary is None or salary[1] < max_salary:
                    continue

            key = (card.title, card.company)
            if key in seen:
                continue
            seen.add(key)
            yield card, idx