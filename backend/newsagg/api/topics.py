from __future__ import annotations

from fastapi import APIRouter

from .. import db as database
from ..models import TopicSummary

router = APIRouter()


@router.get("", response_model=list[TopicSummary])
async def list_topics():
    con = database.get()
    rows = con.execute(
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
    return [TopicSummary(topic=r[0], weight=r[1], item_count=r[2]) for r in rows]
