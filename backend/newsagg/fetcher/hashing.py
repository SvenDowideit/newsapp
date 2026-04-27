from __future__ import annotations

import hashlib
import logging
import re
import threading
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

import httpx

logger = logging.getLogger(__name__)

_REDIRECT_DOMAINS = {
    "t.co",
    "bit.ly",
    "tinyurl.com",
    "ow.ly",
    "buff.ly",
    "dlvr.it",
    "feedburner.com",
    "feeds.feedburner.com",
    "rss.cnn.com",
    "feeds.bbci.co.uk",
    "news.google.com",
}

_resolve_cache: dict[str, tuple[str, str | None]] = {}
_resolve_lock = threading.Lock()


def warm_cache(con) -> None:
    """Load url_resolve_cache from DB into the in-process dict. Call once at startup via run_sync."""
    from .. import db as database
    rows = database.load_url_resolve_cache(con)
    with _resolve_lock:
        for orig, resolved in rows:
            if orig not in _resolve_cache:
                _resolve_cache[orig] = (resolved, None)
    logger.info("url-resolver: warmed %d entries from DB", len(rows))


def resolve_url(url: str | None, reason: str = "") -> tuple[str | None, str | None]:
    """Follow HTTP redirects for known wrapper domains (shorteners etc.).

    Returns (final_url, html_body_or_None). Caches results in-process.
    """
    if not url:
        return url, None
    domain = urlparse(url).netloc.lower().lstrip("www.")
    if domain not in _REDIRECT_DOMAINS:
        return url, None

    with _resolve_lock:
        if url in _resolve_cache:
            return _resolve_cache[url]

    tag = f"[{reason}] " if reason else ""
    html: str | None = None
    try:
        headers = {
            "User-Agent": "newsagg/0.1 (personal aggregator; url resolver)",
            "Accept": "text/html,application/xhtml+xml",
        }
        try:
            resp = httpx.head(url, headers=headers, timeout=10, follow_redirects=True)
            final = str(resp.url)
            if final != url:
                logger.info("url-resolver %sresolved %s -> %s", tag, url[:60], final[:60])
                try:
                    get_resp = httpx.get(final, headers=headers, timeout=10, follow_redirects=True)
                    ct = get_resp.headers.get("content-type", "")
                    if "html" in ct:
                        html = get_resp.text
                except Exception:
                    pass
        except Exception:
            resp = httpx.get(url, headers=headers, timeout=10, follow_redirects=True)
            final = str(resp.url)
            ct = resp.headers.get("content-type", "")
            if "html" in ct:
                html = resp.text
            if final != url:
                logger.info("url-resolver %sresolved (GET) %s -> %s", tag, url[:60], final[:60])
    except Exception as exc:
        logger.warning("url-resolver %sfailed for %s: %s", tag, url[:60], exc)
        final = url

    result = (final, html)
    with _resolve_lock:
        _resolve_cache[url] = result

    if final != url:
        from .. import db as database
        database.run_sync(
            lambda con: database.save_url_resolve_cache(url, final, con),
            priority=database.BG,
        )

    return result


def normalise_url(url: str | None) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip().lower())
        _STRIP = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
                  "ref", "source", "fbclid", "gclid"}
        qs = {k: v for k, v in parse_qs(parsed.query).items() if k not in _STRIP}
        clean = parsed._replace(query=urlencode(qs, doseq=True), fragment="")
        return urlunparse(clean)
    except Exception:
        return url


def normalise_title(title: str | None) -> str:
    if not title:
        return ""
    return re.sub(r"\s+", " ", title.strip().lower())


def content_hash(url: str | None, title: str | None) -> str:
    key = normalise_url(url) + "|" + normalise_title(title)
    return hashlib.sha256(key.encode()).hexdigest()


def url_hash(url: str | None) -> str:
    return hashlib.sha256(normalise_url(url).encode()).hexdigest()


def title_hash(title: str | None) -> str:
    return hashlib.sha256(normalise_title(title).encode()).hexdigest()
