"""TinyDB 文档模型 — 与 storage 层的文档形状一一对应。

每个模型映射一张 TinyDB 表的文档结构，字段名与 DB key 完全一致（snake_case）。
使用 Pydantic BaseModel 以在 Storage 边界获得类型安全。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from bzauto.enums import ConvStatus, DispatchStatus


class JobDoc(BaseModel):
    """jobs 表的文档模型。

    :ivar job_id: 职位唯一标识，由 href 计算得出
    :ivar title: 职位名称
    :ivar salary_raw: 薪资原始文本
    :ivar salary_min: 解析后的最低薪资 (K)
    :ivar salary_max: 解析后的最高薪资 (K)
    :ivar company: 公司名称
    :ivar href: 职位详情链接
    :ivar account: 关联账号 ID
    :ivar status: 业务状态文本（如 "已沟通"）
    :ivar dispatch_status: 派发状态（pending / claimed / success / failed）
    :ivar dispatched_at: 领取时间 ISO 格式
    :ivar applied_at: 沟通成功时间 ISO 格式
    :ivar last_updated: 最后更新时间 ISO 格式
    :ivar note: 备注
    """

    model_config = ConfigDict(use_enum_values=True)

    job_id: str = ""
    title: str = ""
    salary_raw: str = ""
    salary_min: int = 0
    salary_max: int = 0
    company: str = ""
    href: str = ""
    account: str = ""
    status: str = ""
    dispatch_status: str = DispatchStatus.PENDING
    dispatched_at: str | None = None
    applied_at: str | None = None
    last_updated: str = ""
    note: str = ""


class ConvDoc(BaseModel):
    """conversations 表的文档模型。

    :ivar conv_id: 对话唯一标识，由 account:name:company 哈希得出
    :ivar account: 关联账号 ID
    :ivar name: 招聘者姓名
    :ivar company: 公司名称
    :ivar position: 招聘职位
    :ivar last_msg: 最后一条消息文本
    :ivar last_msg_time: 最后消息时间
    :ivar platform_status: BOSS 平台状态文本
    :ivar status: 业务交互状态（新对话 / 待回复 / 已回复 / 已读未回 / 已删除 / 已结束）
    :ivar sender: 最后消息发送方标识（self | other）
    :ivar unread_count: 未读消息数（0=已读, >0=未读, -1=未知）
    :ivar status_changed_at: 状态变更时间 ISO 格式
    :ivar linked_job_id: 关联职位 job_id（可选）
    :ivar first_seen_at: 首次发现时间 ISO 格式
    :ivar last_updated: 最后更新时间 ISO 格式
    :ivar note: 备注
    """

    model_config = ConfigDict(use_enum_values=True)

    conv_id: str = ""
    account: str = ""
    name: str = ""
    company: str = ""
    position: str = ""
    last_msg: str = ""
    last_msg_time: str = ""
    platform_status: str = ""
    status: str = ConvStatus.NEW
    sender: str = ""
    unread_count: int = 0
    status_changed_at: str | None = None
    linked_job_id: str | None = None
    first_seen_at: str = ""
    last_updated: str = ""
    note: str = ""


class AccountDoc(BaseModel):
    """accounts 表的文档模型。

    :ivar account_id: 账号唯一标识
    :ivar name: 账号显示名称
    :ivar daily_count: 当日已投递计数
    :ivar daily_limit: 每日投递上限
    :ivar last_reset_date: 最后重置日期 (YYYY-MM-DD)
    :ivar enabled: 是否启用
    """

    model_config = ConfigDict(use_enum_values=True)

    account_id: str = ""
    name: str = ""
    daily_count: int = 0
    daily_limit: int = 150
    last_reset_date: str = ""
    enabled: bool = True
