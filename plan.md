# bosszhipin-auto 多账号自动化改造 — 执行计划

## 概述

本计划将 bosszhipin-auto 从单账号手动操作工具改造为多账号定时自动化系统。改造范围覆盖配置系统、多 profile 连接、TinyDB 持久化、napcat 通知、定时调度、PyQt CRUD 界面六个子系统。

改造后系统能力：主账号每日采集职位池 → 多个子账号定时投递（每日 3 轮 × 50 个）→ 所有账号每小时扫描消息列表（删拒 + 状态更新）→ 结果通过 napcat 合并通知。

### 依赖图

```
Phase 1 (Config)     ─┐
Phase 2 (Multi-Conn) ─┼─► Phase 3 (Storage) ──► Phase 5 (Flows) ──► Phase 6 (Scheduler) ──► Phase 8 (Integration)
                      │                       ─► Phase 4 (Notify)  ────────────────────────┘
                      └──────────────────────────────────────────────────► Phase 7 (UI) ────┘
```

Phase 1 和 Phase 2 互不依赖，可并行。Phase 3、4 依赖 Phase 1。Phase 5 依赖 1+2+3。Phase 6 依赖 3+4+5。Phase 7 依赖 1+3。Phase 8 依赖全部。

---

## 依赖变更

`pyproject.toml` 的 `dependencies` 新增：

```
tinydb>=4.8.0        # JSON 文档数据库
apscheduler>=3.10.0  # 定时调度（用 3.x 稳定版，不用 4.x）
httpx>=0.27.0        # napcat HTTP 调用（异步）
tomli_w>=1.0.0       # 写入 TOML（Python 3.11+ 自带 tomllib 读取，但无写入）
```

---

## Phase 1：配置系统

**目标：** 消除所有硬编码常量，集中到 `config.toml`，提供简单 UI。

### 1.1 创建 `config.toml`（项目根目录）

完整 schema（注释说明每个字段用途）：

```toml
[server]
host = "127.0.0.1"
port = 8765

[storage]
db_path = "data/bzauto.tinydb"

[scrape]
jobs_url = "https://www.zhipin.com/web/geek/jobs"
chat_url = "https://www.zhipin.com/web/geek/chat"
max_scrolls = 10
scroll_timeout = 5.0
page_load_timeout = 20.0

[scrape.filter]
whitelist = ["前端", "全栈", "Web"]
blacklist = ["出差"]
min_salary = 5
max_salary = 7

[delete]
keywords = ["抱歉", "不好意思", "对不起", "不合适", "不太合适", "荣幸"]

[follow_up]
enabled = false
days_threshold = 3

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
msg_type = "group"          # group | private
target_id = 123456789       # group_id 或 user_id
token = ""                  # Bearer token，无鉴权留空

[[accounts]]
id = "main"
name = "主账号"
profile = "Default"
daily_limit = 150
enabled = true
role = "scraper"            # scraper = 采集+投递; dispatcher = 仅投递

[[accounts]]
id = "sub_1"
name = "子账号1"
profile = "Profile 1"
daily_limit = 150
enabled = true
role = "dispatcher"
```

### 1.2 创建 `src/bzauto/config.py`

职责：加载 `config.toml` → dataclass 实例 → 全局可访问 + 支持热重载。

设计要点：

- 用 `tomllib`（3.11+ stdlib）读取，`tomli_w` 写入
- 定义 `@dataclass` 对应每个 section：`ServerConfig`, `StorageConfig`, `ScrapeConfig`, `ScrapeFilterConfig`, `DeleteConfig`, `FollowUpConfig`, `ScheduleConfig`, `NotificationConfig`, `NapCatConfig`, `AccountConfig`, `AppConfig`（顶层聚合）
- `AccountConfig` 包含 `id`, `name`, `profile`, `daily_limit`, `enabled`, `role`
- 模块级 `_config: AppConfig | None = None` + `get_config() -> AppConfig` + `reload_config() -> AppConfig`
- `get_config()` 首次调用时自动加载（lazy init），从 `config.toml` 所在路径推断项目根目录
- 配置文件不存在时创建默认模板并提示用户编辑

### 1.3 创建 `src/bzauto/ui/config_dialog.py`

职责：简单配置编辑对话框。

设计要点：

- `ConfigDialog(QDialog)`，内含 `QTabWidget`，4 个 tab：采集、调度、通知、账号
- 采集 tab：白名单（QLineEdit，逗号分隔）、黑名单、薪资下限/上限（QSpinBox）
- 调度 tab：投递时间（3 个 QLineEdit "09:00" 格式）、批量大小（QSpinBox）、扫描间隔（QSpinBox 分钟）
- 通知 tab：enabled（QCheckBox）、merge（QCheckBox）、napcat base_url、msg_type（QComboBox）、target_id、token
- 账号 tab：QTableWidget 显示 accounts 列表（id, name, profile, daily_limit, enabled, role），支持编辑
- 底部三按钮："保存"（tomli_w 写回 config.toml + reload_config()）、"在编辑器中打开"（`os.startfile`）、"重载"（仅 reload_config()，不写磁盘）
- 目标用户有能力直接改文件，所以表单只覆盖最常用字段，"在编辑器中打开"是主力编辑入口

### 1.4 集成到 ControlPanel

