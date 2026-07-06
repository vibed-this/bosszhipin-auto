from enum import StrEnum


class JobStatus(StrEnum):
    """职位业务状态枚举。"""

    PENDING = "已沟通"
    GREETED = "已打招呼"
    HR_READ = "HR已读"
    HR_REPLIED = "HR已回复"
    INTERVIEW = "已邀面试"
    REJECTED = "已拒绝"
    CLOSED = "已结束"


class DispatchStatus(StrEnum):
    """派发状态枚举 — 控制 job 的领取与处理流程。"""

    PENDING = "pending"
    CLAIMED = "claimed"
    SUCCESS = "success"
    FAILED = "failed"


class ConvStatus(StrEnum):
    """对话行动性状态枚举 — 指示是否需要用户操作。"""

    NONE = "无操作"
    PENDING = "待回复"
    FOLLOW_UP = "待跟进"
    CLOSED = "已结束"


class MsgType(StrEnum):
    """消息内容分类枚举 — 与行动性状态正交。"""

    NORMAL = "普通"
    REJECTION = "拒信"
    INVITE_RESUME = "邀投简历"
    INVITE_INTERVIEW = "邀面试"
    SYSTEM = "系统"
    UNKNOWN = "未知"
