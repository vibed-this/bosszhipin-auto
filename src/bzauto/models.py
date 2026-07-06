"""业务数据模型：JobCard / ChatItem。"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any


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

    @classmethod
    def from_query_row(cls, row: dict[str, Any]) -> ChatItem:
        return cls(
            name=row.get("name") or "",
            company=row.get("company") or "",
            position=row.get("position") or "",
            time=row.get("time") or "",
            lastMsg=row.get("lastMsg") or "",
            status=(row.get("status") or "").strip(" []"),
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
        }