`control_panel.py` 新增 "配置" 按钮（在 "退出" 按钮上方，用 separator 隔开）。`BzAutoApp._setup_ui` 中连接 `btn_config.clicked.connect(lambda: ConfigDialog().exec())`。

### 1.5 迁移硬编码常量

将以下硬编码值迁移到 config 引用（搜索替换）：

| 原位置 | 原值 | 新引用 |
|--------|------|--------|
| `lifecycle.py:31` | `host="127.0.0.1"`, `port=8765` | `config.server.host/port` |
| `scrape.py:15-18` | 白名单/黑名单/薪资 | `config.scrape.filter.*` |
| `scrape_jobs.py:73` | 职位 URL | `config.scrape.jobs_url` |
| `scrape_chat_auto.py:74` | 聊天 URL | `config.scrape.chat_url` |
| `delete_chat.py:15` | 删除关键词 | `config.delete.keywords` |
| `job_list.py:67` | page_load_timeout=20 | `config.scrape.page_load_timeout` |
| `job_list.py` 各处 | max_scrolls=10, scroll_timeout=5 | `config.scrape.*` |

迁移方式：在 Flow / PageObject 构造时从 `get_config()` 读取，作为参数传入，不在模块级直接引用。

---

## Phase 2：多连接 Registry（地基）

**目标：** 支持多个 Chrome profile 同时连接，按 account_id 路由命令。这是整个改造中最关键的地基。

### 2.1 扩展：options page

在 `extension/src/` 下新建 `options.html` + `options.ts`：

- `options.html`：简单表单，一个文本输入框 "Account ID" + 保存按钮
- `options.ts`：读取/写入 `chrome.storage.local.set({ account_id: value })`
- 表单加载时从 `chrome.storage.local.get('account_id')` 回填当前值

`extension/manifest.json` 新增：

```json
{
  "options_ui": {
    "page": "src/options.html",
    "open_in_tab": false
  },
  "permissions": ["tabs", "storage"]
}
```

（`tabs` 已有，新增 `storage` 权限用于 `chrome.storage.local`）

### 2.2 扩展：连接时发送 account_id

修改 `extension/src/background/socket.ts`：

```typescript
socket.on('connect', () => {
  chrome.storage.local.get('account_id', (result) => {
    const accountId = result.account_id || 'default';
    socket.emit('register_account', { account_id: accountId });
    pushSyncState();
  });
});
```

`extension/src/background/index.ts` 的 `socket.on('connect')` 中移除直接 `pushSyncState()` 调用，改为在 `register_account` 回调后执行（避免竞态）。

### 2.3 Python：TabRegistry 多连接重构

这是最核心的改动。`registry.py` 从单连接改为多连接：

**新增数据结构 `AccountConnection`：**

```python
@dataclass
class AccountConnection:
    account_id: str
    sid: str
    tabs: dict[int, TabInfo] = field(default_factory=dict)
```

**TabRegistry 改造：**

- `self._sid: str | None` → `self._connections: dict[str, AccountConnection]`（key = account_id）
- `self._sid_by_sid: dict[str, str]`（反向映射 sid → account_id，用于事件处理时查找）
- `self._tabs` 移除，改为各 `AccountConnection` 各自持有
- `connect` handler：等待 `register_account` 事件后才注册连接（不信任 sid 直接做 account_id）
- 新增 `register_account` 事件处理：`{account_id}` → 创建 `AccountConnection`，建立 sid → account_id 映射
- `disconnect` handler：通过 `sid → account_id` 反查，移除对应连接
- `is_connected(account_id)` → 检查指定 account_id 是否有连接
- `call(event, data, account_id, timeout)` → 路由到 `self._connections[account_id].sid`
- `sync_state` / `tab_created` / `tab_updated` / `tab_closed` / `tab_activated` 事件：通过 sid → account_id 反查，更新对应 `AccountConnection.tabs`
- `tabs` property → 改为 `get_tabs(account_id) -> list[TabInfo]`
- `get_tab(chrome_tab_id)` → 需要知道 account_id，或遍历所有连接查找
- 事件广播 `_broadcast` 保持不变，但 `TabEvent` 消息中新增 `account_id` 字段
- `_exec_store` 保持全局（execId 是 uuid，不会冲突）

### 2.4 Python：RemoteSession / TabSession account_id 路由

**`remote_session.py`：**

- `__init__(self, registry, account_id: str = "default")` — 存储 account_id
- `call()` → `self._registry.call(event, data, account_id=self._account_id, timeout=...)`
- `open_tab(url)` → 返回结果中含 `chromeTabId`，存入 `AccountConnection.tabs`
- `list_tabs()` → `self._registry.get_tabs(self._account_id)`
- 其他方法（`execute`, `query`, `get_element_coordinates`, `activate_tab`, `close_tab`, `reload_tab`）透传 account_id
- `list_tracked_tabs()` → 从 `AccountConnection.tabs` 取

**`tab_session.py`：**

- `__init__(self, account_id: str = "default")` — 传入 account_id 给 RemoteSession
- `set_current()` → 确保当前 account_id 已连接
- `activate()` → `self._remote.activate_tab(self._chrome_tab_id)`，自动路由到正确 profile
- 其他方法不变，底层 RemoteSession 自动路由

