任何时候执行修改前都必须向用户请求。
如果用户的输入里没有明确表示执行修改，那么禁止擅自修改文件。
如果用户打断进行提问，那么只需要回答用户的问题，回答完后禁止擅自开始执行改动，必须询问用户。
# bzauto

QWebEngineView 桌面浏览器自动控制，支持多账号独立 Profile、JS 远程执行、元素坐标查询、DB 持久化、定时调度。

## 项目结构

```
├── config.toml                   # 配置文件（TOML）
├── data/
│   └── bzauto.db                 # SQLite 数据库文件（曾使用 TinyDB，已迁移）
├── profiles/                     # 每账号独立 QWebEngineProfile 持久化目录
├── scripts/
│   └── migrate_tinydb_to_sqlite.py  # 历史迁移脚本
├── src/
│   └── bzauto/
│       ├── __init__.py           # 顶层导出
│       ├── __main__.py
│       ├── analyze.py            # PageAnalyzer — 页面分析 CLI
│       ├── browser/              # ★ 核心：QWebEngineView 浏览器管理
│       │   ├── __init__.py       # 导出 BrowserManager, BrowserSession, get_browser_manager
│       │   ├── manager.py        # BrowserManager(QMainWindow) — 多账号标签页 + Profile
│       │   ├── session.py        # BrowserSession — 查询 + Qt 事件模拟 API
│       │   ├── js_helper.py      # window.__bz 查询引擎（页面注入）
│       │   ├── events.py         # Qt 事件模拟：send_click / send_wheel / send_key 等
│       │   ├── overlay.py        # DotOverlay 调试红点
│       │   └── types.py          # QueryFilter / BboxResult
│       ├── config.py             # AppConfig + TOML 读写（Pydantic）
│       ├── enums.py              # JobStatus / DispatchStatus / ConvStatus / RunStatus
│       ├── filter.py             # 黑名单匹配工具
│       ├── models.py             # JobCard / ChatItem（轻量数据类）
│       ├── models_doc.py         # JobDoc / ConvDoc / AccountDoc / RunDoc（Pydantic 持久化模型）
│       ├── results.py            # ScrapeResult / DispatchResult / ScrapeChatResult / UrgeResult
│       ├── storage.py            # Storage — sqlite-utils 仓库模式（JobRepo 等）
│       ├── task_runner.py        # TaskRunner — 串行异步任务队列
│       ├── scheduler.py          # BzScheduler + 各类 *Task
│       ├── notify.py             # NapCatNotifier + NotificationAggregator
│       ├── unread_watcher.py     # 未读角标自动触发扫描
│       ├── scrape_jobs.py        # 职位抓取 CLI 入口
│       ├── scrape_chat_auto.py   # 聊天抓取 CLI 入口
│       ├── pages/
│       │   ├── base.py           # BasePage 协议
│       │   ├── job_list.py       # BossJobListPage
│       │   ├── chat_list.py      # BossChatListPage
│       │   ├── job_detail.py     # BossJobDetailPage
│       │   └── header.py         # 头部/导航相关
│       ├── flows/
│       │   ├── base.py           # BaseFlow
│       │   ├── scrape_manual.py     # BossScrapeManualFlow — 手动/单次采集
│       │   ├── scrape_scheduled.py  # BossScrapeScheduledFlow — 定时采集编排
│       │   ├── scrape_chat.py       # BossScrapeChatFlow — 聊天列表爬取
│       │   ├── dispatch.py          # DispatchFlow — DB pending → 投递沟通
│       │   ├── scan.py              # ChatScanFlow — 仅聊天扫描
│       │   ├── delete_chat.py       # BossDeleteChatFlow — 删拒
│       │   └── urge.py              # UrgeFlow — 催促跟进
│       └── ui/
│           ├── __init__.py
│           ├── __main__.py          # UI 启动入口
│           ├── control_panel.py     # 控制面板
│           ├── status_panel.py      # 侧边状态面板
│           ├── log_window.py        # 日志窗口
│           ├── config_dialog.py     # 配置对话框
│           ├── data_window.py       # 数据管理窗口
│           ├── schedule_window.py   # 定时调度设置
│           ├── account_window.py    # 账号管理
│           └── debug_window.py      # 调试工具
├── pyproject.toml
├── AGENTS.md
├── README.md
├── uv.lock
```

## 命令

```bash
uv sync            # 安装/同步依赖
boss-ui            # 启动 Qt 桌面 UI（主窗口 + 控制面板 + 定时调度）
boss-analyze       # 页面分析 CLI
boss-scrape        # 抓取 CLI
boss-scrape-chat   # 聊天抓取 CLI
```

## 配置（config.toml）

