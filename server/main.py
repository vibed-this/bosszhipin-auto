from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn

from server.registry import TabRegistry

logger = logging.getLogger("boss.server")


def create_app(registry: TabRegistry | None = None) -> FastAPI:
    """Build the FastAPI app with WebSocket endpoints for userscript comms.

    Only WebSocket endpoints are exposed — the Python API
    (:class:`RemoteController`) is used directly from code.
    """
    if registry is None:
        registry = TabRegistry()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("bosszhipin 远程控制服务启动中...")
        yield
        logger.info("服务关闭中...")
        await registry.close_all()

    app = FastAPI(title="Boss直聘远程控制", lifespan=lifespan)

    # ── Tab WebSocket (userscripts) ────────────────────────────

    @app.websocket("/api/ws/tab")
    async def tab_websocket(ws: WebSocket):
        tab_id: str | None = None
        await ws.accept()
        try:
            while True:
                raw = await ws.receive_text()
                msg = json.loads(raw)
                t = msg.get("type")

                if t == "register":
                    tab_id = msg.get("tabId", str(uuid.uuid4()))
                    registry.register(
                        tab_id,
                        url=msg.get("url", ""),
                        title=msg.get("title", ""),
                        ws=ws,
                    )
                    await ws.send_text(
                        json.dumps({"type": "registered", "tabId": tab_id})
                    )

                elif t == "unregister":
                    if tab_id:
                        registry.unregister(tab_id)
                    break

                elif t == "result":
                    cmd_id = msg.get("id")
                    if cmd_id:
                        registry.resolve_result(
                            cmd_id,
                            data=msg.get("data"),
                            error=msg.get("error"),
                        )
                    registry._broadcast({
                        "type": "execution_result",
                        "tabId": tab_id,
                        "id": cmd_id,
                        "data": msg.get("data"),
                        "error": msg.get("error"),
                    })

                elif t == "pong":
                    pass

        except WebSocketDisconnect:
            logger.info("[-] 标签断开: %s", (tab_id or "?")[:8])
        except Exception as e:
            logger.error("[!] 标签WS异常 (%s): %s", tab_id, e)
        finally:
            if tab_id:
                registry.unregister(tab_id)

    # ── Control WebSocket (CLI / monitoring) ───────────────────

    @app.websocket("/api/ws/control")
    async def control_websocket(ws: WebSocket):
        await ws.accept()
        registry.add_control_client(ws)
        logger.info("[*] 控制端已连接")
        try:
            await ws.send_text(
                json.dumps({"type": "state", "tabs": registry.tabs})
            )
            while True:
                raw = await ws.receive_text()
                msg = json.loads(raw)

                if msg.get("type") == "execute":
                    tab_id = msg["tabId"]
                    ctx = msg.get("context", "page")
                    code = msg.get("code", "")

                    if not registry.is_connected(tab_id):
                        await ws.send_text(
                            json.dumps({
                                "type": "error",
                                "message": f"标签 {tab_id} 未连接",
                            })
                        )
                        continue

                    try:
                        result = await registry.send_execute(tab_id, code, ctx)
                        await ws.send_text(
                            json.dumps({
                                "type": "result",
                                "id": uuid.uuid4().hex[:12],
                                "tabId": tab_id,
                                "data": result,
                                "error": None,
                            })
                        )
                    except Exception as e:
                        await ws.send_text(
                            json.dumps({
                                "type": "result",
                                "tabId": tab_id,
                                "data": None,
                                "error": str(e),
                            })
                        )

        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error("[!] 控制WS异常: %s", e)
        finally:
            registry.remove_control_client(ws)

    return app


# ── Runner ──────────────────────────────────────────────────

def run_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    reload: bool = False,
) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    app = create_app()
    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )
