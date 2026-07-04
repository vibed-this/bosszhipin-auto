"""Example: 启动 WebSocket 服务并监听标签的打开与关闭。"""

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


async def monitor(host: str, port: int) -> None:
    """通过控制 WebSocket 监听标签事件。"""
    import websockets

    uri = f"ws://{host}:{port}/api/ws/control"
    log.info("监控连接: %s", uri)

    async for ws in websockets.connect(uri):
        try:
            async for raw in ws:
                msg = json.loads(raw)
                t = msg.get("type")

                if t == "tab_connected":
                    tb = msg["tab"]
                    print(
                        f"\n[+] 标签已连接  {tb['tab_id'][:8]}  "
                        f"{tb.get('title', '')}  {tb.get('url', '')}"
                    )

                elif t == "tab_disconnected":
                    tid = msg.get("tabId", "")
                    print(f"\n[-] 标签已断开  {tid[:8]}")

                elif t == "state":
                    tabs = msg.get("tabs", [])
                    log.info("初始状态: %d 个标签已连接", len(tabs))

                elif t == "execution_result":
                    tid = msg.get("tabId", "")
                    cid = msg.get("id", "")[:8]
                    if msg.get("error"):
                        print(f"\n[!] 执行出错 [{tid[:8]}:{cid}]  {msg['error']}")
                    else:
                        data = json.dumps(msg["data"], ensure_ascii=False, default=str)
                        print(f"\n[✓] 执行完成 [{tid[:8]}:{cid}]  {data[:120]}")

        except websockets.ConnectionClosed:
            log.warning("监控断线，重连中...")


async def main() -> None:
    host, port = "127.0.0.1", 8765

    # ── 启动服务 ──────────────────────────────────────────────
    registry = TabRegistry()
    session = RemoteSession(registry)
    app = create_app(registry)

    server = uvicorn.Server(
        uvicorn.Config(app, host=host, port=port, log_level="info")
    )

    # ── 同时运行服务 + 监控 ──────────────────────────────────
    print(f"服务已启动: ws://{host}:{port}/api/ws/tab")
    print("等待标签连接...\n")

    await asyncio.gather(server.serve(), monitor(host, port))


if __name__ == "__main__":
    asyncio.run(main())
