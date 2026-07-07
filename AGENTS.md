任何时候执行修改前都必须向用户请求。
如果用户的输入里没有明确表示执行修改，那么禁止擅自修改文件。
如果用户打断进行提问，那么只需要回答用户的问题，回答完后禁止擅自开始执行改动，必须询问用户。
# bzauto

QWebEngineView 桌面浏览器自动控制，支持多账号独立 Profile、JS 远程执行、元素坐标查询、DB 持久化、定时调度。

## 项目结构

```
├── config.toml                   # 配置文件（TOML）
├── data/
│   └── bzauto.db                 # SQLite 数据库文件
├── profiles/                     # 每账号 QWebEngineProfile 持久化目录
├── test.py                       # Qt 事件模拟原型（参考）
├── src/
│   └── bzauto/
│       ├── __init__.py           # 顶层导出：browser, config, models, enums
│       ├── __main__.py           # python -m bzauto 启动 UI
│       ├── browser/              # ★ 核心：QWebEngineView 浏览器管理
│       │   ├── __init__.py       # 导出 BrowserManager, BrowserSession, get_browser_manager
│       │   ├── manager.py        # BrowserManager(QMainWindow) — QTabWidget + 每账号 Profile/View/Page
│       │   ├── session.py        # BrowserSession — 替代旧 TabSession，公开 API 见 §4
│       │   ├── js_helper.py      # JS_HELPER 字符串：window.__bz 查询引擎
│       │   ├── events.py         # Qt 事件模拟：send_click / send_wheel / send_key
│       │   ├── overlay.py        # DotOverlay 调试红点覆盖层
│       │   └── types.py          # QueryFilter / BboxResult / ProjectSpec
│       ├── analyze.py            # PageAnalyzer — BrowserSession 驱动的页面分析
│       ├── scrape_jobs.py        # BossJobsAuto 入口（最小 Qt 引导）
│       ├── scrape_chat_auto.py   # BossChatAuto 入口（最小 Qt 引导）
│       ├── config.py             # AppConfig + TOML 读写
│       ├── models.py             # JobCard / ChatItem
│       ├── enums.py              # JobStatus / DispatchStatus / ConvStatus
│       ├── storage.py            # Storage — sqlite-utils 仓库模式封装
│       ├── task_runner.py        # TaskRunner — 串行异步任务队列
│       ├── scheduler.py          # BzScheduler — APScheduler 定时调度
│       ├── notify.py             # NapCatNotifier + NotificationAggregator
│       ├── pages/
│       │   ├── base.py           # BasePage 基类
│       │   ├── job_list.py       # BossJobListPage — 职位列表页面对象
│       │   └── chat_list.py      # BossChatListPage — 聊天列表页面对象
│       ├── flows/
│       │   ├── base.py           # BaseFlow 基类
│       │   ├── scrape.py         # [已删除] 爬取+沟通混合版，拆分到 scrape_only + dispatch
│       │   ├── scrape_only.py    # BossScrapeOnlyFlow — 纯爬取
│       │   ├── scrape_chat.py    # BossScrapeChatFlow — 聊天爬取
│       │   ├── delete_chat.py    # BossDeleteChatFlow — 删拒
│       │   ├── dispatch.py       # DispatchFlow — DB pending → 沟通
│       │   └── scan.py           # ScanFlow — 编排 scrape_chat + delete_chat
│       └── ui/
│           ├── __init__.py       # BzAutoApp — qasync 引导 + 浮动面板
│           ├── control_panel.py  # 控制面板
│           ├── log_window.py     # 日志窗口
│           ├── config_dialog.py  # 配置对话框
│           └── data_window.py    # 数据管理窗口
├── pyproject.toml
├── AGENTS.md
├── README.md
├── uv.lock
└── plan.md
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
| `[storage]` | DB 路径 |
| `[scrape]` / `[scrape.filter]` | 采集参数 + 白名单/黑名单/薪资过滤 |
| `[delete]` | 删拒关键词 |
| `[follow_up]` | 跟进配置 |
| `[schedule]` | 定时调度 |
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
| **浏览器层 (browser/)** | QWebEngineView 内核。BrowserManager(QTabWidget) 管理多账号独立 Profile/View/Page；BrowserSession 提供查询原语 + Qt 事件模拟。无端口、无扩展、无 pyautogui |
| **PageObject (pages/)** | 页面模型层。管理选择器 + 页面操作方法（不包含控制流）。组合 BrowserSession |
| **Flow (flows/)** | 业务流程层。编排循环/条件/异常处理（页面不出现选择器）。组合 PageObject |
| **Storage** | TinyDB 持久化层。jobs/conversations/accounts/meta 四表 |
| **Scheduler** | APScheduler 定时调度层。按 cron 触发采集→投递→扫描 |
| **UI (Qt)** | qasync 单线程统一事件循环。BrowserManager 主窗口 + 浮动面板 |

Python 侧层次关系：

```
BrowserSession ← 组合 — PageObject ← 组合 — Flow
                                            ↑
                                    Storage (DB 持久化)
                                            ↑
                                Scheduler (定时触发 Flow)
