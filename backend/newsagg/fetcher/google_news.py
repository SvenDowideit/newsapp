from __future__ import annotations

from .rss import fetch as _rss_fetch
from .types import RawItem


def fetch(source_id: str, query: str) -> list[RawItem]:
    """Fetch via Google News RSS search endpoint."""
    import urllib.parse
    encoded = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
    return _rss_fetch(source_id, url)