**`lifecycle.py`：**

- `ensure_tab(account_id, url, reuse_existing)` — 等待指定 account_id 的扩展连接（`registry.is_connected(account_id)`），然后 open_tab / 复用
- `start_server()` — 不变，仍然是单例 FastAPI + Socket.IO 服务

### 2.5 扩展构建

改动完成后在 `extension/` 目录执行 `npm run build`，用户在 `chrome://extensions` 点击 "更新" 获取新的 `storage` 权限和 options page。

### 2.6 验证标准

- 两个 Chrome profile 各自安装扩展，各自在 options page 设置不同的 account_id
- Python 侧 `registry.is_connected("main")` 和 `registry.is_connected("sub_1")` 均返回 True
- 对两个账号分别 `open_tab` → 各自的 Chrome 窗口打开
- 对两个账号分别 `activate_tab` → 各自的窗口前置
- pyautogui 点击命中正确的窗口

---

## Phase 3：存储层

**目标：** TinyDB 封装，提供 jobs / conversations / accounts / meta 四张表的 CRUD + 调度逻辑。

### 3.1 创建 `src/bzauto/storage.py`

职责：TinyDB 实例管理 + 所有数据操作。

设计要点：

- `Storage` 类，`__init__(db_path: str)` → `TinyDB(db_path, indent=2, ensure_ascii=False)`
- 四张表：`self._db.table("jobs")`, `"conversations"`, `"accounts"`, `"meta"`
- TinyDB 的 `doc_id` 作为记录主键，业务 ID（`job_id`, `conv_id`）存为字段并用 `Query` 查询

### 3.2 表结构

**jobs 表：**

| 字段 | 类型 | 说明 |
|------|------|------|
| job_id | str | 从 href 提取的唯一 ID |
| title | str | 职位名 |
| salary_raw | str | 薪资原文 |
| salary_min | int | 薪资下限（K） |
| salary_max | int | 薪资上限（K） |
| company | str | 来自 .boss-name |
| href | str | 职位链接 |
| status | str | 投递状态 |
| account | str | 执行沟通的账号 ID |
| dispatch_status | str | pending / claimed / success / failed |
| dispatched_at | str | 调度时间 ISO 8601 |
| applied_at | str | 首次沟通时间 |
| last_updated | str | 最后更新时间 |
| note | str | 备注 |

**conversations 表：**

| 字段 | 类型 | 说明 |
|------|------|------|
| conv_id | str | 对话唯一 ID（hash of account+name+company） |
| account | str | 所属账号 |
| name | str | 对话对方名 |
| company | str | 公司名 |
| position | str | 职位名 |
| last_msg | str | 最后消息预览 |
| last_msg_time | str | 最后消息时间 |
| platform_status | str | 平台原始状态（如"已读"） |
| status | str | 业务状态 |
| status_changed_at | str | 状态变更时间 |
| linked_job_id | str | 关联投递岗位 |
| first_seen_at | str | 首次发现时间 |
| last_updated | str | 最后更新时间 |
| note | str | 备注 |

**accounts 表：**

| 字段 | 类型 | 说明 |
|------|------|------|
| account_id | str | 账号 ID |
| name | str | 昵称 |
| daily_count | int | 今日已沟通数 |
| daily_limit | int | 每日上限 |
| last_reset_date | str | 上次重置日期 |
| enabled | bool | 是否启用 |

**meta 表：**

key-value 结构，用于：`last_scrape_time`, `seen_job_hrefs`（去重集合）等。

### 3.3 状态枚举

在 `storage.py` 或单独的 `src/bzauto/enums.py` 中定义：

```python
class JobStatus:
    PENDING = "已沟通"
    GREETED = "已打招呼"
    HR_READ = "HR已读"
    HR_REPLIED = "HR已回复"
    INTERVIEW = "已邀面试"
    REJECTED = "已拒绝"
    CLOSED = "已结束"

class DispatchStatus:
    PENDING = "pending"
    CLAIMED = "claimed"
    SUCCESS = "success"
    FAILED = "failed"

class ConvStatus:
    NEW = "新对话"
    PENDING_REPLY = "待回复"
    REPLIED = "已回复"
    READ_NO_REPLY = "已读未回"
    REJECTION = "拒信"
    INVITATION = "邀约"
    DELETED = "已删除"
    CLOSED = "已结束"
```

### 3.4 核心 API

**Jobs 操作：**

- `upsert_job(job: dict) -> int` — 按 `job_id` upsert，存在则更新非空字段，不存在则插入
- `get_pending_jobs(limit: int) -> list[dict]` — 查询 `dispatch_status == "pending"`，按插入顺序取 limit 条
- `claim_job(job_id: str, account_id: str) -> bool` — 原子设置 `dispatch_status = "claimed"`, `account = account_id`, `dispatched_at = now`。用 TinyDB 的 `update` + 前置查询确保只 claim 仍为 pending 的记录
- `mark_job_success(job_id: str) -> None` — 设 `dispatch_status = "success"`, `status = "已沟通"`, `applied_at = now`
- `mark_job_failed(job_id: str) -> None` — 设 `dispatch_status = "failed"`
- `release_stale_claims(timeout_minutes: int) -> int` — 扫描 `dispatch_status == "claimed"` 且 `dispatched_at` 超时的记录，释放回 `pending`，返回释放数量
- `update_job_status(job_id: str, status: str) -> None` — 手动/自动更新投递状态
- `search_jobs(keyword: str = "", status: str = "") -> list[dict]` — 模糊搜索 + 状态过滤
- `delete_job(job_id: str) -> None`
- `update_job_note(job_id: str, note: str) -> None`

