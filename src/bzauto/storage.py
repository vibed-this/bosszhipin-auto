"""SQLite + sqlite-utils 持久化层 — 仓库模式。

Storage 作为顶层入口，组合 6 个仓库（JobRepo / ConversationRepo / AccountRepo / RunRepo / MetaRepo / SeenHrefsRepo）。
每个仓库持有对 sqlite_utils.Database 的引用，方法返回 Pydantic 模型实例。
"""

from __future__ import annotations

import datetime
import json
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from sqlite_utils import Database
from sqlite_utils.db import NotFoundError

from bzauto.config import get_config
from bzauto.enums import ConvStatus, DispatchStatus
from bzauto.models import make_conv_id, make_job_id
from bzauto.models_doc import AccountDoc, ConvDoc, JobDoc, RunDoc

log = logging.getLogger("boss.storage")


def _now_iso() -> str:
    return datetime.datetime.now().isoformat()


def _today_str() -> str:
    return datetime.date.today().isoformat()


# ──────────────────────────────────────────────
#  Repos
# ──────────────────────────────────────────────


class JobRepo:
    """jobs 表仓库。"""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.tbl = db["jobs"]

    def upsert(self, doc: JobDoc) -> None:
        """插入或更新。保留"空字符串字段不覆盖"语义。"""
        now = _now_iso()
        try:
            existing = self.tbl.get(doc.job_id)
        except NotFoundError:
            existing = None
        if existing:
            update_data = doc.model_dump(exclude={"job_id"}, exclude_none=True)
            update_data = {k: v for k, v in update_data.items() if v != ""}
            update_data["last_updated"] = now
            if update_data:
                self.tbl.update(doc.job_id, update_data)
        else:
            data = doc.model_dump(exclude_none=True)
            data["job_id"] = data.get("job_id") or make_job_id(doc.href)
            data.setdefault("last_updated", now)
            self.tbl.insert(data)

    def get(self, job_id: str) -> JobDoc | None:
        try:
            raw = self.tbl.get(job_id)
        except NotFoundError:
            return None
        return JobDoc(**raw) if raw else None

    def list(self, *, keyword: str = "", status: str = "",
             dispatch_status: str = "", limit: int = 0) -> list[JobDoc]:
        where_clauses: list[str] = []
        params: list[Any] = []
        if keyword:
            where_clauses.append("(LOWER(title) LIKE ? OR LOWER(company) LIKE ?)")
            kw = f"%{keyword.lower()}%"
            params.extend([kw, kw])
        if status:
            where_clauses.append("status = ?")
            params.append(status)
        if dispatch_status:
            where_clauses.append("dispatch_status = ?")
            params.append(dispatch_status)
        sql = "SELECT * FROM jobs"
        if where_clauses:
            sql += " WHERE " + " AND ".join(where_clauses)
        sql += " ORDER BY last_updated DESC"
        if limit:
            sql += f" LIMIT {limit}"
        rows = self.db.query(sql, params)
        return [JobDoc(**r) for r in rows]

    def claim(self, job_id: str, account_id: str) -> bool:
        now = _now_iso()
        cursor = self.db.conn.execute(
            "UPDATE jobs SET dispatch_status=?, dispatched_by=?, "
            "dispatched_at=?, last_updated=? "
            "WHERE job_id=? AND dispatch_status=?",
            (DispatchStatus.CLAIMED, account_id, now, now, job_id, DispatchStatus.PENDING),
        )
        claimed = cursor.rowcount > 0
        if claimed:
            log.info("领取 job: %s -> account=%s", job_id, account_id)
        return claimed

    def mark_success(self, job_id: str) -> None:
        now = _now_iso()
        self.db.conn.execute(
            "UPDATE jobs SET dispatch_status=?, status=?, applied_at=?, last_updated=? "
            "WHERE job_id=?",
            (DispatchStatus.SUCCESS, "已沟通", now, now, job_id),
        )
        log.debug("job 成功: %s", job_id)

    def mark_failed(self, job_id: str) -> None:
        now = _now_iso()
        self.db.conn.execute(
            "UPDATE jobs SET dispatch_status=?, last_updated=? WHERE job_id=?",
            (DispatchStatus.FAILED, now, job_id),
        )
        log.debug("job 失败: %s", job_id)

    def release_stale_claims(self, timeout_minutes: int = 30) -> int:
        now = _now_iso()
        cursor = self.db.conn.execute(
            "UPDATE jobs SET dispatch_status=?, last_updated=? "
            "WHERE dispatch_status=? "
            "AND datetime(dispatched_at) < datetime('now', ?)",
            (DispatchStatus.PENDING, now, DispatchStatus.CLAIMED, f'-{timeout_minutes} minutes'),
        )
        count = cursor.rowcount
        if count:
            log.info("释放超时 claim: %d 条", count)
        return count

    def count(self, *, today: bool = False, dispatched_today: bool = False,
              dispatch_status: str = "", stale_claims_minutes: int = 0) -> int:
        if stale_claims_minutes:
            row = self.db.query(
                "SELECT COUNT(*) as cnt FROM jobs WHERE dispatch_status=? "
                "AND datetime(dispatched_at) < datetime('now', ?)",
                (DispatchStatus.CLAIMED, f'-{stale_claims_minutes} minutes'),
            )
            return list(row)[0]["cnt"]
        if dispatch_status:
            row = self.db.query(
                "SELECT COUNT(*) as cnt FROM jobs WHERE dispatch_status=?",
                (dispatch_status,),
            )
            return list(row)[0]["cnt"]
        if today:
            today_iso = _today_str()
            row = self.db.query(
                "SELECT COUNT(*) as cnt FROM jobs WHERE last_updated LIKE ?",
                (f"{today_iso}%",),
            )
            return list(row)[0]["cnt"]
        if dispatched_today:
            today_iso = _today_str()
            row = self.db.query(
                "SELECT COUNT(*) as cnt FROM jobs "
                "WHERE dispatch_status=? AND applied_at LIKE ?",
                (DispatchStatus.SUCCESS, f"{today_iso}%"),
            )
            return list(row)[0]["cnt"]
        return self.tbl.count

    def update_status(self, job_id: str, status: str) -> None:
        now = _now_iso()
        self.db.conn.execute(
            "UPDATE jobs SET status=?, last_updated=? WHERE job_id=?",
            (status, now, job_id),
        )

    def update_note(self, job_id: str, note: str) -> None:
        now = _now_iso()
        self.db.conn.execute(
            "UPDATE jobs SET note=?, last_updated=? WHERE job_id=?",
            (note, now, job_id),
        )

    def delete(self, job_id: str) -> None:
        self.tbl.delete(job_id)
        log.info("删除 job: %s", job_id)


