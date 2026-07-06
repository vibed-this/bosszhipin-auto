"""业务数据模型：JobCard / ChatItem。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from typing import Any

from bzauto.enums import MsgType
from bzauto.models_doc import ConvDoc, JobDoc


def make_job_id(href: str) -> str:
    """从职位链接提取或计算 job_id。

    优先从 href 末尾提取数字 ID，失败时退化为 MD5 短哈希。

    :param href: 职位详情链接
    :returns: 12 位以内的 job_id
    """
    try:
        return href.rsplit("/", 1)[-1].replace(".html", "")
    except Exception:
        return hashlib.md5(href.encode()).hexdigest()[:12]


def make_conv_id(account_id: str, name: str, company: str) -> str:
    """生成对话唯一标识。

    :param account_id: 账号 ID
    :param name: 招聘者姓名
    :param company: 公司名称
    :returns: 12 位 MD5 哈希
    """
    raw = f"{account_id}:{name}:{company}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def parse_salary(salary_raw: str) -> tuple[int, int]:
    """解析薪资文本为数值范围。

    :param salary_raw: 薪资原始文本，如 "15-20K" 或 "10K"
    :returns: (salary_min, salary_max)，单位 K
    """
    salary_min = salary_max = 0
    m = re.search(r'(\d+)-(\d+)', salary_raw)
    if m:
        salary_min, salary_max = int(m.group(1)), int(m.group(2))
    else:
        m = re.search(r'(\d+)K', salary_raw)
        if m:
            salary_min = salary_max = int(m.group(1))
    return salary_min, salary_max



@dataclass(frozen=True)
class JobCard:
    """职位卡片数据。

    :ivar title: 职位名称
    :ivar salary: 薪资原始文本
    :ivar company: 公司名称
    :ivar href: 职位详情链接
    """

    title: str
    salary: str
    company: str
    href: str

    @classmethod
    def from_query_row(cls, row: dict[str, Any]) -> JobCard:
        """从 DOM 查询行构建 JobCard。

        :param row: 查询返回的原始 dict
        :returns: JobCard 实例
        """
        return cls(
            title=row.get("title") or "",
            salary=row.get("salary") or "",
            company=row.get("company") or "",
            href=row.get("href") or "",
        )

    def to_dict(self) -> dict[str, Any]:
        """转为普通 dict（序列化用）。"""
        return asdict(self)

    def to_doc(self, account_id: str = "") -> JobDoc:
        """转为 DB 文档模型。

        :param account_id: 关联的账号 ID
        :returns: JobDoc 实例
        """
        job_id = make_job_id(self.href)
        salary_min, salary_max = parse_salary(self.salary)
        return JobDoc(
            job_id=job_id,
            title=self.title,
            salary_raw=self.salary,
            salary_min=salary_min,
            salary_max=salary_max,
            company=self.company,
            href=self.href,
            account=account_id,
        )


@dataclass(frozen=True)
class ChatItem:
    """聊天列表项数据。

    :ivar name: 招聘者姓名
    :ivar company: 公司名称
    :ivar position: 招聘职位
    :ivar time: 最后消息时间文本
    :ivar lastMsg: 最后一条消息文本
    :ivar status: BOSS 平台状态文本（如 "已读"）
    :ivar sender: 发送方标识 ("self" | "other")
    :ivar unread_count: 未读消息数（0=已读, >0=对方未读条数, -1=未知）
    """

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
        """从 DOM 查询行构建 ChatItem。

        :param row: 查询返回的原始 dict
        :returns: ChatItem 实例
        """
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
        """转为普通 dict（序列化用）。"""
        return asdict(self)

    def to_doc(self, account_id: str = "") -> ConvDoc:
        """转为 DB 文档模型。

        :param account_id: 关联的账号 ID
        :returns: ConvDoc 实例
        """
        conv_id = make_conv_id(account_id, self.name, self.company)
        return ConvDoc(
            conv_id=conv_id,
            account=account_id,
            name=self.name,
            company=self.company,
            position=self.position,
            last_msg=self.lastMsg,
            last_msg_time=self.time,
            platform_status=self.status,
            sender=self.sender,
            unread_count=self.unread_count,
        )


def classify_msg_type(last_msg: str, sender: str) -> MsgType:
    """根据消息内容和发送方判断内容分类。

    :param last_msg: 最后一条消息文本
    :param sender: 发送方标识 ("self" | "other")
    :returns: 消息内容分类
    """
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
