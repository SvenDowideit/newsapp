from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import ollama

if TYPE_CHECKING:
    from ..config import OllamaConfig

logger = logging.getLogger(__name__)

_CLUSTER_PROMPT = """\
You are deciding whether a news item belongs to an existing story cluster.

New item:
  Title: {title}
  Content: {body}

Candidate clusters (most recent first):
{candidates}

Assign the item to a cluster if it covers the same story or closely related developments
in the same ongoing situation (e.g. same market event, same incident, same policy debate).
Do NOT require identical events — related coverage of the same unfolding story should be merged.
If no candidate is a good match, return null.

Reply ONLY with valid JSON, no other text:
{{"cluster_id": <integer or null>, "confidence": <0.0-1.0>}}"""


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


def assign_cluster(
    title: str,
    body: str,
    candidates: list[dict],
    cfg: "OllamaConfig",
) -> tuple[int | None, float]:
    """Return (cluster_id, confidence) or (None, 0.0) if new cluster."""
    if not candidates:
        return None, 0.0

    cand_text = "\n".join(
        f"  id={c['id']}: {c['headline']} — {(c.get('summary') or '')[:150]}"
        for c in candidates[:50]
    )
    prompt = _CLUSTER_PROMPT.format(
        title=title or "",
        body=(body or "")[:500],
        candidates=cand_text,
    )
    try:
        client = _client(cfg)
        _ensure_model(client, cfg.model)
        resp = client.generate(
            model=cfg.model,
            prompt=prompt,
            stream=False,
            options={"num_predict": 64},
        )
        text = resp.response
        start = text.find("{")
        end = text.rfind("}") + 1
        data = json.loads(text[start:end])
        cid = data.get("cluster_id")
        conf = float(data.get("confidence", 0.0))
        return (int(cid) if cid is not None else None), conf
    except Exception as exc:
        logger.warning("Cluster assignment failed: %s", exc)
        return None, 0.0
