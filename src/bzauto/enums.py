class JobStatus:
    PENDING = "已沟通"
    GREETED = "已打招呼"
    HR_READ = "HR已读"
    HR_REPLIED = "HR已回复"
    INTERVIEW = "已邀面试"
    REJECTED = "已拒绝"
    CLOSED = "已结束"


class DispatchStatus:
    PENDING = "pending"
    CLAIMED = "claimed"
    SUCCESS = "success"
    FAILED = "failed"


class ConvStatus:
    NEW = "新对话"
    PENDING_REPLY = "待回复"
    REPLIED = "已回复"
    READ_NO_REPLY = "已读未回"
    REJECTION = "拒信"
    INVITATION = "邀约"
    DELETED = "已删除"
    CLOSED = "已结束"
