"""GraphRAG indexing for Dashboard knowledge bases (mode=graphrag).

Workspace root: ``bases/<kb_id>/graphrag/`` (settings.yaml, output/, …).
Input text is assembled from the shared ``raw/`` tree as a pandas DataFrame and
passed to ``graphrag.api.build_index(..., input_documents=...)`` so Hermes does
not need a duplicate ``input/`` copy.

See ``docs/zh/graphrag-pipeline.md`` for upstream API notes.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import Any, Callable

from hermes_cli.config import load_config
from hermes_cli.knowledge_registry import KnowledgeRegistry, base_dir
from hermes_cli.knowledge_index import KnowledgeReindexCancelled
from hermes_cli.knowledge_routing_summary import (
    clear_routing_summary_file,
    try_generate_and_write_routing_summary,
)
from hermes_cli.knowledge_text import iter_raw_documents

_log = logging.getLogger(__name__)

# GraphRAG ProgressTicker can fire very often; forwarding each tick to SSE would flood
# asyncio.run_coroutine_threadsafe + React. Cap subprogress events to ~4/s (burst allowed on completion).
_GRAPHRAG_SUBPROGRESS_MIN_INTERVAL_SEC = 0.22


class GraphRAGNotInstalledError(RuntimeError):
    """Optional dependency ``graphrag`` (extra ``[knowledge-graphrag]``) is missing."""


def graphrag_project_root(kb_id: str) -> Path:
    """Return the GraphRAG project directory for *kb_id*."""
    return base_dir(kb_id) / "graphrag"


def graphrag_input_records_from_kb(kb_id: str) -> list[dict[str, Any]]:
    """Build GraphRAG document rows from ``raw/`` (title = relative path under raw/).

    ``title`` MUST stay stable across runs so upstream incremental indexing can
    diff on ``documents.title`` (see ``graphrag.index.update.incremental_index``).
    """
    raw_dir = base_dir(kb_id) / "raw"
    rows: list[dict[str, Any]] = []
    for rel, text in iter_raw_documents(raw_dir):
        rows.append(
            {
                "id": str(uuid.uuid4()),
                "text": text,
                "title": rel,
                "creation_date": datetime.now(timezone.utc).isoformat(),
                "raw_data": None,
                "human_readable_id": len(rows),
            }
        )
    return rows


def _graphrag_has_prior_index(root: Path) -> bool:
    """Best-effort check for an existing GraphRAG output (for incremental runs)."""
    output = root / "output"
    return (output / "entities.parquet").is_file()


def _sync_graphrag_api_key_env() -> None:
    """GraphRAG defaults to ``GRAPHRAG_API_KEY``; bridge from ``OPENAI_API_KEY``."""
    if os.environ.get("GRAPHRAG_API_KEY"):
        return
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if key:
        os.environ["GRAPHRAG_API_KEY"] = key


def _hermes_default_chat_model_id() -> str:
    cfg = load_config()
    rs = (cfg.get("knowledge") or {}).get("routing_summary") or {}
    m = (rs.get("model") or "").strip() if isinstance(rs, dict) else ""
    if m:
        return m
    model_cfg = cfg.get("model")
    if isinstance(model_cfg, dict):
        inner = (model_cfg.get("default") or model_cfg.get("model") or "").strip()
        if inner:
            return inner
    if isinstance(model_cfg, str) and model_cfg.strip():
        return model_cfg.strip()
    return "gpt-4o-mini"


def _resolve_graphrag_completion_embedding_models() -> tuple[str, str]:
    cfg = load_config()
    k = cfg.get("knowledge") or {}
    g = k.get("graphrag") if isinstance(k.get("graphrag"), dict) else {}
    emb = (g.get("embedding_model") or "").strip() if isinstance(g, dict) else ""
    if not emb:
        emb_cfg = k.get("embedding") if isinstance(k.get("embedding"), dict) else {}
        emb = (emb_cfg.get("model") or "").strip() or "text-embedding-3-small"
    chat = (g.get("completion_model") or "").strip() if isinstance(g, dict) else ""
    if not chat:
        chat = _hermes_default_chat_model_id()
    return chat, emb


def _indexing_method_name() -> str:
    cfg = load_config()
    k = cfg.get("knowledge") or {}
    g = k.get("graphrag") if isinstance(k.get("graphrag"), dict) else {}
    m = (g.get("indexing_method") or "standard").strip().lower() if isinstance(g, dict) else "standard"
    return "fast" if m == "fast" else "standard"


def _patch_graphrag_settings_models(
    path: Path, completion_model: str, embedding_model: str
) -> None:
    """Align ``settings.yaml`` chat/embedding model ids with Hermes config.

    Recent PyPI ``graphrag`` only exposes ``initialize_project_at(path, force)`` and
    ships defaults like ``gpt-4-turbo-preview``; older wheels accepted ``model=``
    kwargs. We patch YAML after a fresh init so ``knowledge.graphrag`` /
    ``knowledge.embedding`` win without manual edits.
    """
    try:
        import yaml
    except ImportError:
        return
    try:
        raw = path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
    except (OSError, yaml.YAMLError) as exc:
        _log.debug("skip GraphRAG settings patch: %s", exc)
        return
    if not isinstance(data, dict):
        return
    changed = False
    models_block = data.get("models")
    if isinstance(models_block, dict):
        dc = models_block.get("default_chat_model")
        if isinstance(dc, dict) and completion_model:
            dc["model"] = completion_model
            changed = True
        de = models_block.get("default_embedding_model")
        if isinstance(de, dict) and embedding_model:
            de["model"] = embedding_model
            changed = True
    cm = data.get("completion_models")
    if isinstance(cm, dict) and completion_model:
        for _k, v in cm.items():
            if isinstance(v, dict):
                v["model"] = completion_model
                changed = True
                break
    em = data.get("embedding_models")
    if isinstance(em, dict) and embedding_model:
        for _k, v in em.items():
            if isinstance(v, dict):
                v["model"] = embedding_model
                changed = True
                break
    if not changed:
        return
    try:
        path.write_text(
            yaml.dump(
                data,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
                width=120,
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        _log.warning("Could not write patched GraphRAG settings.yaml: %s", exc)


def _ensure_graphrag_project_initialized(root: Path, completion_model: str, embedding_model: str) -> None:
    import inspect

    try:
        from graphrag.cli.initialize import initialize_project_at
    except ImportError as exc:
        raise GraphRAGNotInstalledError(
            'GraphRAG is not installed. Install with: pip install -e ".[web,knowledge,knowledge-graphrag]"'
        ) from exc

    settings = root / "settings.yaml"
    had_settings = settings.is_file()

    if not had_settings:
        root.mkdir(parents=True, exist_ok=True)
        sig = inspect.signature(initialize_project_at)
        kwargs: dict[str, str] = {}
        if "model" in sig.parameters:
            kwargs["model"] = completion_model
        if "embedding_model" in sig.parameters:
            kwargs["embedding_model"] = embedding_model
        initialize_project_at(root, force=False, **kwargs)

    if settings.is_file() and not had_settings:
        _patch_graphrag_settings_models(settings, completion_model, embedding_model)


def run_graphrag_reindex(
    kb_id: str,
    registry: KnowledgeRegistry | None = None,
    *,
    progress: Callable[[dict[str, Any]], None] | None = None,
    cancel_event: Event | None = None,
    force_full: bool = False,
) -> dict[str, Any]:
    """Run Microsoft GraphRAG indexing for ``mode=graphrag`` knowledge base *kb_id*.

    Uses ``input_documents`` so ``raw/`` remains the single source of truth.
    When a prior ``output/entities.parquet`` exists and *force_full* is false,
    runs an incremental update (``is_update_run=True``).
    """
    try:
        import pandas as pd
    except ImportError as exc:
        raise GraphRAGNotInstalledError(
            "pandas is required for GraphRAG indexing (install the graphrag extra)."
        ) from exc

    reg = registry or KnowledgeRegistry()
    rec = reg.get(kb_id)
    if not rec:
        raise ValueError("Knowledge base not found")
    if rec.mode != "graphrag":
        raise ValueError("Not a GraphRAG knowledge base")

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

    completion_model, embedding_model = _resolve_graphrag_completion_embedding_models()
    root = graphrag_project_root(kb_id)

    try:
        records = graphrag_input_records_from_kb(kb_id)
        if not records:
            reg.update_meta(
                kb_id,
                indexing_status="idle",
                error_message="No text documents under raw/; upload files before reindex.",
            )
            raise ValueError("No documents under raw/")

        _ensure_graphrag_project_initialized(root, completion_model, embedding_model)

        try:
            from graphrag.api.index import build_index
            from graphrag.config.enums import IndexingMethod
            from graphrag.config.load_config import load_config as graphrag_load_config
        except ImportError as exc:
            raise GraphRAGNotInstalledError(
                'GraphRAG is not installed. Install with: pip install -e ".[web,knowledge,knowledge-graphrag]"'
            ) from exc

        _sync_graphrag_api_key_env()
        config = graphrag_load_config(root_dir=root)

        incremental = _graphrag_has_prior_index(root) and not force_full
        method_name = _indexing_method_name()
        method = IndexingMethod.Fast if method_name == "fast" else IndexingMethod.Standard

        df = pd.DataFrame(records)
        _p(
            {
                "phase": "graphrag",
                "graphrag_event": "prepare",
                "graphrag_message": "incremental" if incremental else "full",
                "documents": len(records),
                "indexing_method": method_name,
            }
        )

        if cancel_event and cancel_event.is_set():
            reg.update_meta(kb_id, indexing_status="idle", clear_error=True)
            raise KnowledgeReindexCancelled()

        from graphrag.callbacks.noop_workflow_callbacks import NoopWorkflowCallbacks
        from graphrag.logger.progress import Progress as GrProgress

        class _HermesGraphragWorkflowCallbacks(NoopWorkflowCallbacks):
            """Forward GraphRAG workflow lifecycle to Dashboard SSE (via *on_progress*).

            ``build_index`` calls ``pipeline_start`` with the *pre-removal* workflow list, but
            ``run_pipeline`` drops ``load_input_documents`` / ``load_update_documents`` when
            ``input_documents`` is set (Hermes always passes a DataFrame). We filter those out
            so the UI step list matches executed workflows. Completion is tracked by **name**,
            not a running count (avoids index skew when loaders are skipped).
            """

            def __init__(
                self,
                on_progress: Callable[[dict[str, Any]], None],
                *,
                skip_document_loader: str | None,
            ) -> None:
                super().__init__()
                self._on = on_progress
                self._names: list[str] = []
                self._completed: list[str] = []
                self._skip_document_loader = skip_document_loader
                self._last_subprogress_emit: float = 0.0
                self._last_subprogress_key: tuple[Any, ...] | None = None

            def pipeline_start(self, names: list[str]) -> None:
                self._completed = []
                filtered = [n for n in names if n != self._skip_document_loader]
                self._names = filtered
                n = len(self._names)
                self._on(
                    {
                        "phase": "graphrag",
                        "graphrag_event": "pipeline_start",
                        "workflows": self._names,
                        "workflow_total": n,
                        "skipped_workflow": self._skip_document_loader,
                    }
                )

            def pipeline_end(self, results: list[Any]) -> None:
                self._on(
                    {
                        "phase": "graphrag",
                        "graphrag_event": "pipeline_end",
                        "workflow_total": len(self._names),
                        "workflows_completed": len(results),
                        "completed_workflows": list(self._names),
                        "active_workflow": None,
                    }
                )

            def workflow_start(self, name: str, instance: object) -> None:
                self._last_subprogress_key = None
                idx = self._names.index(name) + 1 if name in self._names else 0
                self._on(
                    {
                        "phase": "graphrag",
                        "graphrag_event": "workflow_start",
                        "workflow": name,
                        "workflow_index": idx,
                        "workflow_total": len(self._names),
                        "active_workflow": name,
                    }
                )

            def workflow_end(self, name: str, instance: object) -> None:
                if name not in self._completed:
                    self._completed.append(name)
                self._on(
                    {
                        "phase": "graphrag",
                        "graphrag_event": "workflow_end",
                        "workflow": name,
                        "workflow_total": len(self._names),
                        "completed_workflows": list(self._completed),
                        "active_workflow": None,
                    }
                )

            def progress(self, progress: GrProgress) -> None:
                desc = progress.description
                cur = progress.completed_items
                tot = progress.total_items
                key = (desc, cur, tot)
                now = time.monotonic()
                batch_done = (
                    isinstance(cur, int)
                    and isinstance(tot, int)
                    and tot > 0
                    and cur >= tot
                )
                if not batch_done:
                    if key == self._last_subprogress_key:
                        return
                    if (now - self._last_subprogress_emit) < _GRAPHRAG_SUBPROGRESS_MIN_INTERVAL_SEC:
                        return
                self._last_subprogress_emit = now
                self._last_subprogress_key = key
                self._on(
                    {
                        "phase": "graphrag",
                        "graphrag_event": "subprogress",
                        "subprogress_description": desc,
                        "subprogress_current": cur,
                        "subprogress_total": tot,
                    }
                )

        skip_loader = "load_update_documents" if incremental else "load_input_documents"
        graph_callbacks = _HermesGraphragWorkflowCallbacks(
            _p,
            skip_document_loader=skip_loader,
        )

        results = asyncio.run(
            build_index(
                config,
                method=method,
                is_update_run=incremental,
                input_documents=df,
                verbose=False,
                callbacks=[graph_callbacks],
            )
        )

        errors = [getattr(r, "error", None) for r in results]
        errors = [e for e in errors if e]
        if errors:
            raise RuntimeError(str(errors[0]))

        if mode == "auto" and rs_enabled:
            pairs = iter_raw_documents(base_dir(kb_id) / "raw")
            summary_rows = [(a, b, []) for a, b in pairs]
            try:
                try_generate_and_write_routing_summary(
                    kb_id,
                    rec.name,
                    summary_rows,
                    cancel_event=cancel_event,
                    progress=_p,
                )
            except Exception as exc:
                _log.warning("routing_summary after graphrag reindex: %s", exc)

        reg.update_meta(kb_id, indexing_status="ready", clear_error=True)
        return {
            "graphrag": True,
            "documents": len(records),
            "incremental": incremental,
            "indexing_method": method_name,
            "workflows": len(results),
        }
    except GraphRAGNotInstalledError:
        raise
    except KnowledgeReindexCancelled:
        raise
    except ValueError:
        raise
    except Exception as exc:
        _log.exception("GraphRAG reindex failed for kb_id=%s", kb_id)
        reg.update_meta(kb_id, indexing_status="error", error_message=str(exc)[:2000])
        raise
