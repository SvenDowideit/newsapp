from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import APIRouter, Depends, Query, Request
from sse_starlette.sse import EventSourceResponse

from .. import db as database
from ..models import FeedResponse, ClusterItem
from ..ranking import refresh_scores
from ..fetcher.scheduler import signal_active_reader

logger = logging.getLogger(__name__)
router = APIRouter()

# In-memory SSE subscribers
_subscribers: list[asyncio.Queue] = []


def get_subscribers() -> list[asyncio.Queue]:
    return _subscribers


async def push_event(event: dict) -> None:
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


@router.get("", response_model=FeedResponse)
async def get_feed(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    topics: list[str] | None = Query(None),
    since: datetime | None = Query(None),
    active: bool = Query(False),
):
    if active:
        signal_active_reader(60)

    con = database.get()
    refresh_scores(con)

    conditions = ["1=1"]
    params = []

    if since:
        conditions.append("latest_seen_at > ?")
        params.append(since)

    if topics:
        # Match if any of the requested topics appears in cluster topics
        topic_conds = " OR ".join(["list_contains(topics, ?)"] * len(topics))
        conditions.append(f"({topic_conds})")
        params.extend(topics)

    where = " AND ".join(conditions)
    total_row = con.execute(f"SELECT count(*) FROM clusters WHERE {where}", params).fetchone()
    total = total_row[0] if total_row else 0

    offset = (page - 1) * page_size
    rows = con.execute(
        f"""
        SELECT id, created_at, updated_at, first_seen_at, latest_seen_at,
               canonical_url, headline, summary, key_points, topics,
               source_ids, item_count, is_breaking, combined_score
        FROM clusters
        WHERE {where}
        ORDER BY combined_score DESC
        LIMIT ? OFFSET ?
        """,
        params + [page_size, offset],
    ).fetchall()

    items = [_row_to_cluster(r) for r in rows]
    return FeedResponse(items=items, page=page, page_size=page_size, total=total)


@router.get("/live")
async def feed_live(request: Request):
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    _subscribers.append(queue)

    async def event_generator() -> AsyncIterator[dict]:
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                    yield {"data": json.dumps(event)}
                except asyncio.TimeoutError:
                    yield {"data": "ping"}
        finally:
            _subscribers.remove(queue)

    return EventSourceResponse(event_generator())


def _row_to_cluster(r) -> ClusterItem:
    key_points = r[8]
    if isinstance(key_points, str):
        try:
            key_points = json.loads(key_points)
        except Exception:
            key_points = []
    return ClusterItem(
        id=r[0],
        created_at=r[1],
        updated_at=r[2],
        first_seen_at=r[3],
        latest_seen_at=r[4],
        canonical_url=r[5],
        headline=r[6],
        summary=r[7],
        key_points=key_points or [],
        topics=r[9] or [],
        source_ids=r[10] or [],
        item_count=r[11],
        is_breaking=r[12],
        combined_score=r[13] or 0.0,
    )
