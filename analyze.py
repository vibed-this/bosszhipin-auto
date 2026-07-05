"""页面分析工具：连接浏览器后扫描 DOM 结构、查找元素、定位坐标。

用法::

    from analyze import PageAnalyzer

    async def main():
        async with PageAnalyzer() as pa:
            await pa.connect()
            await pa.scan("https://www.zhipin.com/")
            await pa.dump("li.job-card-box", limit=2)
            await pa.find_text("留在本页")
            b = await pa.bbox(".greet-boss-dialog .cancel-btn")
"""

from __future__ import annotations

import asyncio
import logging
import sys

import uvicorn

from server import TabRegistry, RemoteSession, create_app

log = logging.getLogger("analyze")


class PageAnalyzer:
    """页面分析工具。"""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        self._host = host
        self._port = port
        self._registry = TabRegistry()
        self.session = RemoteSession(self._registry)
        self._app = create_app(self._registry)
        self._server: uvicorn.Server | None = None
        self._tab_id: int | None = None

    # ── 生命周期 ─────────────────────────────────────────────

    async def start(self) -> None:
        config = uvicorn.Config(self._app, host=self._host, port=self._port, log_level="warning")
        self._server = uvicorn.Server(config)
        asyncio.create_task(self._server.serve())
        log.info("等待扩展连接...")
        while not self._registry.is_connected():
            await asyncio.sleep(0.5)
        log.info("扩展已连接，等待标签同步...")
        while not self._registry.tabs:
            await asyncio.sleep(0.3)
        log.info("已同步 %d 个标签", len(self._registry.tabs))

    async def stop(self) -> None:
        if self._server:
            self._server.should_exit = True

    async def __aenter__(self) -> PageAnalyzer:
        await self.start()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.stop()

    # ── 标签管理 ─────────────────────────────────────────────

    def _tid(self) -> int:
        assert self._tab_id is not None
        return self._tab_id

    async def connect(self, url: str | None = None) -> dict:
        """连接到已打开的 BOSS 直聘标签，或打开指定 URL。"""
        tab = None
        for t in self._registry.tabs:
            if "zhipin.com" in (t.get("url", "") or ""):
                tab = t
                break
        if not tab and self._registry.tabs:
            tab = self._registry.tabs[-1]
        if not tab and url:
            tab = await self.session.open_tab(url)
        if not tab:
            raise RuntimeError("没有可用标签，请指定 url 参数")
        self._tab_id = tab["chromeTabId"]
        log.info("使用标签 %s: %s", self._tab_id, tab.get("url", ""))
        await asyncio.sleep(2.0)
        return tab

    # ── 分析方法 ─────────────────────────────────────────────

    async def scan(self, url: str | None = None) -> None:
        """连接页面并扫描常见 UI 元素。"""
        tab = await self.connect(url)
        log.info("标签: %s", tab.get("url", ""))
        await self.dump_common_elements()

    async def dump(self, selector: str, limit: int = 5) -> list[dict]:
        """获取匹配指定 CSS 选择器的元素 HTML（raw）。"""
        raw = await self.session.query(self._tid(), select=selector, return_="raw")
        if raw:
            log.info("[%s] %d 个匹配:", selector, len(raw))
            for i, r in enumerate(raw[:limit]):
                log.info("  #%d: %s", i, r["html"])
        else:
            log.info("[%s] 无匹配", selector)
        return raw or []

    async def find_text(self, text: str, selector: str = "*", limit: int = 5) -> list[dict]:
        """查找包含指定文本的元素。"""
        raw = await self.session.query(
            self._tid(), select=selector,
            filter={"textContains": text},
            return_="raw",
        )
        if raw:
            log.info("「%s」找到 %d 个:", text, len(raw))
            for i, r in enumerate(raw[:limit]):
                log.info("  #%d: %s", i, r["html"])
        else:
            log.info("「%s」未找到", text)
        return raw or []

    async def bbox(self, selector: str, **filter_kw: object) -> dict | None:
        """获取元素坐标（自动 scrollIntoView）。"""
        return await self.session.bbox(self._tid(), select=selector, filter=filter_kw or None)

    async def dump_common_elements(self) -> None:
        """扫描页面中常见的 UI 组件。"""
        groups = [
            ("职位列表", [".job-list-box", "li.job-card-box", ".job-card-wrapper"]),
            ("弹窗", [
                ".dialog-wrap", ".dialog", "[class*='dialog']",
                "[class*='modal']", "[class*='popup']",
                ".mask", ".tips-success",
                ".greet-boss-dialog",
            ]),
            ("沟通按钮", ["a.op-btn-chat", ".op-btn-chat", "[class*='chat']"]),
            ("表单/输入框", ["input", "textarea", "select"]),
            ("按钮", ["button", ".btn", "[class*='btn']", "[class*='button']"]),
        ]
        for label, selectors in groups:
            for sel in selectors:
                raw = await self.session.query(self._tid(), select=sel, return_="raw")
                if raw:
                    log.info("  [%s] %s: %d 个", label, sel, len(raw))
                    for r in raw[:1]:
                        log.info("    例: %s", r["html"][:200])

    async def dump_visible_dialogs(self) -> list[dict]:
        """查找所有可见的弹窗（通过 JS 检查 offsetParent），仅在 CSP 允许时工作。"""
        result = await self.session.execute(self._tid(), """
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
        """, world="isolated")
        if result:
            log.info("可见弹窗 %d 个:", len(result))
            for r in result:
                log.info("  <%s> class=%r rect=%s", r["tag"], r.get("cls",""), r["rect"])
                log.info("    %s", r["html"][:300])
        else:
            log.info("无可见弹窗（或 CSP 拦截）")
        return result or []

    async def snapshot(self) -> str:
        """返回页面 body 的前 2000 字符用于快速定位。"""
        result = await self.session.execute(
            self._tid(),
            "document.body.innerHTML.slice(0, 2000)",
            world="isolated",
        )
        if result:
            for line in result.split("\n"):
                log.info("  %s", line)
        return result or ""


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    async with PageAnalyzer() as pa:
        url = sys.argv[1] if len(sys.argv) > 1 else None
        await pa.scan(url)
        log.info("\n=== 输入任意关键词搜索（传入命令行参数: python analyze.py <关键词>）===")


if __name__ == "__main__":
    asyncio.run(main())
