"""临时脚本：为数据库中已有的 jobs 逐个访问详情页，抓取 tags / experience / degree / job_desc 并写回。

用法示例:
    uv run python scripts/enrich_job_tags.py
    uv run python scripts/enrich_job_tags.py --limit 30
    uv run python scripts/enrich_job_tags.py --force --limit 100

注意:
- 会打开浏览器窗口，需要确保对应账号已登录（脚本会自动检查聊天页）。
- 运行前最好关闭 boss-ui，避免 profile 冲突。
- 默认会跳过“已有有效 tags”的职位；加 --force 可强制全部重抓。
- 每个职位处理前会重新查询 DB 状态，支持中断后安全续跑。
- 脚本会自动在 job 之间 sleep，避免请求过快。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
import sys
from typing import Any

import qasync
from PySide6.QtWidgets import QApplication

from bzauto.browser import BrowserManager
from bzauto.browser.manager import _set_browser_manager, shutdown_browser_manager
from bzauto.config import get_config
from bzauto.pages.chat_list import CHAT_URL
from bzauto.pages.job_detail import BossJobDetailPage
from bzauto.storage import Storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("enrich")


def _has_nonempty_tags(tags: list[str] | None) -> bool:
    """判断 tags 是否包含有效的非空标签。"""
    if not tags:
        return False
    return any(isinstance(t, str) and t.strip() for t in tags)


async def enrich_one(
    session: Any,
    detail_page: BossJobDetailPage,
    storage: Storage,
    job: Any,
    idx: int,
    total: int,
) -> bool:
    """抓取单个职位的 meta 并写回。返回是否成功。"""
    try:
        href = job.href
        full_url = href if href.startswith("http") else f"https://www.zhipin.com{href}"

        log.info("[%d/%d] 正在访问: %s — %s", idx, total, job.title, job.company)

        await session.ensure_tab(full_url, timeout=60)
        loaded = await detail_page.wait_jd_loaded(timeout=25)
        if not loaded:
            log.warning("  JD 未加载完成，跳过: %s", job.job_id)
            return False

        # 给页面一点时间加载动态内容（尤其是 tags）
        await asyncio.sleep(1.2)

        meta = await detail_page.get_job_meta()
        jd = await detail_page.get_job_desc()

        storage.jobs.update_meta(
            job.job_id,
            tags=meta.tags,
            job_desc=jd,
            experience=meta.experience,
            degree=meta.degree,
        )

        log.info(
            "  ✓ 已更新 tags=%d, exp=%r, deg=%r",
            len(meta.tags),
            meta.experience,
            meta.degree,
        )
        return True

    except Exception as e:
        log.error("  ✗ 处理失败 job_id=%s error=%s", job.job_id, e)
        return False


async def main_async(args: argparse.Namespace) -> int:
    storage = Storage()
    cfg = get_config()

    # 加载所有 job
    all_jobs = storage.jobs.list()
    if args.dispatch_status:
        all_jobs = [j for j in all_jobs if j.dispatch_status == args.dispatch_status]

    # 过滤：默认只处理还没有有效 tags 的
    if args.force:
        to_process = all_jobs[:]
    else:
        to_process = [j for j in all_jobs if not _has_nonempty_tags(j.tags)]

    if args.limit > 0:
        to_process = to_process[: args.limit]

    already_have_tags = len(all_jobs) - len(to_process) if not args.force else 0

    if not to_process:
        log.info("没有需要处理的职位（%d 条已有 tags，过滤后为空）。", already_have_tags)
        return 0

    log.info(
        "共发现 %d 条职位，其中 %d 条已有 tags，计划处理 %d 条（force=%s）",
        len(all_jobs), already_have_tags, len(to_process), args.force
    )

    # 准备浏览器（参考 test_job_detail.py 的做法）
    accounts = [{"id": a.id, "name": a.name} for a in cfg.accounts if a.enabled]
    if not any(a["id"] == args.account for a in accounts):
        accounts.insert(0, {"id": args.account, "name": args.account})

    log.info("使用 profiles_dir=%s", cfg.browser.profiles_dir)
    log.warning("注意: 建议先关闭 boss-ui 以避免 profile 冲突")

    bm: BrowserManager | None = None
    try:
        bm = BrowserManager(accounts, profiles_dir=cfg.browser.profiles_dir)
        _set_browser_manager(bm)
        bm.show()

        session = bm.get_session(args.account)

        # 登录态检查（必须能进聊天页）
        await session.ensure_tab(CHAT_URL, timeout=90)
        await session.activate()
        await asyncio.sleep(6)
        current = await session.eval_js("location.href")
        log.info("当前 URL: %s", current)
        if "chat" not in str(current).lower():
            log.error("未检测到登录态（不在聊天页）。请先手动登录账号 %s 后再运行。", args.account)
            return 1
        log.info("登录态确认 OK，开始逐个抓取详情...")

        detail_page = BossJobDetailPage(session)

        success = 0
        failed = 0
        skipped_existing = 0

        for i, job in enumerate(to_process, 1):
            # 关键：每次处理前重新从数据库读取最新状态，确保“已有 tags”的职位被跳过
            # 这使得脚本在中断后重跑、或长时间运行中更安全（支持断点续跑）
            latest = storage.jobs.get(job.job_id)
            if latest and not args.force and _has_nonempty_tags(latest.tags):
                log.info("[%d/%d] 已有 tags，跳过: %s — %s", i, len(to_process), job.title, job.company)
                skipped_existing += 1
                continue

            ok = await enrich_one(session, detail_page, storage, job, i, len(to_process))
            if ok:
                success += 1
            else:
                failed += 1

            # 礼貌性 sleep，防止被风控
            if i < len(to_process):
                delay = random.uniform(args.delay_min, args.delay_max)
                await asyncio.sleep(delay)

        log.info("=" * 50)
        log.info(
            "处理完成: 成功 %d，失败 %d，跳过(已有tags) %d",
            success, failed, skipped_existing
        )
        return 0 if failed == 0 else 1

    except KeyboardInterrupt:
        log.warning("用户中断")
        return 130
    except Exception:
        log.exception("脚本异常")
        return 1
    finally:
        if bm is not None:
            try:
                await shutdown_browser_manager()
            except Exception:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="为已有 jobs 回填 tags / 详情元数据")
    parser.add_argument("--force", action="store_true", help="强制处理所有职位（忽略已有 tags）")
    parser.add_argument("--limit", type=int, default=0, help="最多处理多少条（0=不限）")
    parser.add_argument("--account", default="main", help="使用的账号 ID（默认 main）")
    parser.add_argument("--dispatch-status", default="", help="只处理特定 dispatch_status 的职位")
    parser.add_argument("--delay-min", type=float, default=1.8, help="job 之间最小 sleep 秒数")
    parser.add_argument("--delay-max", type=float, default=3.5, help="job 之间最大 sleep 秒数")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    exit_code = 1
    with loop:
        exit_code = loop.run_until_complete(main_async(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
