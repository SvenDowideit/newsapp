from __future__ import annotations

import json
import logging

import httpx
from fastapi import APIRouter, HTTPException

from .. import db as database
from .. import interest as interest_model
from ..models import ReadEventBody, InterestAdjustBody, ExpandedItem
from ..fetcher.hashing import resolve_url
from ..fetcher.rss_discovery import autodiscover_rss
from ..pipeline.summarise import summarise_single, summarise_excerpt

logger = logging.getLogger(__name__)
router = APIRouter()

_cfg = None


def set_config(cfg) -> None:
    global _cfg
    _cfg = cfg


async def _record_event(cluster_id: int, event_type: str, **kwargs) -> None:
    def _fn(con):
        if not database.cluster_exists(cluster_id, con):
            raise ValueError("not_found")
        meta = kwargs.get("metadata")
        database.insert_read_event(
            cluster_id, event_type,
            kwargs.get("duration_seconds"),
            kwargs.get("fully_read"),
            json.dumps(meta) if meta else None,
            con,
        )
        if _cfg:
            interest_model.update(cluster_id, event_type, con, _cfg.interest)

    try:
        await database.arun(_fn, priority=database.UI)
    except ValueError as exc:
        if str(exc) == "not_found":
            raise HTTPException(status_code=404, detail="Cluster not found")
        raise


@router.post("/{cluster_id}/read", status_code=204)
async def record_read(cluster_id: int, body: ReadEventBody):
    await _record_event(cluster_id, "read",
                        duration_seconds=body.duration_seconds,
                        fully_read=body.fully_read)


@router.post("/{cluster_id}/discard", status_code=204)
async def record_discard(cluster_id: int):
    await _record_event(cluster_id, "discard")


@router.post("/{cluster_id}/follow", status_code=204)
async def record_follow(cluster_id: int):
    await _record_event(cluster_id, "follow")


@router.post("/{cluster_id}/save", status_code=204)
async def save_item(cluster_id: int):
    await _record_event(cluster_id, "save")


@router.post("/{cluster_id}/interest", status_code=204)
async def adjust_interest(cluster_id: int, body: InterestAdjustBody):
    event_type = "interest_up" if body.direction == "up" else "interest_down"
    await _record_event(cluster_id, event_type)


@router.post("/{cluster_id}/expand", response_model=ExpandedItem)
async def expand_item(cluster_id: int):
    cluster = await database.arun(
        lambda con: database.get_cluster(cluster_id, con),
        priority=database.UI,
    )
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")

    headline, summary, key_points_raw, topics, canonical_url, stored_full_summary = cluster

    source_rows = await database.arun(
        lambda con: database.get_cluster_source_urls(cluster_id, con),
        priority=database.UI,
    )
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
        full_summary = stored_full_summary
        if canonical_url and _cfg:
            try:
                canonical_url, _ = resolve_url(canonical_url, reason="expand-excerpt")
                article_text, raw_html = _fetch_article(canonical_url)
                if raw_html:
                    await database.arun(
                        lambda con: autodiscover_rss(canonical_url, raw_html, con),
                        priority=database.BG,
                    )
                if article_text and _cfg:
                    excerpt = summarise_excerpt(stored_full_summary, key_points, article_text, _cfg.ollama) or None
            except Exception:
                pass
    else:
        full_summary = summary
        if canonical_url and _cfg:
            canonical_url, _ = resolve_url(canonical_url, reason="expand")
            try:
                article_text, raw_html = _fetch_article(canonical_url)
                if article_text:
                    result = summarise_single(headline, article_text, _cfg.ollama)
                    full_summary = result.get("summary", summary)
                    if result.get("key_points"):
                        key_points = result["key_points"]
                        key_points_raw = json.dumps(key_points)
                if raw_html:
                    await database.arun(
                        lambda con: autodiscover_rss(canonical_url, raw_html, con),
                        priority=database.BG,
                    )
            except Exception:
                pass
        await database.arun(
            lambda con: database.update_cluster_full_summary(cluster_id, full_summary, key_points_raw, con),
            priority=database.UI,
        )

    await _record_event(cluster_id, "expand")

    return ExpandedItem(
        id=cluster_id,
        headline=headline,
        full_summary=full_summary,
        key_points=key_points,
        source_urls=source_urls,
        topics=topics or [],
        excerpt=excerpt,
    )


def _fetch_article(url: str) -> tuple[str | None, str | None]:
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