class ConversationRepo:
    """conversations 表仓库（复合主键 conv_id+account）。"""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.tbl = db["conversations"]

    def upsert(self, doc: ConvDoc) -> bool | None:
        cid = doc.conv_id or make_conv_id(doc.account, doc.name, doc.company)
        pk = (cid, doc.account)
        try:
            existing = self.tbl.get(pk)
        except NotFoundError:
            existing = None
        now = _now_iso()
        if existing:
            update_data = doc.model_dump(exclude={"conv_id", "account"}, exclude_none=True)
            update_data = {k: v for k, v in update_data.items() if v != ""}
            tracked_keys = {"last_msg", "last_msg_time", "platform_status", "sender", "unread_count", "position"}
            has_changes = any(
                key in update_data and str(update_data[key]) != str(existing.get(key, ""))
                for key in tracked_keys
            )
            if not has_changes:
                return None
            update_data["last_updated"] = now
            self.tbl.update(pk, update_data)
            return False
        else:
            data = doc.model_dump(exclude_none=True)
            data["conv_id"] = cid
            data.setdefault("first_seen_at", now)
            data.setdefault("last_updated", now)
            self.tbl.insert(data, pk=("conv_id", "account"))  # type: ignore[arg-type]
            return True

    def batch_upsert(self, account_id: str, items: list[Any]) -> tuple[int, int]:
        from bzauto.models import infer_status
        new_count = updated_count = 0
        now = _now_iso()
        tracked_keys = {"last_msg", "last_msg_time", "platform_status", "sender", "unread_count", "position"}

        conn = self.db.conn
        assert conn is not None
        with conn:
            for item in items:
                doc = item.to_doc(account_id)
                cid = doc.conv_id
                pk = (cid, account_id)
                try:
                    existing = self.tbl.get(pk)
                except NotFoundError:
                    existing = None
                if existing is None:
                    data = doc.model_dump(exclude_none=True)
                    data["conv_id"] = cid
                    data["account"] = account_id
                    data["first_seen_at"] = now
                    data["last_updated"] = now
                    old_status = ConvStatus.NONE
                    new_status = infer_status(item.sender, item.unread_count, old_status, doc.last_msg_time)
                    data["status"] = new_status
                    data["status_changed_at"] = now
                    self.tbl.insert(data, pk=("conv_id", "account"))  # type: ignore[arg-type]
                    new_count += 1
                else:
                    old = ConvDoc(**existing)
                    old_status = old.status or ConvStatus.NONE
                    new_status = infer_status(item.sender, item.unread_count, old_status, doc.last_msg_time)
                    update_data = doc.model_dump(exclude={"conv_id", "account"}, exclude_none=True)
                    update_data = {k: v for k, v in update_data.items() if v != ""}
                    has_changes = any(
                        key in update_data and str(update_data[key]) != str(existing.get(key, ""))
                        for key in tracked_keys
                    )
                    status_changed = new_status != old_status
                    if not has_changes and not status_changed:
                        continue
                    if status_changed:
                        update_data["status"] = new_status
                        update_data["status_changed_at"] = now
                    update_data["last_updated"] = now
                    self.tbl.update(pk, update_data)
                    updated_count += 1

        return new_count, updated_count

    def get(self, conv_id: str, account: str = "") -> ConvDoc | None:
        if account:
            try:
                raw = self.tbl.get((conv_id, account))
            except NotFoundError:
                return None
        else:
            rows = list(self.db.query(
                "SELECT * FROM conversations WHERE conv_id=? LIMIT 1", (conv_id,),
            ))
            raw = rows[0] if rows else None
        return ConvDoc(**raw) if raw else None

    def list(self, *, account: str = "", status: str = "", keyword: str = "") -> list[ConvDoc]:
        where: list[str] = []
        params: list[Any] = []
        if account:
            where.append("account = ?")
            params.append(account)
        if status:
            where.append("status = ?")
            params.append(status)
        if keyword:
            where.append("(LOWER(name) LIKE ? OR LOWER(company) LIKE ?)")
            kw = f"%{keyword.lower()}%"
            params.extend([kw, kw])
        sql = "SELECT * FROM conversations"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY last_updated DESC"
        return [ConvDoc(**r) for r in self.db.query(sql, params)]

    def update_status(self, conv_id: str, account: str, status: str) -> None:
        now = _now_iso()
        self.db.conn.execute(
            "UPDATE conversations SET status=?, status_changed_at=?, last_updated=? "
            "WHERE conv_id=? AND account=?",
            (status, now, now, conv_id, account),
        )

    def update_note(self, conv_id: str, account: str, note: str) -> None:
        now = _now_iso()
        self.db.conn.execute(
            "UPDATE conversations SET note=?, last_updated=? WHERE conv_id=? AND account=?",
            (note, now, conv_id, account),
        )

    def mark_deleted(self, conv_id: str, account: str) -> None:
        now = _now_iso()
        self.db.conn.execute(
            "UPDATE conversations SET status=?, status_changed_at=?, last_updated=? "
            "WHERE conv_id=? AND account=?",
            (ConvStatus.CLOSED, now, now, conv_id, account),
        )

    def list_unreplied(self, account: str = "") -> list[ConvDoc]:
        """查找需催促的对话：我方最后发送且无平台状态且最后消息内容为空。

        :param account: 过滤账号 ID，为空时不限账号
        :returns: ConvDoc 列表
        """
        where = ["sender = 'self'", "(last_msg IS NULL OR last_msg = '')",
                 "(platform_status IS NULL OR platform_status = '')"]
        params: list[Any] = []
        if account:
            where.append("account = ?")
            params.append(account)
        sql = "SELECT * FROM conversations WHERE " + " AND ".join(where)
        sql += " ORDER BY last_updated DESC"
        return [ConvDoc(**r) for r in self.db.query(sql, params)]

    def delete(self, conv_id: str, account: str) -> None:
        self.tbl.delete((conv_id, account))
        log.info("删除对话: conv_id=%s account=%s", conv_id, account)


