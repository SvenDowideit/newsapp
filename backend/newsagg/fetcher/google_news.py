from __future__ import annotations

from urllib.parse import urlparse

import feedparser
from bs4 import BeautifulSoup

from .types import RawItem


def _extract_real_url(entry) -> str | None:
    """Extract the real article URL from a Google News RSS entry.

    Google News wraps all article links in a JS-decoded redirect that cannot be
    resolved server-side with plain HTTP. The real publisher URL is available via:
      1. <a href> links in the entry summary that point to the source domain
      2. entry.source.href (publisher homepage — less precise but still better than wrapper)
    """
    source_domain = None
    if hasattr(entry, "source") and entry.source:
        href = entry.source.get("href", "")
        if href:
            source_domain = urlparse(href).netloc

    summary = getattr(entry, "summary", "") or ""
    if summary and source_domain:
        soup = BeautifulSoup(summary, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if source_domain in href and "news.google.com" not in href:
                return href

    if hasattr(entry, "source") and entry.source:
        src_href = entry.source.get("href", "")
        if src_href:
            return src_href

    return None


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
        real_url = _extract_real_url(entry) or getattr(entry, "link", None)
        items.append(RawItem(
            source_id=source_id,
            url=real_url,
            title=getattr(entry, "title", None),
            body_text=body,
            author=getattr(entry, "author", None),
            published_at=pub,
        ))
    return items

