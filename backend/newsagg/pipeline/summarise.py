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
You are summarising a news story. Extract every concrete, specific fact from the article.

Rules:
- Include specific names (people, organisations, places, products), numbers, dates, and locations.
- Do NOT use vague phrases like "a bakery", "a company", "a person" when the name is known — use the actual name.
- Write 2-5 sentences. Use as many as needed to cover the key facts.
- No filler phrases ("It is worth noting", "In conclusion", etc.).
- Start with the most important fact.
- Key points should each be a specific, concrete fact — not a vague category label.
- Topics should be 2-5 short lowercase tags.

Article title: {title}
Article text (may be truncated):
{body}

Reply ONLY with valid JSON, no other text:
{{
  "headline": "<revised headline, max 12 words>",
  "summary": "<2-5 sentences packed with specific facts>",
  "key_points": ["<specific fact>", "<specific fact>", "<specific fact>"],
  "topics": ["<tag1>", "<tag2>"]
}}"""

_EXCERPT_PROMPT = """\
You are writing a deeper reading section for a news story that already has a short summary and key points.
Rules:
- Do NOT repeat information already in the summary or key points below.
- Write 3-6 sentences giving additional context, background, or detail.
- Focus on the "why" and "how", not the "what" (that's already covered).
- No filler phrases. Plain language.

Existing summary: {summary}
Existing key points: {key_points}

Full article text (may be truncated):
{body}

Reply ONLY with valid JSON, no other text:
{{
  "excerpt": "<3-6 sentences of non-redundant additional context>"
}}"""

_MERGE_PROMPT = """\
You are merging {n} news articles covering the same story.

Rules:
- Include specific names (people, organisations, places, products), numbers, dates, and locations.
- Do NOT use vague phrases like "a bakery", "a company", "a person" when the name is known — use the actual name.
- Write 2-5 sentences. Use as many as needed to cover all key facts across the articles.
- No filler phrases.
- Start with the most important fact.
- Key points should each be a specific, concrete fact.
- Topics should be 2-5 short lowercase tags.

Articles:
{articles}

Reply ONLY with valid JSON, no other text:
{{
  "headline": "<unified headline, max 12 words>",
  "summary": "<2-5 sentences packed with specific facts>",
  "key_points": ["<specific fact>", "<specific fact>", "<specific fact>"],
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
    prompt = _SUMMARY_PROMPT.format(title=title or "", body=(body or "")[:6000])
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


def summarise_excerpt(summary: str, key_points: list[str], body: str, cfg: "OllamaConfig") -> str:
    """Return a non-redundant deeper excerpt from article body."""
    prompt = _EXCERPT_PROMPT.format(
        summary=summary or "",
        key_points="; ".join(key_points) if key_points else "none",
        body=(body or "")[:6000],
    )
    try:
        result = _generate(prompt, cfg)
        return result.get("excerpt") or ""
    except Exception as exc:
        logger.warning("Excerpt generation failed: %s", exc)
        return ""


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
