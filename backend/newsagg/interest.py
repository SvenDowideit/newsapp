from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import duckdb

if TYPE_CHECKING:
    from .config import InterestConfig

logger = logging.getLogger(__name__)


def update(cluster_id: int, event_type: str, con: duckdb.DuckDBPyConnection, cfg: "InterestConfig") -> None:
    delta = cfg.rate_for(event_type)
    if delta == 0.0:
        return

    # Global decay: pull all weights slightly toward 0.5
    con.execute(
        "UPDATE interest_weights SET weight = weight + (0.5 - weight) * ?",
        [cfg.decay_rate],
    )

    topics_row = con.execute(
        "SELECT topics FROM clusters WHERE id = ?", [cluster_id]
    ).fetchone()
    if not topics_row or not topics_row[0]:
        return

    for topic in topics_row[0]:
        con.execute(
            """
            INSERT INTO interest_weights (topic, weight, event_count, last_updated)
            VALUES (?, GREATEST(0, LEAST(1, 0.5 + ?)), 1, now())
            ON CONFLICT (topic) DO UPDATE SET
                weight       = GREATEST(0, LEAST(1, interest_weights.weight + excluded.weight - 0.5)),
                event_count  = interest_weights.event_count + 1,
                last_updated = now()
            """,
            [topic, delta],
        )
