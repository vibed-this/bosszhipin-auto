"""UrgeFlow — 催促：对未回复的对话重新发送打招呼语。"""
from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Literal

from bzauto.browser.session import BrowserSession
from bzauto.config import get_config
from bzauto.models import ChatItem
from bzauto.models_doc import ConvDoc
from bzauto.pages.chat_list import CHAT_URL, BossChatListPage
# from bzauto.pages.job_detail import BossJobDetailPage
from bzauto.results import UrgeResult
from bzauto.storage import Storage

log = logging.getLogger("flow.urge")


@dataclass(frozen=True)
class _UrgeTarget:
    conv: ConvDoc
    kind: Literal["legacy", "delivered"]


class UrgeFlow:
    """催促流程：查找 DB 中需跟进的对话，重新发送招呼语。

    当前仅处理正在交流的目标：
    - legacy：我方最后发送、无平台状态、消息内容为空（直接重发）

    # delivered（已禁用）：「您好」招呼已送达未读且发送超过 7 天，先查职位详情是否仍在招聘，再重发
    """

    def __init__(self, page: BossChatListPage, session: BrowserSession, account_id: str, storage: Storage) -> None:
        self._page = page
        self._session = session
        self._account_id = account_id
        self._storage = storage
        # self._detail_page = BossJobDetailPage(session)

    async def run(self) -> UrgeResult:
        legacy = self._storage.conversations.list_unreplied(self._account_id)
        # delivered = self._storage.conversations.list_urge_delivered(self._account_id)
        targets = (
            [_UrgeTarget(conv=c, kind="legacy") for c in legacy]
            # + [_UrgeTarget(conv=c, kind="delivered") for c in delivered]
        )
        if not targets:
            log.info("无待催促对话: account=%s", self._account_id)
            return UrgeResult(skipped=True, total=0)

        log.info(
            "开始催促: account=%s total=%d (legacy=%d)",
            self._account_id,
            len(targets),
            len(legacy),
        )
        await self._session.ensure_tab(CHAT_URL)
        await self._session.activate()
        if not await self._page.wait_chat_list_ready():
            log.warning("聊天列表加载超时: account=%s", self._account_id)

        success = 0
        failed = 0
        skipped_stopped = 0

        for target in targets:
            try:
                if not await self._page.wait_chat_list_ready(timeout=10.0):
                    log.warning("聊天列表未就绪，跳过: %s·%s", target.conv.name, target.conv.company)
                    failed += 1
                    continue

                all_items = await self._page.get_chat_items()
                by_uid = {item.uniqueId: item for item in all_items if item.uniqueId}
                by_name = {f"{item.name}:{item.company}": item for item in all_items}

                uid, _ = self._resolve_chat_item(target.conv, by_uid, by_name)
                if not uid:
                    log.warning("未在页面找到对话: %s·%s", target.conv.name, target.conv.company)
                    failed += 1
                    continue

                # if target.kind == "delivered":
                #     job_url = self._job_detail_url(target.conv, match)
                #     if not job_url:
                #         log.warning(
                #             "无职位详情链接，跳过: %s·%s",
                #             target.conv.name,
                #             target.conv.company,
                #         )
                #         failed += 1
                #         continue
                #
                #     await self._session.ensure_tab(job_url)
                #     if not await self._detail_page.is_still_recruiting():
                #         status = await self._detail_page.get_job_status()
                #         log.info(
                #             "职位已停招，跳过催促: %s·%s status=%s",
                #             target.conv.name,
                #             target.conv.company,
                #             status,
                #         )
                #         await self._session.ensure_tab(CHAT_URL)
                #         skipped_stopped += 1
                #         continue
                #
                #     await self._session.ensure_tab(CHAT_URL)
                #     if not await self._page.wait_chat_list_ready():
                #         log.warning(
                #             "返回聊天页后列表未就绪: %s·%s",
                #             target.conv.name,
                #             target.conv.company,
                #         )
                #         failed += 1
                #         continue

                await self._page.click_chat_item(uid)
                await self._page.wait_conversation_selected(timeout=10)

                greeting = get_config().scrape.greeting
                if not greeting:
                    log.warning("招呼语为空，跳过发送: %s·%s", target.conv.name, target.conv.company)
                    failed += 1
                    continue

                await self._page.send_message(greeting)
                log.info("已催促: %s·%s kind=%s", target.conv.name, target.conv.company, target.kind)
                success += 1

                await asyncio.sleep(random.uniform(2.0, 4.0))

            except Exception as e:
                log.error("催促异常: %s·%s - %s", target.conv.name, target.conv.company, e)
                failed += 1

        log.info(
            "催促完成: account=%s success=%d failed=%d stopped=%d total=%d",
            self._account_id,
            success,
            failed,
            skipped_stopped,
            len(targets),
        )
        return UrgeResult(
            success=success,
            failed=failed,
            total=len(targets),
            skipped_stopped=skipped_stopped,
        )

    @staticmethod
    def _resolve_chat_item(
        conv: ConvDoc,
        by_uid: dict[str, ChatItem],
        by_name: dict[str, ChatItem],
    ) -> tuple[str | None, ChatItem | None]:
        if conv.unique_id and conv.unique_id in by_uid:
            return conv.unique_id, by_uid[conv.unique_id]
        key = f"{conv.name}:{conv.company}"
        match = by_name.get(key)
        if match and match.uniqueId:
            return match.uniqueId, match
        return None, None

    # def _job_detail_url(self, conv: ConvDoc, match: ChatItem | None) -> str:
    #     encrypt_job_id = conv.encrypt_job_id or (match.encryptJobId if match else "")
    #     if encrypt_job_id:
    #         return f"https://www.zhipin.com/job_detail/{encrypt_job_id}.html"
    #
    #     if conv.linked_job_id:
    #         job = self._storage.jobs.get(conv.linked_job_id)
    #         if job and job.href:
    #             href = job.href
    #             return href if href.startswith("http") else f"https://www.zhipin.com{href}"
    #
    #     if match and match.job_href:
    #         return match.job_href
    #     return ""