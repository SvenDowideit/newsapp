from __future__ import annotations

import json
import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


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
