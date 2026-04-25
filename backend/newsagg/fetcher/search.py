from __future__ import annotations

import httpx
from bs4 import BeautifulSoup

from .types import RawItem


def fetch(source_id: str, query: str, max_results: int = 10) -> list[RawItem]:
    """Search DuckDuckGo HTML endpoint (no API key required)."""
    url = "https://html.duckduckgo.com/html/"
    headers = {"User-Agent": "newsagg/0.1 (personal aggregator)"}
    resp = httpx.post(url, data={"q": query}, headers=headers, timeout=15, follow_redirects=True)
    soup = BeautifulSoup(resp.text, "html.parser")
    items: list[RawItem] = []
    for result in soup.select(".result")[:max_results]:
        a = result.select_one(".result__a")
        snippet = result.select_one(".result__snippet")
        if not a:
            continue
        items.append(RawItem(
            source_id=source_id,
            url=a.get("href"),
            title=a.get_text(strip=True),
            body_text=snippet.get_text(strip=True) if snippet else None,
        ))
    return items
