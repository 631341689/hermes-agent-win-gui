"""Hermes Dashboard knowledge bases — catalog (light), full list, vector + GraphRAG search.

Uses the same registry and index as ``/api/knowledge`` (profile-scoped via
``HERMES_HOME``). Enable toolset ``knowledge`` for the agent to pick bases and
query them without the Dashboard HTTP API.

**Recommended flow**: call ``knowledge_catalog`` first (id, name, mode,
``indexing_status``, ``agent_summary`` only) to choose ``kb_ids``, then
``knowledge_vector_query`` for **vector** bases (chunk + FAISS), or
``knowledge_graphrag_query`` for **graphrag** bases (exactly one kb_id per call).
Use ``knowledge_list_bases`` when you need per-KB ``chunk_config`` or other full metadata.

When ``kb_ids`` is empty, ``HERMES_ACTIVE_KB_IDS`` (comma-separated) is used if
set (e.g. embedded Chat from Dashboard).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from tools.registry import registry

_log = logging.getLogger(__name__)


def _parse_kb_ids(raw: str | None) -> list[str]:
    s = (raw or "").strip()
    if not s:
        env = (os.environ.get("HERMES_ACTIVE_KB_IDS") or "").strip()
        if not env:
            return []
        return [x.strip() for x in env.split(",") if x.strip()]
    if s.startswith("["):
        val = json.loads(s)
        if not isinstance(val, list):
            return []
        return [str(x).strip() for x in val if str(x).strip()]
    return [x.strip() for x in s.split(",") if x.strip()]


def check_knowledge_list_requirements() -> bool:
    return True


def check_knowledge_vector_query_requirements() -> bool:
    try:
        import faiss  # noqa: F401
    except Exception:
        return False
    try:
        from hermes_cli.config import get_env_value

        return bool((get_env_value("OPENAI_API_KEY") or "").strip())
    except Exception:
        return False


def check_knowledge_graphrag_query_requirements() -> bool:
    try:
        import graphrag.api  # noqa: F401
    except Exception:
        return False
    try:
        from hermes_cli.config import get_env_value

        if (get_env_value("GRAPHRAG_API_KEY") or "").strip():
            return True
        return bool((get_env_value("OPENAI_API_KEY") or "").strip())
    except Exception:
        return False


def knowledge_catalog(task_id: str | None = None) -> str:
    """Compact catalog for routing: no chunk_config — use summaries + names to pick kb_ids."""
    try:
        from hermes_cli.knowledge_registry import KnowledgeRegistry
        from hermes_cli.knowledge_routing_summary import routing_summary_for_catalog

        reg = KnowledgeRegistry()
        bases = [
            {
                "id": r.id,
                "name": r.name,
                "mode": r.mode,
                "indexing_status": r.indexing_status,
                "summary_routing_mode": r.summary_routing_mode,
                "routing_summary": routing_summary_for_catalog(r.summary_routing_mode, r.id),
                "agent_summary": r.agent_summary,
            }
            for r in reg.list_all()
        ]
        return json.dumps(
            {
                "success": True,
                "bases": bases,
                "hint": (
                    "summary_routing_mode: manual → use agent_summary (+ name) only; routing_summary is null. "
                    "auto → use routing_summary (file after reindex). "
                    "Then call the search tool that matches each chosen base's mode: "
                    "knowledge_vector_query for mode=vector (chunk+FAISS; multiple kb_ids allowed); "
                    "knowledge_graphrag_query for mode=graphrag (exactly one kb_id; graphrag_method auto|local|global|basic). "
                    "Only indexing_status=ready bases return hits. "
                    "Routing habit (soft): when the question could plausibly match an indexed Hermes base "
                    "(names/summaries below, or HERMES_ACTIVE_KB_IDS in the host), trying the right "
                    "knowledge_* query before public web search often gives tighter excerpts; "
                    "skip when bases are empty, off-topic, or the user clearly needs live internet breadth."
                ),
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        _log.warning("knowledge_catalog failed: %s", exc)
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)


def knowledge_list_bases(task_id: str | None = None) -> str:
    """Return all knowledge bases including chunk_config (heavier than knowledge_catalog)."""
    try:
        from hermes_cli.knowledge_registry import KnowledgeRegistry
        from hermes_cli.knowledge_routing_summary import augment_base_dict

        reg = KnowledgeRegistry()
        bases = [augment_base_dict(r.id, r.to_dict()) for r in reg.list_all()]
        return json.dumps({"success": True, "bases": bases}, ensure_ascii=False)
    except Exception as exc:
        _log.warning("knowledge_list_bases failed: %s", exc)
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)


def knowledge_vector_query(
    query: str,
    kb_ids: str = "",
    top_k: int = 8,
    task_id: str | None = None,
) -> str:
    """Vector search over one or more ``ready`` vector knowledge bases.

    * ``kb_ids`` — comma-separated UUIDs, or a JSON array string, or empty to use
      ``HERMES_ACTIVE_KB_IDS``.
    """
    from hermes_cli.knowledge_embedding import KnowledgeEmbeddingError
    from hermes_cli.knowledge_index import query_vector_bases

    q = (query or "").strip()
    if not q:
        return json.dumps({"success": False, "error": "query is required"}, ensure_ascii=False)
    try:
        ids = _parse_kb_ids(kb_ids)
    except json.JSONDecodeError as exc:
        return json.dumps({"success": False, "error": f"invalid kb_ids JSON: {exc}"}, ensure_ascii=False)
    if not ids:
        return json.dumps(
            {
                "success": False,
                "error": "No kb_ids: pass comma-separated IDs, a JSON array, or set HERMES_ACTIVE_KB_IDS.",
            },
            ensure_ascii=False,
        )
    tk = max(1, min(int(top_k or 8), 50))
    try:
        hits = query_vector_bases(ids, q, tk)
    except KnowledgeEmbeddingError as exc:
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)
    except ValueError as exc:
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)
    except Exception as exc:
        _log.exception("knowledge_vector_query failed")
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)
    return json.dumps({"success": True, "results": hits}, ensure_ascii=False)


def knowledge_graphrag_query(
    query: str,
    kb_ids: str = "",
    graphrag_method: str = "auto",
    task_id: str | None = None,
) -> str:
    """GraphRAG search over exactly one ``ready`` graphrag knowledge base.

    ``graphrag_method``: ``auto`` (Hermes heuristics from ``knowledge.graphrag.auto_method``), or
    ``local`` / ``global`` / ``basic``.
    """
    from hermes_cli.knowledge_graphrag import GraphRAGNotInstalledError
    from hermes_cli.knowledge_graphrag_method import resolve_graphrag_query_method
    from hermes_cli.knowledge_graphrag_query import query_graphrag_base
    from hermes_cli.knowledge_registry import KnowledgeRegistry

    q = (query or "").strip()
    if not q:
        return json.dumps({"success": False, "error": "query is required"}, ensure_ascii=False)
    try:
        ids = _parse_kb_ids(kb_ids)
    except json.JSONDecodeError as exc:
        return json.dumps({"success": False, "error": f"invalid kb_ids JSON: {exc}"}, ensure_ascii=False)
    if not ids:
        return json.dumps(
            {
                "success": False,
                "error": "No kb_ids: pass exactly one graphrag base UUID, or set HERMES_ACTIVE_KB_IDS to one id.",
            },
            ensure_ascii=False,
        )
    if len(ids) != 1:
        return json.dumps(
            {
                "success": False,
                "error": "knowledge_graphrag_query requires exactly one knowledge base id (GraphRAG is single-KB per call).",
            },
            ensure_ascii=False,
        )
    kb_id = ids[0]
    reg = KnowledgeRegistry()
    rec = reg.get(kb_id)
    if not rec:
        return json.dumps({"success": False, "error": f"Unknown knowledge base: {kb_id}"}, ensure_ascii=False)
    if rec.mode != "graphrag":
        return json.dumps(
            {
                "success": False,
                "error": f"Knowledge base {kb_id} is mode={rec.mode}; use knowledge_vector_query for vector bases.",
            },
            ensure_ascii=False,
        )
    if rec.indexing_status != "ready":
        return json.dumps(
            {
                "success": False,
                "error": f"GraphRAG index not ready (indexing_status={rec.indexing_status!r}); reindex in Dashboard first.",
            },
            ensure_ascii=False,
        )

    raw_method = (graphrag_method or "auto").strip().lower()
    method, reason = resolve_graphrag_query_method(q, raw_method)
    try:
        hit = query_graphrag_base(kb_id, q, method)
    except GraphRAGNotInstalledError as exc:
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)
    except ValueError as exc:
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)
    except RuntimeError as exc:
        _log.exception("knowledge_graphrag_query failed kb_id=%s", kb_id)
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)
    except Exception as exc:
        _log.exception("knowledge_graphrag_query failed kb_id=%s", kb_id)
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)

    return json.dumps(
        {
            "success": True,
            "kb_id": kb_id,
            "requested_graphrag_method": raw_method,
            "resolved_graphrag_method": method,
            "method_resolution": reason,
            "results": [hit],
        },
        ensure_ascii=False,
    )


CATALOG_SCHEMA: dict[str, Any] = {
    "name": "knowledge_catalog",
    "description": (
        "List Hermes Dashboard knowledge bases for routing: id, name, mode, indexing_status, "
        "summary_routing_mode (manual|auto), routing_summary (when auto), agent_summary. "
        "Respect summary_routing_mode in the response hint, then knowledge_vector_query for mode=vector "
        "or knowledge_graphrag_query for mode=graphrag (one kb_id). "
        "When a user question might align with uploaded or indexed material here, many workflows "
        "briefly check this catalog (and the matching query tool) before web_search to save noise and tokens—"
        "still use the web when freshness or broad internet coverage is the better fit. "
        "Does not search the public internet; it only lists local bases."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

LIST_SCHEMA: dict[str, Any] = {
    "name": "knowledge_list_bases",
    "description": (
        "Full metadata for every Hermes knowledge base (includes chunk_config, summary_routing_mode, "
        "agent_summary, routing_summary from disk). Use when debugging chunk settings or when "
        "knowledge_catalog is not enough. For routine Q&A, knowledge_catalog plus knowledge_vector_query "
        "is usually enough; you can still use web_search when you need live or site-wide external facts."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

QUERY_SCHEMA: dict[str, Any] = {
    "name": "knowledge_vector_query",
    "description": (
        "Semantic search (embeddings + FAISS) over vector knowledge bases in indexing_status "
        "`ready`. Pick kb_ids using knowledge_catalog and each base's summary_routing_mode. "
        "kb_ids: comma-separated UUIDs, or JSON array string like [\"uuid1\",\"uuid2\"], "
        "or omit / empty to use env HERMES_ACTIVE_KB_IDS when the host injects it. Requires OPENAI_* "
        "embedding config same as Dashboard reindex. "
        "Searches indexed local uploads only. When the topic may already live in Hermes, this is "
        "often a good first retrieval step alongside the catalog; use web_search when you still need "
        "public pages, prices, news, or other live internet coverage. "
        "Server-side retrieval uses config knowledge.retrieval (two-stage widen + optional BM25 blend); "
        "set two_stage false there to restore legacy single-pass behaviour."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural-language search query.",
            },
            "kb_ids": {
                "type": "string",
                "description": "Comma-separated kb UUIDs, JSON array string, or empty for HERMES_ACTIVE_KB_IDS.",
            },
            "top_k": {
                "type": "integer",
                "description": "Max hits to return (1–50, default 8).",
            },
        },
        "required": ["query"],
    },
}

GRAPHRAG_QUERY_SCHEMA: dict[str, Any] = {
    "name": "knowledge_graphrag_query",
    "description": (
        "Microsoft GraphRAG search over exactly one Dashboard knowledge base in mode=graphrag with "
        "indexing_status ready (same Parquet output as Dashboard /api/knowledge/query). "
        "Pick kb_id using knowledge_catalog (check mode). kb_ids must contain a single UUID "
        "(comma or JSON array with one element), or rely on HERMES_ACTIVE_KB_IDS with one id. "
        "graphrag_method: auto (Hermes picks local vs global vs basic from query text and "
        "knowledge.graphrag.auto_method), or explicit local | global | basic. "
        "Requires graphrag extra and OPENAI_* or GRAPHRAG_API_KEY like Dashboard GraphRAG query. "
        "Do not use for mode=vector bases (use knowledge_vector_query)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural-language question for GraphRAG.",
            },
            "kb_ids": {
                "type": "string",
                "description": "Exactly one kb UUID, or empty when HERMES_ACTIVE_KB_IDS is one id.",
            },
            "graphrag_method": {
                "type": "string",
                "description": "auto | local | global | basic (default auto).",
            },
        },
        "required": ["query"],
    },
}


registry.register(
    name="knowledge_catalog",
    toolset="knowledge",
    schema=CATALOG_SCHEMA,
    handler=lambda args, **kw: knowledge_catalog(task_id=kw.get("task_id")),
    check_fn=check_knowledge_list_requirements,
    emoji="📇",
)

registry.register(
    name="knowledge_list_bases",
    toolset="knowledge",
    schema=LIST_SCHEMA,
    handler=lambda args, **kw: knowledge_list_bases(task_id=kw.get("task_id")),
    check_fn=check_knowledge_list_requirements,
    emoji="📚",
)

registry.register(
    name="knowledge_vector_query",
    toolset="knowledge",
    schema=QUERY_SCHEMA,
    handler=lambda args, **kw: knowledge_vector_query(
        query=args.get("query") or "",
        kb_ids=args.get("kb_ids") or "",
        top_k=int(args.get("top_k") or 8),
        task_id=kw.get("task_id"),
    ),
    check_fn=check_knowledge_vector_query_requirements,
    emoji="🧭",
)

registry.register(
    name="knowledge_graphrag_query",
    toolset="knowledge",
    schema=GRAPHRAG_QUERY_SCHEMA,
    handler=lambda args, **kw: knowledge_graphrag_query(
        query=args.get("query") or "",
        kb_ids=args.get("kb_ids") or "",
        graphrag_method=str(args.get("graphrag_method") or "auto"),
        task_id=kw.get("task_id"),
    ),
    check_fn=check_knowledge_graphrag_query_requirements,
    emoji="🕸️",
)
