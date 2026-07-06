任何时候执行修改前都必须向用户请求。
如果用户的输入里没有明确表示执行修改，那么禁止擅自修改文件。
如果用户打断进行提问，那么只需要回答用户的问题，回答完后禁止擅自开始执行改动，必须询问用户。
# bzauto

Chrome 扩展 + Python 服务，远程控制 Boss直聘页面，支持 JS 远程执行、元素坐标查询、标签管理、DB 持久化、多账号定时调度。

## 项目结构

```
├── config.toml                   # 配置文件（TOML）
├── data/
│   └── bzauto.tinydb             # TinyDB 数据库文件
├── src/
│   └── bzauto/
│       ├── __init__.py           # 顶层导出：config, models, server, enums
│       ├── __main__.py           # python -m bzauto 启动服务
│       ├── analyze.py            # PageAnalyzer — 使用 TabSession 的页面分析工具
│       ├── scrape_jobs.py        # BossJobsAuto — 组合 TabSession + BossJobListPage + BossScrapeFlow 的入口
│       ├── scrape_chat_auto.py   # BossChatAuto — 聊天列表自动爬取入口
│       ├── config.py             # AppConfig 配置 Dataclass + TOML 读写（get_config, save_config, reload_config）
│       ├── models.py             # JobCard / ChatItem — 数据模型 + to_db_dict
│       ├── enums.py              # JobStatus / DispatchStatus / ConvStatus 常量
│       ├── storage.py            # Storage — TinyDB 封装（jobs / conversations / accounts / meta 四表）
│       ├── task_runner.py        # TaskRunner — 串行异步任务队列
│       ├── scheduler.py          # BzScheduler — APScheduler 定时调度（采集/投递/扫描）
│       ├── notify.py             # NapCatNotifier — OneBot v11 HTTP 通知 + NotificationAggregator
│       ├── protocol/
│       │   ├── __init__.py
│       │   └── types.py          # TypedDict 定义（与 TS 协议对齐）
│       ├── server/
│       │   ├── __init__.py       # 导出 TabRegistry, RemoteSession, TabSession, create_app, run_server, lifecycle
│       │   ├── registry.py       # TabRegistry — 标签状态、Socket.IO 服务器、执行 store、chromeTabId 映射
│       │   ├── remote_session.py # RemoteSession — Python API (sio.call RPC)
│       │   ├── tab_session.py    # TabSession — 基础设施层：服务器生命周期 + 标签管理 + 设备输入 + RemoteSession 代理
│       │   ├── session.py        # 向后兼容导入
│       │   ├── app.py            # Socket.IO ASGIApp + FastAPI — `/exec/{execId}` HTTP 端点
│       │   └── lifecycle.py      # 进程级单例 + ensure_tab 辅助
│       ├── pages/
│       │   ├── __init__.py
│       │   ├── job_list.py       # BossJobListPage — 职位列表页面对象（选择器 + 操作方法）
│       │   └── chat_list.py      # BossChatListPage — 聊天列表页面对象
│       ├── flows/
│       │   ├── __init__.py
│       │   ├── base.py           # BaseFlow — 所有 Flow 基类（page + session + account_id）
│       │   ├── scrape.py         # BossScrapeFlow — 爬取 + 沟通，存入 DB
│       │   ├── scrape_only.py    # BossScrapeOnlyFlow — 纯爬取，存入 DB
│       │   ├── scrape_chat.py    # BossScrapeChatFlow — 聊天列表爬取，存入 DB
│       │   ├── delete_chat.py    # BossDeleteChatFlow — 删拒聊天，存入 DB
│       │   ├── dispatch.py       # DispatchFlow — 从 DB pending 池取 job → href 定位 → 沟通
│       │   └── scan.py           # ScanFlow — 编排 scrape_chat + delete_chat 扫描任务
│       └── ui/
│           ├── __init__.py       # Qt 主窗口（BzAutoApp），整合 ControlPanel + LogWindow + ConfigDialog + DataWindow + Scheduler
│           ├── control_panel.py  # 控制面板（按钮组）
│           ├── log_window.py     # 日志窗口
│           ├── config_dialog.py  # 配置对话框（采集/调度/通知/账号 tab）
│           └── data_window.py    # 数据管理窗口（投递记录 + 对话记录 tab，CRUD + 搜索 + CSV 导出）
├── extension/                    # CRXJS + TypeScript 前端项目
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── manifest.json             # Chrome Extension MV3 清单（指向 TS）
│   ├── src/
│   │   ├── background/
│   │   │   ├── index.ts          # SW 入口
│   │   │   ├── socket.ts         # Socket.IO client 封装
│   │   │   ├── tab-manager.ts    # chrome.tabs 事件监听
│   │   │   ├── handlers.ts       # 服务端 RPC 命令处理器
│   │   │   ├── execute.ts        # MAIN world 注入逻辑
│   │   │   └── query-engine.ts   # 声明式 DOM 查询引擎
│   │   └── protocol/
│   │       └── types.ts          # 全部消息/事件类型定义
│   ├── src/options.html          # 选项页
│   ├── src/options.ts            # 选项页脚本
│   └── dist/                     # 构建产物（Chrome 加载此目录）
├── scripts/
│   └── bosszhipin-remote.user.js # (旧) 油猴脚本，推荐使用扩展替代
├── pyproject.toml
├── AGENTS.md
├── README.md
├── uv.lock
└── plan.md
```

