下面是完整重构方案。看完确认（或调整）后我再动文件。

## 1. 设计决策（已锁定）

内核 QWebEngineView；单窗口 QTabWidget，每账号一个标签页 + 独立 `QWebEngineProfile` 持久化到 `profiles/<account_id>/`；任务串行，运行前自动切到对应标签页；所有点击统一 bbox → QMouseEvent；主窗口 = 浏览器标签页，控制/日志/配置/数据窗口浮动；qasync 单线程统一事件循环；server 层整体移除；大范围重构但保留 bbox 坐标概念。

## 2. 新架构

```
┌──────────────────────────────────────────────┐
│  UI 层     主窗口(QTabWidget 多账号浏览器)     │
│            + 浮动 ControlPanel/LogWindow/      │
│            ConfigDialog/DataWindow/DebugWindow │
├──────────────────────────────────────────────┤
│  qasync 单一事件循环（Qt = asyncio）           │
├──────────────────────────────────────────────┤
│  Scheduler (APScheduler AsyncIOScheduler)     │
│  TaskRunner (asyncio.Queue 串行)               │
├──────────────────────────────────────────────┤
│  Flow 层   scrape/dispatch/scan/...            │  ← 几乎不动
├──────────────────────────────────────────────┤
│  Page 层   BossJobListPage / BossChatListPage  │  ← 改：统一点击 + 新查询原语
├══════════════════════════════════════════════╡  ← 重构缝
│  ★ browser/  BrowserManager + BrowserSession   │  ← 全新，替代 server/ + extension/
│            + js_helper + events + overlay      │
├──────────────────────────────────────────────┤
│  Storage / Config / Models / Notify            │  ← 不动
└──────────────────────────────────────────────┘
```

没有监听端口、没有 uvicorn、没有 FastAPI、没有 Socket.IO、没有扩展、没有 pyautogui。

## 3. 新目录结构

```
src/bzauto/
├── browser/                    # ★ 新：替代 server/ + extension/
│   ├── __init__.py             # 导出 BrowserManager, BrowserSession, get_browser_manager
│   ├── manager.py              # BrowserManager(QMainWindow) — QTabWidget + 每账号 Profile/View/Page
│   ├── session.py              # BrowserSession — TabSession 替代，公开 API 见 §4
│   ├── js_helper.py            # JS_HELPER 字符串：window.__bz 查询引擎（query-engine.ts 翻译版）
│   ├── events.py               # Qt 事件模拟：send_click / send_wheel / send_key
│   ├── overlay.py              # DotOverlay（test.py 的红点调试覆盖层）
│   └── types.py                # QueryFilter / BboxResult / ProjectSpec
├── pages/                      # 改：用新原语 + 统一点击
├── flows/                      # 几乎不动（仅 ensure_tab 调用方式 + 构造参）
├── ui/                         # 改：qasync 引导 + 主窗口 QTabWidget + 浮动面板
├── storage.py / config.py / models*.py / enums.py / notify.py / scheduler.py / task_runner.py  # 不动或轻改
├── analyze.py / scrape_jobs.py / scrape_chat_auto.py / __main__.py  # 改引导
└── (删除) server/ protocol/
extension/                      # 整目录删除
scripts/bosszhipin-remote.user.js  # 删除
```

## 4. BrowserSession 契约（核心）

`TabSession` 的替代。保留 bbox/click/click_element/scroll 概念，砍掉 chromeTabId/tab_id/set_current/refresh_tab（每账号就一个固定 view，无需管理）。