```

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
- `bbox(select, filter)` — 返回 `{x,y,w,h,cx,cy}` 或 None（逻辑像素，Qt 处理 DPR）
- `find_all/find_one/count` — 声明式 DOM 查询
- `click(x,y)` — `events.send_click` → Qt `QMouseEvent`（Move→Press→Release）
- `click_element` — `bbox → click → 轮询 wait_visible/wait_hidden`

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

```python
from bzauto.storage import Storage
store = Storage()

# 仓库模式：store.<repo>.<method>()
store.jobs.upsert(doc)
store.jobs.list(dispatch_status="pending", limit=50)
store.jobs.claim(job_id, account_id)
store.jobs.mark_success(job_id)
store.jobs.release_stale_claims(timeout_minutes=30)

store.conversations.upsert(doc)
store.conversations.list(keyword="", status="", account="")
store.conversations.batch_upsert(account_id, items)

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
from bzauto.browser import get_browser_manager

loop = asyncio.get_event_loop()
runner = TaskRunner(loop)
storage = Storage()
scheduler = BzScheduler(runner, loop, storage)
scheduler.start()
```

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

所有 Flow 构造签名统一为 `(page, session, account_id, storage)`：

```python
from bzauto.flows.scrape_only import BossScrapeOnlyFlow
flow = BossScrapeOnlyFlow(page, session, "main", storage)
jobs = await flow.run(max_scrolls=10)

from bzauto.flows.dispatch import DispatchFlow
flow = DispatchFlow(page, session, "main", storage)
result = await flow.run(batch_size=50)

from bzauto.flows.scan import ScanFlow
flow = ScanFlow(session, "main", storage)
result = await flow.run()
```

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

## 约定

- 不使用 Playwright / Selenium / pyautogui
- 禁止使用 chrome-devtools-mcp
- 所有点击通过 `browser/events.py` 的 Qt 事件模拟（bbox → QMouseEvent）
- 所有 JS 执行通过 `page.runJavaScript`（eval_js 原语）
- 三层架构：BrowserSession（基础设施）← 组合 — PageObject（页面模型）← 组合 — Flow（业务流程）
- PageObject 不包含控制流（循环/条件），Flow 不出现选择器字符串
- 模块级单例 `get_browser_manager()` 替代旧 `get_registry()`
- 每账号独立 `QWebEngineProfile`，持久化到 `profiles/<id>/`
- 所有 Flow 接受 `account_id` + `Storage`，结果写入 DB

## 调试注意事项

- **需要手动登录一次**：首次启动 `profiles/<id>/` 为空，需在浏览器窗口内手动登录 Boss 直聘；之后 Cookie 持久化自动加载
- **点击失败检查**：用 `PageAnalyzer` 的 `dump_common_elements()` 确认选择器存在、`bbox()` 确认坐标非零
- **QWebEngineView 端检测**：Boss 直聘可能识别 QtWebEngine UA，`profile.setHttpUserAgent()` 可设成真实 Chrome 串