## 命令

```bash
uv sync            # 安装/同步依赖
boss-server        # 启动服务 + 标签监控（CLI entry point）
boss-analyze       # 页面分析 CLI
boss-scrape        # 抓取 CLI
boss-scrape-chat   # 聊天抓取 CLI
boss-ui            # 启动 Qt 桌面 UI（带控制面板 + 定时调度）
```

## 配置（config.toml）

首次运行时自动在项目根目录生成 `config.toml`。

| 节 | 说明 |
|---|---|
| `[server]` | 服务监听 host / port |
| `[storage]` | DB 路径 |
| `[scrape]` / `[scrape.filter]` | 采集参数 + 白名单/黑名单/薪资过滤 |
| `[delete]` | 删拒关键词 |
| `[follow_up]` | 跟进配置（enabled / days_threshold） |
| `[schedule]` | 定时调度（投递时间/批量大小/扫描间隔） |
| `[notification]` / `[notification.napcat]` | NapCat OneBot v11 通知 |
| `[[accounts]]` | 多账号配置（id/name/profile/daily_limit/enabled/role） |

```python
from bzauto.config import get_config, save_config, reload_config

cfg = get_config()
cfg.scrape.filter.whitelist = ["前端", "全栈"]
save_config(cfg)
reload_config()
```

## 扩展安装

1. 浏览器打开 `chrome://extensions`
2. 打开 **开发者模式**
3. 点击 **加载已解压的扩展程序**，选择 `extension/dist/` 目录

## 扩展权限更新

安装新版本后需要手动在 `chrome://extensions` 点击 **更新** 以获取新增的 `tabs` 权限。

## 架构

| 层 | 说明 |
|---|---|
| **Chrome 扩展** | MV3。一条 Socket.IO 通道（background.js 连接，处理所有操作）。background.js 自动连接，开机/安装时启动 |
| **background.js** | Service Worker。连接 Socket.IO 服务器，处理 `open_tab` / `close_tab` / `activate_tab` / `reload_tab` / `list_tabs` / `execute` / `query`。自动重连 + engine.io ping/pong 保活 |
| **Python 服务** | FastAPI + Socket.IO。`/socket.io/` 端点接收 background.js 连接。`/exec/{execId}` HTTP 端点用于 MAIN world 代码注入（绕过 CSP）。所有 Python API 通过 `RemoteSession` 调用 |
| **TabSession** | 基础设施层。server 生命周期 + 标签管理 + pyautogui 设备输入 + RemoteSession 代理（自动注入 chromeTabId）。PageObject 和 Flow 不直接持有 chromeTabId |
| **PageObject** | 页面模型层。管理选择器 + 页面操作方法（不包含控制流）。组合 TabSession |
| **Flow** | 业务流程层。编排循环、条件、异常处理（不出现选择器）。组合 PageObject |
| **Storage** | TinyDB 持久化层。jobs / conversations / accounts / meta 四表，支持 claim/release、每日配额、已见去重 |
| **Scheduler** | APScheduler 定时调度层。按 cron 触发采集 → 投递 → 扫描，通知聚合 |
| **UI (Qt)** | PySide6 桌面界面。控制面板 + 日志 + 配置对话框 + 数据管理窗口 |