```python
class BrowserSession:
    def __init__(self, manager: BrowserManager, account_id: str)
    @property
    def account_id(self) -> str
    @property
    def current_url(self) -> str | None

    async def ensure_tab(self, url: str | None = None, *,
                         reuse_existing: bool = False, timeout: float = 20.0) -> None
    async def activate(self) -> None          # 切 QTabWidget 到本账号 + raise + setFocus

    # —— 查询原语（拆掉旧 query 的 return_ 五模式）——
    async def eval_js(self, code: str, *, timeout: float = 30.0) -> Any
    async def bbox(self, select: str, *, filter: QueryFilter | None = None,
                   timeout: float = 30.0) -> BboxResult | None
    async def find_all(self, select: str, *, filter: QueryFilter | None = None,
                       project: dict[str, str] | None = None, timeout: float = 30.0) -> list[dict]
    async def find_one(self, select: str, *, filter: QueryFilter | None = None,
                       project: dict[str, str] | None = None, timeout: float = 30.0) -> dict | None
    async def count(self, select: str, *, filter: QueryFilter | None = None,
                    timeout: float = 30.0) -> int
    async def dump_html(self, *, timeout: float = 30.0) -> str | None

    # —— 设备输入（Qt 事件模拟，test.py 路径）——
    async def click(self, x: int, y: int) -> None
    async def scroll_wheel(self, dy: int, *, at_x: int | None = None,
                           at_y: int | None = None, presses: int = 1) -> None
    async def scroll_pagedown(self, *, at_x: int | None = None,
                              at_y: int | None = None, presses: int = 3) -> None

    # —— 组合 ——
    async def click_element(self, select: str, *, filter: QueryFilter | None = None,
                            wait_visible: str | None = None, wait_hidden: str | None = None,
                            timeout: float = 30.0, post_sleep: float = 0.5) -> None
```

实现要点：
- `eval_js`：`page.runJavaScript(code, cb)`，`cb` 在 qasync 循环上触发，resolve 一个 Future，`await asyncio.wait_for(fut, timeout)`。
- `bbox`：`eval_js("return window.__bz.bboxOf(select, filter)")` → `{x,y,w,h,cx,cy}` 或 null。坐标即 `getBoundingClientRect()`，控件相对逻辑像素，无 css/physical 双层、无 DPR 换算（Qt 内部处理 HiDPI）。
- `find_all/find_one/count`：`window.__bz.findAll/selectOne/count(select, filter, project)`。
- `click(x,y)`：`await self.activate()` → `events.send_click(view, x, y)`，走 `view.focusProxy()` + `QApplication.sendEvent` 的 Move→Press→Release 链（test.py 已验证）。
- `click_element`：`bbox → click(cx,cy) → 轮询 wait_visible/wait_hidden`，逻辑同旧版，只换底层。
- `ensure_tab(url, reuse_existing)`：`page.load(QUrl(url))`，等 `loadFinished` 

## 5. 查询引擎（js_helper.py）

把 `extension/src/background/query-engine.ts` 翻译成一段注入 JS，挂到 `window.__bz`。保留 `filter` 和 `project` 两个 mini-DSL（紧凑、pages 可读、省往返），砍掉 `return_` 五模式（拆成 §4 的独立方法）。

- `filter`：`textContains` / `textAny` / `textNone` / `nth:"last"` / `index:int`
- `project`：`{"key": "subSelector@attr"}`，attr ∈ `text|html|href|index|<自定义属性>|class~name`
- `bboxOf(select, filter)`：scrollIntoView({block:'center'}) → getBoundingClientRect → `{x,y,w,h,cx,cy}`

注入时机：每个账号 `QWebEnginePage.loadFinished` 时 `runJavaScript(JS_HELPER)`。

## 6. BrowserManager

```python
class BrowserManager(QMainWindow):
    def __init__(self, storage, config):
        # central = QTabWidget
        # 对每个 enabled account:
        #   profile = QWebEngineProfile(account_id)
        #   profile.setPersistentStoragePath(f"{profiles_dir}/{account_id}")
        #   profile.setPersistentCookiesPolicy(ForcePersistentCookies)
        #   page = BzWebEnginePage(profile, view)   # createWindow→原页导航; loadFinished→注入 JS_HELPER
        #   view = QWebEngineView(); view.setPage(page)
        #   overlay = DotOverlay(view)
        #   tab.addTab(view, account.name)
        #   self._sessions[account_id] = BrowserSession(self, account_id)
    def activate_account(self, account_id) -> None      # setCurrentIndex + raise + setFocus
    def get_page(self, account_id) -> QWebEnginePage
    def get_view(self, account_id) -> QWebEngineView
    def get_session(self, account_id) -> BrowserSession
    def connected_accounts(self) -> list[str]            # 替代旧 get_registry().get_connected_accounts()
```

