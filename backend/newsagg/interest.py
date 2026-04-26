from __future__ import annotations

from typing import TYPE_CHECKING

from . import db

if TYPE_CHECKING:
    from .config import InterestConfig
    import duckdb


def update(cluster_id: int, event_type: str, con: "duckdb.DuckDBPyConnection",
           cfg: "InterestConfig") -> None:
    delta = cfg.rate_for(event_type)
    db.update_interest_weights(cluster_id, event_type, delta, cfg.decay_rate, con)