**Conversations 操作：**

- `upsert_conversation(conv: dict) -> bool` — 按 `conv_id` + `account` upsert。返回 True 表示新插入，False 表示更新
- `update_conv_status(conv_id: str, account: str, status: str) -> None` — 更新状态 + `status_changed_at = now`
- `get_conversations(account: str = "", status: str = "") -> list[dict]` — 按账号/状态筛选
- `search_conversations(keyword: str = "", status: str = "", account: str = "") -> list[dict]`
- `delete_conversation(conv_id: str, account: str) -> None`
- `mark_deleted(conv_id: str, account: str) -> None` — 标记 `status = "已删除"`（不物理删除）
- `get_conversations_by_status(status: str, account: str) -> list[dict]` — 用于删拒流程

**Accounts 操作：**

- `get_account(account_id: str) -> dict | None`
- `get_all_accounts() -> list[dict]`
- `get_enabled_accounts() -> list[dict]` — 从 config 读取 accounts 列表，与 DB 中 daily_count 合并
- `get_remaining_quota(account_id: str) -> int` — `daily_limit - daily_count`，自动跨天重置
- `increment_daily_count(account_id: str, n: int = 1) -> None`
- `reset_daily_count(account_id: str) -> None` — 跨天自动调用
- `set_daily_count_maxed(account_id: str) -> None` — 触发沟通上限时调用

**Meta 操作：**

- `get_meta(key: str, default=None) -> Any`
- `set_meta(key: str, value: Any) -> None`
- `get_seen_job_hrefs() -> set[str]` — 已采集过的 href 集合（去重用）
- `add_seen_job_hrefs(hrefs: list[str]) -> None`

### 3.5 conv_id 生成规则

`conv_id = hashlib.md5(f"{account_id}:{name}:{company}".encode()).hexdigest()[:12]`

同一账号下相同 name+company 视为同一对话。不同账号的同名对话是不同记录（因为 account_id 不同）。

### 3.6 job_id 生成规则

从 href 提取职位 ID。Boss 直聘职位链接格式通常为 `https://www.zhipin.com/job_detail/xxxxx.html` 或含 `securityId` 参数。提取路径段或生成 hash：

`job_id = href.rsplit("/", 1)[-1].replace(".html", "")` 或 fallback `hashlib.md5(href.encode()).hexdigest()[:12]`

---

## Phase 4：通知系统

**目标：** napcat 通知 + 多账号结果合并。

### 4.1 创建 `src/bzauto/notify.py`

**Notifier 接口：**

```python
class Notifier(Protocol):
    async def send(self, title: str, body: str) -> None: ...
```

**NapCatNotifier 实现（基于 OneBot v11 HTTP API）：**

- `__init__(self, base_url: str, msg_type: str, target_id: int, token: str = "")`
  - `msg_type = "group"` → endpoint = `/send_group_msg`, id_key = `"group_id"`
  - `msg_type = "private"` → endpoint = `/send_private_msg`, id_key = `"user_id"`
  - `self._url = f"{base_url}/{endpoint}"`
- `async def send(self, title: str, body: str) -> None`
  - Headers: `Content-Type: application/json`，有 token 则加 `Authorization: Bearer {token}`
  - Body: `{id_key: target_id, "message": f"{title}\n{body}"}`
  - 用 `httpx.AsyncClient` POST，`raise_for_status()` 检查
- `async def send_raw(self, message: str) -> None` — 直接发送原始消息文本（供 aggregator 调用）

**禁用时的空实现：**

```python
class NullNotifier:
    async def send(self, title: str, body: str) -> None: pass
```

`get_notifier() -> Notifier` — 根据 `config.notification` 创建对应实例。

### 4.2 NotificationAggregator（合并逻辑）

```python
class NotificationAggregator:
    def __init__(self, notifier: Notifier, title: str):
        self._notifier = notifier
        self._title = title
        self._sections: list[str] = []

    def add_section(self, account_name: str, lines: list[str]) -> None:
        self._sections.append(f"【{account_name}】\n" + "\n".join(lines))

    async def flush(self) -> None:
        if not self._sections:
            return
        body = "\n\n".join(self._sections)
        await self._notifier.send(self._title, body)
        self._sections.clear()
```

调度器在每轮任务（投递轮 / 扫描轮）开始时创建一个 aggregator，每个账号的结果 `add_section`，全部完成后 `flush()` 发送一条合并消息。

### 4.3 通知消息格式

**投递报告：**

```
📋 投递报告 07-06 09:00

【主账号】
投递 50 个 (成功 48, 失败 2)
今日已投 48/150

【子账号1】
投递 50 个 (成功 50, 失败 0)
今日已投 50/150

【子账号2】
投递 50 个 (成功 45, 失败 5)
今日已投 45/150

合计: 150 投递, 143 成功
```

**扫描报告：**

