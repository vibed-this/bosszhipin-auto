"""test_chat_page.py — 验证 chat_list page 新增 API"""
from __future__ import annotations

import asyncio
import logging
import sys

import qasync
from PySide6.QtWidgets import QApplication

from bzauto.browser import BrowserManager
from bzauto.browser.manager import _set_browser_manager, shutdown_browser_manager
from bzauto.pages.chat_list import BossChatListPage, _CHAT_URL

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("test")


async def main() -> int:
    bm: BrowserManager | None = None
    try:
        bm = BrowserManager([{"id": "main", "name": "main"}])
        _set_browser_manager(bm)
        bm.show()

        session = bm.get_session("main")
        page = BossChatListPage(session)

        await session.ensure_tab(_CHAT_URL, timeout=60)
        await session.activate()
        log.info("等待页面加载...")
        await asyncio.sleep(8)

        url = await session.eval_js("location.href")
        log.info("当前 URL: %s", url)
        if "chat" not in str(url):
            log.error("未进入聊天页，请先登录后重试")
            return 1

        items = await page.get_chat_items(limit=5)
        log.info("get_chat_items: %d 条", len(items))
        assert items, "列表为空"
        sample = items[0]
        log.info(
            "首条: name=%s company=%s jobId=%s encryptJobId=%s job_href=%s",
            sample.name, sample.company, sample.jobId, sample.encryptJobId, sample.job_href,
        )
        assert sample.encryptJobId
        assert sample.job_href.startswith("https://www.zhipin.com/job_detail/")
        log.info("✓ get_chat_items")

        await page.click_chat_item(sample.uniqueId)
        assert await page.is_conversation_selected()
        log.info("✓ click_chat_item (%s)", sample.uniqueId)

        boss = await page.get_conversation_boss()
        assert boss and (boss.encryptJobId or boss.jobId)
        log.info(
            "boss: jobName=%s positionName=%s location=%s job_href=%s",
            boss.jobName, boss.positionName, boss.locationName, boss.job_href,
        )
        log.info("✓ get_conversation_boss")

        meta = await page.get_conversation_meta()
        assert meta and meta.pageSize > 0
        log.info("meta: page=%s pageSize=%s msgMinId=%s isToTop=%s",
                 meta.page, meta.pageSize, meta.msgMinId, meta.isToTop)
        log.info("✓ get_conversation_meta")

        msgs = await page.get_loaded_messages()
        log.info("get_loaded_messages (首条会话): %d 条", len(msgs))
        assert msgs and all(m.mid for m in msgs)
        for m in msgs[:2]:
            log.info("  mid=%s isSelf=%s text=%s", m.mid, m.isSelf, (m.text or "")[:50])
        log.info("✓ get_loaded_messages (首条)")

        all_items = await page.get_chat_items(limit=80)
        multi = next((i for i in all_items if not i.lastMsg or i.sender == "other"), None)
        if multi and multi.uniqueId != sample.uniqueId:
            await page.click_chat_item(multi.uniqueId)
            await asyncio.sleep(2)
            msgs2 = await page.get_loaded_messages()
            log.info("get_loaded_messages (%s): %d 条", multi.name, len(msgs2))
            assert msgs2, "多消息会话读取失败"
            log.info("✓ get_loaded_messages (多消息会话)")

        log.info("=" * 40)
        log.info("全部测试通过")
        return 0
    except Exception:
        log.exception("测试失败")
        return 1
    finally:
        await shutdown_browser_manager()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    exit_code = 1
    with loop:
        exit_code = loop.run_until_complete(main())
    sys.exit(exit_code)