from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from ..config import OllamaConfig

logger = logging.getLogger(__name__)

_SUMMARY_PROMPT = """\
You are summarising a news story for display on an eink reader.
Rules:
- Maximum 4 sentences total.
- No filler phrases ("It is worth noting", "In conclusion", etc.).
- Start with the most important fact.
- Use plain language.
- Topics should be 2-5 short lowercase tags.

Article title: {title}
Article text (may be truncated):
{body}

Reply ONLY with valid JSON, no other text:
{{
  "headline": "<revised headline, max 12 words>",
  "summary": "<4 sentences max>",
  "key_points": ["<point>", "<point>", "<point>"],
  "topics": ["<tag1>", "<tag2>"]
}}"""

_MERGE_PROMPT = """\
You are merging {n} news articles covering the same story for display on an eink reader.
Rules:
- Maximum 4 sentences total.
- No filler phrases.
- Start with the most important fact.
- Topics should be 2-5 short lowercase tags.

Articles:
{articles}

Reply ONLY with valid JSON, no other text:
{{
  "headline": "<unified headline, max 12 words>",
  "summary": "<4 sentences max>",
  "key_points": ["<point>", "<point>", "<point>"],
  "topics": ["<tag1>", "<tag2>"]
}}"""


def _call_ollama(prompt: str, cfg: "OllamaConfig") -> dict:
    resp = httpx.post(
        f"{cfg.base_url}/api/generate",
        json={
            "model": cfg.model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": cfg.summary_max_tokens * 2},
        },
        timeout=120,
    )
    resp.raise_for_status()
    text = resp.json().get("response", "")
    # Extract JSON from response (model sometimes wraps in markdown)
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON in response: {text[:200]}")
    return json.loads(text[start:end])


def summarise_single(title: str, body: str, cfg: "OllamaConfig") -> dict:
    prompt = _SUMMARY_PROMPT.format(title=title or "", body=(body or "")[:3000])
    try:
        return _call_ollama(prompt, cfg)
    except Exception as exc:
        logger.warning("Summarisation failed: %s", exc)
        return {
            "headline": (title or "")[:80],
            "summary": (body or "")[:300],
            "key_points": [],
            "topics": [],
        }


def summarise_cluster(articles: list[dict], cfg: "OllamaConfig") -> dict:
    articles_text = json.dumps(
        [{"title": a.get("title", ""), "body": (a.get("body") or "")[:800]} for a in articles],
        indent=2,
    )
    prompt = _MERGE_PROMPT.format(n=len(articles), articles=articles_text)
    try:
        return _call_ollama(prompt, cfg)
    except Exception as exc:
        logger.warning("Cluster summarisation failed: %s", exc)
        first = articles[0] if articles else {}
        return {
            "headline": (first.get("title") or "")[:80],
            "summary": (first.get("body") or "")[:300],
            "key_points": [],
            "topics": [],
        }