```
📬 消息扫描 07-06 10:00

【主账号】
删拒 3 条, 催促 0, 未读 2
  [李女士·某科技] 您好，方便聊聊吗？
  [王先生·某网络] 我们正在审核您的简历

【子账号1】
删拒 1 条, 催促 0, 未读 0

【子账号2】
无新消息
```

---

## Phase 5：流程重构

**目标：** 改造现有 Flow / PageObject，集成 DB 写入 + 多 profile + 状态管理。

### 5.1 BossScrapeFlow / BossScrapeOnlyFlow — 采集 + DB upsert

**涉及文件：** `flows/scrape.py`, `flows/scrape_only.py`, `scrape_jobs.py`

改造点：

- 构造时接收 `account_id` 参数，传给 `TabSession`
- `BossScrapeOnlyFlow.run()`（纯采集）：爬取每条 job card 后调用 `storage.upsert_job(...)` + `storage.add_seen_job_hrefs([href])`
- `BossScrapeFlow.run()`（采集 + 沟通）：同上，但在 `click_chat` 成功后调用 `storage.mark_job_success(job_id)` + `storage.increment_daily_count(account_id)`
- 过滤阶段：内存 `seen` 集合改为查询 `storage.get_seen_job_hrefs()` 做跨次去重
- 沟通前检查 `storage.get_remaining_quota(account_id)`，配额用尽则 break
- 参数从 config 读取（白名单、黑名单、薪资、max_scrolls 等）

### 5.2 新增 DispatchFlow — 从 DB 池取 job + 沟通

**新建文件：** `flows/dispatch.py`

这是投递任务的核心流程，与 `BossScrapeFlow` 的区别是：不爬取职位列表，而是从 DB 的 pending 池中取 job，按 href 定位到职位卡片，然后 click_chat。

流程：

```
1. storage.get_remaining_quota(account_id) → remaining
2. jobs = storage.get_pending_jobs(min(remaining, batch_size))
3. for job in jobs:
     a. storage.claim_job(job.job_id, account_id)  # 领取
     b. session.ensure_tab(jobs_url)               # 打开职位列表
     c. 在页面上定位 job 对应的卡片（通过 href 或 title+company 匹配）
     d. click_card → click_chat → dismiss_dialogs
     e. 成功: storage.mark_job_success(job.job_id) + storage.increment_daily_count(account_id)
     f. 失败: storage.mark_job_failed(job.job_id)
     g. 随机等待
4. 返回 {success: N, failed: M}
```

**定位卡片的方式：**

当前代码通过索引 `click_card_at(idx)` 定位卡片。DispatchFlow 需要通过 href 或 title 匹配。两种方案：

- 方案 A：打开职位列表 → 执行 JS 遍历 `li.job-card-box`，匹配 `a.job-name[href]` 包含目标 href → 得到 index → `click_card_at(index)`
- 方案 B：直接用 JS 找到匹配的卡片并 click（绕过索引机制）

推荐方案 A，复用现有 `click_card_at` + `click_chat` 逻辑，改动最小。

**注意：** pending 池中的 job 可能来自主账号的采集，但投递时使用子账号的 profile 打开职位列表。子账号的职位列表可能与主账号不同（推荐算法差异）。因此需要用 href 精确匹配，不能依赖列表顺序。如果列表中没有该 job（可能翻页太多），标记为 failed 跳过。

### 5.3 BossScrapeChatFlow — upsert conversations + 状态推断

**涉及文件：** `flows/scrape_chat.py`, `scrape_chat_auto.py`

改造点：

- 构造时接收 `account_id` 参数
- `run()` 爬取每条 ChatItem 后：
  1. 生成 `conv_id`
  2. `storage.upsert_conversation(...)` → 返回是否新插入
  3. 如果更新（非新插入）且 `last_msg` 变化 → 推断状态（见下方逻辑）
  4. 如果新插入 → `status = "新对话"`
- 爬取完成后，对 DB 中该账号有、但爬取列表中没有的对话 → `status = "已删除"`
- 返回 `{new: N, updated: M, deleted: K, rejections: list, unread: list}` 供通知使用

**状态推断逻辑：**

```python
def infer_status(last_msg: str, platform_status: str, old_status: str) -> str:
    # 拒信关键词匹配（复用 config.delete.keywords）
    if any(kw in last_msg for kw in config.delete.keywords):
        return ConvStatus.REJECTION
    # 邀约关键词匹配
    invitation_keywords = ["面试", "邀约", "到面", "面试邀请"]
    if any(kw in last_msg for kw in invitation_keywords):
        return ConvStatus.INVITATION
    # 消息变了且之前不是已回复 → 待回复
    if old_status not in (ConvStatus.REPLIED, ConvStatus.CLOSED, ConvStatus.DELETED):
        return ConvStatus.PENDING_REPLY
    return old_status  # 保持原状态
```

### 5.4 BossDeleteChatFlow — DB 驱动删拒

**涉及文件：** `flows/delete_chat.py`

当前逻辑：自己爬列表 → 关键词匹配 → 删除。

改造为 DB 驱动：

1. 从 `storage.get_conversations_by_status("拒信", account_id)` 获取待删对话列表
2. 在聊天列表页面上找到这些对话（通过 name+company 匹配）
3. 执行现有删除流程（click_chat_item → click_more → click_delete → confirm）
4. 删完后 `storage.mark_deleted(conv_id, account_id)`

