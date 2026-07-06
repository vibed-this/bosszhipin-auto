"""TinyDB 封装 — jobs / conversations / accounts / meta 四张表。"""
from __future__ import annotations

import datetime
import hashlib
import logging
from pathlib import Path
from typing import Any

from tinydb import Query, TinyDB

from bzauto.config import get_config
from bzauto.enums import ConvStatus, DispatchStatus

log = logging.getLogger("boss.storage")

_JOB_FIELDS = [
    "job_id", "title", "salary_raw", "salary_min", "salary_max",
    "company", "href", "status", "account", "dispatch_status",
    "dispatched_at", "applied_at", "last_updated", "note",
]
_CONV_FIELDS = [
    "conv_id", "account", "name", "company", "position",
    "last_msg", "last_msg_time", "platform_status", "status",
    "sender", "unread_count",
    "status_changed_at", "linked_job_id", "first_seen_at",
    "last_updated", "note",
]
_ACCOUNT_FIELDS = [
    "account_id", "name", "daily_count", "daily_limit",
    "last_reset_date", "enabled",
]


def _now_iso() -> str:
    return datetime.datetime.now().isoformat()


def _today_str() -> str:
    return datetime.date.today().isoformat()


def _extract_job_id(href: str) -> str:
    try:
        return href.rsplit("/", 1)[-1].replace(".html", "")
    except Exception:
        return hashlib.md5(href.encode()).hexdigest()[:12]


def _conv_id(account_id: str, name: str, company: str) -> str:
    raw = f"{account_id}:{name}:{company}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