| 节 | 说明 |
|---|---|
| `[browser]` | 浏览器配置（profiles_dir） |
| `[storage]` | DB 路径（SQLite） |
| `[scrape]` / `[scrape.filter]` | 采集参数 + 白名单/黑名单/薪资过滤 |
| `[follow_up]` | 跟进配置（enabled / days_threshold） |
| `[schedule]` | 定时调度（dispatch_times、batch 大小、阈值、未读触发、删拒时间、claim 超时等） |
| `[notification]` / `[notification.napcat]` | NapCat 通知 |
| `[[accounts]]` | 多账号配置（id/name/daily_limit/enabled/role） |

```python
from bzauto.config import get_config, save_config, reload_config

cfg = get_config()
cfg.scrape.filter.whitelist = ["前端", "全栈"]
save_config(cfg)
reload_config()
```

## 架构

| 层 | 说明 |
|---|---|
| **浏览器层 (browser/)** | QWebEngineView 内核。BrowserManager 管理多账号独立 Profile/View/Page；BrowserSession 提供查询原语 + Qt 事件模拟。无端口、无扩展、无 pyautogui |
| **PageObject (pages/)** | 页面模型层。管理选择器 + 操作方法（不含控制流）。目前有 job_list、chat_list、job_detail、header 等 |
| **Flow (flows/)** | 业务流程层。编排循环/条件/异常处理。组合 PageObject + Storage |
| **Storage** | SQLite + sqlite-utils + Pydantic（models_doc.py）持久化层。JobRepo / ConversationRepo / AccountRepo / RunRepo / MetaRepo / SeenHrefsRepo |
| **Scheduler** | APScheduler 定时调度层。Scrape / Dispatch / ChatScan / Urge / DeleteChat 等任务 |
| **UI (Qt)** | qasync 单线程统一事件循环。BrowserManager 主窗口 + 多个浮动/独立窗口 |

Python 侧层次关系：

```
BrowserSession ← 组合 — PageObject ← 组合 — Flow
                                            ↑
                                    Storage (DB 持久化)
                                            ↑
                                Scheduler (定时触发 Task → Flow)
```

Flow 执行通常返回 `results.py` 中的结果模型，用于通知和统计。

## BrowserSession API

```python
from bzauto.browser import get_browser_manager

bm = get_browser_manager()
session = bm.get_session("main")

await session.ensure_tab("https://www.zhipin.com/web/geek/jobs")
await session.activate()
await session.eval_js("return document.title")
await session.bbox("a.op-btn-chat")
await session.find_all("li.job-card-box", project={"title": ".job-name@text"})
await session.click(x, y)
await session.click_element("a.op-btn-chat")
await session.scroll_pagedown(presses=3)
```

- `eval_js(code)` — 直接执行 JS，返回 JSON 反序列化结果
- `bbox(select, filter)` — 返回 `{x,y,w,h,cx,cy}` 或 None（逻辑像素）
- `find_all / find_one / count` — 声明式 DOM 查询（支持 filter + project）
- `dump_html()` — 获取页面 HTML 快照
- `click(x, y) / mouse_move(x, y)` — Qt 事件模拟
- `scroll_wheel(...) / scroll_pagedown(...)` — 滚轮/翻页
- `click_element(select, ...)` — bbox → click + 可选 wait_visible / wait_hidden

## 查询引擎（`window.__bz`）

页面 `loadFinished` 时自动注入 `js_helper.py` 的 JS_HELPER。

- `filter`：`textContains` / `textAny` / `textNone` / `nth:"last"` / `index:int`
- `project`：`{"key": "subSelector@attr"}`，attr ∈ `text|html|href|index|<自定义属性>|class~name`

## BrowserManager

模块级单例 `get_browser_manager()`：
```python
from bzauto.browser import get_browser_manager

bm = get_browser_manager()
bm.connected_accounts()        # → ["main", "sub_1"]
session = bm.get_session("main")
page = bm.get_page("main")
view = bm.get_view("main")
```

## Storage API

Storage 使用 sqlite-utils + Pydantic（JobDoc / ConvDoc 等），仓库模式。

