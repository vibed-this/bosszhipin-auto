"""页面分析工具：连接浏览器后扫描 DOM 结构、查找元素、定位坐标。

用法::

    from bzauto.analyze import PageAnalyzer

    async def main():
        async with PageAnalyzer() as pa:
            await pa.scan("https://www.zhipin.com/")
            await pa.dump("li.job-card-box", limit=2)
            await pa.find_text("留在本页")
            b = await pa.bbox(".greet-boss-dialog .cancel-btn")
"""

from __future__ import annotations

import asyncio
import logging
import sys

from bzauto.server.session import TabSession
from bzauto.server.lifecycle import get_registry, start_server, stop_server, ensure_tab

log = logging.getLogger("analyze")


class PageAnalyzer:
    """页面分析工具。"""

    def __init__(self, session: TabSession | None = None) -> None:
        self._session = session or TabSession()

    async def start(self) -> None:
        await start_server()
        log.info("等待扩展连接...")
        registry = self._session.registry
        while not registry.is_connected():
            await asyncio.sleep(0.5)
        log.info("扩展已连接，等待标签同步...")
        while not registry.tabs:
            await asyncio.sleep(0.3)
        log.info("已同步 %d 个标签", len(registry.tabs))
        await ensure_tab(self._session)

    async def stop(self) -> None:
        await stop_server()

    async def __aenter__(self) -> PageAnalyzer:
        await self.start()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.stop()

    async def connect(self, url: str | None = None) -> None:
        await ensure_tab(self._session, url)

    async def scan(self, url: str | None = None) -> None:
        await self.connect(url)
        log.info("标签: %s", self._session.tab_id)
        await self.dump_common_elements()

    async def dump(self, selector: str, limit: int = 5) -> list[dict]:
        raw = await self._session.query(select=selector, return_="raw")
        if raw:
            log.info("[%s] %d 个匹配:", selector, len(raw))
            for i, r in enumerate(raw[:limit]):
                log.info("  #%d: %s", i, r["html"])
        else:
            log.info("[%s] 无匹配", selector)
        return raw or []

    async def find_text(
        self, text: str, selector: str = "*", limit: int = 5,
    ) -> list[dict]:
        raw = await self._session.query(
            select=selector, filter={"textContains": text}, return_="raw",
        )
        if raw:
            log.info("「%s」找到 %d 个:", text, len(raw))
            for i, r in enumerate(raw[:limit]):
                log.info("  #%d: %s", i, r["html"])
        else:
            log.info("「%s」未找到", text)
        return raw or []

    async def bbox(self, selector: str, **filter_kw: object) -> dict | None:
        return await self._session.bbox(select=selector, filter=filter_kw or None)

    async def dump_common_elements(self) -> None:
        groups = [
            ("职位列表", [".job-list-container", "li.job-card-box", ".job-card-wrap"]),
            ("期望tab", ["a.expect-item", ".expect-list", ".expect-and-search"]),
            ("弹窗", [
                ".dialog-wrap", ".dialog", "[class*='dialog']",
                "[class*='modal']", "[class*='popup']",
                ".mask", ".tips-success",
                ".greet-boss-dialog",
            ]),
            ("沟通按钮", ["a.op-btn-chat", ".op-btn-chat", "[class*='chat']"]),
            ("薪资/公司", [".job-salary", ".salary", ".boss-name", ".company-name"]),
            ("表单/输入框", ["input", "textarea", "select"]),
            ("按钮", ["button", ".btn", "[class*='btn']", "[class*='button']"]),
        ]
        for label, selectors in groups:
            for sel in selectors:
                raw = await self._session.query(select=sel, return_="raw")
                if raw:
                    log.info("  [%s] %s: %d 个", label, sel, len(raw))
                    for r in raw[:1]:
                        log.info("    例: %s", r["html"][:200])

    async def dump_visible_dialogs(self) -> list[dict]:
        result = await self._session.execute("""
            (function() {
                var all = document.querySelectorAll('[class*=\"dialog\"],[class*=\"modal\"],[class*=\"popup\"],.mask');
                var visible = [];
                all.forEach(function(el) {
                    if (el.offsetParent !== null || el.style.display !== 'none') {
                        var rect = el.getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0) {
                            visible.push({
                                tag: el.tagName,
                                cls: el.className.slice(0, 80),
                                rect: {w:Math.round(rect.width), h:Math.round(rect.height)},
                                html: el.outerHTML.slice(0, 400),
                            });
                        }
                    }
                });
                return visible;
            })()
        """)
        if result:
            log.info("可见弹窗 %d 个:", len(result))
            for r in result:
                log.info("  <%s> class=%r rect=%s", r["tag"], r.get("cls", ""), r["rect"])
                log.info("    %s", r["html"][:300])
        else:
            log.info("无可见弹窗（或 CSP 拦截）")
        return result or []

    async def snapshot(self) -> str:
        result = await self._session.query(
            select="body", return_="raw",
        )
        if result:
            html = result[0].get("html", "")
            for line in html.split("\n"):
                log.info("  %s", line)
            return html
        return ""


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    async with PageAnalyzer() as pa:
        url = sys.argv[1] if len(sys.argv) > 1 else None
        await pa.scan(url)
        log.info("\n=== 输入任意关键词搜索 ===")


def cli_main() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
