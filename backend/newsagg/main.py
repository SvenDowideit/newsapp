from __future__ import annotations

import asyncio
import logging
import socket
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from zeroconf import ServiceInfo, Zeroconf

from . import db as database
from .config import Config, load as load_config
from .pipeline.dedup import run_pipeline
from .fetcher.scheduler import run_scheduler, breaking_news_detector
from .fetcher.hashing import resolve_url, url_hash as _url_hash, content_hash as _content_hash, warm_cache
from .api import feed as feed_api
from .api import items as items_api
from .api.feed import push_event
from .api import sources as sources_router
from .api import topics as topics_router
from .api import stats as stats_router
from .api import webui as webui_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

_config: Config | None = None


def _pipeline_fn(source_id: str) -> None:
    assert _config is not None
    run_pipeline(source_id, _config)


def _get_lan_addresses() -> list[str]:
    """Return all non-loopback, non-link-local IPv4 addresses on this host."""
    import ipaddress
    addrs = []
    try:
        for iface_addrs in socket.getaddrinfo(socket.gethostname(), None):
            ip = iface_addrs[4][0]
            try:
                obj = ipaddress.ip_address(ip)
                if obj.version == 4 and not obj.is_loopback and not obj.is_link_local:
                    if ip not in addrs:
                        addrs.append(ip)
            except ValueError:
                pass
    except Exception:
        pass
    if not addrs:
        # fallback: connect to a public address to discover the outbound interface
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            addrs.append(ip)
        except Exception:
            pass
    return addrs or ["127.0.0.1"]


def _register_mdns(port: int) -> Zeroconf:
    zc = Zeroconf()
    lan_ips = _get_lan_addresses()
    addresses = [socket.inet_aton(ip) for ip in lan_ips]
    info = ServiceInfo(
        "_http._tcp.local.",
        "newsapp._http._tcp.local.",
        addresses=addresses,
        port=port,
        properties={"path": "/"},
        server="newsapp.local.",
    )
    zc.register_service(info)
    logger.info("mDNS registered: http://newsapp.local:%d/ (addresses: %s)", port, ", ".join(lan_ips))
    return zc


def _backfill_resolved_urls() -> None:
    """Background thread: resolve old redirect-wrapper URLs stored in DB."""
    from googlenewsdecoder import gnewsdecoder

    rows = database.run_sync(database.get_unresolved_redirect_items, priority=database.BG)
    if not rows:
        return

    logger.info("startup-backfill: resolving %d unresolved URLs", len(rows))
    resolved = 0
    for (rid, url, title) in rows:
        try:
            if "news.google.com" in url:
                result = gnewsdecoder(url, interval=1)
                final = result["decoded_url"] if result.get("status") else url
            else:
                final, _ = resolve_url(url, reason="startup-backfill")
        except Exception:
            final = url
        if final and final != url:
            new_uhash = _url_hash(final)
            new_chash = _content_hash(final, title)

            def _update(con, _rid=rid, _final=final, _url=url, _uh=new_uhash, _ch=new_chash):
                database.update_item_resolved_url(_rid, _final, _uh, _ch, con)
                database.update_cluster_canonical_url(_url, _final, con)

            database.run_sync(_update, priority=database.BG)
            resolved += 1

    if resolved:
        logger.info("startup-backfill: updated %d items to resolved URLs", resolved)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _config
    config_path = Path("config.toml")
    _config = load_config(config_path)

    database.init(_config.server.db_path)
    database.upsert_sources(_config.sources)
    database.run_sync(warm_cache, priority=database.BG)

    items_api.set_config(_config)

    zc = await asyncio.get_running_loop().run_in_executor(
        None, _register_mdns, _config.server.port
    )

    threading.Thread(target=_backfill_resolved_urls, daemon=True, name="backfill").start()

    scheduler_task = asyncio.create_task(run_scheduler(_config, _pipeline_fn))
    breaking_task = asyncio.create_task(breaking_news_detector(_config, push_event))

    logger.info("newsagg started on %s:%s", _config.server.host, _config.server.port)
    yield

    scheduler_task.cancel()
    breaking_task.cancel()
    try:
        await asyncio.gather(scheduler_task, breaking_task, return_exceptions=True)
    except Exception:
        pass

    database.stop()
    await asyncio.get_running_loop().run_in_executor(None, zc.close)


app = FastAPI(title="newsagg", version="0.1.0", lifespan=lifespan)

app.include_router(feed_api.router,       prefix="/feed",    tags=["feed"])
app.include_router(items_api.router,      prefix="/items",   tags=["items"])
app.include_router(sources_router.router, prefix="/sources", tags=["sources"])
app.include_router(topics_router.router,  prefix="/topics",  tags=["topics"])
app.include_router(stats_router.router,   prefix="/stats",   tags=["stats"])
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
