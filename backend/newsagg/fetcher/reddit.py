from __future__ import annotations

import httpx

from .types import RawItem


def fetch(source_id: str, subreddit: str, sort: str = "hot", limit: int = 25) -> list[RawItem]:
    url = f"https://www.reddit.com/r/{subreddit}/{sort}.json?limit={limit}"
    headers = {"User-Agent": "newsagg/0.1 (personal aggregator)"}
    resp = httpx.get(url, headers=headers, timeout=15, follow_redirects=True)
    resp.raise_for_status()
    data = resp.json()
    items: list[RawItem] = []
    for post in data.get("data", {}).get("children", []):
        p = post["data"]
        items.append(RawItem(
            source_id=source_id,
            url=p.get("url"),
            title=p.get("title"),
            body_text=p.get("selftext") or None,
            author=p.get("author"),
        ))
    return items
