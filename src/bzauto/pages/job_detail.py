"""Boss直聘职位详情页面对象（选择器 + 操作方法）。"""
from __future__ import annotations

import asyncio
import logging

from bzauto.browser.session import BrowserSession
from bzauto.models import JobDetailMeta, clean_boss_detail_text
from bzauto.pages.base import BasePage

log = logging.getLogger("page.job_detail")


class BossJobDetailPage(BasePage):
    """职位详情页面对象。

    选择器基于实际 DOM 分析确认（服务端渲染，非 Vue data）：
    - .job-status span: 平台招聘状态（招聘中 / 最新 / 停止招聘 等）
    - .job-detail-section:not(.job-detail-company) .job-sec-text: 职位描述
    - .job-detail-section.job-detail-company .job-sec-text: 公司介绍
    - .btn-startchat: 立即沟通按钮
    """

    _LOADED_SELECTOR = ".btn-startchat"
    _JOB_STATUS = ".job-status span"
    _STOP_BANNER = ".job-invalid, .job-stop, .position-stop, .job-closed"
    _JOB_DESC = ".job-detail-section:not(.job-detail-company) .job-sec-text"
    _COMPANY_INTRO = ".job-detail-section.job-detail-company .job-sec-text"

    def __init__(self, session: BrowserSession) -> None:
        super().__init__(session)
        self._session: BrowserSession = session

    async def _get_section_text(self, select: str) -> str:
        items = await self._session.find_all(
            select=select,
            project={"text": "@text"},
        )
        if items:
            return clean_boss_detail_text(items[0].get("text", ""))
        return ""

    async def get_job_status(self) -> str:
        """读取 Boss 平台职位招聘状态（服务端渲染 DOM，非 Vue data）。

        常见返回值：``招聘中``、``最新``、``停止招聘`` 等。
        """
        items = await self._session.find_all(
            select=self._JOB_STATUS,
            project={"text": "@text"},
        )
        if items:
            text = items[0].get("text", "").strip()
            if text:
                return text

        banners = await self._session.find_all(
            select=self._STOP_BANNER,
            project={"text": "@text"},
        )
        if banners:
            return banners[0].get("text", "").strip()
        return ""

    async def is_still_recruiting(self) -> bool:
        """职位是否仍在招聘（status 文本不包含「停止」）。"""
        status = await self.get_job_status()
        return "停止" not in status

    async def get_job_desc(self) -> str:
        """提取职位描述正文（排除公司介绍区块）。"""
        return await self._get_section_text(self._JOB_DESC)

    async def get_company_intro(self) -> str:
        """提取公司介绍正文。"""
        return await self._get_section_text(self._COMPANY_INTRO)

    async def get_job_meta(self) -> JobDetailMeta:
        """读取详情页 banner 区元数据（职位名、薪资、地点、经验、学历、福利标签）。"""
        title = await self._session.find_one(
            select=".name h1",
            project={"text": "@text"},
        )
        salary = await self._session.find_one(
            select=".salary",
            project={"text": "@text"},
        )
        location = await self._session.find_one(
            select=".text-city",
            project={"text": "@text"},
        )
        experience = await self._session.find_one(
            select=".text-experiece, .text-experience",
            project={"text": "@text"},
        )
        degree = await self._session.find_one(
            select=".text-degree",
            project={"text": "@text"},
        )
        tag_items = await self._session.find_all(
            select=".job-tags span",
            project={"text": "@text"},
        )

        tags: list[str] = []
        seen: set[str] = set()
        for item in tag_items:
            tag = clean_boss_detail_text(item.get("text", ""))
            if tag and tag not in seen:
                seen.add(tag)
                tags.append(tag)

        salary_text = clean_boss_detail_text((salary or {}).get("text", ""))
        if len(salary_text) < 2 or salary_text == "元":
            for _ in range(10):
                fallback = await self._session.eval_js(
                    "window._jobInfo && window._jobInfo.job_salary ? window._jobInfo.job_salary : ''"
                )
                fallback_text = clean_boss_detail_text(str(fallback or ""))
                if len(fallback_text) >= 2 and fallback_text != "元":
                    salary_text = fallback_text
                    break
                await asyncio.sleep(0.5)

        is_headhunter = await self.is_headhunter()

        return JobDetailMeta(
            title=clean_boss_detail_text((title or {}).get("text", "")),
            salary=salary_text,
            location=clean_boss_detail_text((location or {}).get("text", "")),
            experience=clean_boss_detail_text((experience or {}).get("text", "")),
            degree=clean_boss_detail_text((degree or {}).get("text", "")),
            tags=tags,
            is_headhunter=is_headhunter,
        )

    async def is_headhunter(self) -> bool:
        """通过招聘方身份信息判断是否为猎头职位。"""
        items = await self._session.find_all(
            select=".boss-info-attr",
            project={"text": "@text"},
        )
        if items:
            text = items[0].get("text", "")
            return "猎头" in text
        return False

    async def click_chat(self) -> None:
        """点击立即沟通按钮。"""
        await self._session.click_element(
            ".btn-startchat",
            post_sleep=1.5,
        )

    async def wait_jd_loaded(self, timeout: float = 20.0) -> bool:
        """等待 JD 文本容器加载完成。"""
        bbox = await self._wait_visible(self._JOB_DESC, timeout=timeout)
        return bbox is not None