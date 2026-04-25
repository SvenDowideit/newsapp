from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

import duckdb
import numpy as np

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
    items = con.execute(
        """
        SELECT id, title, body_text, url, source_id
        FROM raw_items
        WHERE cluster_id IS NULL
          AND duplicate_of IS NULL
          AND source_id = ?
        ORDER BY id ASC
        """,
        [source_id],
    ).fetchall()

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

    # Gate 2: embedding similarity dedup
    # Skip if we already embedded this item in a previous (failed) attempt
    existing_embed = con.execute(
        "SELECT id FROM embeddings WHERE raw_item_id = ?", [item_id]
    ).fetchone()

    if existing_embed is None:
        text_for_embed = f"{title or ''} {(body or '')[:500]}"
        vec = embed(text_for_embed, ollama_cfg)

        if vec is not None:
            dup_id = _find_embedding_duplicate(item_id, vec, con)
            if dup_id is not None:
                con.execute(
                    "UPDATE raw_items SET duplicate_of = ? WHERE id = ?",
                    [dup_id, item_id],
                )
                logger.debug("Item %d is embedding-duplicate of %d", item_id, dup_id)
                return

            con.execute(
                """
                INSERT INTO embeddings (raw_item_id, model, vector) VALUES (?, ?, ?)
                ON CONFLICT (raw_item_id) DO NOTHING
                """,
                [item_id, ollama_cfg.embed_model, vec],
            )
            embed_row = con.execute(
                "SELECT id FROM embeddings WHERE raw_item_id = ?", [item_id]
            ).fetchone()
            if embed_row:
                con.execute("UPDATE raw_items SET embed_id = ? WHERE id = ?", [embed_row[0], item_id])
    else:
        vec = con.execute(
            "SELECT vector FROM embeddings WHERE raw_item_id = ?", [item_id]
        ).fetchone()
        vec = vec[0] if vec else None

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
    rows = con.execute(
        """
        SELECT e.raw_item_id, e.vector
        FROM embeddings e
        JOIN raw_items r ON r.id = e.raw_item_id
        WHERE r.fetched_at >= now() - INTERVAL '7 days'
          AND r.duplicate_of IS NULL
          AND e.raw_item_id != ?
        LIMIT 500
        """,
        [item_id],
    ).fetchall()

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
    limit: int = 10,
) -> list[dict]:
    """Find nearest clusters by embedding similarity (via raw_items embeddings)."""
    rows = con.execute(
        """
        SELECT DISTINCT c.id, c.headline
        FROM clusters c
        JOIN raw_items r ON r.cluster_id = c.id
        JOIN embeddings e ON e.raw_item_id = r.id
        WHERE c.latest_seen_at >= now() - INTERVAL '3 days'
        LIMIT 200
        """
    ).fetchall()

    if not rows:
        return []

    # For MVP: return most recent clusters as candidates (full ANN not needed yet)
    recent = con.execute(
        """
        SELECT id, headline FROM clusters
        WHERE latest_seen_at >= now() - INTERVAL '3 days'
        ORDER BY latest_seen_at DESC
        LIMIT 10
        """
    ).fetchall()
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
    cluster_row = con.execute(
        """
        INSERT INTO clusters
            (first_seen_at, latest_seen_at, canonical_url, headline, summary,
             key_points, topics, source_ids, item_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
        RETURNING id
        """,
        [
            now, now, url,
            result.get("headline") or title or "Untitled",
            result.get("summary") or "",
            json.dumps(result.get("key_points", [])),
            result.get("topics", []),
            [source_id],
        ],
    ).fetchone()
    if cluster_row:
        cid = cluster_row[0]
        con.execute("UPDATE raw_items SET cluster_id = ? WHERE id = ?", [cid, item_id])
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
    con.execute("UPDATE raw_items SET cluster_id = ? WHERE id = ?", [cluster_id, item_id])

    # Fetch all items in cluster for re-summarisation
    articles = con.execute(
        """
        SELECT title, body_text FROM raw_items
        WHERE cluster_id = ? AND duplicate_of IS NULL
        LIMIT 5
        """,
        [cluster_id],
    ).fetchall()

    article_list = [{"title": a[0], "body": a[1]} for a in articles]
    result = summarise_cluster(article_list, ollama_cfg)
    now = datetime.now(timezone.utc)

    # Update source_ids list
    existing = con.execute(
        "SELECT source_ids, item_count FROM clusters WHERE id = ?", [cluster_id]
    ).fetchone()
    source_ids = list(existing[0] or [])
    if source_id not in source_ids:
        source_ids.append(source_id)
    item_count = (existing[1] or 0) + 1

    con.execute(
        """
        UPDATE clusters
        SET updated_at     = ?,
            latest_seen_at = ?,
            headline       = ?,
            summary        = ?,
            key_points     = ?,
            topics         = ?,
            source_ids     = ?,
            item_count     = ?
        WHERE id = ?
        """,
        [
            now, now,
            result.get("headline") or "",
            result.get("summary") or "",
            json.dumps(result.get("key_points", [])),
            result.get("topics", []),
            source_ids,
            item_count,
            cluster_id,
        ],
    )
    logger.debug("Appended item %d to cluster %d (now %d items)", item_id, cluster_id, item_count)
