"""应用配置 — TOML 文件读写 + Pydantic 校验。"""

from __future__ import annotations

import logging
import os
import tomllib
from pathlib import Path
from typing import Any

import tomli_w
from pydantic import BaseModel, ConfigDict

log = logging.getLogger("boss.config")


class BrowserConfig(BaseModel):
    """浏览器配置。

    :ivar profiles_dir: 浏览器用户数据目录
    """

    profiles_dir: str = "profiles"


class StorageConfig(BaseModel):
    """存储配置。

    :ivar db_path: TinyDB 数据库文件路径
    """

    db_path: str = "data/bzauto.db"


class ScrapeFilterConfig(BaseModel):
    """采集过滤配置。

    :ivar whitelist: 职位名称白名单（包含任一即匹配）
    :ivar blacklist: 关键字黑名单（采集时匹配 title；投递时再次匹配 JD）
    :ivar min_salary: 最低薪资过滤 (K)
    :ivar max_salary: 最高薪资过滤 (K)
    """

    whitelist: list[str] = ["前端", "全栈", "Web"]
    blacklist: list[str] = ["出差"]
    min_salary: int = 5
    max_salary: int = 7


class ScrapeConfig(BaseModel):
    """采集配置。

    :ivar scroll_timeout: 滚动超时（秒）
    :ivar page_load_timeout: 页面加载超时（秒）
    :ivar greeting: 打招呼语，为空时不发送；非空时使用新流程（跳转聊天页 + 自动发送）
    :ivar filter: 过滤条件
    """

    scroll_timeout: float = 5.0
    page_load_timeout: float = 20.0
    greeting: str = ""
    filter: ScrapeFilterConfig = ScrapeFilterConfig()


class FollowUpConfig(BaseModel):
    """跟进配置。

    :ivar enabled: 是否启用跟进
    :ivar days_threshold: 跟进天数阈值
    """

    enabled: bool = False
    days_threshold: int = 50


class ScheduleConfig(BaseModel):
    """定时调度配置。

    :ivar dispatch_times: 投递触发时间列表 (HH:MM)
    :ivar dispatch_batch_size: 每批投递数量上限
    :ivar dispatch_total_limit: 单次调度的总沟通上限（跨账号累计）
    :ivar scrape_threshold: 投递前触发采集的 pending 数量下限
    :ivar scrape_interval_minutes: 采集间隔（分钟）
    :ivar scan_interval_minutes: 消息扫描间隔（分钟）
    :ivar unread_trigger_enabled: 未读角标上升时自动触发单账号消息扫描
    :ivar unread_poll_seconds: 未读角标轮询间隔（秒）
    :ivar unread_scan_cooldown_minutes: 单账号未读触发扫描冷却（分钟）
    :ivar delete_chat_time: 消息删拒每天执行时间 (HH:MM)
    :ivar claim_timeout_minutes: claim 超时释放（分钟）
    """

    dispatch_times: list[str] = [
        "09:00", "10:00", "11:00", "13:00", "14:00",
        "15:00", "16:00", "17:00", "19:00", "20:00", "21:00",
    ]
    dispatch_batch_size: int = 20
    dispatch_total_limit: int = 200
    scrape_threshold: int = 50
    scrape_interval_minutes: int = 20
    scan_interval_minutes: int = 15
    unread_trigger_enabled: bool = True
    unread_poll_seconds: int = 5
    unread_scan_cooldown_minutes: int = 3
    delete_chat_time: str = "20:00"
    claim_timeout_minutes: int = 30


class NapCatConfig(BaseModel):
    """NapCat OneBot v11 配置。

    :ivar base_url: NapCat HTTP API 地址
    :ivar msg_type: 消息类型（group / private）
    :ivar target_id: 目标群号或用户号
    :ivar token: API 鉴权 Token
    """

    base_url: str = "http://127.0.0.1:3000"
    msg_type: str = "group"
    target_id: int = 123456789
    token: str = ""


class NotificationConfig(BaseModel):
    """通知配置。

    :ivar enabled: 是否启用通知
    :ivar merge: 是否合并多条通知
    :ivar napcat: NapCat 连接配置
    """

    enabled: bool = True
    merge: bool = True
    napcat: NapCatConfig = NapCatConfig()


class AccountConfig(BaseModel):
    """账号配置。

    :ivar id: 账号唯一标识
    :ivar name: 账号显示名称
    :ivar enabled: 是否启用
    :ivar role: 角色（scraper / dispatcher）
    :ivar daily_limit: 每日投递上限
    """

    id: str = ""
    name: str = ""
    enabled: bool = True
    role: str = "dispatcher"
    daily_limit: int = 150


