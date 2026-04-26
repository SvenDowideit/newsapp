from __future__ import annotations

import asyncio
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

from ..config import Config, SourceConfig
from .. import db as database
from . import hackernews, google_news, reddit, rss, scraper, search, youtube, email_imap
from .types import RawItem
from .hashing import content_hash, url_hash, title_hash, resolve_url
from .rss_discovery import autodiscover_rss, fetch_and_autodiscover

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="fetcher")

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


def _persist_items(items: list[RawItem]) -> int:
    """Resolve URLs, then insert items via DB worker. Returns count of new items."""
    # Phase 1: all HTTP work happens here, outside the DB worker
    resolved: list[tuple[RawItem, str | None]] = []
    for item in items:
        final_url, html = resolve_url(item.url, reason="ingest")
        item.url = final_url
        resolved.append((item, html))

    # Phase 2: single DB transaction via worker
    def _fn(con):
        new_count = 0
        for item, html in resolved:
            if html and item.url:
                try:
                    autodiscover_rss(item.url, html, con)
                except Exception:
                    pass

            chash = content_hash(item.url, item.title)
            uhash = url_hash(item.url)
            thash = title_hash(item.title)

            if database.get_raw_item_by_content_hash(chash, con):
                continue

            url_dup = database.get_raw_item_by_url_hash_clustered(uhash, con)
            if url_dup:
                existing_raw_id, existing_cluster_id = url_dup
                pub = item.published_at.replace(tzinfo=timezone.utc) if item.published_at else None
                database.insert_raw_item(
                    con, item.source_id, item.url, item.title, item.body_text,
                    item.author, pub, uhash, thash, chash,
                    duplicate_of=existing_raw_id, cluster_id=existing_cluster_id,
                )
                database.add_source_to_cluster(existing_cluster_id, item.source_id, con)
                logger.debug(
                    "URL-duplicate: item from %s merged into cluster %d",
                    item.source_id, existing_cluster_id,
                )
                continue

            pub = item.published_at.replace(tzinfo=timezone.utc) if item.published_at else None
            database.insert_raw_item(
                con, item.source_id, item.url, item.title, item.body_text,
                item.author, pub, uhash, thash, chash,
            )
            new_count += 1
        return new_count

    new_count = database.run_sync(_fn, priority=database.BG)

    # Phase 3: RSS autodiscovery for new item pages — HTTP only, outside DB worker
    for item, _ in resolved:
        if item.url:
            try:
                fetch_and_autodiscover(item.url)
            except Exception:
                pass

    return new_count


def _update_scheduler(source_id: str, new_count: int, cfg) -> None:
    def _fn(con):
        row = database.get_source_schedule(source_id, con)
        if not row:
            return
        last_fetched, ema, alpha, consec_empty = row
        now = datetime.now(timezone.utc)

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

        next_fetch = now + timedelta(seconds=interval)
        database.update_source_schedule(source_id, now, next_fetch, ema, consec_empty, con)

    database.run_sync(_fn, priority=database.BG)


def run_fetch(source_cfg: SourceConfig, sched_cfg, pipeline_fn) -> None:
    """Fetch one source, persist items, run pipeline, update scheduler state."""
    items = _fetch_source(source_cfg, sched_cfg)
    new_count = _persist_items(items)
    if new_count > 0:
        logger.info("Source %s: %d new items", source_cfg.id, new_count)
        try:
            database.run_sync(lambda con: pipeline_fn(source_cfg.id, con), priority=database.BG)
        except Exception:
            logger.exception("Pipeline error for source %s", source_cfg.id)
    _update_scheduler(source_cfg.id, new_count, sched_cfg)


async def run_scheduler(cfg: Config, pipeline_fn) -> None:
    sched_cfg = cfg.scheduler
    source_map = {s.id: s for s in cfg.sources}
    loop = asyncio.get_running_loop()

    logger.info("Scheduler started, watching %d config sources", len(source_map))

    while True:
        try:
            due = await database.arun(database.get_due_sources, priority=database.BG)

            for (sid,) in due:
                src = source_map.get(sid)
                if src is None:
                    # Source not in config — may be auto-discovered; load from DB
                    row = await database.arun(
                        lambda con, _sid=sid: database.get_source_config(_sid, con),
                        priority=database.BG,
                    )
                    if row is None:
                        continue
                    src_type, src_label, src_config_json = row
                    extra = json.loads(src_config_json) if src_config_json else {}
                    src = SourceConfig(id=sid, type=src_type, label=src_label, extra=extra)
                loop.run_in_executor(_executor, run_fetch, src, sched_cfg, pipeline_fn)

        except Exception:
            logger.exception("Scheduler loop error")

        await asyncio.sleep(10)


async def breaking_news_detector(cfg: Config, push_fn) -> None:
    window = cfg.scheduler.breaking_news_window_minutes
    threshold = cfg.scheduler.breaking_news_threshold

    while True:
        try:
            spikes = await database.arun(
                lambda con: database.get_topic_spikes(con, window, threshold),
                priority=database.BG,
            )

            for topic, n in spikes:
                updated = await database.arun(
                    lambda con, _t=topic: database.mark_clusters_breaking(_t, window, con),
                    priority=database.BG,
                )
                for (cid,) in updated:
                    logger.info("Breaking news: cluster %d on topic '%s'", cid, topic)
                    try:
                        await push_fn({"type": "breaking", "cluster_id": cid, "topic": topic})
                    except Exception:
                        pass
        except Exception:
            logger.exception("Breaking news detector error")

        await asyncio.sleep(60)
