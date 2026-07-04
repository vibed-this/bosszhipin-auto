# bosszhipin-auto

油猴脚本 + Python 服务，远程控制 Boss直聘页面，支持 JS 远程执行（page / GM 双上下文）。

## 项目结构

```
├── server/
│   ├── __init__.py      # 导出 TabRegistry, RemoteSession, create_app, run_server
│   ├── registry.py      # TabRegistry — 标签状态、WS连接、执行 Futures
│   ├── api.py           # RemoteSession — Python API (open/close/list/execute)
│   └── main.py          # FastAPI app factory — 仅 WS 端点，无 REST
├── scripts/
│   └── bosszhipin-remote.user.js  # 油猴脚本
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

## 架构

| 层 | 说明 |
|---|---|
| **油猴脚本** | `@match *.zhipin.com/*` + `*.bosszhipin.com/*`，每个 tab 生成唯一 UUID，WS 连接 Python 服务，注册/注销生命周期。支持 `page`（注入 `<script>`）和 `gm`（油猴作用域）双上下文执行 |
| **Python 服务** | FastAPI + WebSocket。`/api/ws/tab` 接收油猴连接，`/api/ws/control` 供控制端/监控使用。无 HTTP REST 接口。所有 Python API 通过 `RemoteSession` 直接调用 |
| **RemoteSession** | 高层 Python API：`open_url`、`close_tab`、`list_tabs`、`execute`。`open_url` 通过 `webbrowser` 启动浏览器 + 轮询等待油猴注册来返回 tab_id |

## 消息协议（WebSocket JSON）

油猴 → 服务：`register`, `unregister`, `result`, `ping`
服务 → 油猴：`execute(id, context, code)`, `close`, `registered`, `pong`

`execute` 通过 `id` 关联请求与结果，支持 30s 超时。

## API 使用示例

```python
from server import TabRegistry, RemoteSession, create_app
import uvicorn, asyncio

registry = TabRegistry()
session = RemoteSession(registry)
app = create_app(registry)

server = uvicorn.Server(uvicorn.Config(app, port=8765, log_level="info"))

async def worker():
    tab = await session.open_url("https://www.zhipin.com/")
    result = await session.execute(tab, "document.title")
    await session.close_tab(tab)

asyncio.gather(server.serve(), worker())
```

## 约定

- 不使用 Playwright / Selenium 等浏览器自动化库
- `open_url` 通过 `webbrowser.open` 启动，不管理浏览器进程
- 服务器只有 WebSocket 端点，不暴露任何 HTTP REST API
- Python API 直接在进程内调用 `RemoteSession`，不走网络
- 不保留向后兼容的模块级全局状态
