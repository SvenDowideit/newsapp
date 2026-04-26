from __future__ import annotations

import json
import logging
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException

from .. import db as database
from .. import interest as interest_model
from ..models import ReadEventBody, InterestAdjustBody, ExpandedItem
from ..fetcher.scraper import fetch_article_text
from ..fetcher.hashing import resolve_url
from ..fetcher.rss_discovery import autodiscover_rss
from ..pipeline.summarise import summarise_single, summarise_excerpt

logger = logging.getLogger(__name__)
router = APIRouter()

_cfg = None


def set_config(cfg) -> None:
    global _cfg
    _cfg = cfg


def _record_event(cluster_id: int, event_type: str, **kwargs) -> None:
    con = database.get()
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
    if event_type == "read":
        # Mark cluster as read and clear update flag
        con.execute(
            "UPDATE clusters SET read_at = now(), is_update = FALSE WHERE id = ?",
            [cluster_id],
        )
    elif event_type in ("interest_up", "interest_down", "expand", "follow", "save"):
        # Any meaningful interaction implies the item was seen — set read_at if not already set
        con.execute(
            "UPDATE clusters SET read_at = now(), is_update = FALSE WHERE id = ? AND read_at IS NULL",
            [cluster_id],
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
        "SELECT headline, summary, key_points, topics, canonical_url, full_summary FROM clusters WHERE id = ?",
        [cluster_id],
    ).fetchone()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")

    headline, summary, key_points_raw, topics, canonical_url, stored_full_summary = cluster

    source_rows = con.execute(
        "SELECT DISTINCT url FROM raw_items WHERE cluster_id = ? AND url IS NOT NULL LIMIT 5",
        [cluster_id],
    ).fetchall()
    source_urls = [r[0] for r in source_rows]

    key_points = key_points_raw
    if isinstance(key_points, str):
        try:
            key_points = json.loads(key_points)
        except Exception:
            key_points = []
    key_points = key_points or []

    excerpt: str | None = None

    if stored_full_summary:
        # Already have full summary — generate a non-redundant deeper excerpt
        if canonical_url and _cfg:
            try:
                canonical_url, _ = resolve_url(canonical_url)
                article_text, raw_html = fetch_article_text_with_html(canonical_url)
                if raw_html:
                    autodiscover_rss(canonical_url, raw_html, con)
                if article_text and _cfg:
                    excerpt = summarise_excerpt(stored_full_summary, key_points, article_text, _cfg.ollama) or None
            except Exception:
                pass
        full_summary = stored_full_summary
    else:
        # First expand: fetch article, produce fuller summary, store it
        full_summary = summary
        if canonical_url and _cfg:
            canonical_url, _ = resolve_url(canonical_url)
            try:
                article_text, raw_html = fetch_article_text_with_html(canonical_url)
                if article_text:
                    result = summarise_single(headline, article_text, _cfg.ollama)
                    full_summary = result.get("summary", summary)
                    if result.get("key_points"):
                        key_points = result["key_points"]
                        key_points_raw = json.dumps(key_points)
                if raw_html:
                    autodiscover_rss(canonical_url, raw_html, con)
            except Exception:
                pass
        # Store full_summary so second expand can produce a non-redundant excerpt
        con.execute(
            "UPDATE clusters SET full_summary = ?, key_points = ? WHERE id = ?",
            [full_summary, key_points_raw, cluster_id],
        )

    _record_event(cluster_id, "expand")

    return ExpandedItem(
        id=cluster_id,
        headline=headline,
        full_summary=full_summary,
        key_points=key_points,
        source_urls=source_urls,
        topics=topics or [],
        excerpt=excerpt,
    )


def fetch_article_text_with_html(url: str) -> tuple[str | None, str | None]:
    """Fetch URL, return (plain text, raw html)."""
    try:
        headers = {"User-Agent": "newsagg/0.1 (personal aggregator)"}
        resp = httpx.get(url, headers=headers, timeout=20, follow_redirects=True)
        resp.raise_for_status()
        raw_html = resp.text
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(raw_html, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return text[:8000] if text else None, raw_html
    except Exception:
        return None, None