class AppConfig(BaseModel):
    """顶层应用配置。

    拒绝未知字段（extra="forbid"），确保 TOML 中的拼写错误在加载时即可被发现。
    """

    model_config = ConfigDict(extra="forbid")

    browser: BrowserConfig = BrowserConfig()
    storage: StorageConfig = StorageConfig()
    scrape: ScrapeConfig = ScrapeConfig()
    follow_up: FollowUpConfig = FollowUpConfig()
    schedule: ScheduleConfig = ScheduleConfig()
    notification: NotificationConfig = NotificationConfig()
    accounts: list[AccountConfig] = []


_CONFIG: AppConfig | None = None
_CONFIG_PATH: Path | None = None


def _find_project_root() -> Path:
    """从当前文件位置推断项目根目录。"""
    return Path(__file__).resolve().parent.parent.parent


def _default_config_path() -> Path:
    return _find_project_root() / "config.toml"


def _write_default_template(path: Path) -> None:
    """写入默认配置文件模板。"""
    template = """\
[browser]
profiles_dir = "profiles"

[storage]
db_path = "data/bzauto.db"

[scrape]
scroll_timeout = 5.0
page_load_timeout = 20.0
greeting = ""

[scrape.filter]
whitelist = ["前端", "全栈", "Web"]
blacklist = ["出差"]
min_salary = 5
max_salary = 7

[follow_up]
enabled = false
days_threshold = 50

[schedule]
dispatch_times = ["09:00", "10:00", "11:00", "13:00", "14:00", "15:00", "16:00", "17:00", "19:00", "20:00", "21:00"]
dispatch_batch_size = 20
dispatch_total_limit = 200
scrape_threshold = 50
scan_interval_minutes = 15
unread_trigger_enabled = true
unread_poll_seconds = 5
unread_scan_cooldown_minutes = 3
delete_chat_time = "03:00"
claim_timeout_minutes = 30

[notification]
enabled = true
merge = true

[notification.napcat]
base_url = "http://127.0.0.1:3000"
msg_type = "group"
target_id = 123456789
token = ""

[[accounts]]
id = "main"
name = "主账号"
enabled = true
role = "scraper"
daily_limit = 150

[[accounts]]
id = "sub_1"
name = "子账号1"
enabled = true
role = "dispatcher"
daily_limit = 150
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(template.strip() + "\n", encoding="utf-8")
    log.info("已创建默认配置文件: %s", path)


def get_config() -> AppConfig:
    """获取全局配置单例。

    首次调用时从 TOML 文件加载，之后返回缓存。
    若文件不存在则创建默认模板。

    :returns: AppConfig 实例
    """
    global _CONFIG, _CONFIG_PATH
    if _CONFIG is not None:
        return _CONFIG
    path = _CONFIG_PATH or _default_config_path()
    if not path.exists():
        _write_default_template(path)
        log.warning("配置文件 %s 不存在，已创建默认模板，请编辑后重启", path)
    _CONFIG = _load_config(path)
    _CONFIG_PATH = path
    return _CONFIG


def reload_config() -> AppConfig:
    """重新加载配置文件。

    :returns: 新的 AppConfig 实例
    :raises FileNotFoundError: 配置文件不存在
    """
    global _CONFIG
    path = _CONFIG_PATH or _default_config_path()
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    _CONFIG = _load_config(path)
    log.info("配置已重载: %s", path)
    return _CONFIG


def _load_config(path: Path) -> AppConfig:
    """从 TOML 文件加载并校验配置。

    :param path: 配置文件路径
    :returns: 校验后的 AppConfig 实例
    """
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return AppConfig.model_validate(data)  # type: ignore[no-any-return]


def save_config(config: AppConfig, path: Path | None = None) -> None:
    """保存配置到 TOML 文件。

    :param config: AppConfig 实例
    :param path: 目标路径，None 则使用当前配置路径
    """
    p = path or _CONFIG_PATH or _default_config_path()
    data = _app_config_to_dict(config)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as f:
        tomli_w.dump(data, f)
    log.info("配置已保存: %s", p)


def _app_config_to_dict(config: AppConfig) -> dict:
    """将 AppConfig 转为可序列化的 dict。

    :param config: AppConfig 实例
    :returns: 纯 Python dict（适合 TOML 序列化）
    """
    return config.model_dump(exclude_defaults=False, mode="python")


def get_config_path() -> Path:
    """获取当前配置文件的路径。

    :returns: 配置文件路径
    """
    return _CONFIG_PATH or _default_config_path()