Python 侧层次关系：

```
TabSession  ← 组合 — PageObject  ← 组合 — Flow
                                            ↑
                                    Storage (DB 持久化)
                                            ↑
                                Scheduler (定时触发 Flow)
```

## 端点

| 端点 | 客户端 | 用途 |
|---|---|---|
| `/socket.io/` | background.js | 扩展后台命令（标签管理、JS 执行、DOM 查询） |
| `/exec/{execId}` | `<script>` 标签（页面 MAIN world） | HTTP GET，返回 JS 代码，注入到页面主 world |

## 消息协议

### `/socket.io/`（background.js）

服务 → 扩展：
- `open_tab(id, url)` — 创建标签
- `close_tab(id, chromeTabId)` — 关闭标签
- `activate_tab(id, chromeTabId)` — 激活标签窗口
- `reload_tab(id, chromeTabId)` — 刷新标签
- `list_tabs(id)` — 返回所有标签
- `execute(id, chromeTabId, execId)` — 执行 JS（通过 `<script>` 注入 MAIN world，绕过 CSP）
- `query(id, chromeTabId, select, filter, project, return)` — 声明式 DOM 查询（`chrome.scripting.executeScript`）

扩展 → 服务：`sync_state`, `tab_created`, `tab_updated`, `tab_closed`, `tab_activated`

### 通用

`execute` 通过注入 `<script src="/exec/{execId}">` 到 MAIN world，**绕过 CSP**，可访问 `window.*`、jQuery、React state等页面 JS 变量

`get_coordinates` / `bbox` 返回：
```json
{
  "css": { "x": 100, "y": 200 },
  "physical": { "x": 125, "y": 250 },
  "width": 80,
  "height": 32
}
```

## TabSession API（推荐）

```python
from bzauto.server import TabSession

async with TabSession(account_id="main") as session:
    await session.ensure_tab("https://www.zhipin.com/web/geek/jobs")
    await session.activate()
    await session.click(x, y)
    await session.scroll_pagedown(at_x=x, at_y=y, presses=3)
    result = await session.execute("return document.title")
    data = await session.query("li.job-card-box", project={"title": ".job-name@text"}, return_="list")
    bbox = await session.bbox("a.op-btn-chat")
```

## Storage API（TinyDB）

```python
from bzauto.storage import Storage

store = Storage()

# Jobs
store.upsert_job(job_dict)
store.get_pending_jobs(limit=50)
store.claim_job(job_id, account_id)        # 原子领取
store.mark_job_success(job_id)
store.release_stale_claims(timeout_minutes=30)

# Conversations
store.upsert_conversation(conv_dict)
store.search_conversations(keyword="", status="", account="")

# Accounts
store.get_enabled_accounts()
store.increment_daily_count(account_id)
store.get_remaining_quota(account_id)       # 当日剩余
store.reset_daily_counts_if_new_day()

# Meta (已见去重)
store.get_seen_job_hrefs()
store.add_seen_job_hrefs(["href1", "href2"])
```

## TaskRunner + Scheduler

```python
from bzauto.task_runner import TaskRunner, ScheduledTask
from bzauto.scheduler import BzScheduler
from bzauto.storage import Storage

loop = asyncio.new_event_loop()
runner = TaskRunner(loop)
storage = Storage()
scheduler = BzScheduler(runner, loop, storage)
scheduler.start()
# 自动按 config.toml [schedule] 定时触发采集/投递/扫描
```

