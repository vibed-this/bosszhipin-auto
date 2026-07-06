"""业务数据模型：JobCard / ChatItem。"""
from __future__ import annotations

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
