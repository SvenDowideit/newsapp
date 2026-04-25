from __future__ import annotations

import httpx

from .types import RawItem


_BASE = "https://hn.algolia.com/api/v1/search_by_date"


def fetch(source_id: str, min_score: int = 50, per_page: int = 30) -> list[RawItem]:
    params = {
        "tags": "story",
        "hitsPerPage": per_page,
        "numericFilters": f"points>={min_score}",
    }
    resp = httpx.get(_BASE, params=params, timeout=15)
    resp.raise_for_status()
    hits = resp.json().get("hits", [])
    items: list[RawItem] = []
    for h in hits:
        url = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
        items.append(RawItem(
            source_id=source_id,
            url=url,
            title=h.get("title"),
            body_text=h.get("story_text"),
            author=h.get("author"),
        ))
    return items
