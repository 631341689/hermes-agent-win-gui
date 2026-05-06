"""Vector reindex + query orchestration (track A)."""

from __future__ import annotations

import logging
import threading
import traceback
from collections.abc import Callable
from typing import Any

from hermes_cli.config import load_config
from hermes_cli.knowledge_embedding import (
    EmbeddingCancelled,
    KnowledgeEmbeddingError,
    _embedding_config,
    embed_texts,
)
from hermes_cli.knowledge_registry import KnowledgeRegistry, base_dir
from hermes_cli.knowledge_routing_summary import (
    clear_routing_summary_file,
    try_generate_and_write_routing_summary,
)
from hermes_cli.knowledge_text import chunk_document, iter_raw_documents, resolve_chunk_settings
from hermes_cli.knowledge_rerank import hybrid_vector_lexical_rerank
from hermes_cli.knowledge_vector_store import load_manifest, rebuild_vector_store, search_kb

_log = logging.getLogger(__name__)


def _retrieval_settings() -> dict[str, Any]:
    cfg = load_config()
    k = cfg.get("knowledge") or {}
    r = k.get("retrieval") or {}
    if not isinstance(r, dict):
        return {}
    return r


class KnowledgeReindexCancelled(Exception):
    """Cooperative stop: client disconnected or user clicked cancel during reindex."""


def _cancelled_idle(reg: KnowledgeRegistry, kb_id: str) -> None:
    reg.update_meta(kb_id, indexing_status="idle", error_message="Reindex cancelled")


