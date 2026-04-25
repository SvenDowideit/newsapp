from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx
import numpy as np

if TYPE_CHECKING:
    from ..config import OllamaConfig

logger = logging.getLogger(__name__)


def embed(text: str, cfg: "OllamaConfig") -> list[float] | None:
    """Get embedding vector from Ollama. Returns None on failure."""
    try:
        resp = httpx.post(
            f"{cfg.base_url}/api/embeddings",
            json={"model": cfg.embed_model, "prompt": text[:2000]},
            timeout=30,
        )
        resp.raise_for_status()
        vec = resp.json().get("embedding")
        if not vec:
            return None
        # Normalise to unit vector for cosine similarity via dot product
        arr = np.array(vec, dtype=np.float32)
        norm = np.linalg.norm(arr)
        if norm > 0:
            arr = arr / norm
        return arr.tolist()
    except Exception as exc:
        logger.warning("Embedding failed: %s", exc)
        return None
