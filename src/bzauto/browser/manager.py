"""BrowserManager — QMainWindow + QTabWidget 多账号浏览器管理器。"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QUrl
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QMainWindow, QTabWidget, QVBoxLayout, QWidget

from bzauto.browser.js_helper import JS_HELPER
from bzauto.browser.overlay import DotOverlay

if TYPE_CHECKING:
    from bzauto.browser.session import BrowserSession

log = logging.getLogger("boss.browser.manager")

_manager: BrowserManager | None = None

_PROFILES_DIR = "profiles"


class BzWebEnginePage(QWebEnginePage):
    """自定义 QWebEnginePage：createWindow 在同页导航 + loadFinished 注入 JS_HELPER。"""

    def __init__(self, profile: QWebEngineProfile, view: QWebEngineView) -> None:
        super().__init__(profile, view)
        self._view = view

    def createWindow(self, _type: QWebEnginePage.WebWindowType) -> QWebEnginePage:
        return self

    def _on_load_finished(self, ok: bool) -> None:
        if ok:
            self.runJavaScript(JS_HELPER)

    def javaScriptConsoleMessage(
        self, level: QWebEnginePage.JavaScriptConsoleMessageLevel,
        message: str, line_number: int, source_id: str,
    ) -> None:
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            log.debug("JS error [%s:%d]: %s", source_id, line_number, message)


class _AccountTab:
    """单个账号的视图、页面、覆盖层。"""

    def __init__(self, account_id: str, name: str, view: QWebEngineView,
                 page: QWebEnginePage, overlay: DotOverlay) -> None:
        self.account_id = account_id
        self.name = name
        self.view = view
        self.page = page
        self.overlay = overlay


class BrowserManager(QMainWindow):
    """主窗口 — QTabWidget + 每账号独立 Profile/View/Page。"""

    def __init__(self, accounts: list[dict[str, Any]],
                 profiles_dir: str = _PROFILES_DIR) -> None:
        super().__init__()
        self.setWindowTitle("Boss直聘自动控制")
        self.resize(1200, 800)

        self._profiles_dir = profiles_dir
        self._tabs: QTabWidget = QTabWidget()
        self.setCentralWidget(self._tabs)

        self._account_tabs: dict[str, _AccountTab] = {}
        self._sessions: dict[str, Any] = {}  # lazy init

        for acc in accounts:
            self._add_account_tab(acc)

        self._tabs.currentChanged.connect(self._on_tab_changed)

    def _add_account_tab(self, acc: dict[str, Any]) -> None:
        account_id = acc["id"]
        name = acc.get("name", account_id)
        profile_dir = Path(self._profiles_dir) / account_id
        profile_dir.mkdir(parents=True, exist_ok=True)

        profile = QWebEngineProfile(account_id, self)
        profile.setPersistentStoragePath(str(profile_dir))
        profile.setPersistentCookiesPolicy(
            QWebEngineProfile. PersistentCookiesPolicy.ForcePersistentCookies
        )

        view = QWebEngineView()
        page = BzWebEnginePage(profile, view)
        view.setPage(page)

        overlay = DotOverlay()
        overlay.setParent(view)
        overlay.setGeometry(0, 0, view.width(), view.height())
        overlay.raise_()
        overlay.show()

        def resize_overlay() -> None:
            overlay.setGeometry(0, 0, view.width(), view.height())
            overlay.raise_()

        original_resize = view.resizeEvent
        def _on_resize(event: object) -> None:
            resize_overlay()
            if original_resize:
                original_resize(event)

        view.resizeEvent = _on_resize  # type: ignore[method-assign]

        page.loadFinished.connect(page._on_load_finished)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(view)
        self._tabs.addTab(container, name)

        self._account_tabs[account_id] = _AccountTab(
            account_id=account_id, name=name,
            view=view, page=page, overlay=overlay,
        )

    def _on_tab_changed(self, index: int) -> None:
        log.debug("标签页切换到 index=%d", index)

    def activate_account(self, account_id: str) -> None:
        """切换到指定账号的标签页。"""
        for idx, (aid, atab) in enumerate(self._account_tabs.items()):
            if aid == account_id:
                self._tabs.setCurrentIndex(idx)
                atab.view.setFocus()
                atab.view.raise_()
                return
        log.warning("账号 %s 不存在", account_id)

    def get_account_tab(self, account_id: str) -> _AccountTab | None:
        return self._account_tabs.get(account_id)

    def get_page(self, account_id: str) -> QWebEnginePage | None:
        atab = self._account_tabs.get(account_id)
        return atab.page if atab else None

    def get_view(self, account_id: str) -> QWebEngineView | None:
        atab = self._account_tabs.get(account_id)
        return atab.view if atab else None

    def get_session(self, account_id: str) -> Any:
        """获取或创建账号的 BrowserSession。"""
        if account_id not in self._sessions:
            from bzauto.browser.session import BrowserSession
            self._sessions[account_id] = BrowserSession(self, account_id)
        return self._sessions[account_id]

    def connected_accounts(self) -> list[str]:
        return list(self._account_tabs.keys())

    def load_url(self, account_id: str, url: str) -> None:
        """加载 URL 到指定账号。"""
        page = self.get_page(account_id)
        if page:
            page.load(QUrl(url))

    async def wait_loaded(self, account_id: str, timeout: float = 20.0) -> bool:
        """等待页面加载完成（通过轮询 page.url）。"""
        page = self.get_page(account_id)
        if not page:
            return False
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if page.url().toString() and not page.url().toString().startswith("about:"):
                return True
            await asyncio.sleep(0.3)
        return False


def get_browser_manager() -> BrowserManager | None:
    """模块级单例。"""
    global _manager
    return _manager


def _set_browser_manager(m: BrowserManager) -> None:
    global _manager
    _manager = m
