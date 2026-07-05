任何时候执行修改前都必须向用户请求。
如果用户的输入里没有明确表示执行修改，那么禁止擅自修改文件。
如果用户打断进行提问，那么只需要回答用户的问题，回答完后禁止擅自开始执行改动，必须询问用户。
# bosszhipin-auto

Chrome 扩展 + Python 服务，远程控制 Boss直聘页面，支持 JS 远程执行、元素坐标查询、标签管理。

## 项目结构

```
├── server/
│   ├── __init__.py      # 导出 TabRegistry, RemoteSession, create_app, run_server
│   ├── registry.py      # TabRegistry — 标签状态、WS连接、执行 Futures、chromeTabId 映射
│   ├── api.py           # RemoteSession — Python API (open/close/list/execute/coordinates/activate/reload)
│   └── main.py          # FastAPI app factory — WS 端点 `/api/ws` + `/exec/{execId}` HTTP 端点用于 MAIN world 执行
├── extension/
│   ├── manifest.json    # Chrome Extension MV3 清单
│   ├── content.js       # 内容脚本 — WS 连接、JS 执行、元素坐标计算
│   └── background.js    # Service Worker — WS ext 连接、tab 管理 (chrome.tabs API)
├── scripts/
│   └── bosszhipin-remote.user.js  # (旧) 油猴脚本，推荐使用扩展替代
├── main.py              # 启动入口
├── AGENTS.md
├── pyproject.toml
└── uv.lock
```

## 命令

```bash
uv sync            # 安装/同步依赖
uv run python main.py   # 启动服务 + 标签监控
```

不需要 `uv run` 以外的启动方式。

## 扩展安装

1. 浏览器打开 `chrome://extensions`
2. 打开 **开发者模式**
3. 点击 **加载已解压的扩展程序**，选择 `extension/` 目录

## 扩展权限更新

安装新版本后需要手动在 `chrome://extensions` 点击 **更新** 以获取新增的 `tabs` 权限。

## 架构

| 层 | 说明 |
|---|---|
| **Chrome 扩展** | MV3。一条 WS 通道 `/api/ws`（background.js 连接，处理所有操作）。background.js 自动连接 WS，开机/安装时启动 |
| **content.js** | 运行在 `*.zhipin.com/*` + `*.bosszhipin.com/*`。处理 background.js 发来的 `execute` 消息（content script eval）、监听 `window.postMessage` 回传结果 |
| **background.js** | Service Worker。连接 `/api/ws`，处理 `open_tab` / `close_tab` / `activate_tab` / `reload_tab` / `list_tabs` / `execute` / `query`。自动重连 + ping keepalive |
| **Python 服务** | FastAPI + WebSocket。`/api/ws` 接收 background.js 连接。`/exec/{execId}` HTTP 端点用于 MAIN world 代码注入（绕过 CSP）。所有 Python API 通过 `RemoteSession` 调用 |
| **RemoteSession** | 高层 Python API。标签管理通过 WS 走 `chrome.tabs` API。JS 执行分两路：`world="isolated"` 走 content.js eval（受 CSP 限制），`world="main"` 走 `<script src="/exec/{execId}">` 注入 MAIN world（绕过 CSP）|

## 端点

| 端点 | 客户端 | 用途 |
|---|---|---|
| `/api/ws` | background.js | 扩展后台命令（标签管理、JS 执行、DOM 查询） |
| `/exec/{execId}` | `<script>` 标签（页面 MAIN world） | HTTP GET，返回 JS 代码，注入到页面主 world |

## 消息协议

### `/api/ws`（background.js）

服务 → 扩展：
- `open_tab(id, url)` — 创建标签
- `close_tab(id, chromeTabId)` — 关闭标签
- `activate_tab(id, chromeTabId)` — 激活标签窗口
- `reload_tab(id, chromeTabId)` — 刷新标签
- `list_tabs(id)` — 返回所有标签
- `execute(id, chromeTabId, code, world)` — 执行 JS（`world="isolated"` 走 content.js eval，`world="main"` 走 `<script>` 注入）
- `query(id, chromeTabId, select, filter, project, return)` — 声明式 DOM 查询（`chrome.scripting.executeScript`）

扩展 → 服务：`result(id, data, error)`, `sync_state`, `tab_created`, `tab_updated`, `tab_closed`, `tab_activated`, `ping`

### 通用

`execute` 的 `world` 参数：
- `"isolated"`（默认）— 通过 `chrome.tabs.sendMessage` → content.js `eval()`，**受 CSP 限制**，无法访问页面 JS 变量
- `"main"` — 注入 `<script src="/exec/{execId}">` 到 MAIN world，**绕过 CSP**，可访问 `window.*`、jQuery、React state等页面 JS 变量

