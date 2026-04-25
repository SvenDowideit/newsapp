from __future__ import annotations

import feedparser

from .types import RawItem


def fetch(source_id: str, url: str) -> list[RawItem]:
    feed = feedparser.parse(url)
    items: list[RawItem] = []
    for entry in feed.entries:
        pub = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            from datetime import datetime
            pub = datetime(*entry.published_parsed[:6])
        body = None
        if hasattr(entry, "summary"):
            body = entry.summary
        elif hasattr(entry, "content") and entry.content:
            body = entry.content[0].get("value")
        items.append(RawItem(
            source_id=source_id,
            url=getattr(entry, "link", None),
            title=getattr(entry, "title", None),
            body_text=body,
            author=getattr(entry, "author", None),
            published_at=pub,
        ))
    return items