模块级单例 `get_browser_manager()`（替代旧 `get_registry()`），scheduler 各 Task 通过它拿 session。

## 7. events.py（Qt 事件模拟）

照搬 test.py 的手法，封装成可复用函数：
- `send_click(view, x, y)`：`target = view.focusProxy() or view`；`pos=QPointF(x,y)`；`global=view.mapToGlobal(pos.toPoint())`；构造 Move→Press→Release 三个 `QMouseEvent`，`view.setFocus()` 后 `QApplication.sendEvent(target, e)`。
- `send_wheel(view, dy, at_x, at_y, presses)`：`QWheelEvent`。
- `send_key(view, key, presses)`：`QKeyEvent` Press/Release（PageDown 用这个）。
- 全在 qasync 主线程执行，flows 的 `await` 直达，无跨线程。

## 8. pages/ 改动

原则：**所有点击 → `click_element`/`bbox`+`click`（Qt）；所有读取 → `find_all`/`find_one`/`count`/`eval_js`**。禁止 JS `.click()`。

- `base.py`：`_count` → `session.count(...)`；`_wait_visible/_wait_hidden` 用 `session.bbox`；其余逻辑不变。
- `job_list.py`：
  - `get_job_cards` → `find_all(_JOB_ITEM, project={...})`
  - `click_card_at`：旧版 JS `el.click()` → 改 `click_element(_JOB_ITEM, filter={index})`
  - `click_expect_tab`：旧 JS `.click()` → `click_element`
  - `click_chat` / `dismiss_dialogs`：本来就是 bbox→click，底层自动变 Qt，不动逻辑
  - `find_card_by_href`：保留 `eval_js`（纯查询，返回 index），再 `click_card_at`
  - `iter_job_cards` 滚动：`scroll_wheel`（现 Qt）+ `eval_js` 滚容器，逻辑不变
- `chat_list.py`：点击方法本就用 `click_element`，自动变 Qt；`get_chat_items/get_labels` → `find_all`。

## 9. flows/ 改动（最小）

- `base.py`：`_setup` 里 `await ensure_tab(self._session, url, ...)` → `await self._session.ensure_tab(url, ...)`。
- 各 Flow 构造签名 `(page, session, account_id, storage)` 不变。
- `scan.py`：`ensure_tab(...)` 调用方式同步改。
- 业务逻辑零改动（点击统一在 pages 层完成）。

## 10. scheduler / task_runner

- `task_runner.py`：不动（asyncio.Queue + 单 worker），现在跑在 qasync 循环上。
- `scheduler.py`：各 Task `execute()` 里 `TabSession(account_id=...)` → `get_browser_manager().get_session(account_id)`。其余（cron 触发、账号遍历、通知聚合）不动。

## 11. ui/ 改动

`__init__.py`（BzAutoApp）重写引导：
```python
def run_ui():
    app = QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    manager = BrowserManager(storage, get_config())   # 主窗口（QTabWidget）
    manager.show()
    control = ControlPanel(); control.show()          # 浮动
    log = LogWindow(); log.show()                     # 浮动
    # 在 qasync 循环上起 TaskRunner + BzScheduler
    asyncio.create_task(init_async(manager))
    with loop:
        loop.run_forever()
```
- 砍掉后台线程、`start_server()`、`run_coroutine_threadsafe`。按钮 → `task_runner.submit_and_wait` 直接在同循环。
- `get_debug_status`：`get_browser_manager().connected_accounts()` 替代 `get_registry()`。
- `ControlPanel/LogWindow/ConfigDialog/DataWindow/DebugWindow`：基本不动。`ConfigDialog` 删 `[server]` 字段、`account.profile` 字段。
- 全局热键：保留 `keyboard`（Ctrl+E/W），它自起线程，用 `asyncio.run_coroutine_threadsafe(coro, loop)` 把停止动作投递回 qasync 循环。

