"""业务数据模型：JobCard / ChatItem。"""

from __future__ import annotations

import datetime
import hashlib
import re
from typing import Any
import logging

from pydantic import BaseModel, ConfigDict, computed_field

from bzauto.enums import ConvStatus, MsgType
from bzauto.models_doc import ConvDoc, JobDoc

log = logging.getLogger(__name__)

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


def parse_chat_time(time_text: str) -> str:
    """将 Boss 直聘聊天列表的时间文本转为 ISO 格式。

    "HH:MM" → 当天
    "MM月DD日" → 今年
    "昨天" → 昨天
    "周X" → 最近一周内
    "X分钟前"/"X小时前" → 相对时间
    "刚刚" → 当前时间
    已有 ISO 格式 → 原样返回
    """
    if not time_text:
        return ""
    t = time_text.strip()

    # 已是 ISO 格式
    if re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}', t):
        return t

    now = datetime.datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # HH:MM
    m = re.match(r'^(\d{2}):(\d{2})$', t)
    if m:
        dt = today.replace(hour=int(m.group(1)), minute=int(m.group(2)))
        return dt.isoformat()

    # 昨天
    if "昨天" in t:
        m = re.search(r'(\d{2}):(\d{2})', t)
        if m:
            dt = (today - datetime.timedelta(days=1)).replace(hour=int(m.group(1)), minute=int(m.group(2)))
        else:
            dt = today - datetime.timedelta(days=1)
        return dt.isoformat()

    # MM月DD日（只有日期，没有时间）
    m = re.match(r'^(\d{1,2})月(\d{1,2})日', t)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        dt = today.replace(month=month, day=day)
        if dt > now:
            dt = dt.replace(year=now.year - 1)
        return dt.strftime("%Y-%m-%d")

    # X分钟前
    m = re.match(r'^(\d+)分钟前', t)
    if m:
        dt = now - datetime.timedelta(minutes=int(m.group(1)))
        return dt.isoformat()

    # X小时前
    m = re.match(r'^(\d+)小时前', t)
    if m:
        dt = now - datetime.timedelta(hours=int(m.group(1)))
        return dt.isoformat()

    # 刚刚
    if "刚刚" in t:
        return now.isoformat()

    return t


