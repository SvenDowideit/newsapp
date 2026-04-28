from __future__ import annotations

from fastapi import APIRouter
from .. import db as database

router = APIRouter()


@router.get("/summary")
async def stats_summary():
    def _q(con):
        events = con.execute("""
            SELECT event_type, count(*) AS n
            FROM read_events
            GROUP BY event_type
            ORDER BY n DESC
        """).fetchall()

        daily = con.execute("""
            SELECT
                strftime(occurred_at AT TIME ZONE 'UTC', '%Y-%m-%d') AS day,
                event_type,
                count(*) AS n
            FROM read_events
            WHERE occurred_at >= now() - INTERVAL '30 days'
            GROUP BY day, event_type
            ORDER BY day
        """).fetchall()

        hourly = con.execute("""
            SELECT
                strftime(occurred_at AT TIME ZONE 'UTC', '%Y-%m-%dT%H:00') AS hour,
                event_type,
                count(*) AS n
            FROM read_events
            WHERE occurred_at >= now() - INTERVAL '7 days'
            GROUP BY hour, event_type
            ORDER BY hour
        """).fetchall()

        return events, daily, hourly

    events, daily, hourly = await database.arun(_q, priority=database.UI)

    return {
        "totals": {r[0]: r[1] for r in events},
        "daily": [{"day": r[0], "event": r[1], "n": r[2]} for r in daily],
        "hourly": [{"hour": r[0], "event": r[1], "n": r[2]} for r in hourly],
    }


@router.get("/sources")
async def stats_sources():
    def _q(con):
        item_counts = {r[0]: r[1] for r in con.execute("""
            SELECT sid, count(*) AS n
            FROM (SELECT UNNEST(source_ids) AS sid FROM clusters)
            GROUP BY sid
        """).fetchall()}

        read_counts = {r[0]: r[1] for r in con.execute("""
            SELECT sid, count(*) AS n
            FROM (
                SELECT UNNEST(c.source_ids) AS sid
                FROM read_events re JOIN clusters c ON c.id = re.cluster_id
                WHERE re.event_type = 'read'
            )
            GROUP BY sid
        """).fetchall()}

        link_counts = {r[0]: r[1] for r in con.execute("""
            SELECT sid, count(*) AS n
            FROM (
                SELECT UNNEST(c.source_ids) AS sid
                FROM read_events re JOIN clusters c ON c.id = re.cluster_id
                WHERE re.event_type = 'interest_up'
            )
            GROUP BY sid
        """).fetchall()}

        spark_rows = con.execute("""
            SELECT sid, day, count(*) AS n
            FROM (
                SELECT UNNEST(source_ids) AS sid,
                       strftime(first_seen_at AT TIME ZONE 'UTC', '%Y-%m-%d') AS day
                FROM clusters
                WHERE first_seen_at >= now() - INTERVAL '14 days'
            )
            GROUP BY sid, day
            ORDER BY sid, day
        """).fetchall()

        from datetime import date, timedelta
        today = date.today()
        days14 = [(today - timedelta(days=13-i)).isoformat() for i in range(14)]
        spark_map: dict[str, dict[str, int]] = {}
        for sid, day, n in spark_rows:
            spark_map.setdefault(sid, {})[day] = n

        sources = con.execute("""
            SELECT id, label, type, coalesce(interest, 0.5), last_fetched_at, fetch_error_count
            FROM sources
            ORDER BY id
        """).fetchall()

        result = []
        for s in sources:
            sid = s[0]
            spark = [spark_map.get(sid, {}).get(d, 0) for d in days14]
            result.append({
                "id": sid,
                "label": s[1],
                "type": s[2],
                "interest": s[3],
                "last_fetched_at": s[4].isoformat() if s[4] else None,
                "fetch_error_count": s[5],
                "item_count": item_counts.get(sid, 0),
                "read_count": read_counts.get(sid, 0),
                "link_count": link_counts.get(sid, 0),
                "sparkline": spark,
            })
        result.sort(key=lambda x: x["item_count"], reverse=True)
        return result

    return await database.arun(_q, priority=database.UI)
