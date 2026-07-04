"""Example: 启动 WebSocket 服务并通过本地 API 监听标签事件。"""

import asyncio
import json
import logging

import uvicorn

from server import TabRegistry, RemoteSession, create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")


def print_tab_connected(msg: dict) -> None:
    tb = msg["tab"]
    print(
        f"\n[+] 标签已连接  {tb['tab_id'][:8]}  "
        f"{tb.get('title', '')}  {tb.get('url', '')}"
    )


def print_tab_disconnected(msg: dict) -> None:
    print(f"\n[-] 标签已断开  {msg.get('tabId', '')[:8]}")


def print_execution_result(msg: dict) -> None:
    tid = msg.get("tabId", "")
    cid = msg.get("id", "")[:8]
    if msg.get("error"):
        print(f"\n[!] 执行出错 [{tid[:8]}:{cid}]  {msg['error']}")
    else:
        data = json.dumps(msg["data"], ensure_ascii=False, default=str)
        print(f"\n[✓] 执行完成 [{tid[:8]}:{cid}]  {data[:120]}")


async def main() -> None:
    host, port = "127.0.0.1", 8765

    registry = TabRegistry()
    session = RemoteSession(registry)
    app = create_app(registry)

    # ── 通过本地 API 订阅事件，无需额外 WS 连接 ──────────────
    registry.on("tab_connected", print_tab_connected)
    registry.on("tab_disconnected", print_tab_disconnected)
    registry.on("execution_result", print_execution_result)

    server = uvicorn.Server(
        uvicorn.Config(app, host=host, port=port, log_level="info")
    )

    print(f"服务已启动: ws://{host}:{port}/api/ws/tab")
    print("等待标签连接...\n")

    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
