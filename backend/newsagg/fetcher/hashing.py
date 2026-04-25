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
    "news.google.com",
    "google.com",
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


def resolve_url(url: str | None) -> tuple[str | None, str | None]:
    """
    Follow HTTP redirects for known wrapper domains (Google News, shorteners, etc.).
    Returns (final_url, html_body_or_None).
    html_body is populated when a GET was needed (HEAD failed or redirected to HTML).
    Results are cached per process. Falls back to (original_url, None) on error.
    """
    if not url:
        return url, None
    domain = urlparse(url).netloc.lower().lstrip("www.")
    if domain not in _REDIRECT_DOMAINS:
        return url, None

    with _resolve_lock:
        if url in _resolve_cache:
            return _resolve_cache[url]

    html: str | None = None
    try:
        headers = {
            "User-Agent": "newsagg/0.1 (personal aggregator; url resolver)",
            "Accept": "text/html,application/xhtml+xml",
        }
        try:
            resp = httpx.head(url, headers=headers, timeout=10,
                              follow_redirects=True, max_redirects=10)
            final = str(resp.url)
        except Exception:
            resp = httpx.get(url, headers=headers, timeout=10,
                             follow_redirects=True, max_redirects=10)
            final = str(resp.url)
            ct = resp.headers.get("content-type", "")
            if "html" in ct:
                html = resp.text
    except Exception as exc:
        logger.debug("URL resolve failed for %s: %s", url, exc)
        final = url

    result = (final, html)
    with _resolve_lock:
        _resolve_cache[url] = result

    if final != url:
        logger.debug("Resolved %s -> %s", url, final)
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