class Storage:
    """TinyDB 持久化存储。"""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_path = get_config().storage.db_path
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = TinyDB(str(path), indent=2, ensure_ascii=False, sort_keys=True)
        self._jobs = self._db.table("jobs")
        self._conversations = self._db.table("conversations")
        self._accounts = self._db.table("accounts")
        self._meta = self._db.table("meta")
        self._JobQ = Query()
        self._ConvQ = Query()
        self._AccountQ = Query()
        self._MetaQ = Query()
        log.info("数据库初始化: %s", path)

    # ── Jobs ──

    def upsert_job(self, job: dict[str, Any]) -> int:
        job_id = job.get("job_id") or _extract_job_id(job.get("href", ""))
        existing = self._jobs.get(self._JobQ.job_id == job_id)
        now = _now_iso()
        if existing:
            update = {k: v for k, v in job.items() if k in _JOB_FIELDS and v is not None and v != ""}
            update["last_updated"] = now
            self._jobs.update(update, self._JobQ.job_id == job_id)
            log.debug("更新 job: %s", job_id)
            return existing.doc_id
        else:
            doc = {k: job.get(k) for k in _JOB_FIELDS if job.get(k)}
            doc["job_id"] = job_id
            doc.setdefault("dispatch_status", DispatchStatus.PENDING)
            doc.setdefault("status", "")
            doc.setdefault("last_updated", now)
            doc_id = self._jobs.insert(doc)
            log.debug("插入 job: %s", job_id)
            return doc_id

    def get_pending_jobs(self, limit: int = 50) -> list[dict]:
        results = self._jobs.search(self._JobQ.dispatch_status == DispatchStatus.PENDING)
        return results[:limit]

    def count_pending_jobs(self) -> int:
        return len(self._jobs.search(self._JobQ.dispatch_status == DispatchStatus.PENDING))

    def get_job(self, job_id: str) -> dict | None:
        return self._jobs.get(self._JobQ.job_id == job_id)

    def claim_job(self, job_id: str, account_id: str) -> bool:
        now = _now_iso()
        result = self._jobs.update(
            {
                "dispatch_status": DispatchStatus.CLAIMED,
                "account": account_id,
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
        now = _now_iso()
        self._jobs.update(
            {
                "dispatch_status": DispatchStatus.FAILED,
                "last_updated": now,
            },
            self._JobQ.job_id == job_id,
        )
        log.debug("job 失败: %s", job_id)

    def release_stale_claims(self, timeout_minutes: int = 30) -> int:
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
                    doc.doc_id,
                )
                count += 1
        if count:
            log.info("释放超时 claim: %d 条", count)
        return count

    def update_job_status(self, job_id: str, status: str) -> None:
        self._jobs.update({"status": status, "last_updated": _now_iso()}, self._JobQ.job_id == job_id)

    def search_jobs(self, keyword: str = "", status: str = "") -> list[dict]:
        cond = self._JobQ.job_id != ""  # always true
        if keyword:
            cond &= (self._JobQ.title.test(lambda v: keyword.lower() in (v or "").lower())) | \
                    (self._JobQ.company.test(lambda v: keyword.lower() in (v or "").lower()))
        if status:
            cond &= self._JobQ.status == status
        return self._jobs.search(cond)

    def delete_job(self, job_id: str) -> None:
        self._jobs.remove(self._JobQ.job_id == job_id)
        log.info("删除 job: %s", job_id)

    def update_job_note(self, job_id: str, note: str) -> None:
        self._jobs.update({"note": note, "last_updated": _now_iso()}, self._JobQ.job_id == job_id)

    # ── Conversations ──

    def upsert_conversation(self, conv: dict[str, Any]) -> bool:
        account = conv.get("account", "")
        name = conv.get("name", "")
        company = conv.get("company", "")
        cid = conv.get("conv_id") or _conv_id(account, name, company)
        existing = self._conversations.get(
            (self._ConvQ.conv_id == cid) & (self._ConvQ.account == account),
        )
        now = _now_iso()
        if existing:
            update = {k: v for k, v in conv.items() if k in _CONV_FIELDS and v is not None and v != ""}
            update["last_updated"] = now
            self._conversations.update(
                update,
                (self._ConvQ.conv_id == cid) & (self._ConvQ.account == account),
            )
            return False
        else:
            doc = {k: conv.get(k) for k in _CONV_FIELDS if conv.get(k)}
            doc["conv_id"] = cid
            doc.setdefault("first_seen_at", now)
            doc.setdefault("last_updated", now)
            self._conversations.insert(doc)
            return True

    def update_conv_note(self, conv_id: str, account: str, note: str) -> None:
        self._conversations.update(
            {"note": note, "last_updated": _now_iso()},
            (self._ConvQ.conv_id == conv_id) & (self._ConvQ.account == account),
        )

    def update_conv_status(self, conv_id: str, account: str, status: str) -> None:
        self._conversations.update(
            {"status": status, "status_changed_at": _now_iso(), "last_updated": _now_iso()},
            (self._ConvQ.conv_id == conv_id) & (self._ConvQ.account == account),
        )

    def get_conversations(self, account: str = "", status: str = "") -> list[dict]:
        cond = self._ConvQ.conv_id != ""
        if account:
            cond &= self._ConvQ.account == account
        if status:
            cond &= self._ConvQ.status == status
        return self._conversations.search(cond)

    def search_conversations(self, keyword: str = "", status: str = "", account: str = "") -> list[dict]:
        cond = self._ConvQ.conv_id != ""
        if keyword:
            cond &= (self._ConvQ.name.test(lambda v: keyword.lower() in (v or "").lower())) | \
                    (self._ConvQ.company.test(lambda v: keyword.lower() in (v or "").lower()))
        if status:
            cond &= self._ConvQ.status == status
        if account:
            cond &= self._ConvQ.account == account
        return self._conversations.search(cond)

    def delete_conversation(self, conv_id: str, account: str) -> None:
        self._conversations.remove(
            (self._ConvQ.conv_id == conv_id) & (self._ConvQ.account == account),
        )
        log.info("删除对话: conv_id=%s account=%s", conv_id, account)

    def mark_deleted(self, conv_id: str, account: str) -> None:
        self._conversations.update(
            {"status": ConvStatus.DELETED, "status_changed_at": _now_iso(), "last_updated": _now_iso()},
            (self._ConvQ.conv_id == conv_id) & (self._ConvQ.account == account),
        )

    def get_conversations_by_status(self, status: str, account: str) -> list[dict]:
        cond = (self._ConvQ.status == status) & (self._ConvQ.account == account)
        return self._conversations.search(cond)

    # ── Accounts ──

    def get_account(self, account_id: str) -> dict | None:
        return self._accounts.get(self._AccountQ.account_id == account_id)

    def get_all_accounts(self) -> list[dict]:
        return self._accounts.all()

    def get_enabled_accounts(self) -> list[dict]:
        from bzauto.config import get_config
        cfg = get_config()
        result = []
        for acc_cfg in cfg.accounts:
            if not acc_cfg.enabled:
                continue
            db_acc = self._accounts.get(self._AccountQ.account_id == acc_cfg.id)
            daily_count = db_acc.get("daily_count", 0) if db_acc else 0
            last_reset = db_acc.get("last_reset_date", "") if db_acc else ""
            if last_reset != _today_str():
                daily_count = 0
            result.append({
                "account_id": acc_cfg.id,
                "name": acc_cfg.name,
                "daily_count": daily_count,
                "daily_limit": acc_cfg.daily_limit,
                "last_reset_date": _today_str(),
                "enabled": True,
            })
        return result

    def get_remaining_quota(self, account_id: str) -> int:
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
        self._accounts.update(
            {"daily_count": 0, "last_reset_date": _today_str()},
            self._AccountQ.account_id == account_id,
        )

    def reset_daily_counts_if_new_day(self) -> None:
        today = _today_str()
        for doc in self._accounts.all():
            if doc.get("last_reset_date") != today:
                self._accounts.update(
                    {"daily_count": 0, "last_reset_date": today},
                    doc.doc_id,
                )
        log.info("每日计数已检查/重置")

    def set_daily_count_maxed(self, account_id: str) -> None:
        self.increment_daily_count(account_id, 0)

    def set_account_daily_limit(self, account_id: str, limit: int) -> None:
        self._accounts.upsert(
            {"daily_limit": limit},
            self._AccountQ.account_id == account_id,
        )

    # ── Meta ──

    def get_meta(self, key: str, default: Any = None) -> Any:
        doc = self._meta.get(self._MetaQ.key == key)
        return doc.get("value", default) if doc else default

    def set_meta(self, key: str, value: Any) -> None:
        self._meta.upsert({"key": key, "value": value}, self._MetaQ.key == key)

    def get_seen_job_hrefs(self) -> set[str]:
        val = self.get_meta("seen_job_hrefs", [])
        return set(val) if isinstance(val, list) else set()

    def add_seen_job_hrefs(self, hrefs: list[str]) -> None:
        seen = self.get_seen_job_hrefs()
        seen.update(hrefs)
        self.set_meta("seen_job_hrefs", list(seen))
