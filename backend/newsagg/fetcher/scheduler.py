from __future__ import annotations

import asyncio
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import duckdb

from .. import db as database
from ..config import Config, SourceConfig
from . import hackernews, google_news, reddit, rss, scraper, search, youtube, email_imap
from .types import RawItem
from .hashing import content_hash, url_hash, title_hash, resolve_url
from .rss_discovery import autodiscover_rss, fetch_and_autodiscover

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="fetcher")

# TTL flag: when set, user is actively reading → boost fetch frequency
_active_reader_until: float = 0.0


def signal_active_reader(ttl_seconds: int = 60) -> None:
    global _active_reader_until
    _active_reader_until = time.time() + ttl_seconds


def _is_active_reader() -> bool:
    return time.time() < _active_reader_until


def _fetch_source(src_cfg: SourceConfig, sched_cfg) -> list[RawItem]:
    t = src_cfg.type
    e = src_cfg.extra
    sid = src_cfg.id
    try:
        if t == "rss":
            return rss.fetch(sid, e["url"])
        elif t == "google_news":
            return google_news.fetch(sid, e.get("query", "news"))
        elif t == "hackernews":
            return hackernews.fetch(sid, min_score=e.get("min_score", 50))
        elif t == "reddit":
            return reddit.fetch(sid, e["subreddit"], e.get("sort", "hot"), e.get("limit", 25))
        elif t == "scraper":
            return scraper.fetch(sid, e["url"])
        elif t == "search":
            return search.fetch(sid, e["query"], e.get("max_results", 10))
        elif t == "youtube":
            return youtube.fetch(sid, e.get("channel_id"), e.get("channel_url"))
        elif t == "email_imap":
            return email_imap.fetch(
                sid, e["host"], e["user"], e["password_env"],
                e.get("folder", "INBOX"), e.get("limit", 20),
            )
        else:
            logger.warning("Unknown source type: %s", t)
            return []
    except Exception as exc:
        logger.exception("Error fetching source %s: %s", sid, exc)
        return []


def _persist_items(items: list[RawItem], con: duckdb.DuckDBPyConnection) -> int:
    """Insert raw items, skipping duplicates. Returns count of new items."""
    new_count = 0
    for item in items:
        # Resolve redirect wrappers (Google News, shorteners, etc.) to final URL.
        # resolve_url returns (final_url, html) — html is non-None when a GET was
        # needed, so we scan it for RSS feeds at no extra cost.
        final_url, html = resolve_url(item.url)
        item.url = final_url
        if html and final_url:
            try:
                autodiscover_rss(final_url, html, con)
            except Exception:
                pass
        chash = content_hash(item.url, item.title)
        uhash = url_hash(item.url)
        thash = title_hash(item.title)
        # Gate 0: exact content duplicate
        existing = con.execute(
            "SELECT id FROM raw_items WHERE content_hash = ?", [chash]
        ).fetchone()
        if existing:
            continue
        # Gate 0b: same URL already clustered under a different title (cross-source same article)
        url_existing = con.execute(
            "SELECT id, cluster_id FROM raw_items WHERE url_hash = ? AND cluster_id IS NOT NULL LIMIT 1",
            [uhash],
        ).fetchone()
        if url_existing:
            existing_raw_id, existing_cluster_id = url_existing
            # Insert the new raw item as a duplicate, attached to the existing cluster
            con.execute(
                """
                INSERT INTO raw_items
                    (source_id, url, title, body_text, author, published_at,
                     url_hash, title_hash, content_hash, duplicate_of, cluster_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    item.source_id, item.url, item.title, item.body_text,
                    item.author,
                    item.published_at.replace(tzinfo=timezone.utc) if item.published_at else None,
                    uhash, thash, chash, existing_raw_id, existing_cluster_id,
                ],
            )
            # Update the cluster's source_ids list to include this new source
            existing_src = con.execute(
                "SELECT source_ids FROM clusters WHERE id = ?", [existing_cluster_id]
            ).fetchone()
            if existing_src:
                source_ids = list(existing_src[0] or [])
                if item.source_id not in source_ids:
                    source_ids.append(item.source_id)
                    con.execute(
                        "UPDATE clusters SET source_ids = ? WHERE id = ?",
                        [source_ids, existing_cluster_id],
                    )
            logger.debug(
                "URL-duplicate: item from %s merged into cluster %d",
                item.source_id, existing_cluster_id,
            )
            continue
        con.execute(
            """
            INSERT INTO raw_items
                (source_id, url, title, body_text, author, published_at,
                 url_hash, title_hash, content_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                item.source_id, item.url, item.title, item.body_text,
                item.author,
                item.published_at.replace(tzinfo=timezone.utc) if item.published_at else None,
                uhash, thash, chash,
            ],
        )
        new_count += 1
        # Scan the item's page for RSS feeds (once per domain per process)
        if item.url:
            try:
                fetch_and_autodiscover(item.url, con)
            except Exception:
                pass
    return new_count


