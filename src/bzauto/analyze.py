"""页面分析工具：连接浏览器后扫描 DOM 结构、查找元素、定位坐标。

用法::

    from bzauto.analyze import PageAnalyzer

    async def main():
        async with PageAnalyzer() as pa:
            await pa.connect("https://www.zhipin.com/")
            await pa.dump("li.job-card-box", limit=2)
            await pa.find_text("留在本页")
            b = await pa.bbox(".greet-boss-dialog .cancel-btn")
"""

from __future__ import annotations

import asyncio
import logging
import sys

import qasync

from PySide6.QtWidgets import QApplication

from bzauto.browser import BrowserManager, BrowserSession
from bzauto.browser.manager import _set_browser_manager

log = logging.getLogger("analyze")


class PageAnalyzer:
    """页面分析工具 — 使用 BrowserSession 直接驱动。"""

    def __init__(self, session: BrowserSession | None = None) -> None:
        self._session = session
        self._manager: BrowserManager | None = None

    async def start(self) -> None:
        if self._session is not None:
            return
        accounts = [{"id": "main", "name": "main"}]
        self._manager = BrowserManager(accounts)
        _set_browser_manager(self._manager)
        self._manager.show()
        self._session = self._manager.get_session("main")

    async def stop(self) -> None:
        if self._manager:
            self._manager.close()

    async def __aenter__(self) -> PageAnalyzer:
        await self.start()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.stop()

    async def connect(self, url: str | None = None) -> None:
        if url:
            await self._session.ensure_tab(url, timeout=30.0)
        else:
            await self._session.ensure_tab()

    async def scan(self, url: str | None = None) -> None:
        await self.connect(url)
        log.info("当前 URL: %s", self._session.current_url)
        await self.dump_common_elements()

    async def dump(self, selector: str, limit: int = 5) -> list[dict]:
        items = await self._session.find_all(selector, project={"html": "@html", "text": "@text"})
        if items:
            log.info("[%s] %d 个匹配:", selector, len(items))
            for i, r in enumerate(items[:limit]):
                html = r.get("html", "")[:200]
                log.info("  #%d: %s", i, html)
        else:
            log.info("[%s] 无匹配", selector)
        return items

    async def find_text(
        self, text: str, selector: str = "*", limit: int = 5,
    ) -> list[dict]:
        items = await self._session.find_all(
            select=selector,
            filter={"textContains": text},
            project={"html": "@html", "text": "@text"},
        )
        if items:
            log.info("「%s」找到 %d 个:", text, len(items))
            for i, r in enumerate(items[:limit]):
                html = r.get("html", "")[:200]
                log.info("  #%d: %s", i, html)
        else:
            log.info("「%s」未找到", text)
        return items

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
                items = await self._session.find_all(sel, project={"html": "@html"})
                if items:
                    log.info("  [%s] %s: %d 个", label, sel, len(items))
                    html = items[0].get("html", "")[:200]
                    log.info("    例: %s", html)

    async def dump_visible_dialogs(self) -> list[dict]:
        result = await self._session.eval_js("""
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
            log.info("无可见弹窗")
        return result or []

    async def snapshot(self) -> str:
        html = await self._session.dump_html()
        if html:
            for line in html.split("\n"):
                log.info("  %s", line)
        return html or ""


def cli_main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    app = QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    async def _main():
        url = sys.argv[1] if len(sys.argv) > 1 else None
        pa = PageAnalyzer()
        await pa.start()
        try:
            await pa.scan(url)
        finally:
            await pa.stop()

    loop.create_task(_main())
    with loop:
        loop.run_forever()


if __name__ == "__main__":
    cli_main()
