from __future__ import annotations

import asyncio
import logging
import socket
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from zeroconf import ServiceInfo, Zeroconf

from . import db as database
from .config import Config, load as load_config
from .pipeline.dedup import run_pipeline
from .fetcher.scheduler import run_scheduler, breaking_news_detector
from .api import feed as feed_api
from .api import items as items_api
from .api.feed import push_event
from .api import sources as sources_router
from .api import topics as topics_router
from .api import webui as webui_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

_config: Config | None = None


def _pipeline_fn(source_id: str, con) -> None:
    assert _config is not None
    run_pipeline(source_id, con, _config)


def _register_mdns(port: int) -> Zeroconf:
    """Register newsapp.local via mDNS using zeroconf."""
    zc = Zeroconf()
    try:
        local_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        local_ip = "127.0.0.1"
    addr = socket.inet_aton(local_ip)
    info = ServiceInfo(
        "_http._tcp.local.",
        "newsapp._http._tcp.local.",
        addresses=[addr],
        port=port,
        properties={"path": "/"},
        server="newsapp.local.",
    )
    zc.register_service(info)
    logger.info("mDNS registered: http://newsapp.local:%d/", port)
    return zc


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _config
    config_path = Path("config.toml")
    _config = load_config(config_path)

    database.init(_config.server.db_path)
    database.upsert_sources(_config.sources)

    items_api.set_config(_config)

    zc = await asyncio.get_running_loop().run_in_executor(
        None, _register_mdns, _config.server.port
    )

    scheduler_task = asyncio.create_task(run_scheduler(_config, _pipeline_fn))
    breaking_task = asyncio.create_task(
        breaking_news_detector(_config, push_event)
    )

    logger.info("newsagg started on %s:%s", _config.server.host, _config.server.port)
    yield

    scheduler_task.cancel()
    breaking_task.cancel()
    try:
        await asyncio.gather(scheduler_task, breaking_task, return_exceptions=True)
    except Exception:
        pass

    await asyncio.get_running_loop().run_in_executor(None, zc.close)


app = FastAPI(title="newsagg", version="0.1.0", lifespan=lifespan)

app.include_router(feed_api.router,       prefix="/feed",    tags=["feed"])
app.include_router(items_api.router,      prefix="/items",   tags=["items"])
app.include_router(sources_router.router, prefix="/sources", tags=["sources"])
app.include_router(topics_router.router,  prefix="/topics",  tags=["topics"])
app.include_router(webui_router.router,   prefix="",         tags=["ui"])


@app.get("/health")
async def health():
    return {"status": "ok"}


def run() -> None:
    cfg = load_config("config.toml")
    uvicorn.run(
        "newsagg.main:app",
        host=cfg.server.host,
        port=cfg.server.port,
        reload=False,
        workers=1,
    )