class AccountRepo:
    """accounts 表仓库。"""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.tbl = db["accounts"]

    @staticmethod
    def _get_or_none(tbl: Any, pk: str) -> dict | None:
        try:
            return tbl.get(pk)
        except NotFoundError:
            return None

    def get(self, account_id: str) -> AccountDoc | None:
        raw = self._get_or_none(self.tbl, account_id)
        return AccountDoc(**raw) if raw else None

    def list(self, *, enabled_only: bool = False) -> list[AccountDoc]:
        if enabled_only:
            rows = self.db.query("SELECT * FROM accounts WHERE enabled=1")
        else:
            rows = self.db.query("SELECT * FROM accounts")
        return [AccountDoc(**r) for r in rows]

    def get_remaining_quota(self, account_id: str) -> int:
        raw = self._get_or_none(self.tbl, account_id)
        if raw is None:
            return 150
        doc = AccountDoc(**raw)
        if doc.last_reset_date != _today_str():
            doc.daily_count = 0
            self.reset_daily_count(account_id)
        return max(0, doc.daily_limit - doc.daily_count)

    def increment_daily_count(self, account_id: str, n: int = 1) -> None:
        raw = self._get_or_none(self.tbl, account_id)
        now = _today_str()
        if raw is None:
            from bzauto.config import get_config
            cfg_accounts = get_config().accounts
            limit = 150
            name = account_id
            for a in cfg_accounts:
                if a.id == account_id:
                    limit = a.daily_limit
                    name = a.name
                    break
            self.tbl.insert({
                "account_id": account_id,
                "name": name,
                "daily_count": n,
                "daily_limit": limit,
                "last_reset_date": now,
                "enabled": True,
            })
        else:
            last_reset = raw.get("last_reset_date", "")
            count = raw.get("daily_count", 0)
            if last_reset != now:
                count = 0
            self.db.conn.execute(
                "UPDATE accounts SET daily_count=?, last_reset_date=? WHERE account_id=?",
                (count + n, now, account_id),
            )

    def reset_daily_count(self, account_id: str) -> None:
        self.db.conn.execute(
            "UPDATE accounts SET daily_count=0, last_reset_date=? WHERE account_id=?",
            (_today_str(), account_id),
        )

    def reset_daily_counts_if_new_day(self) -> int:
        today = _today_str()
        cursor = self.db.conn.execute(
            "UPDATE accounts SET daily_count=0, last_reset_date=? "
            "WHERE last_reset_date<>?",
            (today, today),
        )
        if cursor.rowcount:
            log.info("每日计数已重置: %d 条", cursor.rowcount)
        return cursor.rowcount

    def set_daily_count_maxed(self, account_id: str) -> None:
        raw = self._get_or_none(self.tbl, account_id)
        if raw is None:
            return
        limit = raw.get("daily_limit", 150)
        self.db.conn.execute(
            "UPDATE accounts SET daily_count=?, last_reset_date=? WHERE account_id=?",
            (limit, _today_str(), account_id),
        )

    def set_daily_limit(self, account_id: str, limit: int) -> None:
        self.db.conn.execute(
            "UPDATE accounts SET daily_limit=? WHERE account_id=?",
            (limit, account_id),
        )

    def sync_from_config(self) -> None:
        """从 config.toml 同步启用的账号到 SQLite accounts 表。
        
        新账号插入，已有账号更新 name/daily_limit/enabled/role，
        不影响 daily_count/last_reset_date。
        """
        from bzauto.config import get_config
        for a in get_config().accounts:
            existing = self._get_or_none(self.tbl, a.id)
            if existing is None:
                self.tbl.insert({
                    "account_id": a.id,
                    "name": a.name,
                    "daily_limit": a.daily_limit,
                    "daily_count": 0,
                    "last_reset_date": "",
                    "enabled": 1 if a.enabled else 0,
                    "role": a.role,
                })
            else:
                self.db.conn.execute(
                    "UPDATE accounts SET name=?, daily_limit=?, enabled=?, role=? WHERE account_id=?",
                    (a.name, a.daily_limit, 1 if a.enabled else 0, a.role, a.id),
                )


