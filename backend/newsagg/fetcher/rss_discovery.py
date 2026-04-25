from __future__ import annotations

import json
import logging
import re
import threading
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Per-process cache: domains we've already scanned (avoids re-fetching every article from the same site)
_scanned_domains: set[str] = set()
_scan_lock = threading.Lock()


def autodiscover_rss(page_url: str, html: str, con) -> None:
    """
    Parse HTML for RSS/Atom <link rel="alternate"> tags and auto-add any new
    feeds as sources. Skips feeds whose URL is already registered.
    """
    soup = BeautifulSoup(html, "html.parser")
    rss_types = {"application/rss+xml", "application/atom+xml", "application/rdf+xml"}
    found: list[tuple[str, str]] = []
    for link in soup.find_all("link", rel="alternate"):
        link_type = link.get("type", "").strip().lower()
        if link_type in rss_types:
            href = link.get("href", "").strip()
            if href:
                href = urljoin(page_url, href)
                title = link.get("title") or urlparse(href).netloc
                found.append((href, title))

    if not found:
        return

    page_domain = urlparse(page_url).netloc
    existing = {
        r[0] for r in con.execute(
            "SELECT config_json->>'$.url' FROM sources WHERE type = 'rss'"
        ).fetchall() if r[0]
    }

    for feed_url, feed_title in found:
        if feed_url in existing:
            continue
        safe_id = re.sub(r"[^a-z0-9_]", "_", f"rss_{page_domain}").strip("_")[:40]
        base_id = safe_id
        suffix = 0
        while con.execute("SELECT id FROM sources WHERE id = ?", [safe_id]).fetchone():
            suffix += 1
            safe_id = f"{base_id}_{suffix}"
        con.execute(
            "INSERT INTO sources (id, type, label, config_json) VALUES (?, 'rss', ?, ?)",
            [safe_id, f"{feed_title} (auto)", json.dumps({"url": feed_url})],
        )
        logger.info("Auto-discovered RSS feed: %s -> %s", safe_id, feed_url)
        existing.add(feed_url)


def fetch_and_autodiscover(url: str, con) -> None:
    """Fetch url's domain once per process and scan for RSS feeds.

    Skips domains already scanned this run, so calling this for every new raw
    item is cheap — one HTTP GET per domain lifetime.
    """
    if not url:
        return
    domain = urlparse(url).netloc
    if not domain:
        return
    with _scan_lock:
        if domain in _scanned_domains:
            return
        _scanned_domains.add(domain)
    try:
        headers = {"User-Agent": "newsagg/0.1 (personal aggregator)"}
        resp = httpx.get(url, headers=headers, timeout=10, follow_redirects=True, max_redirects=5)
        ct = resp.headers.get("content-type", "")
        if "html" in ct:
            autodiscover_rss(str(resp.url), resp.text, con)
    except Exception as exc:
        logger.debug("fetch_and_autodiscover failed for %s: %s", url, exc)
