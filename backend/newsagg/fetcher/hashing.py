from __future__ import annotations

import hashlib
import logging
import re
import threading
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

import httpx

logger = logging.getLogger(__name__)

# Domains that are known redirect wrappers — always follow their redirects.
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
}

_resolve_cache: dict[str, tuple[str, str | None]] = {}
_resolve_lock = threading.Lock()
_db_cache_loaded = False


def _load_db_cache(con) -> None:
    """Warm the in-process cache from the DB resolve table (called once per process)."""
    global _db_cache_loaded
    with _resolve_lock:
        if _db_cache_loaded:
            return
        _db_cache_loaded = True
    try:
        rows = con.execute(
            "SELECT original_url, resolved_url FROM url_resolve_cache"
        ).fetchall()
        with _resolve_lock:
            for orig, resolved in rows:
                if orig not in _resolve_cache:
                    _resolve_cache[orig] = (resolved, None)
        logger.info("url-resolver: loaded %d cached redirects from DB", len(rows))
    except Exception as exc:
        logger.debug("url-resolver: could not load DB cache: %s", exc)


def _save_to_db_cache(original: str, resolved: str, con) -> None:
    try:
        con.execute(
            """
            INSERT INTO url_resolve_cache (original_url, resolved_url)
            VALUES (?, ?)
            ON CONFLICT (original_url) DO UPDATE SET resolved_url = excluded.resolved_url, resolved_at = now()
            """,
            [original, resolved],
        )
    except Exception as exc:
        logger.debug("url-resolver: could not save to DB cache: %s", exc)


def resolve_url(url: str | None, con=None, reason: str = "") -> tuple[str | None, str | None]:
    """Follow HTTP redirects for known wrapper domains (Google News, shorteners, etc.).

    Returns (final_url, html_body_or_None).
    html_body is populated when the final page was fetched for RSS discovery.
    Results are persisted to url_resolve_cache so restarts don't re-fetch.

    Args:
        url: URL to resolve.
        con: DuckDB connection for cache persistence (optional).
        reason: caller context logged alongside the request (e.g. 'ingest', 'expand').
    """
    if not url:
        return url, None
    domain = urlparse(url).netloc.lower().lstrip("www.")
    if domain not in _REDIRECT_DOMAINS:
        return url, None

    if con is not None:
        _load_db_cache(con)

    with _resolve_lock:
        if url in _resolve_cache:
            cached = _resolve_cache[url]
            logger.debug("url-resolver [%s]: cache hit %s -> %s", reason or "?", url[:60], cached[0][:60] if cached[0] else url)
            return cached

    tag = f"[{reason}] " if reason else ""
    html: str | None = None
    try:
        headers = {
            "User-Agent": "newsagg/0.1 (personal aggregator; url resolver)",
            "Accept": "text/html,application/xhtml+xml",
        }
        try:
            logger.debug("url-resolver %sHEAD %s", tag, url[:80])
            resp = httpx.head(url, headers=headers, timeout=10, follow_redirects=True)
            final = str(resp.url)
            if final != url:
                logger.info("url-resolver %sresolved %s -> %s", tag, url[:60], final[:60])
                try:
                    logger.debug("url-resolver %sGET %s (RSS discovery)", tag, final[:80])
                    get_resp = httpx.get(final, headers=headers, timeout=10, follow_redirects=True)
                    ct = get_resp.headers.get("content-type", "")
                    if "html" in ct:
                        html = get_resp.text
                except Exception:
                    pass
            else:
                logger.debug("url-resolver %sno redirect: %s", tag, url[:60])
        except Exception:
            logger.debug("url-resolver %sHEAD failed, falling back to GET: %s", tag, url[:60])
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

    if con is not None and final != url:
        _save_to_db_cache(url, final, con)

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