def run_vector_reindex(
    kb_id: str,
    registry: KnowledgeRegistry | None = None,
    *,
    progress: Callable[[dict[str, Any]], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> dict:
    """Build FAISS + chunk DB from ``bases/<kb_id>/raw/``. Updates registry status.

    If *progress* is set, it receives lightweight dicts (e.g. ``phase`` ``chunking`` /
    ``embedding`` / ``writing_index``) for UI streaming; may be called from a worker thread.
    """
    reg = registry or KnowledgeRegistry()
    rec = reg.get(kb_id)
    if not rec:
        raise ValueError("Knowledge base not found")
    if rec.mode != "vector":
        raise ValueError("Not a vector knowledge base")

    def _p(payload: dict[str, Any]) -> None:
        if progress:
            progress(dict(payload))

    reg.update_meta(kb_id, indexing_status="indexing", clear_error=True)
    mode = (rec.summary_routing_mode or "auto").strip().lower()
    if mode not in ("manual", "auto"):
        mode = "auto"
    rs_cfg = (load_config().get("knowledge") or {}).get("routing_summary") or {}
    rs_enabled = rs_cfg.get("enabled", True) is not False
    clear_routing_summary_file(kb_id)
    model, _, _ = _embedding_config()
    try:
        raw_dir = base_dir(kb_id) / "raw"
        docs = iter_raw_documents(raw_dir)
        rec = reg.get(kb_id)
        assert rec is not None
        knowledge_cfg = load_config().get("knowledge") or {}
        resolved = resolve_chunk_settings(knowledge_cfg, rec.chunk_config)
        flat: list[tuple[str, str]] = []
        n_docs = len(docs)
        _p({"phase": "chunking", "current": 0, "total": n_docs, "path": ""})
        for i, (rel, text) in enumerate(docs):
            if cancel_event and cancel_event.is_set():
                _cancelled_idle(reg, kb_id)
                raise KnowledgeReindexCancelled()
            _p({"phase": "chunking", "current": i + 1, "total": n_docs, "path": rel})
            n_piece = 0
            for piece in chunk_document(text, resolved, embed_fn=embed_texts):
                if n_piece % 32 == 0 and cancel_event and cancel_event.is_set():
                    _cancelled_idle(reg, kb_id)
                    raise KnowledgeReindexCancelled()
                flat.append((rel, piece))
                n_piece += 1

        if not flat:
            _p({"phase": "embedding", "chunk_count": 0})
            _p({"phase": "writing_index"})
            rebuild_vector_store(kb_id, [], embedding_model=model)
            if mode == "auto" and rs_enabled:
                try:
                    try_generate_and_write_routing_summary(
                        kb_id,
                        rec.name,
                        [],
                        cancel_event=cancel_event,
                        progress=_p,
                    )
                except Exception as exc:
                    _log.warning("routing_summary after empty reindex: %s", exc)
            reg.update_meta(kb_id, indexing_status="ready", clear_error=True)
            return {"chunk_count": 0, "embedding_model": model}

        texts = [t[1] for t in flat]
        _p({"phase": "embedding", "chunk_count": len(flat)})
        try:
            vectors = embed_texts(
                texts,
                cancel_check=(lambda: bool(cancel_event.is_set()) if cancel_event else False),
            )
        except EmbeddingCancelled:
            _cancelled_idle(reg, kb_id)
            raise KnowledgeReindexCancelled() from None
        rows = [(flat[i][0], flat[i][1], vectors[i]) for i in range(len(flat))]
        _p({"phase": "writing_index"})
        if cancel_event and cancel_event.is_set():
            _cancelled_idle(reg, kb_id)
            raise KnowledgeReindexCancelled()
        manifest = rebuild_vector_store(kb_id, rows, embedding_model=model)
        if mode == "auto" and rs_enabled:
            try:
                try_generate_and_write_routing_summary(
                    kb_id,
                    rec.name,
                    rows,
                    cancel_event=cancel_event,
                    progress=_p,
                )
            except Exception as exc:
                _log.warning("routing_summary after reindex: %s", exc)
        reg.update_meta(kb_id, indexing_status="ready", clear_error=True)
        return {
            "chunk_count": manifest.get("chunk_count", len(rows)),
            "embedding_model": model,
            "dimension": manifest.get("dimension", len(vectors[0]) if vectors else 0),
        }
    except KnowledgeReindexCancelled:
        raise
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        _log.exception("Vector reindex failed for kb_id=%s", kb_id)
        reg.update_meta(kb_id, indexing_status="error", error_message=str(exc)[:2000])
        raise


def query_vector_bases(kb_ids: list[str], query: str, top_k: int) -> list[dict]:
    """Embed *query* and merge vector search across *kb_ids* (same dimension required).

    When ``knowledge.retrieval.two_stage`` is true (default), stage-1 widens per-KB
    FAISS recall, merges up to ``max_candidates`` unique chunks, then stage-2
    re-ranks with a BM25 + dense blend and returns ``top_k`` hits.

    When ``two_stage`` is false, behaviour matches the original single-pass merge
    (each KB contributes at most ``top_k`` FAISS hits, then global top_k).
    """
    if not kb_ids:
        return []
    reg = KnowledgeRegistry()
    for kb_id in kb_ids:
        rec = reg.get(kb_id)
        if not rec:
            raise ValueError(f"Unknown knowledge base: {kb_id}")
        if rec.mode != "vector":
            raise ValueError(f"Knowledge base {kb_id} is not in vector mode")

    active: list[tuple[str, int]] = []
    for kb_id in kb_ids:
        man = load_manifest(kb_id)
        cnt = int(man.get("chunk_count", 0)) if man else 0
        dim = int(man.get("dimension", 0)) if man else 0
        if cnt > 0 and dim > 0:
            active.append((kb_id, dim))
    if not active:
        return []

    dims = {d for _, d in active}
    if len(dims) > 1:
        raise ValueError(
            "Selected knowledge bases have different embedding dimensions; "
            "reindex them with the same embedding model or query one base at a time."
        )

    qvec = embed_texts([query.strip()])[0]
    if len(qvec) != next(iter(dims)):
        raise ValueError(
            "Query embedding dimension does not match stored indexes; "
            "reindex after changing knowledge.embedding.model."
        )

    ret = _retrieval_settings()
    two_stage = bool(ret.get("two_stage", True))
    if not two_stage:
        merged_legacy: list[tuple[float, dict]] = []
        for kb_id, _ in active:
            for hit in search_kb(kb_id, qvec, top_k):
                hit = {**hit, "kb_id": kb_id}
                merged_legacy.append((float(hit["score"]), hit))
        merged_legacy.sort(key=lambda x: -x[0])
        return [h for _, h in merged_legacy[:top_k]]

    recall_per_kb = int(ret.get("recall_per_kb") or 48)
    recall_per_kb = max(top_k, min(128, recall_per_kb))
    max_candidates = int(ret.get("max_candidates") or 96)
    max_candidates = max(top_k, min(256, max_candidates))
    lexical_weight = float(ret.get("lexical_weight") if ret.get("lexical_weight") is not None else 0.3)

    merged_map: dict[tuple[str, str], tuple[float, dict]] = {}
    for kb_id, _ in active:
        for hit in search_kb(kb_id, qvec, recall_per_kb):
            hit = {**hit, "kb_id": kb_id}
            key = (kb_id, str(hit.get("chunk_id") or ""))
            sc = float(hit["score"])
            prev = merged_map.get(key)
            if prev is None or sc > prev[0]:
                merged_map[key] = (sc, hit)

    pooled = list(merged_map.values())
    pooled.sort(key=lambda x: -x[0])
    candidates = [h for _, h in pooled[:max_candidates]]
    if not candidates:
        return []

    return hybrid_vector_lexical_rerank(
        query.strip(),
        candidates,
        top_k=top_k,
        lexical_weight=lexical_weight,
    )
