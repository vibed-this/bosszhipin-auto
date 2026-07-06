"""Browser 模块类型定义 — 替代 protocol/types.py。"""

from __future__ import annotations

from typing import Any, Literal, TypedDict


class QueryFilter(TypedDict, total=False):
    textContains: str
    textAny: str | list[str]
    textNone: str | list[str]
    nth: Literal["last"]
    index: int


class BboxResult(TypedDict):
    x: float
    y: float
    w: float
    h: float
    cx: float
    cy: float


class ProjectSpec(TypedDict, total=False):
    """project 参数：{key: "subSelector@attr"}"""

    pass


ProjectArg = dict[str, str]
FindResult = list[dict[str, Any]]
