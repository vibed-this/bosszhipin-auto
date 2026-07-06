from __future__ import annotations

from enum import StrEnum
from typing import Any, Dict, List, Literal, Optional, TypedDict, Union


class CommandName(StrEnum):
    OPEN_TAB = "open_tab"
    CLOSE_TAB = "close_tab"
    ACTIVATE_TAB = "activate_tab"
    RELOAD_TAB = "reload_tab"
    LIST_TABS = "list_tabs"
    EXECUTE = "execute"
    QUERY = "query"
    DUMP_HTML = "dump_html"


class EventName(StrEnum):
    SYNC_STATE = "sync_state"
    TAB_CREATED = "tab_created"
    TAB_UPDATED = "tab_updated"
    TAB_CLOSED = "tab_closed"
    TAB_ACTIVATED = "tab_activated"
    TAB_READY = "tab_ready"
    TAB_GONE = "tab_gone"
    TAB_CHANGED = "tab_changed"


class RemoteCallError(Exception):
    """Raised when a remote Socket.IO call returns an error response."""

    def __init__(self, event: str, message: str) -> None:
        self.event = event
        super().__init__(f"{event}: {message}")


class TabInfo(TypedDict):
    chromeTabId: int
    url: str
    title: str
    status: Optional[str]
    active: bool
    windowId: Optional[int]


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


class QueryMeta(TypedDict):
    url: str
    matched: int
    tookMs: int


class QueryResult(TypedDict):
    data: Any
    _meta: Optional[QueryMeta]
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
    windowId: Optional[int]


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


class RawElement(TypedDict):
    text: str
    html: str


class TabReadyEvent(TypedDict):
    type: Literal["tab_ready"]
    chromeTabId: int
    source: str
    url: str
    title: str
    status: Optional[str]
    active: bool
    windowId: Optional[int]


class TabGoneEvent(TypedDict):
    type: Literal["tab_gone"]
    chromeTabId: int
    source: str
    url: str
    title: str
    status: Optional[str]
    active: bool
    windowId: Optional[int]


class TabChangedEvent(TypedDict):
    type: Literal["tab_changed"]
    chromeTabId: int
    changes: Dict[str, Any]
    url: str
    title: str
    status: Optional[str]
    active: bool
    windowId: Optional[int]


TabEvent = Union[TabReadyEvent, TabGoneEvent, TabChangedEvent]