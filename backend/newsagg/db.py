"""
All DuckDB access is funnelled through a single worker thread that owns the
connection.  Two priority queues separate interactive (UI/API) work from
background (fetcher/pipeline) work:

  UI_PRIORITY   = 0   — fed by arun(..., priority=UI)   / run_sync(..., priority=UI)
  BG_PRIORITY   = 1   — fed by arun(..., priority=BG)   / run_sync(..., priority=BG)

The worker drains the UI queue first; background work only runs when the UI
queue is empty.  Within each queue items are ordered by a monotonically
increasing sequence number so that equal-priority items are FIFO.

All SQL lives in this module.  Callers import named helper functions; they
never write SQL themselves and never hold a DuckDB connection.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from concurrent.futures import Future as ThreadFuture
from datetime import datetime, timezone, timedelta
from pathlib import Path
from queue import PriorityQueue, Empty

import duckdb

logger = logging.getLogger(__name__)

UI = 0   # interactive / API priority
BG = 1   # background fetcher / pipeline priority

_db_path: str = "news.duckdb"
_ui_queue: PriorityQueue = PriorityQueue()   # priority-0 work (API/UI)
_bg_queue: PriorityQueue = PriorityQueue()   # priority-1 work (background)
_worker_thread: threading.Thread | None = None
_seq = 0
_seq_lock = threading.Lock()
_shutdown = threading.Event()


def _next_seq() -> int:
    global _seq
    with _seq_lock:
        _seq += 1
        return _seq


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

class _LoggingConn:
    """Thin proxy around a DuckDB connection that logs every execute() call."""
    def __init__(self, con):
        self._con = con

    def execute(self, sql: str, params=None):
        sql_short = " ".join(sql.split())[:120]
        if params is not None:
            logger.info("db-sql: %s  params=%r", sql_short, params)
        else:
            logger.info("db-sql: %s", sql_short)
        if params is not None:
            return self._con.execute(sql, params)
        return self._con.execute(sql)

    def __getattr__(self, name):
        return getattr(self._con, name)


def _worker(db_path: str) -> None:
    """Single DB worker thread — owns the DuckDB connection exclusively."""
    raw_con = duckdb.connect(db_path)
    con = _LoggingConn(raw_con)
    _run_migrations(con)
    _reseed_sequences(con)
    while not _shutdown.is_set():
        # Always check UI queue first — never block while it has work
        item = None
        try:
            item = _ui_queue.get_nowait()
            queue_name = "ui"
        except Empty:
            try:
                item = _bg_queue.get_nowait()
                queue_name = "bg"
            except Empty:
                # Both queues empty — sleep briefly then re-check
                _shutdown.wait(timeout=0.01)
                continue

        _seq_num, fut, fn = item
        if fn is None:
            break  # shutdown sentinel
        fn_name = getattr(fn, "__name__", None) or getattr(fn, "__qualname__", repr(fn))
        caller_thread = getattr(fn, "_caller_thread", "?")
        caller_site = getattr(fn, "_caller_site", "?")
        logger.info("db-worker [%s] seq=%d fn=%s submitted-by=%s from=%s",
                    queue_name, _seq_num, fn_name, caller_thread, caller_site)
        try:
            result = fn(con)
            logger.info("db-worker [%s] seq=%d fn=%s -> ok", queue_name, _seq_num, fn_name)
        except BaseException as exc:
            logger.error("db-worker [%s] seq=%d fn=%s -> EXCEPTION %r",
                         queue_name, _seq_num, fn_name, exc)
            _resolve_future(fut, None, exc)
        else:
            _resolve_future(fut, result, None)


def _resolve_future(fut, result, exc):
    if isinstance(fut, ThreadFuture):
        if exc is not None:
            fut.set_exception(exc)
        else:
            fut.set_result(result)
    else:
        loop, afut = fut
        if exc is not None:
            loop.call_soon_threadsafe(afut.set_exception, exc)
        else:
            loop.call_soon_threadsafe(afut.set_result, result)


# ---------------------------------------------------------------------------
# Public dispatch helpers
# ---------------------------------------------------------------------------

def init(db_path: str) -> None:
    global _db_path, _worker_thread
    _db_path = db_path
    _shutdown.clear()
    _worker_thread = threading.Thread(
        target=_worker, args=(db_path,), daemon=True, name="db-worker"
    )
    _worker_thread.start()


async def arun(fn, priority: int = UI):
    """Await fn(con) on the DB worker. Use priority=UI for API, priority=BG for background."""
    loop = asyncio.get_running_loop()
    afut = loop.create_future()
    _enqueue(priority, (loop, afut), fn)
    return await afut


def run_sync(fn, priority: int = BG):
    """Submit fn(con) from any thread and block until complete."""
    fut: ThreadFuture = ThreadFuture()
    _enqueue(priority, fut, fn)
    return fut.result()


def _enqueue(priority: int, fut, fn):
    import traceback as _tb
    seq = _next_seq()
    # Annotate fn with caller info for the worker's log
    caller_thread = threading.current_thread().name
    # grab the first frame outside db.py
    stack = _tb.extract_stack()
    caller_site = "?"
    for frame in reversed(stack[:-1]):
        if not frame.filename.endswith("db.py"):
            caller_site = f"{frame.filename.rsplit('/',1)[-1]}:{frame.lineno} {frame.name}"
            break
    try:
        fn._caller_thread = caller_thread
        fn._caller_site = caller_site
    except (AttributeError, TypeError):
        pass  # built-in or method — can't set attributes
    logger.info("db-enqueue priority=%d seq=%d fn=%s thread=%s from=%s",
                priority, seq, getattr(fn, "__name__", None) or getattr(fn, "__qualname__", repr(fn)),
                caller_thread, caller_site)
    item = (seq, fut, fn)
    if priority <= UI:
        _ui_queue.put(item)
    else:
        _bg_queue.put(item)


def stop() -> None:
    _shutdown.set()
    if _worker_thread and _worker_thread.is_alive():
        # Drain sentinel into both queues so the worker definitely wakes
        _ui_queue.put((0, None, None))
        _worker_thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Migrations & sequence reseeding
# ---------------------------------------------------------------------------

def _reseed_sequences(con: duckdb.DuckDBPyConnection) -> None:
    reseeds = [
        ("seq_raw_items",   "SELECT coalesce(max(id), 0) FROM raw_items"),
        ("seq_clusters",    "SELECT coalesce(max(id), 0) FROM clusters"),
        ("seq_embeddings",  "SELECT coalesce(max(id), 0) FROM embeddings"),
        ("seq_read_events", "SELECT coalesce(max(id), 0) FROM read_events"),
    ]
    for seq, query in reseeds:
        try:
            row = con.execute(query).fetchone()
            max_id = (row[0] if row else 0) or 0
            # Advance the sequence by consuming values until nextval() > max_id.
            # DROP+CREATE is NOT used because it corrupts DuckDB's internal
            # catalog reference for tables that use the sequence as a DEFAULT.
            # ALTER SEQUENCE and setval() are not implemented in this DuckDB version.
            current = con.execute(f"SELECT nextval('{seq}')").fetchone()[0]
            steps = 0
            while current <= max_id:
                current = con.execute(f"SELECT nextval('{seq}')").fetchone()[0]
                steps += 1
            logger.info(
                "sequence reseed: %s max_id=%d advanced to %d (consumed %d extra values)",
                seq, max_id, current, steps,
            )
        except Exception as exc:
            logger.error("Could not reseed %s: %s", seq, exc)


def _run_migrations(con: duckdb.DuckDBPyConnection) -> None:
    migrations_dir = Path(__file__).parent.parent / "migrations"
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


# ===========================================================================
# All SQL operations — callers import these functions, never write SQL
# ===========================================================================

# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def upsert_sources(sources: list) -> None:
    def _fn(con):
        for src in sources:
            config_json = json.dumps(src.extra)
            con.execute(
                """
                INSERT INTO sources (id, type, label, config_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (id) DO UPDATE SET
                    type        = excluded.type,
                    label       = excluded.label,
                    config_json = excluded.config_json
                """,
                [src.id, src.type, src.label, config_json],
            )
    run_sync(_fn, priority=BG)


def get_all_sources(con):
    return con.execute(
        """
        SELECT id, type, label, enabled, last_fetched_at, next_fetch_at,
               ema_interval_s, fetch_error_count, last_error
        FROM sources
        ORDER BY label
        """
    ).fetchall()


def add_source(source_id: str, source_type: str, label: str, config: dict, con) -> None:
    """Must be called from within a DB worker lambda (con is the worker's connection)."""
    if con.execute("SELECT id FROM sources WHERE id = ?", [source_id]).fetchone():
        raise ValueError("conflict")
    con.execute(
        "INSERT INTO sources (id, type, label, config_json) VALUES (?, ?, ?, ?)",
        [source_id, source_type, label, json.dumps(config)],
    )


def disable_source(source_id: str, con) -> None:
    """Must be called from within a DB worker lambda (con is the worker's connection)."""
    con.execute("UPDATE sources SET enabled = FALSE WHERE id = ?", [source_id])


def get_due_sources(con):
    return con.execute(
        """
        SELECT id FROM sources
        WHERE enabled = TRUE
          AND (next_fetch_at IS NULL OR next_fetch_at <= now())
        ORDER BY next_fetch_at ASC NULLS FIRST
        LIMIT 10
        """
    ).fetchall()


def update_source_schedule(source_id: str, now: datetime, next_fetch: datetime,
                            ema: float, consec_empty: int, con) -> None:
    """Must be called from within a DB worker lambda (con is the worker's connection)."""
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


def get_source_schedule(source_id: str, con):
    return con.execute(
        "SELECT last_fetched_at, ema_interval_s, ema_alpha, consecutive_empty FROM sources WHERE id = ?",
        [source_id],
    ).fetchone()


# ---------------------------------------------------------------------------
# Raw items
# ---------------------------------------------------------------------------

def get_raw_item_by_content_hash(content_hash: str, con):
    return con.execute(
        "SELECT id FROM raw_items WHERE content_hash = ?", [content_hash]
    ).fetchone()


def get_raw_item_by_url_hash_clustered(url_hash: str, con):
    return con.execute(
        "SELECT id, cluster_id FROM raw_items WHERE url_hash = ? AND cluster_id IS NOT NULL LIMIT 1",
        [url_hash],
    ).fetchone()


def insert_raw_item(con, source_id: str, url: str | None, title: str | None,
                    body_text: str | None, author: str | None, published_at,
                    url_hash: str, title_hash: str, content_hash: str,
                    duplicate_of=None, cluster_id=None) -> int:
    row = con.execute(
        """
        INSERT INTO raw_items
            (id, source_id, url, title, body_text, author, published_at,
             url_hash, title_hash, content_hash, duplicate_of, cluster_id)
        VALUES (nextval('seq_raw_items'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        [source_id, url, title, body_text, author, published_at,
         url_hash, title_hash, content_hash, duplicate_of, cluster_id],
    ).fetchone()
    return row[0] if row else None


def get_unprocessed_items(source_id: str, con):
    return con.execute(
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


def mark_item_duplicate(item_id: int, duplicate_of: int, con) -> None:
    con.execute(
        "UPDATE raw_items SET duplicate_of = ? WHERE id = ?",
        [duplicate_of, item_id],
    )


def set_item_cluster(item_id: int, cluster_id: int, con) -> None:
    con.execute(
        "UPDATE raw_items SET cluster_id = ? WHERE id = ?",
        [cluster_id, item_id],
    )


def set_item_embed(item_id: int, embed_id: int, con) -> None:
    con.execute(
        "UPDATE raw_items SET embed_id = ? WHERE id = ?",
        [embed_id, item_id],
    )


def get_items_for_cluster(cluster_id: int, con, limit: int = 5):
    return con.execute(
        """
        SELECT title, body_text FROM raw_items
        WHERE cluster_id = ? AND duplicate_of IS NULL
        LIMIT ?
        """,
        [cluster_id, limit],
    ).fetchall()


def get_unresolved_redirect_items(con, limit: int = 2000):
    return con.execute(
        """
        SELECT id, url, title FROM raw_items
        WHERE url LIKE '%news.google.com%'
           OR url LIKE '%t.co/%'
           OR url LIKE '%bit.ly/%'
           OR url LIKE '%feedburner.com%'
        ORDER BY id DESC
        LIMIT ?
        """,
        [limit],
    ).fetchall()


def update_item_resolved_url(item_id: int, final_url: str,
                              new_url_hash: str, new_content_hash: str, con) -> None:
    con.execute(
        "UPDATE raw_items SET url = ?, url_hash = ?, content_hash = ? WHERE id = ?",
        [final_url, new_url_hash, new_content_hash, item_id],
    )


def update_cluster_canonical_url(old_url: str, new_url: str, con) -> None:
    con.execute(
        "UPDATE clusters SET canonical_url = ? WHERE canonical_url = ?",
        [new_url, old_url],
    )


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------

def get_embedding_for_item(item_id: int, con):
    return con.execute(
        "SELECT id FROM embeddings WHERE raw_item_id = ?", [item_id]
    ).fetchone()


def get_embedding_vector(item_id: int, con):
    row = con.execute(
        "SELECT vector FROM embeddings WHERE raw_item_id = ?", [item_id]
    ).fetchone()
    return row[0] if row else None


def insert_embedding(item_id: int, model: str, vector: list, con):
    con.execute(
        """
        INSERT INTO embeddings (id, raw_item_id, model, vector)
        VALUES (nextval('seq_embeddings'), ?, ?, ?)
        ON CONFLICT (raw_item_id) DO NOTHING
        """,
        [item_id, model, vector],
    )
    row = con.execute(
        "SELECT id FROM embeddings WHERE raw_item_id = ?", [item_id]
    ).fetchone()
    return row[0] if row else None


def get_recent_embeddings(item_id: int, con, days: int = 7, limit: int = 500):
    return con.execute(
        """
        SELECT e.raw_item_id, e.vector
        FROM embeddings e
        JOIN raw_items r ON r.id = e.raw_item_id
        WHERE r.fetched_at >= now() - INTERVAL '7 days'
          AND r.duplicate_of IS NULL
          AND e.raw_item_id != ?
        LIMIT ?
        """,
        [item_id, limit],
    ).fetchall()


# ---------------------------------------------------------------------------
# Clusters
# ---------------------------------------------------------------------------

def get_recent_clusters(con, days: int = 3, limit: int = 10):
    return con.execute(
        """
        SELECT id, headline FROM clusters
        WHERE latest_seen_at >= now() - INTERVAL '3 days'
        ORDER BY latest_seen_at DESC
        LIMIT ?
        """,
        [limit],
    ).fetchall()


def insert_cluster(con, first_seen_at, latest_seen_at, canonical_url: str | None,
                   headline: str, summary: str, key_points_json: str,
                   topics: list, source_ids: list) -> int:
    row = con.execute(
        """
        INSERT INTO clusters
            (id, created_at, updated_at, first_seen_at, latest_seen_at, canonical_url,
             headline, summary, key_points, topics, source_ids, item_count, is_breaking)
        VALUES (nextval('seq_clusters'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, FALSE)
        RETURNING id
        """,
        [first_seen_at, first_seen_at, first_seen_at, latest_seen_at, canonical_url,
         headline, summary, key_points_json, topics, source_ids],
    ).fetchone()
    cid = row[0] if row else None
    logger.debug("insert_cluster: id=%s headline=%r", cid, headline[:60])
    return cid


def get_cluster_source_ids(cluster_id: int, con):
    row = con.execute(
        "SELECT source_ids, item_count FROM clusters WHERE id = ?", [cluster_id]
    ).fetchone()
    return row


def update_cluster(con, cluster_id: int, now: datetime, headline: str, summary: str,
                   key_points_json: str, topics: list, source_ids: list, item_count: int) -> None:
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
            item_count     = ?,
            is_update      = CASE WHEN read_at IS NOT NULL THEN TRUE ELSE is_update END
        WHERE id = ?
        """,
        [now, now, headline, summary, key_points_json, topics, source_ids, item_count, cluster_id],
    )


def add_source_to_cluster(cluster_id: int, source_id: str, con) -> None:
    row = con.execute(
        "SELECT source_ids FROM clusters WHERE id = ?", [cluster_id]
    ).fetchone()
    if not row:
        return
    source_ids = list(row[0] or [])
    if source_id not in source_ids:
        source_ids.append(source_id)
        con.execute(
            "UPDATE clusters SET source_ids = ? WHERE id = ?",
            [source_ids, cluster_id],
        )


def get_cluster(cluster_id: int, con):
    return con.execute(
        """
        SELECT headline, summary, key_points, topics, canonical_url, full_summary
        FROM clusters WHERE id = ?
        """,
        [cluster_id],
    ).fetchone()


def get_cluster_source_urls(cluster_id: int, con, limit: int = 5):
    return con.execute(
        """
        SELECT DISTINCT url FROM raw_items
        WHERE cluster_id = ? AND url IS NOT NULL
          AND length(regexp_replace(url, '^https?://[^/]+', '')) > 1
        LIMIT ?
        """,
        [cluster_id, limit],
    ).fetchall()


def update_cluster_full_summary(cluster_id: int, full_summary: str,
                                 key_points_json: str, con) -> None:
    con.execute(
        "UPDATE clusters SET full_summary = ?, key_points = ? WHERE id = ?",
        [full_summary, key_points_json, cluster_id],
    )


def get_feed(con, conditions: list[str], params: list, page: int, page_size: int):
    where = " AND ".join(conditions)
    total_row = con.execute(f"SELECT count(*) FROM clusters WHERE {where}", params).fetchone()
    total = total_row[0] if total_row else 0
    offset = (page - 1) * page_size
    rows = con.execute(
        f"""
        SELECT id, created_at, updated_at, first_seen_at, latest_seen_at,
               canonical_url, headline, summary, key_points, topics,
               source_ids, item_count, is_breaking, combined_score,
               interest_score, coalesce(is_update, FALSE), full_summary,
               (SELECT list(url) FROM (
                   SELECT DISTINCT url FROM raw_items
                   WHERE cluster_id = c.id AND url IS NOT NULL
                     AND length(regexp_replace(url, '^https?://[^/]+', '')) > 1
                   LIMIT 5
               )),
               (SELECT list(s.label) FROM (
                   SELECT DISTINCT s.label FROM sources s
                   WHERE list_contains(c.source_ids, s.id)
                   LIMIT 5
               ) s)
        FROM clusters c
        WHERE {where}
        ORDER BY combined_score DESC
        LIMIT ? OFFSET ?
        """,
        params + [page_size, offset],
    ).fetchall()
    return total, rows


def mark_clusters_breaking(topic: str, window_minutes: int, con):
    return con.execute(
        f"""
        UPDATE clusters SET is_breaking = TRUE
        WHERE is_breaking = FALSE
          AND list_contains(topics, ?)
          AND created_at >= now() - INTERVAL '{window_minutes} minutes'
        RETURNING id
        """,
        [topic],
    ).fetchall()


def get_topic_spikes(con, window_minutes: int, threshold: int):
    return con.execute(
        f"""
        SELECT t.topic, count(*) AS n
        FROM clusters c, UNNEST(c.topics) AS t(topic)
        WHERE c.created_at >= now() - INTERVAL '{window_minutes} minutes'
        GROUP BY t.topic
        HAVING count(*) >= {threshold}
        """
    ).fetchall()


def refresh_scores(con) -> None:
    """Recompute combined_score for clusters whose score is stale (>5 min old).

    The single-statement correlated-subquery form crashes DuckDB 1.5.2 in its
    primary-index MVCC path (RevertCommit / IndexDataRemover) when the UPDATE
    touches a table that has a correlated UNNEST subquery referencing the same
    table.  Work around by computing scores in a separate SELECT first, then
    joining back for the UPDATE.
    """
    con.execute("""
        CREATE OR REPLACE TEMP TABLE _score_update AS
        SELECT
            c.id,
            exp(-extract(epoch FROM (now() - c.latest_seen_at)) / 86400.0) AS recency,
            coalesce(avg(tw.weight), 0.5) AS topic_interest,
            coalesce(avg(sw.interest), 0.5) AS source_interest
        FROM clusters c
        LEFT JOIN LATERAL (
            SELECT w2.weight
            FROM UNNEST(c.topics) AS t(topic)
            JOIN interest_weights w2 ON w2.topic = t.topic
        ) tw ON TRUE
        LEFT JOIN LATERAL (
            SELECT s.interest
            FROM UNNEST(c.source_ids) AS sid(id)
            JOIN sources s ON s.id = sid.id
        ) sw ON TRUE
        WHERE c.scored_at IS NULL
           OR c.scored_at < now() - INTERVAL '5 minutes'
        GROUP BY c.id, c.latest_seen_at
    """)
    con.execute("""
        UPDATE clusters
        SET recency_score  = s.recency,
            interest_score = 0.7 * s.topic_interest + 0.3 * s.source_interest,
            combined_score = 0.4 * s.recency + 0.6 * (0.7 * s.topic_interest + 0.3 * s.source_interest),
            scored_at      = now()
        FROM _score_update s
        WHERE clusters.id = s.id
    """)
    con.execute("DROP TABLE IF EXISTS _score_update")


# ---------------------------------------------------------------------------
# Read events & interest weights
# ---------------------------------------------------------------------------

def cluster_exists(cluster_id: int, con) -> bool:
    return con.execute("SELECT id FROM clusters WHERE id = ?", [cluster_id]).fetchone() is not None


def insert_read_event(cluster_id: int, event_type: str, duration_seconds,
                      fully_read, metadata_json: str | None, con) -> None:
    con.execute(
        """
        INSERT INTO read_events (id, cluster_id, event_type, duration_seconds, fully_read, metadata_json)
        VALUES (nextval('seq_read_events'), ?, ?, ?, ?, ?)
        """,
        [cluster_id, event_type, duration_seconds, fully_read, metadata_json],
    )
    if event_type == "read":
        con.execute(
            "UPDATE clusters SET read_at = now(), is_update = FALSE WHERE id = ?",
            [cluster_id],
        )
    elif event_type in ("interest_up", "interest_down", "expand", "follow", "save"):
        con.execute(
            "UPDATE clusters SET read_at = now(), is_update = FALSE WHERE id = ? AND read_at IS NULL",
            [cluster_id],
        )


def update_interest_weights(cluster_id: int, event_type: str, delta: float,
                             decay_rate: float, con) -> None:
    if delta == 0.0:
        return
    con.execute(
        "UPDATE interest_weights SET weight = weight + (0.5 - weight) * ?",
        [decay_rate],
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


def list_topics(con):
    return con.execute(
        """
        SELECT
            t.topic,
            coalesce(w.weight, 0.5) AS weight,
            count(DISTINCT c.id)    AS item_count
        FROM (
            SELECT DISTINCT t.topic
            FROM clusters, UNNEST(topics) AS t(topic)
        ) t
        LEFT JOIN interest_weights w ON w.topic = t.topic
        LEFT JOIN clusters c ON list_contains(c.topics, t.topic)
        GROUP BY t.topic, w.weight
        ORDER BY item_count DESC, weight DESC
        LIMIT 50
        """
    ).fetchall()


# ---------------------------------------------------------------------------
# URL resolve cache
# ---------------------------------------------------------------------------

def set_topic_interest(topic: str, weight: float, con) -> None:
    weight = max(0.0, min(1.0, weight))
    con.execute(
        """
        INSERT INTO interest_weights (topic, weight, event_count, last_updated)
        VALUES (?, ?, 1, now())
        ON CONFLICT (topic) DO UPDATE SET
            weight       = excluded.weight,
            last_updated = now()
        """,
        [topic, weight],
    )


def set_source_interest(source_id: str, weight: float, con) -> None:
    weight = max(0.0, min(1.0, weight))
    con.execute(
        "UPDATE sources SET interest = ? WHERE id = ?",
        [weight, source_id],
    )


def list_source_interests(con):
    return con.execute(
        """
        SELECT id, label, coalesce(interest, 0.5) AS weight
        FROM sources
        WHERE enabled = TRUE
        ORDER BY weight DESC, label
        """
    ).fetchall()


def load_url_resolve_cache(con) -> list:
    try:
        return con.execute(
            "SELECT original_url, resolved_url FROM url_resolve_cache"
        ).fetchall()
    except Exception as exc:
        logger.debug("url-resolver: could not load DB cache: %s", exc)
        return []


def save_url_resolve_cache(original: str, resolved: str, con) -> None:
    try:
        con.execute(
            """
            INSERT INTO url_resolve_cache (original_url, resolved_url)
            VALUES (?, ?)
            ON CONFLICT (original_url) DO UPDATE SET
                resolved_url = excluded.resolved_url,
                resolved_at  = now()
            """,
            [original, resolved],
        )
    except Exception as exc:
        logger.debug("url-resolver: could not save to DB cache: %s", exc)


# ---------------------------------------------------------------------------
# RSS scan log
# ---------------------------------------------------------------------------

def domain_scanned(domain: str, con) -> bool:
    try:
        return con.execute(
            "SELECT 1 FROM rss_scan_log WHERE url = ?", [f"domain:{domain}"]
        ).fetchone() is not None
    except Exception:
        return False


def record_rss_scan(url: str, domain: str, feeds_found: int, con) -> None:
    for key in (url, f"domain:{domain}"):
        try:
            con.execute(
                """
                INSERT INTO rss_scan_log (url, feeds_found) VALUES (?, ?)
                ON CONFLICT (url) DO UPDATE SET scanned_at = now(), feeds_found = excluded.feeds_found
                """,
                [key, feeds_found],
            )
        except Exception as exc:
            logger.debug("rss_scan_log insert failed: %s", exc)


def get_rss_source_urls(con) -> set:
    return {
        r[0] for r in con.execute(
            "SELECT config_json->>'$.url' FROM sources WHERE type = 'rss'"
        ).fetchall() if r[0]
    }


def insert_rss_source(source_id: str, label: str, feed_url: str, con) -> None:
    con.execute(
        "INSERT INTO sources (id, type, label, config_json) VALUES (?, 'rss', ?, ?)",
        [source_id, f"{label} (auto)", json.dumps({"url": feed_url})],
    )


def source_id_exists(source_id: str, con) -> bool:
    return con.execute("SELECT id FROM sources WHERE id = ?", [source_id]).fetchone() is not None


def get_source_config(source_id: str, con):
    """Return (type, label, config_json) for a source, or None if not found/disabled."""
    return con.execute(
        "SELECT type, label, config_json FROM sources WHERE id = ? AND enabled = TRUE",
        [source_id],
    ).fetchone()
    """Return (type, label, config_json) for a source, or None if not found/disabled."""
    return con.execute(
        "SELECT type, label, config_json FROM sources WHERE id = ? AND enabled = TRUE",
        [source_id],
    ).fetchone()
