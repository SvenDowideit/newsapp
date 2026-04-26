from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import numpy as np

from .. import db as database
from .embed import embed
from .cluster import assign_cluster
from .summarise import summarise_single, summarise_cluster

if TYPE_CHECKING:
    from ..config import Config

logger = logging.getLogger(__name__)

_EMBED_SIM_THRESHOLD = 0.92
_CLUSTER_CONF_THRESHOLD = 0.70


def run_pipeline(source_id: str, cfg: "Config") -> None:
    """Process all unprocessed raw items for a source.

    Each DB operation is a separate run_sync call so the DB worker is never
    held while ollama HTTP requests are in flight.
    """
    items = database.run_sync(
        lambda con: database.get_unprocessed_items(source_id, con),
        priority=database.BG,
    )
    for (item_id, title, body, url, sid) in items:
        try:
            _process_item(item_id, title, body, url, sid, cfg)
        except Exception:
            logger.exception("Pipeline error on item %d", item_id)


def _process_item(
    item_id: int,
    title: str | None,
    body: str | None,
    url: str | None,
    source_id: str,
    cfg: "Config",
) -> None:
    ollama_cfg = cfg.ollama

    # ── Step 1: DB read — do we already have an embedding? ──────────────────
    existing_embed = database.run_sync(
        lambda con: database.get_embedding_for_item(item_id, con),
        priority=database.BG,
    )

    vec = None
    if existing_embed is None:
        # ── Step 2: ollama HTTP — compute embedding (outside DB worker) ──────
        text_for_embed = f"{title or ''} {(body or '')[:500]}"
        vec = embed(text_for_embed, ollama_cfg)

        if vec is not None:
            # ── Step 3: DB read — check for embedding duplicate ──────────────
            recent_embeddings = database.run_sync(
                lambda con: database.get_recent_embeddings(item_id, con),
                priority=database.BG,
            )
            dup_id = _find_embedding_duplicate(vec, recent_embeddings)
            if dup_id is not None:
                database.run_sync(
                    lambda con: database.mark_item_duplicate(item_id, dup_id, con),
                    priority=database.BG,
                )
                logger.debug("Item %d is embedding-duplicate of %d", item_id, dup_id)
                return

            # ── Step 4: DB write — store embedding ───────────────────────────
            database.run_sync(
                lambda con: _store_embedding(item_id, ollama_cfg.embed_model, vec, con),
                priority=database.BG,
            )
    else:
        vec = database.run_sync(
            lambda con: database.get_embedding_vector(item_id, con),
            priority=database.BG,
        )

    # ── Step 5: DB read — get candidate clusters ─────────────────────────────
    recent_clusters = database.run_sync(
        database.get_recent_clusters,
        priority=database.BG,
    )
    candidates = [{"id": r[0], "headline": r[1]} for r in recent_clusters]

    # ── Step 6: ollama HTTP — cluster assignment (outside DB worker) ─────────
    cluster_id, confidence = assign_cluster(title, body, candidates, ollama_cfg)

    if cluster_id is not None and confidence >= _CLUSTER_CONF_THRESHOLD:
        _append_to_cluster(item_id, cluster_id, title, body, url, source_id, cfg)
    else:
        _create_cluster(item_id, title, body, url, source_id, cfg)


def _store_embedding(item_id: int, model: str, vec, con) -> None:
    embed_id = database.insert_embedding(item_id, model, vec, con)
    if embed_id:
        database.set_item_embed(item_id, embed_id, con)


def _find_embedding_duplicate(vec, rows) -> int | None:
    if not rows:
        return None
    query_vec = np.array(vec, dtype=np.float32)
    best_id = None
    best_sim = 0.0
    for (rid, rvec) in rows:
        if rvec is None:
            continue
        rv = np.array(rvec, dtype=np.float32)
        sim = float(np.dot(query_vec, rv))
        if sim > best_sim:
            best_sim = sim
            best_id = rid
    return best_id if best_sim >= _EMBED_SIM_THRESHOLD else None


