"""browser — QWebEngineView 浏览器管理，替代 server/ + extension/。"""

from bzauto.browser.manager import BrowserManager, get_browser_manager
from bzauto.browser.session import BrowserSession

__all__ = [
    "BrowserManager",
    "BrowserSession",
    "get_browser_manager",
]