def _update_scheduler(source_id: str, new_count: int, con: duckdb.DuckDBPyConnection, cfg) -> None:
    now = datetime.now(timezone.utc)
    row = con.execute(
        "SELECT last_fetched_at, ema_interval_s, ema_alpha, consecutive_empty FROM sources WHERE id = ?",
        [source_id],
    ).fetchone()
    if not row:
        return
    last_fetched, ema, alpha, consec_empty = row

    if new_count > 0 and last_fetched:
        observed_gap = (now - last_fetched).total_seconds()
        ema = alpha * observed_gap + (1 - alpha) * ema
        consec_empty = 0
    else:
        consec_empty += 1

    backoff = 2 ** (consec_empty // 3)
    interval = min(ema * backoff, cfg.max_interval_seconds)
    interval = max(interval, cfg.min_interval_seconds)

    if _is_active_reader():
        interval = interval * cfg.active_reader_boost
        interval = max(interval, cfg.min_interval_seconds)

    from datetime import timedelta
    next_fetch = now + timedelta(seconds=interval)

    con.execute(
        """
        UPDATE sources
        SET last_fetched_at   = ?,
            next_fetch_at     = ?,
            ema_interval_s    = ?,
            consecutive_empty = ?,
            fetch_error_count = 0,
            last_error        = NULL
        WHERE id = ?
        """,
        [now, next_fetch, ema, consec_empty, source_id],
    )


def run_fetch(source_cfg: SourceConfig, sched_cfg, pipeline_fn) -> None:
    """Fetch one source, persist items, run pipeline, update scheduler state."""
    con = database.get()
    items = _fetch_source(source_cfg, sched_cfg)
    new_count = _persist_items(items, con)
    if new_count > 0:
        logger.info("Source %s: %d new items", source_cfg.id, new_count)
        try:
            pipeline_fn(source_cfg.id, con)
        except Exception:
            logger.exception("Pipeline error for source %s", source_cfg.id)
    _update_scheduler(source_cfg.id, new_count, con, sched_cfg)


async def run_scheduler(cfg: Config, pipeline_fn) -> None:
    """Main scheduler coroutine. Dispatches due sources to thread pool."""
    sched_cfg = cfg.scheduler
    source_map = {s.id: s for s in cfg.sources}
    loop = asyncio.get_running_loop()

    logger.info("Scheduler started, watching %d sources", len(source_map))

    while True:
        try:
            con = database.get()
            due = con.execute(
                """
                SELECT id FROM sources
                WHERE enabled = TRUE
                  AND (next_fetch_at IS NULL OR next_fetch_at <= now())
                ORDER BY next_fetch_at ASC NULLS FIRST
                LIMIT 10
                """
            ).fetchall()

            for (sid,) in due:
                if sid not in source_map:
                    continue
                src = source_map[sid]
                loop.run_in_executor(_executor, run_fetch, src, sched_cfg, pipeline_fn)

        except Exception:
            logger.exception("Scheduler loop error")

        await asyncio.sleep(10)


async def breaking_news_detector(cfg: Config, push_fn) -> None:
    """Detects topic spikes and marks clusters as breaking news."""
    window = cfg.scheduler.breaking_news_window_minutes
    threshold = cfg.scheduler.breaking_news_threshold

    while True:
        try:
            con = database.get()
            spikes = con.execute(
                f"""
                SELECT t.topic, count(*) AS n
                FROM clusters c, UNNEST(c.topics) AS t(topic)
                WHERE c.created_at >= now() - INTERVAL '{window} minutes'
                GROUP BY t.topic
                HAVING count(*) >= {threshold}
                """
            ).fetchall()

            for topic, n in spikes:
                updated = con.execute(
                    """
                    UPDATE clusters SET is_breaking = TRUE
                    WHERE is_breaking = FALSE
                      AND list_contains(topics, ?)
                      AND created_at >= now() - INTERVAL '1 hour'
                    RETURNING id
                    """,
                    [topic],
                ).fetchall()
                for (cid,) in updated:
                    logger.info("Breaking news: cluster %d on topic '%s'", cid, topic)
                    try:
                        await push_fn({"type": "breaking", "cluster_id": cid, "topic": topic})
                    except Exception:
                        pass
        except Exception:
            logger.exception("Breaking news detector error")

        await asyncio.sleep(60)
