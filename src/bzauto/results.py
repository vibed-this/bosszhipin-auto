"""Flow 执行结果模型 — pydantic BaseModel。

每个 Flow 的 run() 返回一个结果模型，Task 据此拼通知。
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from bzauto.models import ChatItem


class ScrapeChatResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    items: list[ChatItem] = []
    new: int = 0
    updated: int = 0
    deleted: int = 0
    rejections: list[ChatItem] = []
    unread: list[ChatItem] = []
    invite_resume: list[ChatItem] = []
    invite_interview: list[ChatItem] = []
    followed_up: int = 0


class DispatchResult(BaseModel):
    success: int = 0
    failed: int = 0
    skipped: bool = False
    skip_reason: str = ""


class ScrapeResult(BaseModel):
    scraped: int = 0
    skipped: bool = False
