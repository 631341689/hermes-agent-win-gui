"""GraphRAG query path for Dashboard ``POST /api/knowledge/query`` (mode=graphrag)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Literal

from hermes_cli.config import load_config
from hermes_cli.knowledge_graphrag import (
    GraphRAGNotInstalledError,
    _sync_graphrag_api_key_env,
    graphrag_project_root,
)

_log = logging.getLogger(__name__)

GraphragQueryMethod = Literal["local", "global", "basic"]


def _output_dir(kb_id: str) -> Path:
    return graphrag_project_root(kb_id) / "output"


def _read_parquet(path: Path):
    import pandas as pd

    if not path.is_file():
        return pd.DataFrame()
    return pd.read_parquet(path)


def _default_response_type() -> str:
    return "Multiple Paragraphs"


def _default_community_level() -> int:
    k = load_config().get("knowledge") or {}
    g = k.get("graphrag") if isinstance(k.get("graphrag"), dict) else {}
    raw = g.get("community_level")
    if isinstance(raw, int) and 0 <= raw <= 10:
        return raw
    return 2


def query_graphrag_base(
    kb_id: str,
    query: str,
    method: GraphragQueryMethod,
    *,
    community_level: int | None = None,
    response_type: str | None = None,
    dynamic_community_selection: bool = True,
) -> dict[str, Any]:
    """Run one GraphRAG search for *kb_id*; returns a single hit-shaped dict for the REST layer."""
    q = (query or "").strip()
    if not q:
        raise ValueError("query must not be empty")

    _sync_graphrag_api_key_env()
    out = _output_dir(kb_id)
    if not (out / "entities.parquet").is_file():
        raise ValueError(
            "GraphRAG index not found (missing output/entities.parquet). Run reindex on this knowledge base."
        )

    try:
        from graphrag.api import basic_search, global_search, local_search
        from graphrag.config.load_config import load_config as graphrag_load_config
    except ImportError as exc:
        raise GraphRAGNotInstalledError(
            'GraphRAG is not installed. Install with: pip install -e ".[web,knowledge,knowledge-graphrag]"'
        ) from exc

    root = graphrag_project_root(kb_id)
    config = graphrag_load_config(root_dir=root)
    rt = (response_type or _default_response_type()).strip() or _default_response_type()
    cl = _default_community_level() if community_level is None else int(community_level)

    entities = _read_parquet(out / "entities.parquet")
    communities = _read_parquet(out / "communities.parquet")
    community_reports = _read_parquet(out / "community_reports.parquet")
    text_units = _read_parquet(out / "text_units.parquet")
    relationships = _read_parquet(out / "relationships.parquet")
    covariates = _read_parquet(out / "covariates.parquet")
    cov_arg: pd.DataFrame | None = None if covariates.empty else covariates

    method_l = (method or "local").strip().lower()
    if method_l not in ("local", "global", "basic"):
        raise ValueError(f"Unsupported graphrag method: {method!r}")

    async def _run() -> tuple[Any, Any]:
        if method_l == "global":
            if entities.empty or communities.empty or community_reports.empty:
                raise ValueError(
                    "GraphRAG index incomplete for global search "
                    "(need entities, communities, community_reports parquets)."
                )
            return await global_search(
                config,
                entities,
                communities,
                community_reports,
                community_level=None,
                dynamic_community_selection=dynamic_community_selection,
                response_type=rt,
                query=q,
            )
        if method_l == "basic":
            if text_units.empty:
                raise ValueError(
                    "GraphRAG index incomplete for basic search (text_units.parquet missing or empty)."
                )
            return await basic_search(
                config,
                text_units,
                response_type=rt,
                query=q,
            )
        # local
        if (
            entities.empty
            or communities.empty
            or community_reports.empty
            or text_units.empty
        ):
            raise ValueError(
                "GraphRAG index incomplete for local search "
                "(need entities, communities, community_reports, text_units parquets)."
            )
        return await local_search(
            config,
            entities,
            communities,
            community_reports,
            text_units,
            relationships,
            cov_arg,
            community_level=cl,
            response_type=rt,
            query=q,
        )

    try:
        answer, _ctx = asyncio.run(_run())
    except GraphRAGNotInstalledError:
        raise
    except Exception as exc:
        _log.exception("GraphRAG query failed kb_id=%s method=%s", kb_id, method_l)
        raise RuntimeError(str(exc)) from exc

    text_out = answer if isinstance(answer, str) else str(answer)
    return {
        "kb_id": kb_id,
        "chunk_id": None,
        "text": text_out,
        "source_path": None,
        "score": None,
        "kind": "graphrag",
        "graphrag_method": method_l,
    }