`get_coordinates` / `bbox` 返回：
```json
{
  "css": { "x": 100, "y": 200 },
  "physical": { "x": 125, "y": 250 },
  "width": 80,
  "height": 32
}
```

## RemoteSession API

```python
from server import TabRegistry, RemoteSession

registry = TabRegistry()
session = RemoteSession(registry)

# 事件订阅（无需走 WS 监控，直接本地回调）
def on_tab_connected(msg):
    print(f"已连接: {msg['tab']['tab_id'][:8]}")
registry.on("tab_connected", on_tab_connected)
registry.on("tab_disconnected", lambda m: print(f"已断开: {m['tabId'][:8]}"))
registry.on("execution_result", lambda m: print(f"执行结果: {m.get('data')}"))

# 打开 URL（走扩展 chrome.tabs.create）
tab = await session.open_tab("https://www.zhipin.com/")
# tab == {chromeTabId: 42, uuid: "xxx-yyy", url: "...", title: "..."}

# 执行 JS（world="main" 通过 /exec/{execId} 绕过 CSP）
result = await session.execute(tab["uuid"], "document.title", timeout=30.0)

# 执行 JS（world="isolated" 走 content.js eval，受 CSP 限制）
result = await session.execute(tab["uuid"], "document.title", world="isolated", timeout=30.0)

# 执行 JS（world="main" 注入 MAIN world，绕过 CSP，可访问 window.* 等）
result = await session.execute(tab["uuid"], "return window._PAGE", world="main", timeout=30.0)

# 获取元素屏幕坐标（CSS 像素 + DPI 缩放物理像素）
coords = await session.get_element_coordinates(tab["uuid"], ".job-name")

# 激活标签页（窗口置前 + 标签聚焦，需要 chromeTabId）
ok = await session.activate_tab(tab["chromeTabId"])

# 关闭标签（需要 chromeTabId）
await session.close_tab(tab["chromeTabId"])

# 刷新标签
new_info = await session.reload_tab(tab["chromeTabId"])

# 列出所有 Chrome 标签
tabs = await session.list_tabs()

# 列出已连接 content script 的标签
tracked = session.list_tracked_tabs()
```

## analyze.py — 页面分析工具

用于开发时分析页面 DOM 结构、查找弹窗、定位元素坐标。

### 用法

```python
from analyze import PageAnalyzer

async def main():
    async with PageAnalyzer() as pa:
        # 自动连接已打开的 BOSS 直聘标签
        await pa.connect()

        # 扫描常见 UI 组件（列表、弹窗、按钮等）
        await pa.dump_common_elements()

        # 查看指定选择器的 HTML
        await pa.dump(".greet-boss-dialog")

        # 查找包含文本的元素（走 query filter，绕过 CSP）
        await pa.find_text("留在本页")

        # 获取元素屏幕坐标（自动 scrollIntoView）
        b = await pa.bbox(".greet-boss-dialog .cancel-btn")
        if b:
            print(f"坐标: {b['physical']['cx']}, {b['physical']['cy']}")

        # 查找可见弹窗（需要 CSP 允许 eval，否则 fallback 为空）
        await pa.dump_visible_dialogs()

        # 页面快照
        await pa.snapshot()
```

### 原理

- 启动内嵌 uvicorn 服务，复用扩展的 WS 连接
- 所有 `dump` / `find_text` 走 `session.query`（`chrome.scripting.executeScript`，绕过页面 CSP）
- `dump_visible_dialogs` / `snapshot` 走 `session.execute`（content.js eval），受 CSP 限制
- 需要浏览器扩展已安装并连接到 WS

### 调试流程

1. 浏览器已打开 BOSS 直聘页面，扩展已连接
2. 运行分析脚本或直接在代码中引入 `PageAnalyzer`
3. 先用 `dump_common_elements()` 看有哪些弹窗类元素
4. 用 `find_text("留在此页")` 定位目标文本
5. 用 `bbox()` 获取点击坐标
6. 将确定的选择器和流程搬进 `scrape_jobs.py`

## 约定

- 不使用 Playwright / Selenium 等浏览器自动化库
- 禁止使用 chrome-devtools-mcp（此项目通过自身 Chrome 扩展 + WS 协议控制浏览器，不使用 DevTools 协议）
- 标签管理走 `chrome.tabs` API（通过 ext WS），JS 执行和坐标走 content script（通过 tab WS）
- HTTP 端点 `/exec/{execId}` 仅对内网 localhost 开放，用于 MAIN world 代码注入
- Python API 直接在进程内调用 `RemoteSession`，不走网络
- 不保留向后兼容的模块级全局状态
