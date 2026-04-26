from __future__ import annotations

import json
import logging
import re
import threading
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# In-process cache of domains already scanned this run (backed by DB across restarts)
_scanned_domains: set[str] = set()
_scan_lock = threading.Lock()


def autodiscover_rss(page_url: str, html: str, con) -> int:
    """Parse HTML for RSS/Atom <link rel="alternate"> tags and auto-add new sources.

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
    existing = {
        r[0] for r in con.execute(
            "SELECT config_json->>'$.url' FROM sources WHERE type = 'rss'"
        ).fetchall() if r[0]
    }

    added = 0
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
        added += 1
    return added


def _domain_already_scanned(domain: str, con) -> bool:
    """Check in-process cache first, then DB."""
    with _scan_lock:
        if domain in _scanned_domains:
            return True
    try:
        row = con.execute(
            "SELECT 1 FROM rss_scan_log WHERE url = ?", [f"domain:{domain}"]
        ).fetchone()
        if row:
            with _scan_lock:
                _scanned_domains.add(domain)
            return True
    except Exception:
        pass
    return False


def _record_scan(url: str, domain: str, feeds_found: int, con) -> None:
    """Record the scan in the DB and in-process cache."""
    with _scan_lock:
        _scanned_domains.add(domain)
    try:
        con.execute(
            """
            INSERT INTO rss_scan_log (url, feeds_found) VALUES (?, ?)
            ON CONFLICT (url) DO UPDATE SET scanned_at = now(), feeds_found = excluded.feeds_found
            """,
            [url, feeds_found],
        )
        # Also record domain sentinel so we skip it on restart
        con.execute(
            """
            INSERT INTO rss_scan_log (url, feeds_found) VALUES (?, ?)
            ON CONFLICT (url) DO UPDATE SET scanned_at = now(), feeds_found = excluded.feeds_found
            """,
            [f"domain:{domain}", feeds_found],
        )
    except Exception as exc:
        logger.debug("rss_scan_log insert failed: %s", exc)


def fetch_and_autodiscover(url: str, con) -> None:
    """Fetch a URL and scan it for RSS feeds, once per domain per process/restart.

    Results (both hits and misses) are persisted to rss_scan_log so the domain
    is only ever fetched once across backend restarts.
    """
    if not url:
        return
    parsed = urlparse(url)
    domain = parsed.netloc
    if not domain:
        return

    if _domain_already_scanned(domain, con):
        return

    try:
        headers = {"User-Agent": "newsagg/0.1 (personal aggregator)"}
        resp = httpx.get(url, headers=headers, timeout=10, follow_redirects=True)
        ct = resp.headers.get("content-type", "")
        feeds_found = 0
        if "html" in ct:
            feeds_found = autodiscover_rss(str(resp.url), resp.text, con)
        _record_scan(url, domain, feeds_found, con)
        logger.debug("RSS scan %s: %d feed(s) found", domain, feeds_found)
    except Exception as exc:
        logger.warning("fetch_and_autodiscover failed for %s: %s", url, exc)
        # Still record the attempt so we don't retry on every item from this domain
        _record_scan(url, domain, 0, con)