## 12. config 改动

- 删 `ServerConfig`（`[server]` 节）。
- 删 `AccountConfig.profile`（路径直接用 `account.id`）。
- 新增 `[browser]` 节：`profiles_dir = "profiles"`（未来可加 `user_agent` 覆盖、`headless`）。
- `config.toml` 同步更新。

## 13. 入口点

- `__main__.py`：`run_ui()` 新引导。
- `scrape_jobs.py` / `scrape_chat_auto.py`：`BossJobsAuto/BossChatAuto` 从 `start_server` ctx 改成"建 QApplication + qasync + BrowserManager + 跑 flow + quit"的最小 Qt 引导（浏览器窗口可见，无控制面板）。
- `analyze.py`：`PageAnalyzer` 改用 `BrowserSession` 直接驱动，dump/find_text/bbox/snapshot 全走 `eval_js`/`bbox`。

## 14. 依赖变更

删：`fastapi`、`uvicorn[standard]`、`python-socketio`、`pyautogui`、`beautifulsoup4`（先确认无引用）。
留：`pyside6`（含 QtWebEngine，test.py 已验证可导入）、`keyboard`、`tinydb`、`apscheduler`、`httpx`、`tomli_w`、`pydantic`。
加：`qasync`。

## 15. 删除清单

`extension/`（整目录）、`src/bzauto/server/`（整目录）、`src/bzauto/protocol/`（整目录，类型搬到 `browser/types.py`）、`scripts/bosszhipin-remote.user.js`。

## 16. 迁移阶段（顺序）

1. 依赖 + 骨架：改 `pyproject.toml`；建 `browser/` 空骨架 + qasync 引导；单账号能加载 Boss 直聘 + `eval_js` 通 + 一次 Qt 点击通（把 test.py 收进 `browser/session.py`）。
2. `BrowserSession` 全原语实现 + `js_helper` 注入。
3. `pages/` 迁移到新原语 + 统一点击，逐方法对活页验证。
4. `flows/` + `scheduler` + `task_runner` 接 `get_browser_manager().get_session(...)`，逐 flow 跑通。
5. `ui/` 重写引导 + 主窗口 + 浮动面板接线，手动触发任务验证。
6. `config` + 入口点（scrape_jobs/chat_auto/analyze）引导。
7. 清理：删 `extension/ server/ protocol/ scripts` 旧物，更新 `AGENTS.md` / `README.md`。
8. 端到端验证：scrape_only / scrape+greet / scrape_chat / delete_chat / dispatch / scan 全跑一遍；多账号切标签页；定时触发。

## 17. 风险

- **反检测**：QWebEngineView 的 UA/指纹含 QtWebEngine，Boss 直聘可能识别。缓解：`profile.setHttpUserAgent()` 设成真实 Chrome 串；首次登录后观察是否触发安全页。需实测，这是最大不确定项。
- **Qt 事件到渲染层**：test.py 验证了 focusProxy+sendEvent 能点，但弹窗/iframe/动态元素可能要 QTimer 拆时序。串行模型下运行前切到对应 tab，可见即可点。
- **非当前 tab 的 runJavaScript**：页面存活就能跑，但布局可能惰性。串行模型规避。
- **登录持久化**：`profiles/<id>/` 首次为空，需手动登录一次；换引擎后 Boss 可能要求重新验证，可接受。
- **qasync / PySide6 版本**：需实测匹配，一般 OK。

---

方案就这些。确认没问题我就按阶段 1 开干；要调整哪块直接说。需要我把这份方案存成 `plan.md` 吗？