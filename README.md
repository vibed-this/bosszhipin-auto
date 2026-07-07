# Boss直聘自动控制

QWebEngineView 桌面浏览器自动控制，支持多账号独立 Profile、JS 远程执行、元素坐标查询、DB 持久化、定时调度。

## 安装

```bash
uv sync
```

## 使用

| 命令 | 说明 |
|---|---|
| `boss-ui` | 启动桌面 UI（多账号浏览器 + 控制面板 + 定时调度） |
| `boss-scrape` | 职位抓取 CLI |
| `boss-scrape-chat` | 聊天列表抓取 CLI |
| `boss-analyze` | 页面分析 CLI |

## 首次启动

1. 运行 `boss-ui`
2. 浏览器窗口加载后，在页面内手动登录 Boss 直聘（Cookie 自动持久化到 `profiles/<id>/`）
3. 配置定时策略后即可自动化运行

## 架构

| 层 | 说明 |
|---|---|
| **browser/** | QWebEngineView 内核。每账号独立 Profile/View/Page，支持 JS 执行、DOM 查询、Qt 事件模拟 |
| **pages/** | 页面对象模型，封装选择器和操作方法 |
| **flows/** | 业务流程编排（爬取、投递、扫描、删拒） |
| **Storage** | TinyDB 持久化 |
| **Scheduler** | APScheduler 定时调度 |

## 配置

编辑 `config.toml`，支持白名单/黑名单/薪资过滤、多账号、定时调度、NapCat 通知。

## 依赖

`pyside6`、`qasync`、`sqlite-utils`、`apscheduler`、`httpx`、`keyboard`
