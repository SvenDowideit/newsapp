from __future__ import annotations

import logging

import feedparser
from googlenewsdecoder import gnewsdecoder

from .types import RawItem

logger = logging.getLogger(__name__)


def _decode_url(url: str) -> str:
    """Decode a Google News wrapper URL to the real article URL."""
    try:
        result = gnewsdecoder(url, interval=1)
        if result.get("status"):
            return result["decoded_url"]
    except Exception as exc:
        logger.debug("googlenewsdecoder failed for %s: %s", url[:80], exc)
    return url


def fetch(source_id: str, query: str) -> list[RawItem]:
    """Fetch via Google News RSS search endpoint."""
    import urllib.parse
    encoded = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=en-AU&gl=AU&ceid=AU:en"
    feed = feedparser.parse(url)
    items: list[RawItem] = []
    for entry in feed.entries:
        pub = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            from datetime import datetime
            pub = datetime(*entry.published_parsed[:6])
        body = getattr(entry, "summary", None) or (
            entry.content[0].get("value") if getattr(entry, "content", None) else None
        )
        raw_url = getattr(entry, "link", None)
        real_url = _decode_url(raw_url) if raw_url else raw_url
        items.append(RawItem(
            source_id=source_id,
            url=real_url,
            title=getattr(entry, "title", None),
            body_text=body,
            author=getattr(entry, "author", None),
            published_at=pub,
        ))
    return items
