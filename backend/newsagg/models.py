from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class SourceInfo(BaseModel):
    id: str
    type: str
    label: str
    enabled: bool
    last_fetched_at: datetime | None
    next_fetch_at: datetime | None
    ema_interval_s: float
    fetch_error_count: int
    last_error: str | None


class SourceCreate(BaseModel):
    id: str
    type: str
    label: str
    config: dict[str, Any] = {}


class ClusterItem(BaseModel):
    id: int
    created_at: datetime
    updated_at: datetime
    first_seen_at: datetime
    latest_seen_at: datetime
    canonical_url: str | None
    headline: str
    summary: str
    key_points: list[str]
    topics: list[str]
    source_ids: list[str]
    item_count: int
    is_breaking: bool
    combined_score: float


class FeedResponse(BaseModel):
    items: list[ClusterItem]
    page: int
    page_size: int
    total: int


class ReadEventBody(BaseModel):
    duration_seconds: int | None = None
    fully_read: bool | None = None


class InterestAdjustBody(BaseModel):
    direction: str  # "up" or "down"


class ExpandedItem(BaseModel):
    id: int
    headline: str
    full_summary: str
    key_points: list[str]
    source_urls: list[str]
    topics: list[str]


class TopicSummary(BaseModel):
    topic: str
    weight: float
    item_count: int
