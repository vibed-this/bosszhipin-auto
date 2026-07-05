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
export interface QueryResult {
  data: any;
  _meta?: {
    url: string;
    matched: number;
    tookMs: number;
  };
  __error__?: string;
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