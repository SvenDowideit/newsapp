from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import duckdb
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


def run_pipeline(source_id: str, con: duckdb.DuckDBPyConnection, cfg: "Config") -> None:
    """Process all unprocessed raw items for a source through the full pipeline."""
    items = database.get_unprocessed_items(source_id, con)

    for (item_id, title, body, url, sid) in items:
        try:
            _process_item(item_id, title, body, url, sid, con, cfg)
        except Exception:
            logger.exception("Pipeline error on item %d", item_id)


def _process_item(
    item_id: int,
    title: str | None,
    body: str | None,
    url: str | None,
    source_id: str,
    con: duckdb.DuckDBPyConnection,
    cfg: "Config",
) -> None:
    ollama_cfg = cfg.ollama

    existing_embed = database.get_embedding_for_item(item_id, con)

    if existing_embed is None:
        text_for_embed = f"{title or ''} {(body or '')[:500]}"
        vec = embed(text_for_embed, ollama_cfg)

        if vec is not None:
            dup_id = _find_embedding_duplicate(item_id, vec, con)
            if dup_id is not None:
                database.mark_item_duplicate(item_id, dup_id, con)
                logger.debug("Item %d is embedding-duplicate of %d", item_id, dup_id)
                return

            embed_id = database.insert_embedding(item_id, ollama_cfg.embed_model, vec, con)
            if embed_id:
                database.set_item_embed(item_id, embed_id, con)
    else:
        vec = database.get_embedding_vector(item_id, con)

    # Gate 3: cluster assignment
    candidate_clusters = _find_candidate_clusters(vec, con) if vec else []
    cluster_id, confidence = assign_cluster(title, body, candidate_clusters, ollama_cfg)

    if cluster_id is not None and confidence >= _CLUSTER_CONF_THRESHOLD:
        _append_to_cluster(item_id, cluster_id, title, body, url, source_id, con, ollama_cfg)
    else:
        _create_cluster(item_id, title, body, url, source_id, con, ollama_cfg)


def _find_embedding_duplicate(
    item_id: int,
    vec: list[float],
    con: duckdb.DuckDBPyConnection,
) -> int | None:
    rows = database.get_recent_embeddings(item_id, con)

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

    if best_sim >= _EMBED_SIM_THRESHOLD:
        return best_id
    return None


def _find_candidate_clusters(
    vec: list[float],
    con: duckdb.DuckDBPyConnection,
) -> list[dict]:
    recent = database.get_recent_clusters(con)
    return [{"id": r[0], "headline": r[1]} for r in recent]


def _create_cluster(
    item_id: int,
    title: str | None,
    body: str | None,
    url: str | None,
    source_id: str,
    con: duckdb.DuckDBPyConnection,
    ollama_cfg,
) -> None:
    result = summarise_single(title or "", body or "", ollama_cfg)
    now = datetime.now(timezone.utc)
    cid = database.insert_cluster(
        con, now, now, url,
        result.get("headline") or title or "Untitled",
        result.get("summary") or "",
        json.dumps(result.get("key_points", [])),
        result.get("topics", []),
        [source_id],
    )
    if cid:
        database.set_item_cluster(item_id, cid, con)
        logger.debug("Created cluster %d for item %d", cid, item_id)


def _append_to_cluster(
    item_id: int,
    cluster_id: int,
    title: str | None,
    body: str | None,
    url: str | None,
    source_id: str,
    con: duckdb.DuckDBPyConnection,
    ollama_cfg,
) -> None:
    database.set_item_cluster(item_id, cluster_id, con)

    articles = database.get_items_for_cluster(cluster_id, con)
    article_list = [{"title": a[0], "body": a[1]} for a in articles]
    result = summarise_cluster(article_list, ollama_cfg)
    now = datetime.now(timezone.utc)

    row = database.get_cluster_source_ids(cluster_id, con)
    source_ids = list(row[0] or [])
    if source_id not in source_ids:
        source_ids.append(source_id)
    item_count = (row[1] or 0) + 1

    database.update_cluster(
        con, cluster_id, now,
        result.get("headline") or "",
        result.get("summary") or "",
        json.dumps(result.get("key_points", [])),
        result.get("topics", []),
        source_ids,
        item_count,
    )
    logger.debug("Appended item %d to cluster %d (now %d items)", item_id, cluster_id, item_count)
