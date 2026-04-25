from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
import ollama

if TYPE_CHECKING:
    from ..config import OllamaConfig

logger = logging.getLogger(__name__)


def _ensure_model(client: ollama.Client, model: str) -> None:
    """Pull the model if it is not already present on the server."""
    try:
        client.show(model)
    except ollama.ResponseError as exc:
        if exc.status_code == 404:
            logger.info("Pulling embed model '%s' from Ollama registry…", model)
            client.pull(model)
        else:
            raise


def embed(text: str, cfg: "OllamaConfig") -> list[float] | None:
    """Return a unit-normalised embedding vector, or None on failure."""
    try:
        client = ollama.Client(host=cfg.base_url)
        _ensure_model(client, cfg.embed_model)
        resp = client.embed(model=cfg.embed_model, input=text[:2000])
        vec = resp.embeddings[0] if resp.embeddings else None
        if not vec:
            return None
        arr = np.array(vec, dtype=np.float32)
        norm = np.linalg.norm(arr)
        if norm > 0:
            arr = arr / norm
        return arr.tolist()
    except Exception as exc:
        logger.warning("Embedding failed: %s", exc)
        return None
