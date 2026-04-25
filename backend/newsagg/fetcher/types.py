from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class RawItem:
    source_id: str
    url: str | None
    title: str | None
    body_text: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)
