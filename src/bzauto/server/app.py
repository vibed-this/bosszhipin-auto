from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
import uvicorn

from bzauto.server.registry import TabRegistry

logger = logging.getLogger("boss.server")


def create_app(registry: TabRegistry | None = None) -> FastAPI:
    if registry is None:
        registry = TabRegistry()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("bosszhipin 远程控制服务启动中...")
        try:
            yield
        except asyncio.CancelledError:
            pass
        finally:
            logger.info("服务关闭中...")
            await registry.close_all()

    app = FastAPI(title="Boss直聘远程控制", lifespan=lifespan)

    @app.get("/exec/{exec_id}")
    async def exec_script(exec_id: str):
        code = registry._exec_store.pop(exec_id, None)
        if code is None:
            return Response(status_code=404)
        return Response(content=code, media_type="application/javascript")

    @app.websocket("/api/ws")
    async def bg_websocket(ws: WebSocket):
        await ws.accept()
        registry.set_ws(ws)
        logger.info("[*] 扩展后台已连接")
        try:
            while True:
                raw = await ws.receive_text()
                msg = json.loads(raw)
                t = msg.get("type")

                logger.debug("<< 收到消息: type=%s id=%s", t, msg.get("id", ""))

                if t == "result":
                    cmd_id = msg.get("id")
                    error = msg.get("error")
                    if error:
                        logger.debug("结果包含错误: cmd_id=%s error=%s", cmd_id, error)
                    else:
                        data = msg.get("data")
                        data_str = str(data) if data else "None"
                        logger.debug("结果数据: cmd_id=%s data=%s", cmd_id, data_str[:200] if len(data_str) > 200 else data_str)
                    if cmd_id:
                        registry.resolve_result(
                            cmd_id,
                            data=msg.get("data"),
                            error=error,
                        )
                    registry._broadcast({
                        "type": "execution_result",
                        "id": cmd_id,
                        "data": msg.get("data"),
                        "error": error,
                    })

                elif t in (
                    "sync_state",
                    "tab_created",
                    "tab_updated",
                    "tab_closed",
                    "tab_activated",
                ):
                    logger.debug("处理标签事件: type=%s", t)
                    registry.handle_tab_event(msg)

                elif t == "ping":
                    logger.debug("收到心跳")
                    pass

                else:
                    logger.debug("未知消息类型: %s", t)

        except asyncio.CancelledError:
            logger.debug("WebSocket 连接被取消")
            pass
        except WebSocketDisconnect:
            logger.info("[-] 扩展后台断开")
        except Exception as e:
            logger.error("[!] 扩展WS异常: %s", e)
        finally:
            registry.remove_ws(ws)

    return app


def run_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    reload: bool = False,
) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("boss").setLevel(logging.DEBUG)
    app = create_app()
    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )
