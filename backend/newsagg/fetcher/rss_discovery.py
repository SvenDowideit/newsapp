from __future__ import annotations

import logging
import re
import threading
from urllib.parse import urljoin, urlparse

import feedparser
import httpx
from bs4 import BeautifulSoup

from .. import db as database
from ..models import SourceDiscoverResult

logger = logging.getLogger(__name__)

_scanned_domains: set[str] = set()
_scan_lock = threading.Lock()

COMMON_FEED_PATHS = [
    "/feed",
    "/rss",
    "/atom.xml",
    "/feed.xml",
    "/index.xml",
    "/rss.xml",
    "/feed/atom",
]


def _make_source_id(url: str, feed_url: str) -> str:
    domain = urlparse(feed_url).netloc or urlparse(url).netloc
    safe = re.sub(r"[^a-z0-9_]", "_", domain).strip("_")[:40]
    if not safe:
        safe = "feed"
    return safe


def discover_feed(url: str) -> SourceDiscoverResult | None:
    """Given a URL or partial URL, try to discover a feed.

    Strategy (no DB calls made here):
    1. Try parsing the URL directly as RSS/Atom via feedparser.
    2. If the URL looks like a website, fetch HTML and look for <link> tags.
    3. Try common feed paths (/feed, /rss, /atom.xml, etc.).
    Returns a SourceDiscoverResult (already_exists is always False here;
    caller checks DB separately) or None if nothing worked.
    """
    cleaned = url.strip()

    if not cleaned.startswith(("http://", "https://")):
        cleaned = "https://" + cleaned

    headers = {"User-Agent": "newsagg/0.1 (personal aggregator)"}

    # Strategy 1: Try direct feed parse
    feed = feedparser.parse(cleaned)
    if feed.version and feed.entries:
        title = feed.feed.get("title", "") or urlparse(cleaned).netloc
        feed_type = "atom" if "atom" in (feed.version or "") else "rss"
        source_id = _make_source_id(cleaned, cleaned)
        return SourceDiscoverResult(
            feed_url=cleaned,
            title=title,
            type=feed_type,
            source_id=source_id,
        )

    # Strategy 2: Fetch HTML, look for <link> tags
    try:
        resp = httpx.get(cleaned, headers=headers, timeout=10, follow_redirects=True)
        final_url = str(resp.url)
        ct = resp.headers.get("content-type", "")
        html = resp.text if "html" in ct else None

        if html:
            soup = BeautifulSoup(html, "html.parser")
            rss_types = {
                "application/rss+xml",
                "application/atom+xml",
                "application/rdf+xml",
            }
            for link in soup.find_all("link", rel="alternate"):
                link_type = link.get("type", "").strip().lower()
                if link_type in rss_types:
                    href = link.get("href", "").strip()
                    if href:
                        feed_url = urljoin(final_url, href)
                        title_tag = link.get("title") or soup.find("title")
                        if title_tag and hasattr(title_tag, "get_text"):
                            title = title_tag.get_text(strip=True)
                        elif title_tag:
                            title = str(title_tag)
                        else:
                            title = urlparse(final_url).netloc
                        feed_type = "atom" if "atom" in link_type else "rss"
                        source_id = _make_source_id(cleaned, feed_url)
                        return SourceDiscoverResult(
                            feed_url=feed_url,
                            title=title,
                            type=feed_type,
                            source_id=source_id,
                        )

    except Exception as exc:
        logger.debug("discover_feed: HTML fetch failed for %s: %s", cleaned, exc)

    # Strategy 3: Try common feed paths
    parsed = urlparse(cleaned)
    base = f"{parsed.scheme}://{parsed.netloc}"
    for path in COMMON_FEED_PATHS:
        candidate = base + path
        try:
            feed = feedparser.parse(candidate)
            if feed.version and feed.entries:
                title = feed.feed.get("title", "") or parsed.netloc
                feed_type = "atom" if "atom" in (feed.version or "") else "rss"
                source_id = _make_source_id(cleaned, candidate)
                return SourceDiscoverResult(
                    feed_url=candidate,
                    title=title,
                    type=feed_type,
                    source_id=source_id,
                )
        except Exception:
            continue

        alt_path = parsed.path.rstrip("/") + path
        if alt_path != path:
            candidate2 = base + alt_path
            try:
                feed = feedparser.parse(candidate2)
                if feed.version and feed.entries:
                    title = feed.feed.get("title", "") or parsed.netloc
                    feed_type = "atom" if "atom" in (feed.version or "") else "rss"
                    source_id = _make_source_id(cleaned, candidate2)
                    return SourceDiscoverResult(
                        feed_url=candidate2,
                        title=title,
                        type=feed_type,
                        source_id=source_id,
                    )
            except Exception:
                continue

    return None


def autodiscover_rss(page_url: str, html: str, con) -> int:
    """Parse HTML for RSS/Atom <link rel="alternate"> tags and auto-add new sources.

    Must be called from inside a DB worker lambda (con is the worker's connection).
    Returns the number of new feeds registered.
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
        return 0

    page_domain = urlparse(page_url).netloc
    existing = database.get_rss_source_urls(con)

    added = 0
    for feed_url, feed_title in found:
        if feed_url in existing:
            continue
        safe_id = re.sub(r"[^a-z0-9_]", "_", f"rss_{page_domain}").strip("_")[:40]
        base_id = safe_id
        suffix = 0
        while database.source_id_exists(safe_id, con):
            suffix += 1
            safe_id = f"{base_id}_{suffix}"
        database.insert_rss_source(safe_id, feed_title, feed_url, con)
        logger.info("Auto-discovered RSS feed: %s -> %s", safe_id, feed_url)
        existing.add(feed_url)
        added += 1
    return added


def fetch_and_autodiscover(url: str) -> None:
    """Fetch url (HTTP only) and submit RSS discovery to the DB worker.

    The HTTP fetch happens in the calling thread. DB writes go through database.run_sync
    at priority=BG so they never block foreground requests.
    Safe to call from any non-DB-worker thread.
    """
    if not url:
        return
    domain = urlparse(url).netloc
    if not domain:
        return

    with _scan_lock:
        if domain in _scanned_domains:
            return

    already = database.run_sync(
        lambda con: database.domain_scanned(domain, con), priority=database.BG
    )
    if already:
        with _scan_lock:
            _scanned_domains.add(domain)
        return

    page_url = url
    html: str | None = None
    try:
        headers = {"User-Agent": "newsagg/0.1 (personal aggregator)"}
        resp = httpx.get(url, headers=headers, timeout=10, follow_redirects=True)
        page_url = str(resp.url)
        ct = resp.headers.get("content-type", "")
        if "html" in ct:
            html = resp.text
    except Exception as exc:
        logger.warning("fetch_and_autodiscover HTTP failed for %s: %s", url, exc)

    def _write(con, _pu=page_url, _h=html, _u=url, _d=domain):
        feeds_found = 0
        if _h:
            feeds_found = autodiscover_rss(_pu, _h, con)
        database.record_rss_scan(_u, _d, feeds_found, con)
        logger.debug("RSS scan %s: %d feed(s) found", _d, feeds_found)
        with _scan_lock:
            _scanned_domains.add(_d)

    database.run_sync(_write, priority=database.BG)
