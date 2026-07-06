// Command names
export const COMMAND_NAMES = {
  OPEN_TAB: 'open_tab',
  CLOSE_TAB: 'close_tab',
  ACTIVATE_TAB: 'activate_tab',
  RELOAD_TAB: 'reload_tab',
  LIST_TABS: 'list_tabs',
  EXECUTE: 'execute',
  QUERY: 'query',
  DUMP_HTML: 'dump_html',
} as const;

export type CommandName = (typeof COMMAND_NAMES)[keyof typeof COMMAND_NAMES];

// Event names
export const EVENT_NAMES = {
  SYNC_STATE: 'sync_state',
  TAB_CREATED: 'tab_created',
  TAB_UPDATED: 'tab_updated',
  TAB_CLOSED: 'tab_closed',
  TAB_ACTIVATED: 'tab_activated',
  TAB_READY: 'tab_ready',
  TAB_GONE: 'tab_gone',
  TAB_CHANGED: 'tab_changed',
} as const;

export type EventName = (typeof EVENT_NAMES)[keyof typeof EVENT_NAMES];

// Ack callback type
export type Ack = (result: any) => void;

// Tab info
export interface TabInfo {
  chromeTabId: number;
  url: string;
  title: string;
  status?: string;
  active: boolean;
  windowId: number;
}

// Query filter
export interface QueryFilter {
  textContains?: string;
  textAny?: string | string[];
  textNone?: string | string[];
  nth?: 'last';
  index?: number;
}

// Query args
export interface QueryArgs {
  select: string;
  filter?: QueryFilter;
  project?: Record<string, string | string[]>;
  return?: QueryReturn;
}

// Query return type
export type QueryReturn = 'bbox' | 'bboxList' | 'list' | 'first' | 'count' | 'raw';

// Bbox coordinates
export interface BboxCoords {
  x: number;
  y: number;
  w: number;
  h: number;
  cx: number;
  cy: number;
}

// Bbox result
export interface BboxResult {
  css: BboxCoords;
  physical: BboxCoords;
}

// Query result
export interface QueryMeta {
  url: string;
  matched: number;
  tookMs: number;
}

export interface QueryResult {
  data: any;
  _meta?: QueryMeta;
  __error__?: string;
}

// Raw element (return_="raw")
export interface RawElement {
  text: string;
  html: string;
}

// RPC command args/results
export interface OpenTabArgs {
  url: string;
}
export interface OpenTabResult {
  chromeTabId: number;
  url: string;
}

export interface CloseTabArgs {
  chromeTabId: number;
}
export interface CloseTabResult {
  success: boolean;
}

export interface ActivateTabArgs {
  chromeTabId: number;
}
export interface ActivateTabResult {
  success: boolean;
}

export interface ReloadTabArgs {
  chromeTabId: number;
}
export interface ReloadTabResult {
  chromeTabId: number;
}

export interface ListTabsArgs {}
export type ListTabsResult = TabInfo[];

export interface ExecuteArgs {
  chromeTabId: number;
  execId: string;
}
export type ExecuteResult = any;

export interface QueryCommandArgs {
  chromeTabId: number;
  select: string;
  filter?: QueryFilter;
  project?: Record<string, string | string[]>;
  return?: QueryReturn;
}
export type QueryCommandResult = QueryResult;

export interface DumpHtmlArgs {
  chromeTabId: number;
}
export type DumpHtmlResult = string;

// Tab event payloads
export interface TabCreatedPayload extends TabInfo {}
export interface TabUpdatedPayload {
  chromeTabId: number;
  url?: string;
  title?: string;
  status?: string;
}
export interface TabClosedPayload {
  chromeTabId: number;
}
export interface TabActivatedPayload {
  chromeTabId: number;
  windowId: number;
}
export interface SyncStatePayload {
  tabs: TabInfo[];
}