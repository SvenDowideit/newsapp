from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import ollama
from json_repair import repair_json

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


def _client(cfg: "OllamaConfig") -> ollama.Client:
    return ollama.Client(host=cfg.base_url)


def _ensure_model(client: ollama.Client, model: str) -> None:
    try:
        client.show(model)
    except ollama.ResponseError as exc:
        if exc.status_code == 404:
            logger.info("Pulling model '%s' from Ollama registry…", model)
            client.pull(model)
        else:
            raise


def _parse_json(text: str) -> dict:
    start = text.find("{")
    if start == -1:
        raise ValueError(f"No JSON object in response: {text[:200]}")
    candidate = text[start:]
    # First try strict parse
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    # Fall back to repair (handles truncated responses missing closing braces)
    repaired = repair_json(candidate)
    result = json.loads(repaired)
    if not isinstance(result, dict):
        raise ValueError(f"Repaired JSON is not a dict: {repaired[:200]}")
    return result


def _generate(prompt: str, cfg: "OllamaConfig") -> dict:
    client = _client(cfg)
    _ensure_model(client, cfg.model)
    resp = client.generate(
        model=cfg.model,
        prompt=prompt,
        stream=False,
        options={"num_predict": cfg.summary_max_tokens},
    )
    text = resp.response.strip()
    if text.startswith("```"):
        text = "\n".join(
            line for line in text.splitlines()
            if not line.startswith("```")
        ).strip()
    try:
        return _parse_json(text)
    except (ValueError, json.JSONDecodeError):
        tokens_generated = getattr(resp, "eval_count", None)
        if tokens_generated and tokens_generated >= cfg.summary_max_tokens:
            logger.warning(
                "Ollama response hit the token limit (%d tokens generated = limit). "
                "Increase [ollama] summary_max_tokens in config.toml above %d.",
                tokens_generated, cfg.summary_max_tokens,
            )
        else:
            logger.warning(
                "Ollama response contained no parseable JSON "
                "(%s tokens generated, limit %d). Raw tail: %r",
                tokens_generated, cfg.summary_max_tokens, text[-120:],
            )
        raise


def summarise_single(title: str, body: str, cfg: "OllamaConfig") -> dict:
    prompt = _SUMMARY_PROMPT.format(title=title or "", body=(body or "")[:3000])
    try:
        return _generate(prompt, cfg)
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
        return _generate(prompt, cfg)
    except Exception as exc:
        logger.warning("Cluster summarisation failed: %s", exc)
        first = articles[0] if articles else {}
        return {
            "headline": (first.get("title") or "")[:80],
            "summary": (first.get("body") or "")[:300],
            "key_points": [],
            "topics": [],
        }
