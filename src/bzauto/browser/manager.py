"""BrowserManager — QMainWindow + QTabWidget 多账号浏览器管理器。"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, QUrl, Signal, QEvent
from PySide6.QtGui import QColor, QShowEvent, QWindowStateChangeEvent
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QMainWindow, QMenu, QPushButton, QSplitter, QTabWidget, QVBoxLayout, QWidget

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
    """单个账号的视图、页面、覆盖层、导航栏。"""

    def __init__(self, account_id: str, name: str, profile: QWebEngineProfile,
                 view: QWebEngineView, page: QWebEnginePage,
                 # overlay: DotOverlay,
                 url_input: QLineEdit | None = None,
                 back_btn: QPushButton | None = None,
                 forward_btn: QPushButton | None = None,
                 refresh_btn: QPushButton | None = None,
                 nav_btn: QPushButton | None = None) -> None:
        self.account_id = account_id
        self.name = name
        self.profile = profile
        self.view = view
        self.page = page
        # self.overlay = overlay
        self.url_input = url_input
        self.back_btn = back_btn
        self.forward_btn = forward_btn
        self.refresh_btn = refresh_btn
        self.nav_btn = nav_btn
        self.unread_count: int = 0


class BrowserManager(QMainWindow):
    """主窗口 — QTabWidget + 每账号独立 Profile/View/Page。"""

    windowStateChanged = Signal(object)
    windowActivated = Signal(bool)

    def __init__(self, accounts: list[dict[str, Any]],
                 profiles_dir: str = _PROFILES_DIR) -> None:
        super().__init__()
        self.setWindowTitle("Boss直聘自动控制")
        self.resize(1200, 800)

        self._profiles_dir = profiles_dir
        self._tabs: QTabWidget = QTabWidget()

        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.addWidget(self._tabs)
        self.setCentralWidget(self._splitter)
        self._side_splitter: QSplitter | None = None

        self._account_tabs: dict[str, _AccountTab] = {}
        self._sessions: dict[str, Any] = {}  # lazy init
        self._load_futures: dict[str, asyncio.Future[bool]] = {}
        self._load_finished: dict[str, bool] = {}

        for acc in accounts:
            self._add_account_tab(acc)

        self._tabs.currentChanged.connect(self._on_tab_changed)

    def showEvent(self, event: QShowEvent) -> None:
        self.setWindowState(self.windowState() | Qt.WindowMaximized)
        super().showEvent(event)

    def changeEvent(self, event: QWindowStateChangeEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self.windowStateChanged.emit(self.windowState())
        elif event.type() == QEvent.Type.ActivationChange:
            self.windowActivated.emit(self.isActiveWindow())

    def _add_account_tab(self, acc: dict[str, Any]) -> None:
        account_id: str = acc["id"]
        name = acc.get("name", account_id)
        profile_dir = Path(self._profiles_dir) / account_id
        profile_dir.mkdir(parents=True, exist_ok=True)

        profile = QWebEngineProfile(account_id, self)
        profile.setPersistentStoragePath(profile_dir.absolute().as_posix())
        profile.setPersistentCookiesPolicy(
            QWebEngineProfile. PersistentCookiesPolicy.ForcePersistentCookies
        )

        view = QWebEngineView()
        page = BzWebEnginePage(profile, view)
        view.setPage(page)

        self._load_finished[account_id] = False

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
        page.loadFinished.connect(lambda ok: self._on_page_loaded(account_id, ok))

        # ── 每 tab 独立地址栏 ──
        back_btn = QPushButton("←")
        back_btn.setFixedWidth(32)
        forward_btn = QPushButton("→")
        forward_btn.setFixedWidth(32)
        refresh_btn = QPushButton("↻")
        refresh_btn.setFixedWidth(32)

        nav_btn = QPushButton("快速跳转")
        nav_btn.setFixedWidth(80)
        nav_menu = QMenu(nav_btn)
        nav_menu.addAction("首页", lambda: page.load(QUrl("https://www.zhipin.com/")))
        nav_menu.addAction("职位", lambda: page.load(QUrl("https://www.zhipin.com/web/geek/jobs?ka=header-jobs")))
        nav_menu.addAction("消息", lambda: page.load(QUrl("https://www.zhipin.com/web/geek/chat")))
        nav_btn.setMenu(nav_menu)

        url_input = QLineEdit()
        url_input.setPlaceholderText("输入网址...")

        def _normalize_and_navigate() -> None:
            raw = url_input.text().strip()
            if not raw:
                return
            if not raw.startswith(("http://", "https://", "ftp://", "file://")):
                raw = "https://" + raw
            page.load(QUrl(raw))

        back_btn.clicked.connect(view.back)
        forward_btn.clicked.connect(view.forward)
        refresh_btn.clicked.connect(view.reload)
        url_input.returnPressed.connect(_normalize_and_navigate)
        view.urlChanged.connect(lambda url: url_input.setText(url.toString()))
        page.loadFinished.connect(lambda _ok: url_input.setText(page.url().toString()))

        nav_layout = QHBoxLayout()
        nav_layout.setContentsMargins(4, 4, 4, 4)
        nav_layout.setSpacing(4)
        nav_layout.addWidget(back_btn)
        nav_layout.addWidget(forward_btn)
        nav_layout.addWidget(refresh_btn)
        nav_layout.addWidget(nav_btn)
        nav_layout.addWidget(url_input, 1)

        nav_widget = QWidget()
        nav_widget.setLayout(nav_layout)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(nav_widget)
        layout.addWidget(view, 1)
        self._tabs.addTab(container, name)

        self._account_tabs[account_id] = _AccountTab(
            account_id=account_id, name=name, profile=profile,
            view=view, page=page, # overlay=overlay,
            url_input=url_input,
            back_btn=back_btn,
            forward_btn=forward_btn,
            refresh_btn=refresh_btn,
            nav_btn=nav_btn,
        )

    def set_side_panel(self, top: QWidget, bottom: QWidget) -> None:
        """将控制面板和日志面板嵌入浏览器右侧（垂直分割）。"""
        self._side_splitter = QSplitter(Qt.Vertical)
        self._side_splitter.addWidget(top)
        self._side_splitter.addWidget(bottom)
        self._side_splitter.setStretchFactor(0, 0)
        self._side_splitter.setStretchFactor(1, 1)
        self._splitter.addWidget(self._side_splitter)
        self._splitter.setStretchFactor(0, 1)
        default_width = 200
        self._splitter.setSizes([self.width() - default_width, default_width])

    def _on_tab_changed(self, index: int) -> None:
        pass
        # log.debug("标签页切换到 index=%d", index)

    def add_account(self, acc: dict[str, Any]) -> None:
        """运行时新增账号 tab+profile。acc 需包含 id 和 name。"""
        if acc["id"] in self._account_tabs:
            raise ValueError(f"账号已加载: {acc['id']}")
        self._add_account_tab(acc)

    def remove_account(self, account_id: str) -> None:
        """移除 tab + 释放 in-memory profile/view/page。磁盘 profiles/<id>/ 保留。"""
        atab = self._account_tabs.pop(account_id, None)
        if atab is None:
            return
        container = atab.view.parent()
        idx = self._tabs.indexOf(container)
        if idx >= 0:
            self._tabs.removeTab(idx)
        atab.view.stop()
        atab.view.setPage(None)
        atab.page.deleteLater()
        atab.view.deleteLater()
        atab.profile.deleteLater()
        self._sessions.pop(account_id, None)
        container.deleteLater()

    def activate_account(self, account_id: str) -> None:
        """切换到指定账号的标签页。"""
        for idx, (aid, atab) in enumerate(self._account_tabs.items()):
            if aid == account_id:
                self._tabs.setCurrentIndex(idx)
                atab.view.setFocus()
                return
        log.warning("账号 %s 不存在", account_id)

    def update_tab_badge(self, account_id: str, count: int) -> None:
        """更新指定账号 tab 的未读消息角标和背景色。"""
        atab = self._account_tabs.get(account_id)
        if not atab:
            return
        if count == atab.unread_count:
            return
        atab.unread_count = count
        container = atab.view.parent()
        idx = self._tabs.indexOf(container)
        if idx < 0:
            return
        bar = self._tabs.tabBar()
        if count > 0:
            bar.setTabText(idx, f"{atab.name} ({count})")
            bar.setTabTextColor(idx, QColor("#E67E22"))
        else:
            bar.setTabText(idx, atab.name)
            bar.setTabTextColor(idx, bar.palette().windowText().color())

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

    def _on_page_loaded(self, account_id: str, ok: bool) -> None:
        """loadFinished 回调 — 记录加载状态，唤醒等待的协程。"""
        self._load_finished[account_id] = ok
        future = self._load_futures.get(account_id)
        if future and not future.done():
            future.set_result(ok)

    def load_url(self, account_id: str, url: str) -> None:
        """加载 URL 到指定账号。"""
        page = self.get_page(account_id)
        if page:
            self._load_finished.pop(account_id, None)
            page.load(QUrl(url))

    async def wait_loaded(self, account_id: str, timeout: float = 20.0) -> bool:
        """等待 loadFinished 信号，确保 JS_HELPER 已注入。"""
        page = self.get_page(account_id)
        if not page:
            return False

        # 已加载完成，直接返回
        if account_id in self._load_finished:
            return bool(self._load_finished[account_id])

        # 等待 loadFinished
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._load_futures[account_id] = future
        try:
            ok = await asyncio.wait_for(future, timeout=timeout)
            return bool(ok)
        except asyncio.TimeoutError:
            return False
        finally:
            self._load_futures.pop(account_id, None)


def get_browser_manager() -> BrowserManager | None:
    """模块级单例。"""
    global _manager
    return _manager


def _set_browser_manager(m: BrowserManager) -> None:
    global _manager
    _manager = m
