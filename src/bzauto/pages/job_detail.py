"""Boss直聘职位详情页面对象（选择器 + 操作方法）。"""
from __future__ import annotations

import asyncio
import logging

from bzauto.browser.session import BrowserSession
from bzauto.pages.base import BasePage

log = logging.getLogger("page.job_detail")


class BossJobDetailPage(BasePage):
    """职位详情页面对象。

    选择器基于实际 DOM 分析确认：
    - .btn-startchat: 立即沟通按钮
    - .job-sec-text: 职位描述正文
    - .detail-content-header h3: "职位描述" 标题
    """

    _LOADED_SELECTOR = ".btn-startchat"

    async def get_job_desc(self) -> str:
        """提取职位描述文本（.job-sec-text 的纯文本内容）。"""
        items = await self._session.find_all(
            select=".job-sec-text",
            project={"text": "@text"},
        )
        if items:
            return items[0].get("text", "").strip()
        return ""

    async def click_chat(self) -> None:
        """点击立即沟通按钮。"""
        await self._session.click_element(
            ".btn-startchat",
            post_sleep=1.5,
        )

    async def wait_jd_loaded(self, timeout: float = 20.0) -> bool:
        """等待 JD 文本容器加载完成。"""
        bbox = await self._wait_visible(".job-sec-text", timeout=timeout)
        return bbox is not None
