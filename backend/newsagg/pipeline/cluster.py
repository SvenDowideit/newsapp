from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from ..config import OllamaConfig

logger = logging.getLogger(__name__)

_CLUSTER_PROMPT = """\
You are deciding whether a news item belongs to an existing story cluster.

New item title: {title}
New item summary (first 200 chars): {body}

Candidate clusters:
{candidates}

If the item clearly covers the same event as a candidate, return that cluster_id.
Otherwise return null.

Reply ONLY with valid JSON, no other text:
{{"cluster_id": <integer or null>, "confidence": <0.0-1.0>}}"""


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
        f"  id={c['id']}: {c['headline']}" for c in candidates[:10]
    )
    prompt = _CLUSTER_PROMPT.format(
        title=title or "",
        body=(body or "")[:200],
        candidates=cand_text,
    )
    try:
        resp = httpx.post(
            f"{cfg.base_url}/api/generate",
            json={"model": cfg.model, "prompt": prompt, "stream": False,
                  "options": {"num_predict": 64}},
            timeout=60,
        )
        resp.raise_for_status()
        text = resp.json().get("response", "")
        start = text.find("{")
        end = text.rfind("}") + 1
        data = json.loads(text[start:end])
        cid = data.get("cluster_id")
        conf = float(data.get("confidence", 0.0))
        return (int(cid) if cid is not None else None), conf
    except Exception as exc:
        logger.warning("Cluster assignment failed: %s", exc)
        return None, 0.0
