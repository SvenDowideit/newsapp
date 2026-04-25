from __future__ import annotations

import json
import threading
from pathlib import Path

import duckdb

_local = threading.local()
_db_path: str = "news.duckdb"
_lock = threading.Lock()


def init(db_path: str) -> None:
    global _db_path
    _db_path = db_path
    # Run migrations on a dedicated connection, then close it.
    con = duckdb.connect(_db_path)
    _run_migrations(con)
    _reseed_sequences(con)
    con.close()


def _reseed_sequences(con: duckdb.DuckDBPyConnection) -> None:
    """Advance each sequence past the highest existing ID to prevent PK collisions."""
    reseeds = [
        ("seq_raw_items",   "SELECT coalesce(max(id), 0) FROM raw_items"),
        ("seq_clusters",    "SELECT coalesce(max(id), 0) FROM clusters"),
        ("seq_embeddings",  "SELECT coalesce(max(id), 0) FROM embeddings"),
        ("seq_read_events", "SELECT coalesce(max(id), 0) FROM read_events"),
    ]
    for seq, query in reseeds:
        try:
            row = con.execute(query).fetchone()
            max_id = row[0] if row else 0
            if max_id > 0:
                # setval sets the sequence's next value to max_id + 1
                con.execute(f"SELECT setval('{seq}', {max_id})")
        except Exception:
            pass  # table may not exist yet on first run


def get() -> duckdb.DuckDBPyConnection:
    """Return a per-thread DuckDB connection."""
    con = getattr(_local, "con", None)
    if con is None:
        _local.con = duckdb.connect(_db_path)
        con = _local.con
    return con


def _run_migrations(con: duckdb.DuckDBPyConnection) -> None:
    migrations_dir = Path(__file__).parent.parent / "migrations"
    # Ensure the tracking table exists first (bootstrap)
    con.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    VARCHAR PRIMARY KEY,
            applied_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    applied = {row[0] for row in con.execute("SELECT version FROM schema_migrations").fetchall()}

    for sql_file in sorted(migrations_dir.glob("*.sql")):
        version = sql_file.stem
        if version in applied:
            continue
        sql = sql_file.read_text()
        con.execute("BEGIN")
        try:
            con.execute(sql)
            con.execute("INSERT INTO schema_migrations (version) VALUES (?)", [version])
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise


def upsert_sources(sources: list, con: duckdb.DuckDBPyConnection | None = None) -> None:
    """Sync source rows from config into DB without wiping scheduler state."""
    con = con or get()
    for src in sources:
        existing = con.execute(
            "SELECT id FROM sources WHERE id = ?", [src.id]
        ).fetchone()
        config_json = json.dumps(src.extra)
        if existing:
            con.execute(
                "UPDATE sources SET type=?, label=?, config_json=? WHERE id=?",
                [src.type, src.label, config_json, src.id],
            )
        else:
            con.execute(
                """
                INSERT INTO sources (id, type, label, config_json)
                VALUES (?, ?, ?, ?)
                """,
                [src.id, src.type, src.label, config_json],
            )