def clean_boss_detail_text(text: str) -> str:
    """清洗 Boss 详情页反爬混淆文本（如插入的 kanzhun / 直聘 噪声）。"""
    if not text:
        return ""
    cleaned = text.replace("kanzhun", "")
    # 正文中插入的 BOSS直聘 / 直聘 / boss（非句首品牌名）
    cleaned = re.sub(r"^直聘(?=[\u4e00-\u9fff])", "", cleaned)
    cleaned = re.sub(r"(?<=[\u4e00-\u9fff])BOSS直聘(?=[\u4e00-\u9fff])", "", cleaned)
    cleaned = re.sub(r"(?<=[\u4e00-\u9fff])直聘(?=[\u4e00-\u9fff])", "", cleaned)
    cleaned = re.sub(r"(?<=[\u4e00-\u9fff])boss(?=[\u4e00-\u9fff])", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


class JobCard(BaseModel):
    model_config = ConfigDict(frozen=True)
    """职位卡片数据。

    :ivar title: 职位名称
    :ivar salary: 薪资原始文本
    :ivar company: 公司名称
    :ivar href: 职位详情链接
    :ivar location: 地点原始文本（如 "长沙·岳麓区·望城坡"）
    """

    title: str
    salary: str
    company: str
    href: str
    location: str = ""

    @classmethod
    def from_vue_row(cls, row: dict[str, Any]) -> JobCard:
        """从 Vue jobList 数据构建 JobCard。

        :param row: Vue page-jobs-main.jobList 中的单个 job 对象
        :returns: JobCard 实例
        """
        encrypt_job_id = row.get("encryptJobId") or ""
        href = f"https://www.zhipin.com/job_detail/{encrypt_job_id}.html" if encrypt_job_id else ""
        location = "\u00B7".join(filter(None, [
            row.get("cityName") or "",
            row.get("areaDistrict") or "",
            row.get("businessDistrict") or "",
        ]))
        return cls(
            title=row.get("jobName") or "",
            salary=row.get("salaryDesc") or "",
            company=row.get("brandName") or "",
            href=href,
            location=location,
        )

    def to_dict(self) -> dict[str, Any]:
        """转为普通 dict（序列化用）。"""
        return self.model_dump()

    def to_doc(self, account_id: str = "") -> JobDoc:
        """转为 DB 文档模型。

        :param account_id: 关联的账号 ID
        :returns: JobDoc 实例
        """
        job_id = make_job_id(self.href)
        salary_min, salary_max = parse_salary(self.salary)
        location_parts = [p.strip() for p in self.location.split("\u00B7") if p.strip()]
        return JobDoc(
            job_id=job_id,
            title=self.title,
            salary_raw=self.salary,
            salary_min=salary_min,
            salary_max=salary_max,
            company=self.company,
            href=self.href,
            account=account_id,
            location=location_parts,
        )


class JobDetailMeta(BaseModel):
    model_config = ConfigDict(frozen=True)
    """职位详情页 banner 区元数据（服务端渲染 DOM）。"""

    title: str = ""
    salary: str = ""
    location: str = ""
    experience: str = ""
    degree: str = ""
    tags: list[str] = []


class ChatMessage(BaseModel):
    model_config = ConfigDict(frozen=True)
    """单条聊天消息（来自已载入的 .message-item DOM）。"""

    mid: int = 0
    time: int = 0
    formateTime: str = ""
    isSelf: bool = False
    type: int = 0
    bodyType: int = 0
    fromName: str = ""
    text: str = ""
    status: int = 0
    messageType: str = ""
    securityId: str = ""
    uniqueId: str = ""
    friendId: int = 0
    friendSource: int = 0

    @classmethod
    def from_vue_message(cls, row: dict[str, Any]) -> ChatMessage:
        text = row.get("text") or ""
        return cls(
            mid=row.get("mid") or 0,
            time=row.get("time") or 0,
            formateTime=row.get("formateTime") or "",
            isSelf=bool(row.get("isSelf")),
            type=row.get("type") or 0,
            bodyType=row.get("bodyType") or 0,
            fromName=row.get("fromName") or "",
            text=text,
            status=row.get("status") or 0,
            messageType=str(row.get("messageType") or ""),
            securityId=row.get("securityId") or "",
            uniqueId=row.get("uniqueId") or "",
            friendId=row.get("friendId") or 0,
            friendSource=row.get("friendSource") or 0,
        )


class ConversationBoss(BaseModel):
    model_config = ConfigDict(frozen=True)
    """当前选中会话的 Boss/职位详情（来自 message-list.$data.boss）。"""

    name: str = ""
    company: str = ""
    hrTitle: str = ""
    jobName: str = ""
    positionName: str = ""
    locationName: str = ""
    jobTypeDesc: str = ""
    avatar: str = ""
    encryptBossId: str = ""
    encryptJobId: str = ""
    securityId: str = ""
    jobId: int = 0
    uniqueId: str = ""
    uid: int = 0
    friendId: int = 0
    friendSource: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def job_href(self) -> str:
        if self.encryptJobId:
            return f"https://www.zhipin.com/job_detail/{self.encryptJobId}.html"
        return ""

    @classmethod
    def from_vue_boss(cls, row: dict[str, Any]) -> ConversationBoss:
        return cls(
            name=row.get("name") or "",
            company=row.get("brandName") or "",
            hrTitle=row.get("title") or "",
            jobName=row.get("jobName") or "",
            positionName=row.get("positionName") or "",
            locationName=row.get("locationName") or "",
            jobTypeDesc=row.get("jobTypeDesc") or "",
            avatar=row.get("avatar") or "",
            encryptBossId=row.get("encryptBossId") or "",
            encryptJobId=row.get("encryptJobId") or "",
            securityId=row.get("securityId") or "",
            jobId=row.get("jobId") or 0,
            uniqueId=row.get("uniqueId") or "",
            uid=row.get("uid") or 0,
            friendId=row.get("friendId") or 0,
            friendSource=row.get("friendSource") or 0,
        )


class ConversationMeta(BaseModel):
    model_config = ConfigDict(frozen=True)
    """当前会话 message-list 分页/加载状态。"""

    page: int = 0
    pageSize: int = 0
    msgMinId: int = 0
    history: bool = False
    isToTop: bool = False
    loading: bool = False


class ChatItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    """聊天列表项数据。

    :ivar name: 招聘者姓名
    :ivar company: 公司名称
    :ivar position: HR 头衔（对应 Vue source.title）
    :ivar time: 最后消息时间文本（DOM 来源）或时间戳字符串（Vue 来源）
    :ivar lastMsg: 最后一条消息文本
    :ivar status: BOSS 平台状态文本（如 "已读"）
    :ivar sender: 发送方标识 ("self" | "other")
    :ivar unread_count: 未读消息数（0=已读, >0=对方未读条数, -1=未知）
    :ivar uniqueId: Vue 侧唯一标识（{uid}-{friendSource}）
    :ivar jobId: Boss 直聘职位数字 ID
    :ivar encryptJobId: 加密职位 ID，可拼职位详情 URL
    :ivar encryptBossId: 加密 Boss ID
    :ivar securityId: 会话 securityId
    """

    name: str
    company: str
    position: str
    time: str
    lastMsg: str
    status: str = ""
    sender: str = ""        # "self" | "other"
    unread_count: int = 0   # 0=已读, >0=对方未读条数, -1=未知
    uniqueId: str = ""
    jobId: int = 0
    encryptJobId: str = ""
    encryptBossId: str = ""
    securityId: str = ""
    lastMsgId: int = 0
    uid: int = 0
    friendId: int = 0
    friendSource: int = 0
    avatar: str = ""
    relationType: int = 0
    sourceTitle: str = ""
    isTop: int = 0
    note: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def job_href(self) -> str:
        if self.encryptJobId:
            return f"https://www.zhipin.com/job_detail/{self.encryptJobId}.html"
        return ""

    @classmethod
    def from_vue_row(cls, row: dict[str, Any]) -> ChatItem:
        """从 Vue __vue__.$props.source 构建 ChatItem。

        :param row: Vue source 原始 dict
        :returns: ChatItem 实例
        """
        name = row.get("name") or ""
        company = row.get("brandName") or ""
        position = row.get("title") or ""
        last_msg = row.get("lastText") or ""
        last_is_self = row.get("lastIsSelf", False)
        sender = "self" if last_is_self else "other"
        unread = row.get("unreadCount") or 0
        unique_id = row.get("uniqueId") or ""
        job_id = row.get("jobId") or 0
        last_msg_status = row.get("lastMsgStatus")

        # 毫秒时间戳 → ISO 格式
        last_ts = row.get("lastTS") or 0
        if last_ts:
            time_str = datetime.datetime.fromtimestamp(last_ts / 1000).isoformat()
        else:
            time_str = ""

        status = ""
        if last_msg_status == 2:
            status = "已读"
        elif last_msg_status == 1:
            status = "送达"

        # 文件消息覆写 sender / unread_count
        if last_msg.lower().endswith(".pdf"):
            sender = "self"
            unread = -1

        return cls(
            name=name,
            company=company,
            position=position,
            time=time_str,
            lastMsg=last_msg,
            status=status,
            sender=sender,
            unread_count=unread,
            uniqueId=unique_id,
            jobId=job_id,
            encryptJobId=row.get("encryptJobId") or "",
            encryptBossId=row.get("encryptBossId") or "",
            securityId=row.get("securityId") or "",
            lastMsgId=row.get("lastMsgId") or 0,
            uid=row.get("uid") or 0,
            friendId=row.get("friendId") or 0,
            friendSource=row.get("friendSource") or 0,
            avatar=row.get("avatar") or "",
            relationType=row.get("relationType") or 0,
            sourceTitle=row.get("sourceTitle") or "",
            isTop=row.get("isTop") or 0,
            note=row.get("note") or "",
        )

    def to_dict(self) -> dict[str, Any]:
        """转为普通 dict（序列化用）。"""
        return self.model_dump()

    def to_doc(self, account_id: str = "") -> ConvDoc:
        """转为 DB 文档模型。

        :param account_id: 关联的账号 ID
        :returns: ConvDoc 实例
        """
        conv_id = make_conv_id(account_id, self.name, self.company)
        parsed_time = parse_chat_time(self.time)
        linked_job_id = make_job_id(self.job_href) if self.job_href else None
        return ConvDoc(
            conv_id=conv_id,
            account=account_id,
            name=self.name,
            company=self.company,
            position=self.position,
            last_msg=self.lastMsg,
            last_msg_time=parsed_time,
            platform_status=self.status,
            sender=self.sender,
            unread_count=self.unread_count,
            unique_id=self.uniqueId,
            encrypt_boss_id=self.encryptBossId,
            encrypt_job_id=self.encryptJobId,
            linked_job_id=linked_job_id,
        )


_REJECTION_KWS: list[str | re.Pattern] = [
    "抱歉", "不好意思", "对不起", "不合适", "不适合",
    "荣幸", "遗憾", "谢谢", "祝",
    "感谢",
    re.compile(r"不.?匹配"),
]
_INVITE_RESUME_KWS = ["方便", "发", "附件"]
_INVITE_INTERVIEW_KWS = ["时间", "什么时候"]


def is_older_than_week(last_msg_time: str) -> bool:
    """判断 ISO 时间字符串是否超过 7 天。"""
    if not last_msg_time:
        return False
    try:
        dt = datetime.datetime.fromisoformat(last_msg_time)
        return (datetime.datetime.now() - dt) > datetime.timedelta(days=7)
    except (ValueError, TypeError):
        return False


_SYSTEM_RULES: list[str | re.Pattern] = [
    "对方已同意，您的附件简历已发送给对方",
    "工作地点我可以接受。",
    "已到达面试现场",
    "你撤回了一条消息",
    "已到面试时间，点击进入面试间",
    "我想要和您交换联系方式，您是否同意",
    re.compile(r"您的附件简历.+已发送给Boss"),
]


def classify_msg_type(last_msg: str, sender: str, platform_status: str = "") -> MsgType:
    """根据消息内容、发送方和平台状态判断内容分类。

    :param last_msg: 最后一条消息文本
    :param sender: 发送方标识 ("self" | "other")
    :param platform_status: 平台状态（已读/送达/空）
    :returns: 消息内容分类
    """
    for rule in _SYSTEM_RULES:
        if isinstance(rule, re.Pattern):
            if rule.search(last_msg):
                return MsgType.SYSTEM
        elif last_msg == rule:
            return MsgType.SYSTEM

    if sender == "self":
        if last_msg.lower().endswith(".pdf"):
            return MsgType.SYSTEM
        if last_msg.startswith("您好") and platform_status == "已读":
            return MsgType.REJECTION
        return MsgType.NORMAL

    for kw in _REJECTION_KWS:
        if isinstance(kw, re.Pattern):
            if kw.search(last_msg):
                return MsgType.REJECTION
        elif kw in last_msg:
            return MsgType.REJECTION

    if any(kw in last_msg for kw in _INVITE_INTERVIEW_KWS):
        return MsgType.INVITE_INTERVIEW
    if any(kw in last_msg for kw in _INVITE_RESUME_KWS):
        return MsgType.INVITE_RESUME

    return MsgType.NORMAL


def infer_status(sender: str, unread_count: int, old_status: str, last_msg_time: str = "") -> str:
    """推断行动性状态，不涉及消息内容分类。

    注意：不再保留 CLOSED（每次扫描根据页面现场重新推导），
    使得因滚动遗漏/误标而设为 CLOSED 的对话在再次出现时能自动恢复。
    """
    if sender == "self":
        return ConvStatus.NONE
    if unread_count > 0:
        if is_older_than_week(last_msg_time):
            return ConvStatus.FOLLOW_UP
        return ConvStatus.PENDING
    return ConvStatus.NONE
