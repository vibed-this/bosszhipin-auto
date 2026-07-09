"""test_job_detail.py — 验证 job_detail page API + clean_boss_detail_text"""
from __future__ import annotations

import asyncio
import logging
import sys

import qasync
from PySide6.QtWidgets import QApplication

from bzauto.browser import BrowserManager
from bzauto.browser.manager import _set_browser_manager, shutdown_browser_manager
from bzauto.config import get_config
from bzauto.models import clean_boss_detail_text
from bzauto.pages.chat_list import _CHAT_URL
from bzauto.pages.job_detail import BossJobDetailPage

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("test")

JOB_URLS = [
    {
        "url": "https://www.zhipin.com/job_detail/2b299fbbf2736aba1XZ70t-8FVJT.html",
        "company": "数里行间",
        "desc_prefix": "岗位",
        "min_desc_len": 50,
    },
    {
        "url": "https://www.zhipin.com/job_detail/5a42321254fe02130nF529q4F1tQ.html",
        "company": "元始数据",
        "desc_prefix": "岗位",
        "min_desc_len": 500,
    },
]

CLEAN_CASES: list[tuple[str, str]] = [
    ("负kanzhun责", "负责"),
    ("职kanzhun位描述", "职位描述"),
    ("岗BOSS直聘位需求", "岗位需求"),
    ("岗位直聘职责", "岗位职责"),
    ("负kanzhun责AI直聘开发", "负责AI直聘开发"),
    ("负责直聘开发", "负责开发"),
    ("BOSS直聘岗位职责1、负责", "BOSS直聘岗位职责1、负责"),
    ("a   b\tc", "a b c"),
    ("line1\n\n\n\nline2", "line1\n\nline2"),
    ("", ""),
    ("kanzhun", ""),
    ("  前后空白  ", "前后空白"),
    ("精通HTML5、CSS3", "精通HTML5、CSS3"),
    ("岗kanzhun位kanzhun需kanzhun求", "岗位需求"),
    ("直聘岗位需求", "岗位需求"),
    ("岗boss位需求", "岗位需求"),
    ("岗Boss位需求", "岗位需求"),
    ("负boss责开boss发", "负责开发"),
]


def test_clean_boss_detail_text() -> None:
    log.info("=" * 40)
    log.info("单元测试: clean_boss_detail_text (%d cases)", len(CLEAN_CASES))
    for raw, expected in CLEAN_CASES:
        got = clean_boss_detail_text(raw)
        assert got == expected, f"clean({raw!r}) => {got!r}, want {expected!r}"
        log.info("  ✓ %r -> %r", raw[:40], got[:40] if got else "")
    log.info("✓ clean_boss_detail_text 全部通过")


async def test_job_page(page: BossJobDetailPage, case: dict) -> None:
    url = case["url"]
    log.info("=" * 40)
    log.info("live: %s (%s)", case["company"], url)

    session = page._session
    await session.ensure_tab(url, timeout=90)
    await session.activate()
    assert await page.wait_jd_loaded(timeout=30), f"JD 未加载: {url}"
    await asyncio.sleep(2)

    status = await page.get_job_status()
    log.info("  get_job_status: %s", status)
    assert status, "招聘状态为空"

    meta = await page.get_job_meta()
    log.info(
        "  get_job_meta: title=%s salary=%s loc=%s exp=%s deg=%s tags=%d",
        meta.title, meta.salary, meta.location, meta.experience, meta.degree, len(meta.tags),
    )
    assert meta.title
    assert meta.salary and meta.salary != "元", f"薪资未完整加载: {meta.salary!r}"
    assert "kanzhun" not in meta.title

    desc = await page.get_job_desc()
    log.info("  get_job_desc: len=%d preview=%s", len(desc), desc[:100])
    assert len(desc) >= case["min_desc_len"]
    assert "kanzhun" not in desc
    assert "BOSS直聘" not in desc
    assert desc.startswith(case["desc_prefix"])

    intro = await page.get_company_intro()
    log.info("  get_company_intro: len=%d preview=%s", len(intro), intro[:100])
    assert len(intro) > 20
    assert "kanzhun" not in intro
    assert desc != intro, "JD 与公司介绍不应相同"

    if case["company"] == "元始数据":
        assert "VOC.AI" not in desc
        assert any(k in desc for k in ("职责", "要求", "任职", "优势"))

    log.info("✓ live 通过: %s", case["company"])


async def main() -> int:
    bm: BrowserManager | None = None
    try:
        test_clean_boss_detail_text()

        cfg = get_config()
        accounts = [{"id": a.id, "name": a.name} for a in cfg.accounts if a.enabled]
        if not any(a["id"] == "main" for a in accounts):
            accounts.insert(0, {"id": "main", "name": "main"})
        log.info("使用 profiles_dir=%s", cfg.browser.profiles_dir)
        log.info("注意: 运行前请关闭 boss-ui，避免 profile 冲突")

        bm = BrowserManager(accounts, profiles_dir=cfg.browser.profiles_dir)
        _set_browser_manager(bm)
        bm.show()
        session = bm.get_session("main")

        # 与 test_chat_page 一致：用聊天页 URL 判断登录态
        await session.ensure_tab(_CHAT_URL, timeout=60)
        await session.activate()
        await asyncio.sleep(8)
        url = await session.eval_js("location.href")
        log.info("登录检查 URL: %s", url)
        if "chat" not in str(url):
            log.error("未进入聊天页，请先登录 main 账号（或关闭 boss-ui 后重试）")
            return 1
        log.info("已登录，开始 live 测试")

        page = BossJobDetailPage(session)
        for case in JOB_URLS:
            await test_job_page(page, case)

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