def _geo_interest_weights(locations: dict, geo_cfg) -> list[tuple[str, float]]:
    """Return (topic_tag, weight) pairs for any geo locations matching user config."""
    if not locations or not geo_cfg:
        return []
    results = []
    for level in ("city", "state", "country", "region"):
        place = locations.get(level)
        if not place:
            continue
        place_lower = place.lower()
        configured: dict[str, float] = getattr(geo_cfg, level, {})
        for name, weight in configured.items():
            if name.lower() in place_lower or place_lower in name.lower():
                tag = f"geo:{level}:{place_lower}"
                results.append((tag, weight))
                break
    return results


def _apply_geo_weights(cluster_id: int, locations: dict, geo_cfg, interest_cfg) -> None:
    """Seed interest_weights for geo tags matched by user config."""
    pairs = _geo_interest_weights(locations, geo_cfg)
    if not pairs:
        return

    def _write(con):
        for tag, weight in pairs:
            database.set_topic_interest(tag, weight, con)
            logger.debug("geo interest: cluster %d tag=%s weight=%.2f", cluster_id, tag, weight)

    database.run_sync(_write, priority=database.BG)


def _create_cluster(
    item_id: int,
    title: str | None,
    body: str | None,
    url: str | None,
    source_id: str,
    cfg,
) -> None:
    ollama_cfg = cfg.ollama
    # ollama call outside DB worker
    result = summarise_single(title or "", body or "", ollama_cfg)
    locations = result.get("locations") or {}
    now = datetime.now(timezone.utc)

    # Merge geo tags into topics so they participate in interest scoring
    topics = result.get("topics", [])
    for level in ("city", "state", "country", "region"):
        place = locations.get(level)
        if place:
            geo_tag = f"geo:{level}:{place.lower()}"
            if geo_tag not in topics:
                topics.append(geo_tag)

    def _write(con):
        cid = database.insert_cluster(
            con, now, now, url,
            result.get("headline") or title or "Untitled",
            result.get("summary") or "",
            json.dumps(result.get("key_points", [])),
            topics,
            [source_id],
        )
        if cid:
            database.set_item_cluster(item_id, cid, con)
            logger.debug("Created cluster %d for item %d", cid, item_id)
        return cid

    cid = database.run_sync(_write, priority=database.BG)
    if cid:
        _apply_geo_weights(cid, locations, cfg.geography, cfg.interest)


def _append_to_cluster(
    item_id: int,
    cluster_id: int,
    title: str | None,
    body: str | None,
    url: str | None,
    source_id: str,
    cfg,
) -> None:
    ollama_cfg = cfg.ollama
    # ── DB read — mark item, get articles for summarisation ──────────────────
    def _read(con):
        database.set_item_cluster(item_id, cluster_id, con)
        articles = database.get_items_for_cluster(cluster_id, con)
        row = database.get_cluster_source_ids(cluster_id, con)
        return articles, row

    articles, row = database.run_sync(_read, priority=database.BG)

    article_list = [{"title": a[0], "body": a[1]} for a in articles]

    # ollama call outside DB worker
    result = summarise_cluster(article_list, ollama_cfg)
    locations = result.get("locations") or {}
    now = datetime.now(timezone.utc)

    source_ids = list(row[0] or [])
    if source_id not in source_ids:
        source_ids.append(source_id)
    item_count = (row[1] or 0) + 1

    topics = result.get("topics", [])
    for level in ("city", "state", "country", "region"):
        place = locations.get(level)
        if place:
            geo_tag = f"geo:{level}:{place.lower()}"
            if geo_tag not in topics:
                topics.append(geo_tag)

    database.run_sync(
        lambda con: database.update_cluster(
            con, cluster_id, now,
            result.get("headline") or "",
            result.get("summary") or "",
            json.dumps(result.get("key_points", [])),
            topics,
            source_ids,
            item_count,
        ),
        priority=database.BG,
    )
    _apply_geo_weights(cluster_id, locations, cfg.geography, cfg.interest)
    logger.debug("Appended item %d to cluster %d (now %d items)", item_id, cluster_id, item_count)
