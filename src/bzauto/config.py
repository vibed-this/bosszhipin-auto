from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomli_w

log = logging.getLogger("boss.config")


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8765


@dataclass
class StorageConfig:
    db_path: str = "data/bzauto.tinydb"


@dataclass
class ScrapeFilterConfig:
    whitelist: list[str] = field(default_factory=lambda: ["前端", "全栈", "Web"])
    blacklist: list[str] = field(default_factory=lambda: ["出差"])
    min_salary: int = 5
    max_salary: int = 7


@dataclass
class ScrapeConfig:
    scroll_timeout: float = 5.0
    page_load_timeout: float = 20.0
    filter: ScrapeFilterConfig = field(default_factory=ScrapeFilterConfig)


@dataclass
class DeleteConfig:
    keywords: list[str] = field(default_factory=lambda: ["抱歉", "不好意思", "对不起", "不合适", "不太合适", "荣幸", "遗憾", "不太匹配"])


@dataclass
class FollowUpConfig:
    enabled: bool = False
    days_threshold: int = 50


@dataclass
class ScheduleConfig:
    scrape_time: str = "08:00"
    dispatch_times: list[str] = field(default_factory=lambda: ["09:00", "14:00", "19:00"])
    dispatch_batch_size: int = 50
    scan_interval_minutes: int = 60
    claim_timeout_minutes: int = 30


@dataclass
class NapCatConfig:
    base_url: str = "http://127.0.0.1:3000"
    msg_type: str = "group"
    target_id: int = 123456789
    token: str = ""


@dataclass
class NotificationConfig:
    enabled: bool = True
    merge: bool = True
    napcat: NapCatConfig = field(default_factory=NapCatConfig)


@dataclass
class AccountConfig:
    id: str = ""
    name: str = ""
    profile: str = "Default"
    daily_limit: int = 150
    enabled: bool = True
    role: str = "dispatcher"


@dataclass
class AppConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    scrape: ScrapeConfig = field(default_factory=ScrapeConfig)
    delete: DeleteConfig = field(default_factory=DeleteConfig)
    follow_up: FollowUpConfig = field(default_factory=FollowUpConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    notification: NotificationConfig = field(default_factory=NotificationConfig)
    accounts: list[AccountConfig] = field(default_factory=list)


_CONFIG: AppConfig | None = None
_CONFIG_PATH: Path | None = None


def _find_project_root() -> Path:
    """从当前文件位置推断项目根目录。"""
    return Path(__file__).resolve().parent.parent.parent


def _default_config_path() -> Path:
    return _find_project_root() / "config.toml"


def _write_default_template(path: Path) -> None:
    template = """\
[server]
host = "127.0.0.1"
port = 8765

[storage]
db_path = "data/bzauto.tinydb"

[scrape]
scroll_timeout = 5.0
page_load_timeout = 20.0

[scrape.filter]
whitelist = ["前端", "全栈", "Web"]
blacklist = ["出差"]
min_salary = 5
max_salary = 7

[delete]
keywords = ["抱歉", "不好意思", "对不起", "不合适", "不太合适", "荣幸", "遗憾", "不太匹配"]

[follow_up]
enabled = false
days_threshold = 50

[schedule]
scrape_time = "08:00"
dispatch_times = ["09:00", "14:00", "19:00"]
dispatch_batch_size = 50
scan_interval_minutes = 60
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
profile = "Default"
daily_limit = 150
enabled = true
role = "scraper"

[[accounts]]
id = "sub_1"
name = "子账号1"
profile = "Profile 1"
daily_limit = 150
enabled = true
role = "dispatcher"
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(template.strip() + "\n", encoding="utf-8")
    log.info("已创建默认配置文件: %s", path)


def _dataclass_from_dict(cls: type, data: dict) -> Any:
    """递归将 dict 转为 dataclass。"""
    from dataclasses import fields
    field_types = {f.name: f.type for f in fields(cls)}
    kwargs = {}
    for key, value in data.items():
        if key in field_types:
            ft = field_types[key]
            if hasattr(ft, "__origin__") and ft.__origin__ is list:  # type: ignore[union-attr]
                inner = ft.__args__[0] if ft.__args__ else None  # type: ignore[union-attr]
                if inner and hasattr(inner, "__dataclass_fields__"):
                    kwargs[key] = [_dataclass_from_dict(inner, v) for v in value]
                else:
                    kwargs[key] = value
            elif hasattr(ft, "__dataclass_fields__"):
                kwargs[key] = _dataclass_from_dict(ft, value) if isinstance(value, dict) else ft()
            else:
                kwargs[key] = value
    return cls(**kwargs)


def _app_config_from_dict(data: dict) -> AppConfig:
    server = _dataclass_from_dict(ServerConfig, data.get("server", {}))
    storage = _dataclass_from_dict(StorageConfig, data.get("storage", {}))
    scrape_data = data.get("scrape", {})
    filter_data = scrape_data.pop("filter", {}) if isinstance(scrape_data, dict) else {}
    scrape = _dataclass_from_dict(ScrapeConfig, scrape_data)
    scrape.filter = _dataclass_from_dict(ScrapeFilterConfig, filter_data)
    delete = _dataclass_from_dict(DeleteConfig, data.get("delete", {}))
    follow_up = _dataclass_from_dict(FollowUpConfig, data.get("follow_up", {}))
    schedule = _dataclass_from_dict(ScheduleConfig, data.get("schedule", {}))
    notify_data = data.get("notification", {})
    napcat_data = notify_data.pop("napcat", {}) if isinstance(notify_data, dict) else {}
    notification = _dataclass_from_dict(NotificationConfig, notify_data)
    notification.napcat = _dataclass_from_dict(NapCatConfig, napcat_data)
    accounts = [_dataclass_from_dict(AccountConfig, a) for a in data.get("accounts", [])]
    return AppConfig(
        server=server,
        storage=storage,
        scrape=scrape,
        delete=delete,
        follow_up=follow_up,
        schedule=schedule,
        notification=notification,
        accounts=accounts,
    )


def get_config() -> AppConfig:
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
    global _CONFIG
    path = _CONFIG_PATH or _default_config_path()
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    _CONFIG = _load_config(path)
    log.info("配置已重载: %s", path)
    return _CONFIG


def _load_config(path: Path) -> AppConfig:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return _app_config_from_dict(data)


def save_config(config: AppConfig, path: Path | None = None) -> None:
    p = path or _CONFIG_PATH or _default_config_path()
    data = _app_config_to_dict(config)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as f:
        tomli_w.dump(data, f)
    log.info("配置已保存: %s", p)


def _app_config_to_dict(config: AppConfig) -> dict:
    def _to_dict(obj: Any) -> Any:
        if hasattr(obj, "__dataclass_fields__"):
            from dataclasses import fields
            return {f.name: _to_dict(getattr(obj, f.name)) for f in fields(obj)}
        if isinstance(obj, list):
            return [_to_dict(v) for v in obj]
        return obj
    return _to_dict(config)


def get_config_path() -> Path:
    return _CONFIG_PATH or _default_config_path()
