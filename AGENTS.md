# bosszhipin-auto

Chrome 扩展 + Python 服务，远程控制 Boss直聘页面，支持 JS 远程执行、元素坐标查询、标签激活。

## 项目结构

```
├── server/
│   ├── __init__.py      # 导出 TabRegistry, RemoteSession, create_app, run_server
│   ├── registry.py      # TabRegistry — 标签状态、WS连接、执行 Futures
│   ├── api.py           # RemoteSession — Python API (open/close/list/execute/coordinates/activate)
│   └── main.py          # FastAPI app factory — 仅 WS 端点，无 REST
├── extension/
│   ├── manifest.json    # Chrome Extension MV3 清单
│   ├── content.js       # 内容脚本 — WS 连接、消息处理、元素坐标计算
│   └── background.js    # Service Worker — tab/window 激活
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

## 架构

| 层 | 说明 |
|---|---|
| **Chrome 扩展** (推荐) | MV3，`content.js` 运行在 `*.zhipin.com/*` + `*.bosszhipin.com/*`，每个 tab 生成唯一 UUID，WS 连接 Python 服务。`background.js` 处理 `activate_tab` 消息（调用 `chrome.tabs.update` + `chrome.windows.update`） |
| **油猴脚本** (旧) | `@match *.zhipin.com/*` + `*.bosszhipin.com/*`，功能同扩展但无拓展 API 权限（不支持标签激活） |
| **Python 服务** | FastAPI + WebSocket。`/api/ws/tab` 接收扩展/油猴连接，`/api/ws/control` 供控制端/监控使用。无 HTTP REST 接口。所有 Python API 通过 `RemoteSession` 直接调用 |
| **RemoteSession** | 高层 Python API：`open_url`、`close_tab`、`list_tabs`、`execute`、`get_element_coordinates`、`activate_tab`。`open_url` 通过 `webbrowser` 启动浏览器 + 轮询等待注册来返回 tab_id |

## 消息协议（WebSocket JSON）

扩展/油猴 → 服务：`register`, `unregister`, `result`, `ping`
服务 → 扩展/油猴：`execute(id, context, code)`, `get_coordinates(id, selector)`, `activate(id)`, `close`, `registered`, `pong`

所有请求（`execute`、`get_coordinates`、`activate`）通过 `id` 关联请求与结果。

`get_coordinates` 返回：
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

# 打开 URL
tab = await session.open_url("https://www.zhipin.com/")

# 执行 JS
result = await session.execute(tab, "document.title")

# 获取元素屏幕坐标（CSS 像素 + DPI 缩放物理像素）
coords = await session.get_element_coordinates(tab, ".job-name")

# 激活标签页（窗口置前 + 标签聚焦）
ok = await session.activate_tab(tab)

# 关闭标签
await session.close_tab(tab)

# 列出所有标签
tabs = session.list_tabs()
```

## 约定

- 不使用 Playwright / Selenium 等浏览器自动化库
- `open_url` 通过 `webbrowser.open` 启动，不管理浏览器进程
- 服务器只有 WebSocket 端点，不暴露任何 HTTP REST API
- Python API 直接在进程内调用 `RemoteSession`，不走网络
- 不保留向后兼容的模块级全局状态