保留原关键词匹配作为 fallback：如果 DB 中没有记录但页面上有新的拒信，仍用关键词匹配删除并写入 DB。

### 5.5 新增 ScanFlow — 扫描任务编排

**新建文件：** `flows/scan.py`

编排扫描任务的完整流程（供调度器调用）：

```python
class ScanFlow:
    def __init__(self, account_id: str):
        self.session = TabSession(account_id)
        self.chat_page = BossChatListPage(self.session)
        self.scrape_flow = BossScrapeChatFlow(self.chat_page, self.session, account_id)
        self.delete_flow = BossDeleteChatFlow(self.chat_page, self.session, account_id)

    async def run(self) -> dict:
        # 1. 爬取 + upsert conversations + 状态推断
        result = await self.scrape_flow.run(max_scrolls=config.scrape.max_scrolls)
        # 2. 删拒
        deleted = await self.delete_flow.run(dry_run=False)
        # 3. placeholder: 未读检测
        # 4. placeholder: 催促
        return {
            "new": result["new"],
            "updated": result["updated"],
            "deleted": len(deleted),
            "rejections": result["rejections"],
            "unread": result["unread"],  # placeholder: 空列表
            "followed_up": 0,            # placeholder
        }
```

### 5.6 models.py 更新

`JobCard` 和 `ChatItem` 保持 frozen dataclass 不变，但新增 `to_db_dict()` 方法生成 DB 文档格式（包含 `job_id`/`conv_id`、时间戳、状态等 DB 专属字段）。

或者更干净的方式：`storage.py` 接收 `JobCard`/`ChatItem` 实例，内部转换。这样 models.py 几乎不变。

---

## Phase 6：调度系统

**目标：** 定时触发采集/投递/扫描任务，串行执行，合并通知。

### 6.1 创建 `src/bzauto/task_runner.py`

串行任务队列，挂在现有后台 asyncio event loop 上：

```python
class TaskRunner:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._queue: asyncio.Queue[ScheduledTask] = asyncio.Queue()
        self._current: ScheduledTask | None = None
        self._loop.create_task(self._worker())

    async def submit(self, task: ScheduledTask) -> None:
        await self._queue.put(task)

    async def _worker(self):
        while True:
            task = await self._queue.get()
            self._current = task
            try:
                await task.execute()
            except Exception as e:
                log.error("任务异常: %s", e)
            self._current = None

    @property
    def is_busy(self) -> bool:
        return self._current is not None
```

`ScheduledTask` 基类：

```python
class ScheduledTask:
    name: str
    async def execute(self) -> dict: ...
```

### 6.2 创建 `src/bzauto/scheduler.py`

用 APScheduler 3.x 的 `AsyncIOScheduler`：

```python
class BzScheduler:
    def __init__(self, task_runner: TaskRunner, loop):
        self._scheduler = AsyncIOScheduler(event_loop=loop)
        self._runner = task_runner

    def start(self):
        cfg = get_config().schedule
        # 采集任务：每天 scrape_time
        self._scheduler.add_job(self._trigger_scrape, 'cron', **parse_cron_time(cfg.scrape_time))
        # 投递任务：每个 dispatch_time
        for t in cfg.dispatch_times:
            self._scheduler.add_job(self._trigger_dispatch, 'cron', **parse_cron_time(t))
        # 扫描任务：每 scan_interval_minutes
        self._scheduler.add_job(self._trigger_scan, 'interval', minutes=cfg.scan_interval_minutes)
        self._scheduler.start()

    async def _trigger_scrape(self):
        accounts = storage.get_enabled_accounts()
        scrapers = [a for a in accounts if a["role"] == "scraper"]
        agg = NotificationAggregator(get_notifier(), f"📋 采集报告 {now}")
        for acc in scrapers:
            await self._runner.submit(ScrapeTask(acc["id"]))
            # ScrapeTask 完成后结果加入 agg
        await agg.flush()

    async def _trigger_dispatch(self):
        accounts = storage.get_enabled_accounts()
        agg = NotificationAggregator(get_notifier(), f"📋 投递报告 {now}")
        for acc in accounts:
            task = DispatchTask(acc["id"], batch_size=config.schedule.dispatch_batch_size)
            await self._runner.submit(task)
            # task 完成后结果加入 agg
        await agg.flush()

    async def _trigger_scan(self):
        accounts = storage.get_enabled_accounts()
        agg = NotificationAggregator(get_notifier(), f"📬 消息扫描 {now}")
        for acc in accounts:
            await self._runner.submit(ScanTask(acc["id"]))
            # task 完成后结果加入 agg
        await agg.flush()
```

**注意 aggregator 的时序问题：** `task_runner.submit` 是异步的（放入队列后立即返回），但 aggregator flush 需要等所有 task 完成。解决方式：

- 方案 A：`submit` 改为 `await self._runner.submit_and_wait(task)` —— 提交后等待执行完毕再返回。这样 `_trigger_dispatch` 自然串行执行所有账号，最后 flush。
- 方案 B：用 `asyncio.Event` 或 future 追踪每个 task 的完成。

推荐方案 A，最简单。`submit_and_wait` 内部 `put` 到队列 + `await` 一个 future。

### 6.3 三种 Task 实现