class RunRepo:
    """schedule_runs 表仓库。"""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.tbl = db["schedule_runs"]

    def insert(self, doc: RunDoc) -> int:
        data = doc.model_dump(exclude={"id"}, exclude_none=True)
        self.tbl.insert(data)
        return self.tbl.last_pk  # type: ignore[no-any-return]

    def list_recent(self, limit: int = 50) -> list[RunDoc]:
        rows = self.db.query(
            "SELECT * FROM schedule_runs ORDER BY started_at DESC LIMIT ?",
            (limit,),
        )
        return [RunDoc(**r) for r in rows]

    def list_today(self) -> list[RunDoc]:
        today = _today_str()
        rows = self.db.query(
            "SELECT * FROM schedule_runs WHERE started_at LIKE ?",
            (f"{today}%",),
        )
        return [RunDoc(**r) for r in rows]

    def purge_old(self, days: int = 30) -> int:
        cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
        cursor = self.db.conn.execute(
            "DELETE FROM schedule_runs WHERE started_at < ?", (cutoff,),
        )
        if cursor.rowcount:
            log.info("清理旧执行记录: %d 条 (截止 %s)", cursor.rowcount, cutoff)
        return cursor.rowcount





class MetaRepo:
    """meta 键值表仓库。"""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.tbl = db["meta"]

    def get(self, key: str, default: Any = None) -> Any:
        try:
            raw = self.tbl.get(key)
        except NotFoundError:
            return default
        if raw is None:
            return default
        try:
            return json.loads(raw["value"])
        except (json.JSONDecodeError, TypeError, ValueError):
            return raw["value"]

    def set(self, key: str, value: Any) -> None:
        self.tbl.upsert(
            {"key": key, "value": json.dumps(value, ensure_ascii=False)},
            pk="key",  # type: ignore[arg-type]
        )


