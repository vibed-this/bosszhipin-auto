from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict, Union


class TabInfo(TypedDict):
    chromeTabId: int
    url: str
    title: str
    status: Optional[str]
    active: bool
    windowId: int


class QueryFilter(TypedDict, total=False):
    textContains: str
    textAny: Union[str, List[str]]
    textNone: Union[str, List[str]]
    nth: Literal["last"]
    index: int


class QueryArgs(TypedDict):
    select: str
    filter: Optional[QueryFilter]
    project: Optional[Dict[str, Union[str, List[str]]]]
    return_: Optional[QueryReturn]  # 在 JSON 中序列化为 "return"


QueryReturn = Literal["bbox", "bboxList", "list", "first", "count", "raw"]


class BboxCoords(TypedDict):
    x: int
    y: int
    w: int
    h: int
    cx: int
    cy: int


class BboxResult(TypedDict):
    css: BboxCoords
    physical: BboxCoords


class QueryResult(TypedDict):
    data: Any
    _meta: Optional[Dict[str, Any]]
    __error__: Optional[str]


class OpenTabArgs(TypedDict):
    url: str


class OpenTabResult(TypedDict):
    chromeTabId: int
    url: str


class CloseTabArgs(TypedDict):
    chromeTabId: int


class CloseTabResult(TypedDict):
    success: bool


class ActivateTabArgs(TypedDict):
    chromeTabId: int


class ActivateTabResult(TypedDict):
    success: bool


class ReloadTabArgs(TypedDict):
    chromeTabId: int


class ReloadTabResult(TypedDict):
    chromeTabId: int


class ListTabsArgs(TypedDict):
    pass


ListTabsResult = List[TabInfo]


class ExecuteArgs(TypedDict):
    chromeTabId: int
    execId: str


ExecuteResult = Any


class QueryCommandArgs(TypedDict):
    chromeTabId: int
    select: str
    filter: Optional[QueryFilter]
    project: Optional[Dict[str, Union[str, List[str]]]]
    return_: Optional[QueryReturn]  # 在 JSON 中序列化为 "return"


QueryCommandResult = QueryResult


class DumpHtmlArgs(TypedDict):
    chromeTabId: int


DumpHtmlResult = str


class TabCreatedPayload(TypedDict):
    chromeTabId: int
    url: str
    title: str
    status: Optional[str]
    active: bool
    windowId: int


class TabUpdatedPayload(TypedDict):
    chromeTabId: int
    url: Optional[str]
    title: Optional[str]
    status: Optional[str]


class TabClosedPayload(TypedDict):
    chromeTabId: int


class TabActivatedPayload(TypedDict):
    chromeTabId: int
    windowId: int


class SyncStatePayload(TypedDict):
    tabs: List[TabInfo]