```python
from bzauto.storage import Storage
store = Storage()

# 仓库模式：store.<repo>.<method>()
store.jobs.upsert(doc)                    # 传入 JobDoc
store.jobs.list(dispatch_status="pending", limit=50)
store.jobs.claim(job_id, account_id)
store.jobs.mark_success(job_id)
store.jobs.mark_failed(job_id)
store.jobs.mark_filtered(job_id, note="...")
store.jobs.release_stale_claims(timeout_minutes=30)
store.jobs.count(today=True, dispatch_status=...)
store.jobs.update_status / update_note / delete

store.conversations.upsert(doc)
store.conversations.list(keyword="", status="", account="")
store.conversations.batch_upsert(account_id, items)
store.conversations.list_unreplied(account="")

store.accounts.list(enabled_only=True)
store.accounts.increment_daily_count(account_id)
store.accounts.get_remaining_quota(account_id)
store.accounts.reset_daily_counts_if_new_day()

store.seen_hrefs.get_all()
store.seen_hrefs.add(["href1", "href2"])

store.meta.get(key, default)
store.meta.set(key, value)

store.runs.insert(doc)
store.runs.list_recent(limit=50)

# 显式事务
with store.transaction():
    store.jobs.claim(job_id, account_id)
    store.jobs.mark_success(job_id)
    store.accounts.increment_daily_count(account_id)
```

## TaskRunner + Scheduler

```python
from bzauto.task_runner import TaskRunner, ScheduledTask
from bzauto.scheduler import BzScheduler
from bzauto.storage import Storage

loop = asyncio.get_event_loop()
runner = TaskRunner(loop)
storage = Storage()
scheduler = BzScheduler(runner, loop, storage)
scheduler.start()
```

内部定义了多个 Task：
- ScrapeTask / ScrapeManualTask
- DispatchTask
- ScrapeChatTask
- UrgeTask
- DeleteChatTask

调度器根据 config.schedule 自动注册 cron 任务。

## 通知系统

```python
from bzauto.notify import NapCatNotifier, NotificationAggregator, get_notifier

notifier = get_notifier()
await notifier.send("标题", "正文")

agg = NotificationAggregator(notifier, "报告标题")
agg.add_section("账号1", ["采集 10 个", "新对话 3 条"])
await agg.flush()
```

## Flow API

大多数 Flow 构造签名为 `(page, session, account_id, storage)`（部分如 ChatScanFlow、UrgeFlow 简化）：

```python
from bzauto.flows.scrape_manual import BossScrapeManualFlow
from bzauto.pages.job_list import BossJobListPage

flow = BossScrapeManualFlow(page, session, "main", storage)
result: ScrapeResult = await flow.run(max_scrolls=10)

from bzauto.flows.dispatch import DispatchFlow
flow = DispatchFlow(page, session, "main", storage)
result: DispatchResult = await flow.run(batch_size=50)

from bzauto.flows.scan import ChatScanFlow
from bzauto.pages.chat_list import BossChatListPage
flow = ChatScanFlow(page, session, "main", storage)
result: ScrapeChatResult = await flow.run()

from bzauto.flows.urge import UrgeFlow
flow = UrgeFlow(session, "main", storage)
result: UrgeResult = await flow.run()
```

调度器内部会根据配置编排 `BossScrapeScheduledFlow` + `DispatchFlow` + `ChatScanFlow` + `UrgeFlow` 等。

## 依赖

| 库 | 用途 |
|---|---|
| `pyside6` | Qt WebEngine 浏览器 + 桌面 UI |
| `qasync` | Qt + asyncio 统一事件循环 |
| `keyboard` | 全局热键（自起线程 → run_coroutine_threadsafe 投递） |
| `sqlite-utils` | SQLite 数据库工具库 |
| `apscheduler` | 定时调度 |
| `httpx` | 通知 HTTP 客户端 |
| `tomli_w` | TOML 写入 |
| `pydantic` | 配置 + 持久化模型 + 结果类型 |

## 约定

- 不使用 Playwright / Selenium / pyautogui
- 禁止使用 chrome-devtools-mcp
- 所有点击通过 `browser/events.py` 的 Qt 事件模拟（bbox → QMouseEvent）
- 所有 JS 执行通过 `page.runJavaScript`（eval_js 原语）
- 三层架构：BrowserSession ← PageObject ← Flow
- PageObject 不包含控制流，Flow 通常不直接写选择器
- 模块级单例 `get_browser_manager()`
- 每账号独立 `QWebEngineProfile`，持久化到 `profiles/<id>/`
- Flow 接受 `account_id` + `Storage`，结果通常返回 `results.*Result` 并写入 DB
- Storage 仓库返回 Pydantic 模型（models_doc.py）

## 调试注意事项

- **需要手动登录一次**：首次启动 `profiles/<id>/` 为空，需在浏览器窗口内手动登录 Boss 直聘；之后 Cookie 持久化自动加载
- **点击失败检查**：用 `boss-analyze` 或 `PageAnalyzer.dump_common_elements()` / `dump()` 确认选择器、`bbox()` 确认坐标
- **QWebEngineView 端检测**：Boss 直聘可能识别 QtWebEngine UA，可通过 `profile.setHttpUserAgent()` 设置真实 Chrome UA
- **查看数据**：使用 UI 的「数据管理」窗口或直接查询 `data/bzauto.db`
