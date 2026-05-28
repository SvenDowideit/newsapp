from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException

from .. import db as database
from ..fetcher.rss_discovery import discover_feed
from ..models import (
    SourceInfo,
    SourceCreate,
    SourceDiscoverRequest,
    SourceDiscoverResult,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_model=list[SourceInfo])
async def list_sources():
    rows = await database.arun(database.get_all_sources, priority=database.UI)
    return [
        SourceInfo(
            id=r[0],
            type=r[1],
            label=r[2],
            enabled=r[3],
            last_fetched_at=r[4],
            next_fetch_at=r[5],
            ema_interval_s=r[6] or 900,
            fetch_error_count=r[7] or 0,
            last_error=r[8],
        )
        for r in rows
    ]


@router.post("", response_model=SourceInfo, status_code=201)
async def add_source(body: SourceCreate):
    try:
        await database.arun(
            lambda con: database.add_source(
                body.id, body.type, body.label, body.config, con
            ),
            priority=database.UI,
        )
    except ValueError:
        raise HTTPException(status_code=409, detail="Source ID already exists")

    return SourceInfo(
        id=body.id,
        type=body.type,
        label=body.label,
        enabled=True,
        last_fetched_at=None,
        next_fetch_at=None,
        ema_interval_s=900,
        fetch_error_count=0,
        last_error=None,
    )


@router.delete("/{source_id}", status_code=204)
async def disable_source(source_id: str):
    await database.arun(
        lambda con: database.disable_source(source_id, con),
        priority=database.UI,
    )


_discover_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="discover")


@router.post("/discover", response_model=SourceDiscoverResult)
async def discover_source(body: SourceDiscoverRequest):
    result = await database.arun(database.get_all_sources, priority=database.UI)
    existing_urls = set()
    for r in result:
        try:
            cfg = json.loads(r[2]) if isinstance(r[2], str) else {}
            if "url" in cfg:
                existing_urls.add(cfg["url"].rstrip("/"))
        except (json.JSONDecodeError, TypeError):
            pass

    loop = asyncio.get_running_loop()
    found = await loop.run_in_executor(_discover_executor, discover_feed, body.url)
    if found is None:
        raise HTTPException(
            status_code=404,
            detail="Could not discover a feed from that URL. Try providing a direct RSS/Atom feed URL.",
        )

    found.already_exists = found.feed_url.rstrip("/") in existing_urls
    return found


@router.post("/confirm-add", response_model=SourceInfo, status_code=201)
async def confirm_add_source(body: SourceCreate):
    try:
        await database.arun(
            lambda con: database.add_source(
                body.id, body.type, body.label, body.config, con
            ),
            priority=database.UI,
        )
    except ValueError:
        raise HTTPException(status_code=409, detail="Source ID already exists")

    return SourceInfo(
        id=body.id,
        type=body.type,
        label=body.label,
        enabled=True,
        last_fetched_at=None,
        next_fetch_at=None,
        ema_interval_s=900,
        fetch_error_count=0,
        last_error=None,
    )
