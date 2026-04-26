from __future__ import annotations

from fastapi import APIRouter

from .. import db as database
from ..models import TopicSummary

router = APIRouter()


@router.get("", response_model=list[TopicSummary])
async def list_topics():
    rows = await database.arun(database.list_topics, priority=database.UI)
    return [TopicSummary(topic=r[0], weight=r[1], item_count=r[2]) for r in rows]
