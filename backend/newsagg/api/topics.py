from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from .. import db as database
from ..models import TopicSummary

router = APIRouter()


class InterestUpdate(BaseModel):
    weight: float


@router.get("", response_model=list[TopicSummary])
async def list_topics():
    rows = await database.arun(database.list_topics, priority=database.UI)
    return [TopicSummary(topic=r[0], weight=r[1], item_count=r[2]) for r in rows]


@router.put("/{topic}/interest", status_code=204)
async def set_topic_interest(topic: str, body: InterestUpdate):
    await database.arun(
        lambda con: database.set_topic_interest(topic, body.weight, con),
        priority=database.UI,
    )


@router.get("/sources")
async def list_source_interests():
    rows = await database.arun(database.list_source_interests, priority=database.UI)
    return [{"id": r[0], "label": r[1], "weight": r[2]} for r in rows]


@router.put("/sources/{source_id}/interest", status_code=204)
async def set_source_interest(source_id: str, body: InterestUpdate):
    await database.arun(
        lambda con: database.set_source_interest(source_id, body.weight, con),
        priority=database.UI,
    )
