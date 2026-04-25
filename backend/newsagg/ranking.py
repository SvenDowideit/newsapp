from __future__ import annotations

import logging

import duckdb

logger = logging.getLogger(__name__)


def refresh_scores(con: duckdb.DuckDBPyConnection) -> None:
    """Recompute combined_score for clusters whose score is stale (>5 min old)."""
    con.execute(
        """
        UPDATE clusters
        SET
            recency_score  = exp(-extract(epoch FROM (now() - latest_seen_at)) / 86400.0),
            interest_score = (
                SELECT coalesce(avg(w.weight), 0.5)
                FROM (SELECT unnest(clusters.topics)) AS t(topic)
                LEFT JOIN interest_weights w ON w.topic = t.topic
            ),
            combined_score = 0.4 * exp(-extract(epoch FROM (now() - latest_seen_at)) / 86400.0)
                           + 0.6 * (
                               SELECT coalesce(avg(w.weight), 0.5)
                               FROM (SELECT unnest(clusters.topics)) AS t(topic)
                               LEFT JOIN interest_weights w ON w.topic = t.topic
                           ),
            scored_at = now()
        WHERE scored_at IS NULL
           OR scored_at < now() - INTERVAL '5 minutes'
        """
    )