class SeenHrefsRepo:
    """seen_job_hrefs 表仓库。"""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.tbl = db["seen_job_hrefs"]

    def get_all(self) -> set[str]:
        rows = self.db.query("SELECT href FROM seen_job_hrefs")
        return {r["href"] for r in rows}

    def add(self, hrefs: list[str]) -> int:
        count = 0
        for href in hrefs:
            try:
                self.tbl.insert({"href": href}, pk="href", ignore=True)  # type: ignore[arg-type]
                count += 1
            except Exception:
                pass
        return count

    def count(self) -> int:
        row = list(self.db.query("SELECT COUNT(*) AS cnt FROM seen_job_hrefs"))
        return row[0]["cnt"] if row else 0


# ──────────────────────────────────────────────
#  Storage 顶层入口
# ──────────────────────────────────────────────


class Storage:
    """SQLite + sqlite-utils 持久化层。

    使用 store.jobs.xxx() / store.conversations.xxx() 访问各仓库。
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        cfg = get_config()
        path = Path(db_path or cfg.storage.db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = Database(str(path))
        self.db.enable_wal()
        self.db.conn.execute("PRAGMA busy_timeout=5000")
        self._init_schema()

        self.jobs = JobRepo(self.db)
        self.conversations = ConversationRepo(self.db)
        self.accounts = AccountRepo(self.db)
        self.runs = RunRepo(self.db)
        self.meta = MetaRepo(self.db)
        self.seen_hrefs = SeenHrefsRepo(self.db)

        self.accounts.sync_from_config()

        log.info("数据库初始化: %s", path)

    def _init_schema(self) -> None:
        """幂等建表 + 索引。"""

        # jobs
        self.db["jobs"].create({
            "job_id": str,
            "title": str,
            "salary_raw": str,
            "salary_min": int,
            "salary_max": int,
            "company": str,
            "href": str,
            "location": str,
            "account": str,
            "dispatched_by": str,
            "status": str,
            "dispatch_status": str,
            "dispatched_at": str,
            "applied_at": str,
            "last_updated": str,
            "job_desc": str,
            "note": str,
        }, pk="job_id", if_not_exists=True)
        self.db.conn.execute(
            "CREATE INDEX IF NOT EXISTS [idx_jobs_dispatch_status] ON [jobs]([dispatch_status])",
        )
        self.db.conn.execute(
            "CREATE INDEX IF NOT EXISTS [idx_jobs_dispatch_status_dispatched_at] "
            "ON [jobs]([dispatch_status], [dispatched_at])",
        )
        self.db.conn.execute(
            "CREATE INDEX IF NOT EXISTS [idx_jobs_last_updated] ON [jobs]([last_updated])",
        )

        # conversations
        self.db["conversations"].create({
            "conv_id": str,
            "account": str,
            "name": str,
            "company": str,
            "position": str,
            "last_msg": str,
            "last_msg_time": str,
            "platform_status": str,
            "status": str,
            "sender": str,
            "unread_count": int,
            "status_changed_at": str,
            "linked_job_id": str,
            "first_seen_at": str,
            "last_updated": str,
            "note": str,
            "unique_id": str,
            "encrypt_boss_id": str,
            "encrypt_job_id": str,
        }, pk=("conv_id", "account"), if_not_exists=True)
        self.db.conn.execute(
            "CREATE INDEX IF NOT EXISTS [idx_conv_account] ON [conversations]([account])",
        )
        self.db.conn.execute(
            "CREATE INDEX IF NOT EXISTS [idx_conv_account_status] ON [conversations]([account], [status])",
        )

        # accounts
        self.db["accounts"].create({
            "account_id": str,
            "name": str,
            "daily_count": int,
            "daily_limit": int,
            "last_reset_date": str,
            "enabled": int,
            "role": str,
        }, pk="account_id", if_not_exists=True)

        # schedule_runs
        self.db["schedule_runs"].create({
            "id": int,
            "trigger": str,
            "account_id": str,
            "account_name": str,
            "started_at": str,
            "finished_at": str,
            "status": str,
            "result": str,
            "error": str,
        }, pk="id", if_not_exists=True)
        self.db.conn.execute(
            "CREATE INDEX IF NOT EXISTS [idx_runs_started_at] ON [schedule_runs]([started_at])",
        )

        # meta
        self.db["meta"].create({
            "key": str,
            "value": str,
        }, pk="key", if_not_exists=True)

        # seen_job_hrefs
        self.db["seen_job_hrefs"].create({
            "href": str,
        }, pk="href", if_not_exists=True)

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """显式事务上下文。异常时自动回滚。"""
        conn = self.db.conn
        assert conn is not None
        with conn:
            yield