**ScrapeTask：**

```python
class ScrapeTask(ScheduledTask):
    name = "采集"
    def __init__(self, account_id: str): ...
    async def execute(self) -> dict:
        # 检查 pending 池是否充足，不足才采集
        # 或者直接采集（配置驱动）
        session = TabSession(self.account_id)
        page = BossJobListPage(session)
        flow = BossScrapeOnlyFlow(page, session, self.account_id)
        jobs = await flow.run(max_scrolls=config.scrape.max_scrolls)
        return {"scraped": len(jobs)}
```

**DispatchTask：**

```python
class DispatchTask(ScheduledTask):
    name = "投递"
    def __init__(self, account_id: str, batch_size: int): ...
    async def execute(self) -> dict:
        # 启动时先释放超时 claim
        storage.release_stale_claims(config.schedule.claim_timeout_minutes)
        # 检查配额
        remaining = storage.get_remaining_quota(self.account_id)
        if remaining <= 0:
            return {"skipped": "配额已满"}
        # 如果 pending 池不够，先触发采集（仅 scraper 账号）
        pending_count = storage.count_pending_jobs()
        if pending_count < self.batch_size and self.is_scraper:
            await ScrapeTask(self.account_id).execute()
        # 执行投递
        flow = DispatchFlow(self.account_id)
        result = await flow.run(batch_size=min(remaining, self.batch_size))
        return result
```

**ScanTask：**

```python
class ScanTask(ScheduledTask):
    name = "扫描"
    def __init__(self, account_id: str): ...
    async def execute(self) -> dict:
        flow = ScanFlow(self.account_id)
        return await flow.run()
```

### 6.4 启动时恢复

`BzAutoApp.__init__` 或 `start_server` 之后：

- 调用 `storage.release_stale_claims(config.schedule.claim_timeout_minutes)` 释放卡住的 claim
- 调用 `storage.reset_daily_counts_if_new_day()` 跨天重置配额
- 启动 `BzScheduler`

### 6.5 parse_cron_time 辅助函数

将 "09:00" 转为 APScheduler cron 参数：`{"hour": 9, "minute": 0}`。简单字符串分割即可。

---

## Phase 7：UI

**目标：** PyQt 数据管理窗口 + 控制面板更新。

### 7.1 创建 `src/bzauto/ui/data_window.py`

`DataWindow(QWidget)`：带 `QTabWidget` 的独立窗口，两个 tab。

**投递记录 tab（JobsTab）：**

- 顶部工具栏：`QLineEdit`（搜索框，按 title/company 模糊搜索）、`QComboBox`（状态筛选：全部/已沟通/HR已读/HR已回复/已邀面试/已拒绝/已结束）、`QPushButton`("导出 CSV")
- 中间 `QTableWidget`：列 = 职位名, 公司, 薪资, 状态, 账号, 投递时间, 备注
  - 从 `storage.search_jobs(keyword, status)` 加载数据
  - 双击状态列 → `QComboBox` 编辑器弹出选择新状态
  - 双击备注列 → `QLineEdit` 编辑器
  - 右键菜单：修改状态 / 删除记录(确认弹窗) / 复制链接 / 打开职位页(`os.startfile(href)`)
- 底部状态栏：`总 X 条 | 筛选 Y 条 | 今日新增 Z 条`

**对话记录 tab（ConversationsTab）：**

- 顶部工具栏：搜索框、状态筛选（全部/新对话/待回复/已回复/已读未回/拒信/邀约/已删除）、账号筛选（全部/各账号）
- 中间 `QTableWidget`：列 = 招聘者, 公司, 职位, 最后消息, 平台状态, 业务状态, 账号, 时间, 备注
  - 双击业务状态列 → 修改状态
  - 右键菜单：修改状态 / 删除记录 / 关联岗位(弹窗选择 job) / 打开聊天页
- 底部状态栏：`总 X 条 | 待回复 Y 条 | 拒信 Z 条`

**数据刷新：**

- 窗口打开时自动加载
- 提供 "刷新" 按钮
- 后台任务完成后通过 signal 触发刷新（`BzAutoApp` 的 `_TaskBridge` 新增 `data_updated = Signal()`）

### 7.2 ControlPanel 更新

`control_panel.py` 新增按钮：

- "配置" → 打开 `ConfigDialog`
- "数据" → 打开 `DataWindow`

按钮布局（更新后的 ControlPanel）：

```
┌──────────────┐
│ 聊天爬取     │
│ 聊天删拒     │
│ ───────────  │
│ 职位爬取     │
│ 批量沟通     │
│ ───────────  │
│ 配置         │  ← 新增
│ 数据         │  ← 新增
│ ───────────  │
│ 退出 (Ctrl+E)│
└──────────────┘
```

### 7.3 BzAutoApp 集成

`ui/__init__.py` 的 `BzAutoApp`：

- `__init__` 中创建 `TaskRunner` + `BzScheduler`（在后台 loop 启动后）
- `_setup_ui` 中：新增 `self._data_win = DataWindow()`，连接 "数据" 按钮
- `_TaskBridge` 新增 `data_updated = Signal()`，任务完成后 emit，`DataWindow` 接收后刷新表格
- 手动按钮（聊天爬取、职位爬取等）保留，但内部改用新的 Flow（带 account_id 和 DB 写入）
  - 手动操作默认使用 "main" 账号
  - 或者增加账号选择下拉框