## 通知系统

```python
from bzauto.notify import NapCatNotifier, NotificationAggregator, get_notifier

notifier = get_notifier()
await notifier.send("标题", "正文")

# 合并通知
agg = NotificationAggregator(notifier, "报告标题")
agg.add_section("账号1", ["采集 10 个", "新对话 3 条"])
await agg.flush()
```

## Flow API（业务流程层）

所有 Flow 接受 `account_id` + `Storage`，操作结果写入 DB：

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

## analyze.py — 页面分析工具

用于开发时分析页面 DOM 结构、查找弹窗、定位元素坐标。

### 用法

```python
from bzauto.analyze import PageAnalyzer

async def main():
    async with PageAnalyzer() as pa:
        await pa.connect()
        await pa.dump_common_elements()
        await pa.dump(".greet-boss-dialog")
        await pa.find_text("留在本页")
        b = await pa.bbox(".greet-boss-dialog .cancel-btn")
        if b:
            print(f"坐标: {b['physical']['cx']}, {b['physical']['cy']}")
        await pa.dump_visible_dialogs()
        await pa.snapshot()
```

### 原理

- 启动内嵌 uvicorn 服务，复用扩展的 WS 连接
- 所有 `dump` / `find_text` / `snapshot` 走 `session.query`（`chrome.scripting.executeScript`，绕过页面 CSP）
- `dump_visible_dialogs` 走 `session.execute`（通过 `<script>` 注入 MAIN world）
- 需要浏览器扩展已安装并连接到 WS

### 调试流程

1. 浏览器已打开 BOSS 直聘页面，扩展已连接
2. 运行分析脚本或直接在代码中引入 `PageAnalyzer`
3. 先用 `dump_common_elements()` 看有哪些弹窗类元素
4. 用 `find_text("留在此页")` 定位目标文本
5. 用 `bbox()` 获取点击坐标
6. 将确定的选择器和流程搬进 `src/bzauto/scrape_jobs.py`

## 依赖

| 库 | 用途 |
|---|---|
| `fastapi` / `uvicorn[standard]` | WebSocket + HTTP 服务 |
| `python-socketio` | Socket.IO 服务端 |
| `pyautogui` / `keyboard` | 桌面自动化（点击/滚屏/全局热键） |
| `pyside6` | Qt 桌面 UI（控制面板/配置/数据窗口） |
| `tinydb` | JSON 文件数据库 |
| `apscheduler` | 定时调度（cron / interval） |
| `httpx` | 通知 HTTP 客户端 |
| `tomli_w` | TOML 配置写入 |

## 约定

- 不使用 Playwright / Selenium 等浏览器自动化库
- 禁止使用 chrome-devtools-mcp（此项目通过自身 Chrome 扩展 + WS 协议控制浏览器，不使用 DevTools 协议）
- 标签管理走 `chrome.tabs` API（通过 ext WS），JS 执行和坐标走 content script（通过 tab WS）
- HTTP 端点 `/exec/{execId}` 仅对内网 localhost 开放，用于 MAIN world 代码注入
- Python API 直接在进程内调用 `RemoteSession`，不走网络
- 三层架构：TabSession（基础设施）← 组合 — PageObject（页面模型）← 组合 — Flow（业务流程）
- 所有 Flow 接受 `account_id` + `Storage`，结果写入 DB（不写 JSON 文件）
- PageObject 不包含控制流（循环/条件），Flow 不出现选择器字符串
- 不保留向后兼容的模块级全局状态
- 所有 Flow 构造函数签名统一为 `(page, session, account_id, storage)`

## 调试注意事项

- **不要用 Chrome DevTools MCP** — 此项目通过自身扩展的 Socket.IO 连接控制浏览器，DevTools 协议无法连接
- **`CancelledError` 是正常的** — uvicorn 内部在 WebSocket 连接关闭时会打印 `asyncio.CancelledError`，这是 asyncio 的正常行为，不影响功能
