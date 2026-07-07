"""TinyDB 封装 — jobs / conversations / accounts / meta 四张表。"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Any

from tinydb import Query, TinyDB

from bzauto.config import get_config
from bzauto.enums import ConvStatus, DispatchStatus
from bzauto.models import make_conv_id, make_job_id
from bzauto.models_doc import AccountDoc, ConvDoc, JobDoc, RunDoc

log = logging.getLogger("boss.storage")


def _now_iso() -> str:
    return datetime.datetime.now().isoformat()


def _today_str() -> str:
    return datetime.date.today().isoformat()


class Storage:
    """TinyDB 持久化存储。

    :ivar _db: TinyDB 实例
    :ivar _jobs: jobs 表
    :ivar _conversations: conversations 表
    :ivar _accounts: accounts 表
    :ivar _meta: meta 表（键值存储）
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        """初始化 Storage。

        :param db_path: 数据库文件路径，None 则从配置读取
        """
        resolved: str | Path = db_path if db_path is not None else get_config().storage.db_path
        path = Path(resolved)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = TinyDB(str(path), indent=2, ensure_ascii=False, sort_keys=True, encoding="utf-8")
        self._jobs = self._db.table("jobs")
        self._conversations = self._db.table("conversations")
        self._accounts = self._db.table("accounts")
        self._meta = self._db.table("meta")
        self._runs = self._db.table("schedule_runs")
        self._JobQ = Query()
        self._ConvQ = Query()
        self._AccountQ = Query()
        self._MetaQ = Query()
        self._RunQ = Query()
        log.info("数据库初始化: %s", path)

    # ── Jobs ──

    def upsert_job(self, doc: JobDoc) -> int:
        """插入或更新一条职位记录。

        :param doc: 职位文档
        :returns: TinyDB doc_id
        """
        existing = self._jobs.get(self._JobQ.job_id == doc.job_id)
        now = _now_iso()
        if existing:
            update_data = doc.model_dump(exclude={"job_id"}, exclude_none=True)
            # 只更新非空字段（保持 DB 整洁）
            update_data = {k: v for k, v in update_data.items() if v != ""}
            update_data["last_updated"] = now
            self._jobs.update(update_data, self._JobQ.job_id == doc.job_id)
            log.debug("更新 job: %s", doc.job_id)
            return existing.doc_id
        else:
            data = doc.model_dump(exclude_none=True)
            data["job_id"] = data.get("job_id") or make_job_id(doc.href)
            data.setdefault("last_updated", now)
            doc_id = self._jobs.insert(data)
            log.debug("插入 job: %s", doc.job_id)
            return doc_id

    def get_pending_jobs(self, limit: int = 50) -> list[JobDoc]:
        """获取待派发职位列表。

        :param limit: 最大返回条数
        :returns: 待派发职位文档列表
        """
        results = self._jobs.search(self._JobQ.dispatch_status == DispatchStatus.PENDING)
        return [JobDoc(**r) for r in results[:limit]]  # type: ignore[arg-type]

    def count_jobs_today(self) -> int:
        """统计今日更新的职位总数（近似今日采集/更新量）。

        :returns: 当日更新职位数
        """
        today = _today_str()
        return len(self._jobs.search(
            self._JobQ.last_updated.test(lambda v: v.startswith(today) if v else False),
        ))

    def count_dispatched_today(self) -> int:
        """统计今日成功投递的职位数。

        :returns: 当日成功投递数
        """
        today = _today_str()
        return len(self._jobs.search(
            (self._JobQ.dispatch_status == DispatchStatus.SUCCESS) &
            (self._JobQ.applied_at.test(lambda v: v.startswith(today) if v else False)),
        ))

    def count_pending_jobs(self) -> int:
        """统计待派发职位数量。"""
        return len(self._jobs.search(self._JobQ.dispatch_status == DispatchStatus.PENDING))

    def get_job(self, job_id: str) -> JobDoc | None:
        """按 job_id 查询职位。

        :param job_id: 职位标识
        :returns: 职位文档或 None
        """
        raw = self._jobs.get(self._JobQ.job_id == job_id)
        return JobDoc(**raw) if raw else None  # type: ignore[arg-type]

    def claim_job(self, job_id: str, account_id: str) -> bool:
        """原子领取一个 job（仅 PENDING 状态可领取）。

        :param job_id: 职位标识
        :param account_id: 账号 ID
        :returns: 是否领取成功
        """
        now = _now_iso()
        result = self._jobs.update(
            {
                "dispatch_status": DispatchStatus.CLAIMED,
                "dispatched_by": account_id,
                "dispatched_at": now,
                "last_updated": now,
            },
            (self._JobQ.job_id == job_id) & (self._JobQ.dispatch_status == DispatchStatus.PENDING),
        )
        claimed = len(result) > 0
        if claimed:
            log.info("领取 job: %s -> account=%s", job_id, account_id)
        return claimed

    def mark_job_success(self, job_id: str) -> None:
        """标记 job 沟通成功。

        :param job_id: 职位标识
        """
        now = _now_iso()
        self._jobs.update(
            {
                "dispatch_status": DispatchStatus.SUCCESS,
                "status": "已沟通",
                "applied_at": now,
                "last_updated": now,
            },
            self._JobQ.job_id == job_id,
        )
        log.debug("job 成功: %s", job_id)

    def mark_job_failed(self, job_id: str) -> None:
        """标记 job 沟通失败。

        :param job_id: 职位标识
        """
        now = _now_iso()
        self._jobs.update(
            {
                "dispatch_status": DispatchStatus.FAILED,
                "last_updated": now,
            },
            self._JobQ.job_id == job_id,
        )
        log.debug("job 失败: %s", job_id)

    def count_stale_claims(self, timeout_minutes: int = 30) -> int:
        """统计超时未完成的 claim 数量（不释放）。

        :param timeout_minutes: 超时分钟数
        :returns: 超时 claim 数量
        """
        now = datetime.datetime.now()
        count = 0
        for doc in self._jobs.search(self._JobQ.dispatch_status == DispatchStatus.CLAIMED):
            dispatched_str = doc.get("dispatched_at", "")
            try:
                dispatched = datetime.datetime.fromisoformat(dispatched_str)
            except (ValueError, TypeError):
                continue
            if (now - dispatched).total_seconds() > timeout_minutes * 60:
                count += 1
        return count

    def release_stale_claims(self, timeout_minutes: int = 30) -> int:
        """释放超时未完成的 claim。

        :param timeout_minutes: 超时分钟数
        :returns: 释放的 claim 数量
        """
        now = datetime.datetime.now()
        count = 0
        for doc in self._jobs.search(self._JobQ.dispatch_status == DispatchStatus.CLAIMED):
            dispatched_str = doc.get("dispatched_at", "")
            try:
                dispatched = datetime.datetime.fromisoformat(dispatched_str)
            except (ValueError, TypeError):
                continue
            if (now - dispatched).total_seconds() > timeout_minutes * 60:
                self._jobs.update(
                    {"dispatch_status": DispatchStatus.PENDING, "last_updated": _now_iso()},
                    doc.doc_id,  # type: ignore[arg-type]
                )
                count += 1
        if count:
            log.info("释放超时 claim: %d 条", count)
        return count

    def update_job_status(self, job_id: str, status: str) -> None:
        """更新职位的业务状态。

        :param job_id: 职位标识
        :param status: 新状态文本
        """
        self._jobs.update({"status": status, "last_updated": _now_iso()}, self._JobQ.job_id == job_id)

    def search_jobs(self, keyword: str = "", status: str = "") -> list[JobDoc]:
        """搜索职位记录。

        :param keyword: 搜索关键词（匹配 title / company）
        :param status: 按状态筛选
        :returns: 匹配的职位文档列表
        """
        cond = self._JobQ.job_id != ""  # always true
        if keyword:
            cond &= (self._JobQ.title.test(lambda v: keyword.lower() in (v or "").lower())) | \
                    (self._JobQ.company.test(lambda v: keyword.lower() in (v or "").lower()))
        if status:
            cond &= self._JobQ.status == status
        return [JobDoc(**r) for r in self._jobs.search(cond)]  # type: ignore[arg-type]

    def delete_job(self, job_id: str) -> None:
        """删除职位记录。

        :param job_id: 职位标识
        """
        self._jobs.remove(self._JobQ.job_id == job_id)
        log.info("删除 job: %s", job_id)

    def update_job_note(self, job_id: str, note: str) -> None:
        """更新职位备注。

        :param job_id: 职位标识
        :param note: 备注文本
        """
        self._jobs.update({"note": note, "last_updated": _now_iso()}, self._JobQ.job_id == job_id)

    # ── Conversations ──

    def upsert_conversation(self, doc: ConvDoc) -> bool:
        """插入或更新一条对话记录。

        :param doc: 对话文档
        :returns: True 表示新建，False 表示更新
        """
        cid = doc.conv_id or make_conv_id(doc.account, doc.name, doc.company)
        existing = self._conversations.get(
            (self._ConvQ.conv_id == cid) & (self._ConvQ.account == doc.account),
        )
        now = _now_iso()
        if existing:
            update_data = doc.model_dump(exclude={"conv_id", "account"}, exclude_none=True)
            update_data = {k: v for k, v in update_data.items() if v != ""}
            update_data["last_updated"] = now
            self._conversations.update(
                update_data,
                (self._ConvQ.conv_id == cid) & (self._ConvQ.account == doc.account),
            )
            return False
        else:
            data = doc.model_dump(exclude_none=True)
            data["conv_id"] = cid
            data.setdefault("first_seen_at", now)
            data.setdefault("last_updated", now)
            self._conversations.insert(data)
            return True

    def update_conv_note(self, conv_id: str, account: str, note: str) -> None:
        """更新对话备注。

        :param conv_id: 对话标识
        :param account: 账号 ID
        :param note: 备注文本
        """
        self._conversations.update(
            {"note": note, "last_updated": _now_iso()},
            (self._ConvQ.conv_id == conv_id) & (self._ConvQ.account == account),
        )

    def update_conv_status(self, conv_id: str, account: str, status: str) -> None:
        """更新对话业务状态。

        :param conv_id: 对话标识
        :param account: 账号 ID
        :param status: 新状态文本
        """
        self._conversations.update(
            {"status": status, "status_changed_at": _now_iso(), "last_updated": _now_iso()},
            (self._ConvQ.conv_id == conv_id) & (self._ConvQ.account == account),
        )

    def get_conversations(self, account: str = "", status: str = "") -> list[ConvDoc]:
        """查询对话记录。

        :param account: 按账号筛选
        :param status: 按状态筛选
        :returns: 对话文档列表
        """
        cond = self._ConvQ.conv_id != ""
        if account:
            cond &= self._ConvQ.account == account
        if status:
            cond &= self._ConvQ.status == status
        return [ConvDoc(**r) for r in self._conversations.search(cond)]  # type: ignore[arg-type]

    def get_conversation(self, conv_id: str, account: str = "") -> ConvDoc | None:
        """按 conv_id 查询单条对话。

        :param conv_id: 对话 ID
        :param account: 账号 ID
        :returns: ConvDoc 或 None
        """
        cond = self._ConvQ.conv_id == conv_id
        if account:
            cond &= self._ConvQ.account == account
        results = self._conversations.search(cond)
        return ConvDoc(**results[0]) if results else None

    def search_conversations(self, keyword: str = "", status: str = "", account: str = "") -> list[ConvDoc]:
        """搜索对话记录。

        :param keyword: 搜索关键词（匹配 name / company）
        :param status: 按状态筛选
        :param account: 按账号筛选
        :returns: 对话文档列表
        """
        cond = self._ConvQ.conv_id != ""
        if keyword:
            cond &= (self._ConvQ.name.test(lambda v: keyword.lower() in (v or "").lower())) | \
                    (self._ConvQ.company.test(lambda v: keyword.lower() in (v or "").lower()))
        if status:
            cond &= self._ConvQ.status == status
        if account:
            cond &= self._ConvQ.account == account
        return [ConvDoc(**r) for r in self._conversations.search(cond)]  # type: ignore[arg-type]

    def delete_conversation(self, conv_id: str, account: str) -> None:
        """删除对话记录。

        :param conv_id: 对话标识
        :param account: 账号 ID
        """
        self._conversations.remove(
            (self._ConvQ.conv_id == conv_id) & (self._ConvQ.account == account),
        )
        log.info("删除对话: conv_id=%s account=%s", conv_id, account)

    def mark_deleted(self, conv_id: str, account: str) -> None:
        """标记对话为已删除。

        :param conv_id: 对话标识
        :param account: 账号 ID
        """
        self._conversations.update(
            {"status": ConvStatus.CLOSED, "status_changed_at": _now_iso(), "last_updated": _now_iso()},
            (self._ConvQ.conv_id == conv_id) & (self._ConvQ.account == account),
        )

    def get_conversations_by_status(self, status: str, account: str) -> list[ConvDoc]:
        """按状态查询对话。

        :param status: 状态文本
        :param account: 账号 ID
        :returns: 对话文档列表
        """
        cond = (self._ConvQ.status == status) & (self._ConvQ.account == account)
        return [ConvDoc(**r) for r in self._conversations.search(cond)]  # type: ignore[arg-type]

    # ── Accounts ──

    def get_account(self, account_id: str) -> AccountDoc | None:
        """查询账号。

        :param account_id: 账号 ID
        :returns: 账号文档或 None
        """
        raw = self._accounts.get(self._AccountQ.account_id == account_id)
        return AccountDoc(**raw) if raw else None  # type: ignore[arg-type]

    def get_all_accounts(self) -> list[AccountDoc]:
        """获取全部账号。"""
        return [AccountDoc(**r) for r in self._accounts.all()]  # type: ignore[arg-type]

    def get_enabled_accounts(self) -> list[AccountDoc]:
        """获取已启用账号列表（含当日配额重置检查）。

        从配置读取账号列表，从 DB 获取当日计数，
        自动处理跨日重置（last_reset_date != today 时 daily_count 归零）。

        :returns: 已启用账号文档列表
        """
        from bzauto.config import get_config
        cfg = get_config()
        result: list[AccountDoc] = []
        for acc_cfg in cfg.accounts:
            if not acc_cfg.enabled:
                continue
            db_acc = self._accounts.get(self._AccountQ.account_id == acc_cfg.id)
            daily_count: int
            last_reset: str
            if db_acc:
                daily_count = db_acc.get("daily_count", 0)
                last_reset = db_acc.get("last_reset_date", "")
                if last_reset != _today_str():
                    daily_count = 0
            else:
                daily_count = 0
                last_reset = ""
            doc = AccountDoc(
                account_id=acc_cfg.id,
                name=acc_cfg.name,
                daily_count=daily_count,
                daily_limit=acc_cfg.daily_limit,
                last_reset_date=_today_str(),
                enabled=True,
                role=acc_cfg.role,
            )
            result.append(doc)
        return result

    def get_remaining_quota(self, account_id: str) -> int:
        """获取账号当日剩余配额。

        :param account_id: 账号 ID
        :returns: 剩余可投递次数
        """
        account = self._accounts.get(self._AccountQ.account_id == account_id)
        if account is None:
            return 0
        daily_limit = account.get("daily_limit", 150)
        daily_count = account.get("daily_count", 0)
        last_reset = account.get("last_reset_date", "")
        if last_reset != _today_str():
            daily_count = 0
            self._accounts.update(
                {"daily_count": 0, "last_reset_date": _today_str()},
                self._AccountQ.account_id == account_id,
            )
        return max(0, daily_limit - daily_count)

    def increment_daily_count(self, account_id: str, n: int = 1) -> None:
        """增加账号当日计数。

        :param account_id: 账号 ID
        :param n: 增量（默认 1）
        """
        account = self._accounts.get(self._AccountQ.account_id == account_id)
        if account is None:
            from bzauto.config import get_config
            cfg_accounts = get_config().accounts
            limit = 150
            name = account_id
            for a in cfg_accounts:
                if a.id == account_id:
                    limit = a.daily_limit
                    name = a.name
                    break
            self._accounts.insert({
                "account_id": account_id,
                "name": name,
                "daily_count": n,
                "daily_limit": limit,
                "last_reset_date": _today_str(),
                "enabled": True,
            })
        else:
            last_reset = account.get("last_reset_date", "")
            count = account.get("daily_count", 0)
            if last_reset != _today_str():
                count = 0
            self._accounts.update(
                {
                    "daily_count": count + n,
                    "last_reset_date": _today_str(),
                },
                self._AccountQ.account_id == account_id,
            )

    def reset_daily_count(self, account_id: str) -> None:
        """重置账号当日计数为 0。

        :param account_id: 账号 ID
        """
        self._accounts.update(
            {"daily_count": 0, "last_reset_date": _today_str()},
            self._AccountQ.account_id == account_id,
        )

    def reset_daily_counts_if_new_day(self) -> None:
        """检查并重置所有账号的跨日计数。"""
        today = _today_str()
        for doc in self._accounts.all():
            if doc.get("last_reset_date") != today:
                self._accounts.update(
                    {"daily_count": 0, "last_reset_date": today},
                    doc.doc_id,  # type: ignore[arg-type]
                )
        log.info("每日计数已检查/重置")

    def set_daily_count_maxed(self, account_id: str) -> None:
        """保持当日计数不变（触发跨日检查的轻量操作）。

        :param account_id: 账号 ID
        """
        self.increment_daily_count(account_id, 0)

    def set_account_daily_limit(self, account_id: str, limit: int) -> None:
        """设置账号每日上限。

        :param account_id: 账号 ID
        :param limit: 上限值
        """
        self._accounts.upsert(
            {"daily_limit": limit},
            self._AccountQ.account_id == account_id,
        )

    # ── Schedule Runs ──

    def insert_run(self, doc: RunDoc) -> int:
        """插入一条调度执行记录。

        :param doc: 执行记录文档
        :returns: TinyDB doc_id
        """
        data = doc.model_dump(exclude_none=True)
        return self._runs.insert(data)

    def get_recent_runs(self, limit: int = 50) -> list[RunDoc]:
        """获取最近执行记录（按 started_at 倒序）。

        :param limit: 最大返回条数
        :returns: 执行记录文档列表
        """
        docs = self._runs.all()
        docs.sort(key=lambda d: d.get("started_at", ""), reverse=True)
        return [RunDoc(**r) for r in docs[:limit]]  # type: ignore[arg-type]

    def get_runs_today(self) -> list[RunDoc]:
        """获取今日执行记录。

        :returns: 今日执行记录列表
        """
        today = _today_str()
        return [RunDoc(**r) for r in self._runs.search(
            self._RunQ.started_at.test(lambda v: v.startswith(today) if v else False),
        )]  # type: ignore[arg-type]

    def purge_old_runs(self, days: int = 30) -> int:
        """清理指定天数之前的执行记录。

        :param days: 保留天数（默认 30）
        :returns: 删除的记录数
        """
        cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
        removed = self._runs.remove(self._RunQ.started_at < cutoff)
        if removed:
            log.info("清理旧执行记录: %d 条 (截止 %s)", len(removed), cutoff)
        return len(removed)

    # ── Meta ──

    def get_meta(self, key: str, default: Any = None) -> Any:
        """读取元数据。

        :param key: 键
        :param default: 默认值
        :returns: 存储的值
        """
        doc = self._meta.get(self._MetaQ.key == key)
        return doc.get("value", default) if doc else default

    def set_meta(self, key: str, value: Any) -> None:
        """写入元数据。

        :param key: 键
        :param value: 值
        """
        self._meta.upsert({"key": key, "value": value}, self._MetaQ.key == key)

    def get_seen_job_hrefs(self) -> set[str]:
        """获取已见过的职位 href 集合（用于跨次去重）。

        :returns: href 集合
        """
        val = self.get_meta("seen_job_hrefs", [])
        return set(val) if isinstance(val, list) else set()

    def add_seen_job_hrefs(self, hrefs: list[str]) -> None:
        """添加已见过的职位 href。

        :param hrefs: 待添加的 href 列表
        """
        seen = self.get_seen_job_hrefs()
        seen.update(hrefs)
        self.set_meta("seen_job_hrefs", list(seen))
