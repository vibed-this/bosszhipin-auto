"""业务数据模型：JobCard / ChatItem。"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any

from bzauto.enums import MsgType



@dataclass(frozen=True)
class JobCard:
    """职位卡片数据。"""

    title: str
    salary: str
    company: str
    href: str

    @classmethod
    def from_query_row(cls, row: dict[str, Any]) -> JobCard:
        return cls(
            title=row.get("title") or "",
            salary=row.get("salary") or "",
            company=row.get("company") or "",
            href=row.get("href") or "",
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_db_dict(self, account_id: str = "") -> dict[str, Any]:
        """转为 DB 文档格式。"""
        import re
        job_id = self.href.rsplit("/", 1)[-1].replace(".html", "") if self.href else \
            hashlib.md5(self.href.encode()).hexdigest()[:12]
        salary_min, salary_max = 0, 0
        m = re.search(r'(\d+)-(\d+)', self.salary)
        if m:
            salary_min, salary_max = int(m.group(1)), int(m.group(2))
        else:
            m = re.search(r'(\d+)K', self.salary)
            if m:
                salary_min = salary_max = int(m.group(1))
        return {
            "job_id": job_id,
            "title": self.title,
            "salary_raw": self.salary,
            "salary_min": salary_min,
            "salary_max": salary_max,
            "company": self.company,
            "href": self.href,
            "account": account_id,
        }


@dataclass(frozen=True)
class ChatItem:
    """聊天列表项数据。"""

    name: str
    company: str
    position: str
    time: str
    lastMsg: str
    status: str = ""
    sender: str = ""        # "self" | "other"
    unread_count: int = 0   # 0=已读, >0=对方未读条数, -1=未知

    @classmethod
    def from_query_row(cls, row: dict[str, Any]) -> ChatItem:
        last_msg = row.get("lastMsg") or ""
        first_child_class = row.get("firstChildClass") or ""
        sender = "other" if first_child_class == "last-msg-text" else "self"
        unread_text = row.get("unreadCount")
        unread_count = int(unread_text) if unread_text and unread_text.strip().isdigit() else 0

        # 文件消息覆写 sender / unread_count
        if last_msg.lower().endswith(".pdf"):
            sender = "self"
            unread_count = -1

        return cls(
            name=row.get("name") or "",
            company=row.get("company") or "",
            position=row.get("position") or "",
            time=row.get("time") or "",
            lastMsg=last_msg,
            status=(row.get("status") or "").strip(" []"),
            sender=sender,
            unread_count=unread_count,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_db_dict(self, account_id: str = "") -> dict[str, Any]:
        raw = f"{account_id}:{self.name}:{self.company}"
        conv_id = hashlib.md5(raw.encode()).hexdigest()[:12]
        return {
            "conv_id": conv_id,
            "account": account_id,
            "name": self.name,
            "company": self.company,
            "position": self.position,
            "last_msg": self.lastMsg,
            "last_msg_time": self.time,
            "platform_status": self.status,
            "sender": self.sender,
            "unread_count": self.unread_count,
        }


def classify_msg_type(last_msg: str, sender: str) -> str:
    """根据消息内容和发送方判断内容分类。"""
    if sender == "self":
        if last_msg.lower().endswith(".pdf"):
            return MsgType.FILE
        return MsgType.NORMAL
    from bzauto.config import get_config
    cfg = get_config()
    if any(kw in last_msg for kw in cfg.delete.keywords):
        return MsgType.REJECTION
    invitation_keywords = ["面试", "邀约", "到面", "面试邀请"]
    if any(kw in last_msg for kw in invitation_keywords):
        return MsgType.INVITATION
    return MsgType.NORMAL
