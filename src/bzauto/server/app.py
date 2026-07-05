from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import Response
import socketio
import uvicorn

from bzauto.server.registry import TabRegistry

logger = logging.getLogger("boss.server")


def create_app(registry: TabRegistry | None = None) -> socketio.ASGIApp:
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

    fastapi_app = FastAPI(title="Boss直聘远程控制", lifespan=lifespan)

    @fastapi_app.get("/exec/{exec_id}")
    async def exec_script(exec_id: str):
        code = registry._exec_store.pop(exec_id, None)
        if code is None:
            return Response(status_code=404)
        return Response(content=code, media_type="application/javascript")

    # 将 FastAPI 应用作为其他 ASGI 应用传递给 Socket.IO
    sio_app = socketio.ASGIApp(registry.sio, other_asgi_app=fastapi_app)
    return sio_app


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