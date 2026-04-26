from __future__ import annotations

import logging
import re
import threading
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .. import db as database

logger = logging.getLogger(__name__)

_scanned_domains: set[str] = set()
_scan_lock = threading.Lock()


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