---

## Phase 8：集成与验收

### 8.1 新增/修改文件清单

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `config.toml` | 配置模板 |
| 新建 | `src/bzauto/config.py` | 配置加载/重载 |
| 新建 | `src/bzauto/storage.py` | TinyDB 封装 |
| 新建 | `src/bzauto/enums.py` | 状态枚举 |
| 新建 | `src/bzauto/notify.py` | napcat 通知 + aggregator |
| 新建 | `src/bzauto/task_runner.py` | 串行任务队列 |
| 新建 | `src/bzauto/scheduler.py` | APScheduler 调度 |
| 新建 | `src/bzauto/flows/dispatch.py` | DB 池投递流程 |
| 新建 | `src/bzauto/flows/scan.py` | 扫描任务编排 |
| 新建 | `src/bzauto/ui/config_dialog.py` | 配置对话框 |
| 新建 | `src/bzauto/ui/data_window.py` | CRUD 数据窗口 |
| 新建 | `extension/src/options.html` | 扩展选项页 |
| 新建 | `extension/src/options.ts` | 扩展选项逻辑 |
| 修改 | `src/bzauto/server/registry.py` | 多连接重构 |
| 修改 | `src/bzauto/server/remote_session.py` | account_id 路由 |
| 修改 | `src/bzauto/server/tab_session.py` | account_id 参数 |
| 修改 | `src/bzauto/server/lifecycle.py` | per-account ensure_tab |
| 修改 | `src/bzauto/flows/scrape.py` | DB upsert + config |
| 修改 | `src/bzauto/flows/scrape_only.py` | DB upsert + config |
| 修改 | `src/bzauto/flows/scrape_chat.py` | DB upsert + 状态推断 |
| 修改 | `src/bzauto/flows/delete_chat.py` | DB 驱动删拒 |
| 修改 | `src/bzauto/flows/base.py` | account_id 传递 |
| 修改 | `src/bzauto/pages/job_list.py` | href 定位卡片 |
| 修改 | `src/bzauto/pages/chat_list.py` | account_id |
| 修改 | `src/bzauto/pages/base.py` | account_id |
| 修改 | `src/bzauto/scrape_jobs.py` | config + DB |
| 修改 | `src/bzauto/scrape_chat_auto.py` | config + DB |
| 修改 | `src/bzauto/models.py` | to_db_dict() |
| 修改 | `src/bzauto/ui/__init__.py` | 集成 scheduler + data_window |
| 修改 | `src/bzauto/ui/control_panel.py` | 新增按钮 |
| 修改 | `extension/manifest.json` | options_ui + storage 权限 |
| 修改 | `extension/src/background/socket.ts` | 发送 account_id |
| 修改 | `extension/src/background/index.ts` | connect 时序调整 |
| 修改 | `pyproject.toml` | 新增依赖 |

### 8.2 验收检查项

**Phase 1 — 配置：**
- `config.toml` 不存在时自动创建默认模板
- 修改 config.toml 后点"重载"生效
- 所有原硬编码值已从 config 读取

**Phase 2 — 多连接：**
- 两个 profile 各自设置 account_id 后均能连接
- `registry.is_connected("main")` 和 `registry.is_connected("sub_1")` 均为 True
- 对不同账号 `activate_tab` → 各自窗口前置，pyautogui 点击命中正确窗口

**Phase 3 — 存储：**
- `upsert_job` 重复调用不产生重复记录
- `claim_job` 对已 claimed 的记录返回 False
- `release_stale_claims` 正确释放超时记录
- 跨天 `get_remaining_quota` 自动重置

**Phase 4 — 通知：**
- napcat 收到消息（先 curl 验证 napcat 本身，再验证 Python 调用）
- `merge=true` 时多账号结果合并为 1 条消息
- `merge=false` 时各发 1 条

**Phase 5 — 流程：**
- 采集后 DB 中有 pending 记录
- 投递后对应记录 dispatch_status = success, status = 已沟通
- 扫描后 conversations 表有记录，状态推断正确
- 删拒后 DB 中 status = 已删除

**Phase 6 — 调度：**
- 到达 dispatch_time 时自动触发投递
- 每 scan_interval_minutes 自动触发扫描
- 任务串行，无并发
- 通知合并为 1 条
- 重启后释放 stale claims + 重置跨天配额

**Phase 7 — UI：**
- DataWindow 表格正确显示 DB 数据
- 搜索/筛选生效
- 双击编辑状态/备注 → DB 更新 → 表格刷新
- 右键删除 → 确认弹窗 → DB 删除 → 表格刷新

### 8.3 实施顺序建议

```
Phase 1 (Config)     ─┐ 可并行
Phase 2 (Multi-Conn) ─┘
         │
         ▼
Phase 3 (Storage) ─► Phase 4 (Notify) ─┐ 可并行
         │                              │
         ▼                              ▼
Phase 5 (Flows) ◄───────────────────────┘
         │
         ▼
Phase 6 (Scheduler)
         │
         ▼
Phase 7 (UI)
         │
         ▼
Phase 8 (验收)
```

每个 Phase 完成后做对应验收检查，再进入下一个 Phase。
