from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from .. import db as database
from .. import interest as interest_model
from ..models import ReadEventBody, InterestAdjustBody, ExpandedItem
from ..fetcher.scraper import fetch_article_text
from ..pipeline.summarise import summarise_single

logger = logging.getLogger(__name__)
router = APIRouter()

_cfg = None  # set by main.py after startup


def set_config(cfg) -> None:
    global _cfg
    _cfg = cfg


def _record_event(cluster_id: int, event_type: str, **kwargs) -> None:
    con = database.get()
    # Validate cluster exists
    row = con.execute("SELECT id FROM clusters WHERE id = ?", [cluster_id]).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Cluster not found")
    con.execute(
        """
        INSERT INTO read_events (cluster_id, event_type, duration_seconds, fully_read, metadata_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            cluster_id, event_type,
            kwargs.get("duration_seconds"),
            kwargs.get("fully_read"),
            json.dumps(kwargs.get("metadata")) if kwargs.get("metadata") else None,
        ],
    )
    if _cfg:
        interest_model.update(cluster_id, event_type, con, _cfg.interest)


@router.post("/{cluster_id}/read", status_code=204)
async def record_read(cluster_id: int, body: ReadEventBody):
    _record_event(cluster_id, "read",
                  duration_seconds=body.duration_seconds,
                  fully_read=body.fully_read)


@router.post("/{cluster_id}/discard", status_code=204)
async def record_discard(cluster_id: int):
    _record_event(cluster_id, "discard")


@router.post("/{cluster_id}/follow", status_code=204)
async def record_follow(cluster_id: int):
    _record_event(cluster_id, "follow")


@router.post("/{cluster_id}/save", status_code=204)
async def save_item(cluster_id: int):
    _record_event(cluster_id, "save")


@router.post("/{cluster_id}/interest", status_code=204)
async def adjust_interest(cluster_id: int, body: InterestAdjustBody):
    event_type = "interest_up" if body.direction == "up" else "interest_down"
    _record_event(cluster_id, event_type)


@router.post("/{cluster_id}/expand", response_model=ExpandedItem)
async def expand_item(cluster_id: int):
    con = database.get()
    cluster = con.execute(
        "SELECT headline, summary, key_points, topics, canonical_url FROM clusters WHERE id = ?",
        [cluster_id],
    ).fetchone()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")

    headline, summary, key_points_raw, topics, canonical_url = cluster

    # Fetch source URLs for this cluster
    source_rows = con.execute(
        "SELECT DISTINCT url FROM raw_items WHERE cluster_id = ? AND url IS NOT NULL LIMIT 5",
        [cluster_id],
    ).fetchall()
    source_urls = [r[0] for r in source_rows]

    # Try to fetch and re-summarise the canonical article for a deeper summary
    full_summary = summary
    if canonical_url and _cfg:
        try:
            article_text = fetch_article_text(canonical_url)
            if article_text:
                result = summarise_single(headline, article_text, _cfg.ollama)
                full_summary = result.get("summary", summary)
                if result.get("key_points"):
                    key_points_raw = json.dumps(result["key_points"])
        except Exception:
            pass

    key_points = key_points_raw
    if isinstance(key_points, str):
        try:
            key_points = json.loads(key_points)
        except Exception:
            key_points = []

    _record_event(cluster_id, "expand")

    return ExpandedItem(
        id=cluster_id,
        headline=headline,
        full_summary=full_summary,
        key_points=key_points or [],
        source_urls=source_urls,
        topics=topics or [],
    )
