"""BrowserSession — QWebEnginePage 操作代理，替代 TabSession。"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from PySide6.QtCore import QUrl

from bzauto.browser import events
from bzauto.browser.manager import BrowserManager
from bzauto.browser.types import BboxResult, QueryFilter

log = logging.getLogger("boss.browser.session")


class ElementNotFound(LookupError):
    def __init__(self, selector: str, filter: QueryFilter | None = None) -> None:
        self.selector = selector
        self.filter = filter
        ctx = f"selector={selector!r}"
        if filter:
            ctx += f" filter={filter!r}"
        super().__init__(f"未找到匹配元素: {ctx}")


class PageLoadTimeout(TimeoutError):
    pass


class BrowserSession:
    """QWebEnginePage 操作代理 — 替代 TabSession。

    每账号一个实例，保证只操作自己的 View/Page。
    """

    def __init__(self, manager: BrowserManager, account_id: str) -> None:
        self._manager = manager
        self._account_id = account_id
        self._load_future: asyncio.Future[bool] | None = None

    @property
    def account_id(self) -> str:
        return self._account_id

    @property
    def current_url(self) -> str | None:
        page = self._manager.get_page(self._account_id)
        if page:
            url = page.url().toString()
            return url if url and not url.startswith("about:") else None
        return None

    # ── 生命周期 ──

    async def ensure_tab(self, url: str | None = None, *,
                         reuse_existing: bool = False,
                         timeout: float = 20.0) -> None:
        """确保账号标签已加载指定 URL。

        若 url 为 None 则不导航；若 reuse_existing 且当前 URL 相同则不复载。
        """
        page = self._manager.get_page(self._account_id)
        if not page:
            raise RuntimeError(f"账号 {self._account_id} 没有页面")

        if url:
            if reuse_existing and self.current_url == url:
                log.debug("复用已有标签: url=%s", url)
                return
            self._manager.load_url(self._account_id, url)

        loaded = await self._manager.wait_loaded(self._account_id, timeout=timeout)
        if not loaded:
            raise PageLoadTimeout(f"页面加载超时: {url}")

    async def activate(self) -> None:
        """切换到该账号的标签页并聚焦。"""
        self._manager.activate_account(self._account_id)

    # ── 查询原语 ──

    async def eval_js(self, code: str, *, timeout: float = 30.0) -> Any:
        """在页面 MAIN world 执行 JS 代码，返回 JSON 反序列化结果。"""
        page = self._manager.get_page(self._account_id)
        if not page:
            raise RuntimeError(f"账号 {self._account_id} 没有页面")

        loop = asyncio.get_event_loop()
        future: asyncio.Future[Any] = loop.create_future()

        def callback(raw: Any) -> None:
            if not future.done():
                if raw is None:
                    future.set_result(None)
                elif isinstance(raw, str):
                    try:
                        future.set_result(json.loads(raw))
                    except (json.JSONDecodeError, TypeError):
                        future.set_result(raw)
                else:
                    future.set_result(raw)

        page.runJavaScript(code, callback)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"eval_js 超时 ({timeout}s)")

    async def bbox(self, select: str, *,
                   filter: QueryFilter | None = None,
                   timeout: float = 30.0) -> BboxResult | None:
        """查询元素在视口中的位置。返回 {x,y,w,h,cx,cy} 或 None。"""
        code = f"JSON.stringify(window.__bz.bboxOf({json.dumps(select)}, {json.dumps(filter or {})}))"
        raw = await self.eval_js(code, timeout=timeout)
        if not raw or raw == "null":
            return None
        if isinstance(raw, str):
            return json.loads(raw)
        return raw  # type: ignore[return-value]

    async def find_all(self, select: str, *,
                       filter: QueryFilter | None = None,
                       project: dict[str, str] | None = None,
                       timeout: float = 30.0) -> list[dict]:
        """查找所有匹配元素，投影指定字段。"""
        code = (
            f"JSON.stringify(window.__bz.findAll("
            f"{json.dumps(select)}, {json.dumps(filter or {})}, {json.dumps(project or {})}))"
        )
        raw = await self.eval_js(code, timeout=timeout)
        if not raw:
            return []
        if isinstance(raw, str):
            return json.loads(raw)
        return raw  # type: ignore[return-value]

    async def find_one(self, select: str, *,
                       filter: QueryFilter | None = None,
                       project: dict[str, str] | None = None,
                       timeout: float = 30.0) -> dict | None:
        """查找第一个匹配元素。"""
        code = (
            f"JSON.stringify(window.__bz.findOne("
            f"{json.dumps(select)}, {json.dumps(filter or {})}, {json.dumps(project or {})}))"
        )
        raw = await self.eval_js(code, timeout=timeout)
        if not raw or raw == "null":
            return None
        if isinstance(raw, str):
            return json.loads(raw)
        return raw  # type: ignore[return-value]

    async def count(self, select: str, *,
                    filter: QueryFilter | None = None,
                    timeout: float = 30.0) -> int:
        code = f"window.__bz.count({json.dumps(select)}, {json.dumps(filter or {})})"
        raw = await self.eval_js(code, timeout=timeout)
        return int(raw) if raw else 0

    async def dump_html(self, *, timeout: float = 30.0) -> str | None:
        code = "window.__bz.dumpHtml()"
        return await self.eval_js(code, timeout=timeout)

    # ── 设备输入（Qt 事件模拟）──

    async def click(self, x: int, y: int) -> None:
        """在 (x,y) 逻辑像素位置点击。"""
        view = self._manager.get_view(self._account_id)
        if not view:
            raise RuntimeError(f"账号 {self._account_id} 没有视图")
        events.send_click(view, x, y)

    async def mouse_move(self, x: int, y: int) -> None:
        """在 (x,y) 逻辑像素位置发送鼠标移动。"""
        view = self._manager.get_view(self._account_id)
        if not view:
            raise RuntimeError(f"账号 {self._account_id} 没有视图")
        events.send_mousemove(view, x, y)

    async def scroll_wheel(self, dy: int, *,
                           at_x: int | None = None,
                           at_y: int | None = None,
                           presses: int = 1) -> None:
        view = self._manager.get_view(self._account_id)
        if not view:
            raise RuntimeError(f"账号 {self._account_id} 没有视图")
        events.send_wheel(view, dy, at_x=at_x, at_y=at_y, presses=presses)

    async def scroll_pagedown(self, *,
                               at_x: int | None = None,
                               at_y: int | None = None,
                               presses: int = 3) -> None:
        view = self._manager.get_view(self._account_id)
        if not view:
            raise RuntimeError(f"账号 {self._account_id} 没有视图")
        from PySide6.QtCore import Qt
        events.send_key(view, Qt.Key_PageDown, presses=presses)

    # ── 组合操作 ──

    async def click_element(self, select: str, *,
                            filter: QueryFilter | None = None,
                            wait_visible: str | None = None,
                            wait_hidden: str | None = None,
                            timeout: float = 30.0,
                            post_sleep: float = 0.5) -> None:
        """bbox → 点击 → 轮询等待。"""
        bbox = await self.bbox(select, filter=filter, timeout=timeout)
        if bbox is None or bbox.get("cx", 0) <= 0:
            raise ElementNotFound(select, filter)
        await self.click(int(bbox["cx"]), int(bbox["cy"]))
        await asyncio.sleep(post_sleep)

        if wait_visible:
            deadline = asyncio.get_event_loop().time() + timeout
            while asyncio.get_event_loop().time() < deadline:
                check = await self.bbox(wait_visible, timeout=5.0)
                if check is not None:
                    break
                await asyncio.sleep(0.3)

        if wait_hidden:
            deadline = asyncio.get_event_loop().time() + timeout
            while asyncio.get_event_loop().time() < deadline:
                check = await self.bbox(wait_hidden, timeout=5.0)
                if check is None:
                    break
                await asyncio.sleep(0.3)
