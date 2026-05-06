"""OpenAI-compatible text embeddings for knowledge bases (OPENAI_* from ~/.hermes/.env)."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

from hermes_cli.config import get_env_value, load_config

_log = logging.getLogger(__name__)


class KnowledgeEmbeddingError(RuntimeError):
    """Missing configuration or provider error for embeddings."""


class EmbeddingCancelled(Exception):
    """Embedding batch stopped early (e.g. user cancelled reindex)."""


def _embedding_config() -> tuple[str, str | None, str | None]:
    """Return (model, api_key, base_url) after merging user config and env.

    Keys ``OPENAI_*`` are resolved via :func:`get_env_value` so ``~/.hermes/.env``
    is honored even when :func:`reload_env` has not been called (e.g. standalone
    scripts).
    """
    cfg = load_config()
    k = cfg.get("knowledge") or {}
    emb = k.get("embedding") or {}
    model = (emb.get("model") or "").strip() or "text-embedding-3-small"
    model = os.environ.get("HERMES_KNOWLEDGE_EMBEDDING_MODEL", model).strip()
    api_key = (get_env_value("OPENAI_API_KEY") or "").strip() or None
    base = (get_env_value("OPENAI_BASE_URL") or "").strip().rstrip("/") or None
    return model, api_key, base


def embed_texts(
    texts: list[str],
    *,
    cancel_check: Callable[[], bool] | None = None,
) -> list[list[float]]:
    """Batch-embed non-empty strings; preserves order (same length as *texts*).

    If *cancel_check* is set and returns True before a batch, raises :exc:`EmbeddingCancelled`.
    """
    if not texts:
        return []
    model, api_key, base_url = _embedding_config()
    if not api_key:
        raise KnowledgeEmbeddingError(
            "OPENAI_API_KEY is not set. Add it to ~/.hermes/.env (see docs/zh/knowledge-api.md)."
        )
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise KnowledgeEmbeddingError("openai package is required for embeddings") from exc

    kwargs: dict = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    client = OpenAI(**kwargs)

    out: list[list[float]] = []
    batch_size = 64
    for i in range(0, len(texts), batch_size):
        if cancel_check and cancel_check():
            raise EmbeddingCancelled()
        batch = texts[i : i + batch_size]
        resp = client.embeddings.create(model=model, input=batch)
        # data is aligned with input order per OpenAI API
        out.extend([list(d.embedding) for d in resp.data])
    if len(out) != len(texts):
        raise KnowledgeEmbeddingError(
            f"Embedding provider returned {len(out)} vectors for {len(texts)} inputs"
        )
    return out


def probe_embedding(text: str = "hello") -> dict:
    """Single-string probe for dashboards / scripts (returns dimension, no raw vector)."""
    vec = embed_texts([text])[0]
    model, _, _ = _embedding_config()
    return {
        "ok": True,
        "model": model,
        "dimension": len(vec),
        "base_url_set": bool((get_env_value("OPENAI_BASE_URL") or "").strip()),
    }
