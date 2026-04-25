from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode


def normalise_url(url: str | None) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip().lower())
        # Strip common tracking params
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
