"""持久化文档模型（Pydantic）。

与 storage 层仓库的文档形状一一对应。字段名与 DB 列一致（snake_case）。
使用 Pydantic BaseModel 以在 Storage 边界获得类型安全。
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, field_validator

from bzauto.enums import ConvStatus, DispatchStatus, RunStatus


class JobDoc(BaseModel):
    """jobs 表的文档模型。

    :ivar job_id: 职位唯一标识，由 href 计算得出
    :ivar title: 职位名称
    :ivar salary_raw: 薪资原始文本
    :ivar salary_min: 解析后的最低薪资 (K)
    :ivar salary_max: 解析后的最高薪资 (K)
    :ivar company: 公司名称
    :ivar href: 职位详情链接
    :ivar location: 地点列表（如 ["长沙", "岳麓区", "望城坡"]）
    :ivar account: 采集账号 ID（记录谁采集的，写入后不变）
    :ivar dispatched_by: 投递账号 ID（记录谁沟通的，由 claim 时设置）
    :ivar status: 业务状态文本（如 "已沟通"）
    :ivar dispatch_status: 派发状态（pending / claimed / success / failed / filtered）
    :ivar dispatched_at: 领取时间 ISO 格式
    :ivar applied_at: 沟通成功时间 ISO 格式
    :ivar last_updated: 最后更新时间 ISO 格式
    :ivar job_desc: 职位描述文本（详情页抓取填充）
    :ivar experience: 经验要求（详情页）
    :ivar degree: 学历要求（详情页）
    :ivar tags: 福利/职位标签列表（详情页 .job-tags）
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
    location: list[str] = []
    account: str = ""
    dispatched_by: str = ""
    status: str = ""
    dispatch_status: str = DispatchStatus.PENDING
    dispatched_at: str | None = None
    applied_at: str | None = None
    last_updated: str = ""
    job_desc: str = ""
    experience: str = ""
    degree: str = ""
    tags: list[str] = []
    note: str = ""

    @field_validator("location", mode="before")
    @classmethod
    def _parse_location(cls, v: object) -> object:
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return parsed
            except (json.JSONDecodeError, TypeError):
                pass
        return v

    @field_validator("tags", mode="before")
    @classmethod
    def _parse_tags(cls, v: object) -> object:
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return [str(x) for x in parsed]
            except (json.JSONDecodeError, TypeError):
                pass
        if isinstance(v, list):
            return [str(x) for x in v]
        return []

    @field_validator("experience", "degree", mode="before")
    @classmethod
    def _parse_str_or_empty(cls, v: object) -> object:
        if v is None:
            return ""
        if isinstance(v, str):
            return v
        return str(v) if v else ""


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
    :ivar status: 业务交互状态（无操作 / 待回复 / 待跟进 / 已结束）
    :ivar sender: 最后消息发送方标识（self | other）
    :ivar unread_count: 未读消息数（0=已读, >0=未读, -1=未知）
    :ivar status_changed_at: 状态变更时间 ISO 格式
    :ivar linked_job_id: 关联职位 job_id（可选）
    :ivar first_seen_at: 首次发现时间 ISO 格式
    :ivar last_updated: 最后更新时间 ISO 格式
    :ivar note: 备注
    :ivar unique_id: Vue 侧唯一标识（uid-friendSource）
    :ivar encrypt_boss_id: 加密 Boss ID
    :ivar encrypt_job_id: 加密职位 ID
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
    status: str = ConvStatus.NONE
    sender: str = ""
    unread_count: int = 0
    last_msg_id: int = 0
    last_notified_msg_key: str = ""
    status_changed_at: str | None = None
    linked_job_id: str | None = None
    first_seen_at: str = ""
    last_updated: str = ""
    note: str = ""
    unique_id: str = ""
    encrypt_boss_id: str = ""
    encrypt_job_id: str = ""


class AccountDoc(BaseModel):
    """accounts 表的文档模型。

    :ivar account_id: 账号唯一标识
    :ivar name: 账号显示名称
    :ivar daily_count: 当日已投递计数
    :ivar daily_limit: 每日投递上限
    :ivar last_reset_date: 最后重置日期 (YYYY-MM-DD)
    :ivar enabled: 是否启用
    :ivar role: 角色（scraper / dispatcher）
    """

    model_config = ConfigDict(use_enum_values=True)

    account_id: str = ""
    name: str = ""
    daily_count: int = 0
    daily_limit: int = 150
    last_reset_date: str = ""
    enabled: bool = True
    role: str = "dispatcher"


class RunDoc(BaseModel):
    """schedule_runs 表的文档模型 — 记录每次调度/手动触发的执行结果。

    :ivar id: 自增主键（SQLite 回填，回滚时可用）
    :ivar trigger: 触发类型（采集 / 投递 / 扫描）
    :ivar account_id: 账号 ID
    :ivar account_name: 账号显示名称（冗余存储，面板免二次查询）
    :ivar started_at: 开始时间 ISO 格式
    :ivar finished_at: 结束时间 ISO 格式
    :ivar status: 执行状态（success / failed / skipped）
    :ivar result: execute() 返回值字典
    :ivar error: 异常堆栈文本（失败时）
    """

    model_config = ConfigDict(use_enum_values=True)

    id: int | None = None
    trigger: str = ""
    account_id: str = ""
    account_name: str = ""
    started_at: str = ""
    finished_at: str = ""
    status: str = RunStatus.SUCCESS
    result: dict = {}
    error: str = ""

    @field_validator("result", mode="before")
    @classmethod
    def _parse_result(cls, v: object) -> object:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return {}
        return v if isinstance(v, dict) else {}


