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
    """对话交互状态枚举 — 与消息内容分类正交。"""

    NEW = "新对话"
    PENDING_REPLY = "待回复"
    REPLIED = "已回复"
    READ_NO_REPLY = "已读未回"
    DELETED = "已删除"
    CLOSED = "已结束"


class MsgType(StrEnum):
    """消息内容分类枚举 — 与交互状态正交。"""

    NORMAL = "普通"
    REJECTION = "拒信"
    INVITATION = "邀约"
    FILE = "文件"
    UNKNOWN = "未知"
