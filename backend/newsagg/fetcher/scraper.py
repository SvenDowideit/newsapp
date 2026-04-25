from __future__ import annotations

import httpx
from bs4 import BeautifulSoup

from .types import RawItem


def fetch(source_id: str, url: str) -> list[RawItem]:
    """
    Scrape a page for article links. Falls back gracefully if BeautifulSoup
    finds nothing useful.
    """
    headers = {"User-Agent": "newsagg/0.1 (personal aggregator)"}
    resp = httpx.get(url, headers=headers, timeout=20, follow_redirects=True)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    items: list[RawItem] = []
    for tag in soup.find_all("article"):
        a = tag.find("a", href=True)
        h = tag.find(["h1", "h2", "h3"])
        if not a and not h:
            continue
        link = a["href"] if a else None
        title = h.get_text(strip=True) if h else (a.get_text(strip=True) if a else None)
        body_tag = tag.find("p")
        body = body_tag.get_text(strip=True) if body_tag else None
        items.append(RawItem(source_id=source_id, url=link, title=title, body_text=body))
    return items


def fetch_article_text(url: str) -> str:
    """Fetch and extract readable text from a single article URL."""
    headers = {"User-Agent": "newsagg/0.1 (personal aggregator)"}
    try:
        resp = httpx.get(url, headers=headers, timeout=20, follow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)[:8000]
    except Exception:
        return ""
