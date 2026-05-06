"""Dashboard REST API for knowledge bases (track A: registry + upload + FAISS + query)."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import threading
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from hermes_cli.config import load_config
from hermes_cli.knowledge_embedding import KnowledgeEmbeddingError, probe_embedding
from hermes_cli.knowledge_graphrag import GraphRAGNotInstalledError, run_graphrag_reindex
from hermes_cli.knowledge_index import (
    KnowledgeReindexCancelled,
    query_vector_bases,
    run_vector_reindex,
)
from hermes_cli.knowledge_registry import KnowledgeRegistry, base_dir
from hermes_cli.knowledge_routing_summary import augment_base_dict

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

_SAFE_NAME_RE = re.compile(r"^[^\\/:*?\"<>|\x00-\x1f]+$")
_AGENT_SUMMARY_MAX_LEN = 4096
SummaryRoutingMode = Literal["manual", "auto"]
# Lazy init so tests that patch HERMES_HOME before first import of this module
# still get a registry under the temp home (see tests/hermes_cli/test_knowledge_api.py).
_REGISTRY: KnowledgeRegistry | None = None


class CreateKnowledgeBaseBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    mode: Literal["vector", "graphrag"] = "vector"
    agent_summary: str | None = Field(
        default=None,
        max_length=_AGENT_SUMMARY_MAX_LEN,
        description="Short description for the model to pick this KB before vector search (like a skill blurb).",
    )
    summary_routing_mode: SummaryRoutingMode = Field(
        default="auto",
        description="manual = only agent_summary for routing; auto = LLM writes routing_summary.txt after vector reindex.",
    )


class PatchKnowledgeBaseBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    mode: Literal["vector", "graphrag"] | None = None
    chunk_config: dict[str, Any] | None = None
    agent_summary: str | None = Field(
        default=None,
        max_length=_AGENT_SUMMARY_MAX_LEN,
        description="Replace or clear (null) the agent-facing summary for this knowledge base.",
    )
    summary_routing_mode: SummaryRoutingMode | None = None


class KnowledgeQueryBody(BaseModel):
    kb_ids: list[str] = Field(..., min_length=1)
    query: str = Field(..., min_length=1, max_length=16000)
    top_k: int = Field(default=8, ge=1, le=50)
    graphrag_method: Literal["local", "global", "basic", "drift"] | None = Field(
        default=None,
        description="GraphRAG search mode when all kb_ids are mode=graphrag; ignored for vector bases.",
    )


class DebugEmbedBody(BaseModel):
    input: str = Field(default="hello", min_length=1, max_length=8000)


def _normalize_agent_summary(raw: str | None) -> str | None:
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    if len(s) > _AGENT_SUMMARY_MAX_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"agent_summary exceeds {_AGENT_SUMMARY_MAX_LEN} characters",
        )
    return s


def _get_registry() -> KnowledgeRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = KnowledgeRegistry()
    return _REGISTRY


@router.get("/bases")
def list_knowledge_bases() -> dict:
    rows = _get_registry().list_all()
    return {"bases": [augment_base_dict(r.id, r.to_dict()) for r in rows]}


@router.post("/bases")
def create_knowledge_base(body: CreateKnowledgeBaseBody) -> dict:
    summary = _normalize_agent_summary(body.agent_summary)
    rec = _get_registry().create(
        body.name,
        mode=body.mode,
        agent_summary=summary,
        summary_routing_mode=body.summary_routing_mode,
    )
    return {"base": augment_base_dict(rec.id, rec.to_dict())}


@router.get("/bases/{kb_id}")
def get_knowledge_base(kb_id: str) -> dict:
    rec = _get_registry().get(kb_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return {"base": augment_base_dict(kb_id, rec.to_dict())}


@router.patch("/bases/{kb_id}")
def patch_knowledge_base(kb_id: str, body: PatchKnowledgeBaseBody) -> dict:
    reg = _get_registry()
    cur = reg.get(kb_id)
    if not cur:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    dump = body.model_dump(exclude_unset=True)
    if not dump:
        raise HTTPException(status_code=400, detail="No fields to update")
    if body.mode is not None and body.mode != cur.mode and cur.indexing_status == "ready":
        raise HTTPException(
            status_code=400,
            detail="Cannot change mode while indexing_status is ready; delete index first",
        )
    kw: dict[str, Any] = {}
    if "name" in dump:
        kw["name"] = body.name
    if "mode" in dump:
        kw["mode"] = body.mode
    if "chunk_config" in dump:
        kw["chunk_config"] = _validate_chunk_config_payload(body.chunk_config)
    if "agent_summary" in dump:
        kw["agent_summary"] = _normalize_agent_summary(body.agent_summary)
    if "summary_routing_mode" in dump and body.summary_routing_mode is not None:
        kw["summary_routing_mode"] = body.summary_routing_mode
    updated = reg.update_meta(kb_id, **kw)
    assert updated is not None
    return {"base": augment_base_dict(kb_id, updated.to_dict())}


@router.delete("/bases/{kb_id}")
def delete_knowledge_base(kb_id: str) -> dict:
    if not _get_registry().delete(kb_id):
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return {"ok": True}


def _validate_chunk_config_payload(cfg: dict[str, Any] | None) -> dict[str, Any] | None:
    """Validate PATCH chunk_config; ``None`` clears per-KB overrides."""
    if cfg is None:
        return None
    if not isinstance(cfg, dict):
        raise HTTPException(status_code=400, detail="chunk_config must be an object")
    if not cfg:
        return None
    raw = json.dumps(cfg)
    if len(raw) > 32000:
        raise HTTPException(status_code=400, detail="chunk_config too large")
    strat = cfg.get("strategy")
    if strat is not None and strat not in ("window", "delimiter", "semantic", "smart"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid chunk.strategy: {strat!r} (use window, delimiter, semantic, smart)",
        )
    st = cfg.get("size_tokens")
    if st is not None and (not isinstance(st, int) or not (1 <= st <= 100_000)):
        raise HTTPException(status_code=400, detail="size_tokens must be int in [1, 100000]")
    ot = cfg.get("overlap_tokens")
    if ot is not None and (not isinstance(ot, int) or not (0 <= ot <= 50_000)):
        raise HTTPException(status_code=400, detail="overlap_tokens must be int in [0, 50000]")
    deli = cfg.get("delimiter")
    if deli is not None:
        if not isinstance(deli, dict):
            raise HTTPException(status_code=400, detail="chunk.delimiter must be an object")
        seps = deli.get("separators")
        if seps is not None:
            if not isinstance(seps, list) or len(seps) > 40:
                raise HTTPException(
                    status_code=400,
                    detail="delimiter.separators must be a list (max 40 items)",
                )
            for x in seps:
                if not isinstance(x, str) or len(x) > 64:
                    raise HTTPException(status_code=400, detail="invalid delimiter.separators entry")
    sem = cfg.get("semantic")
    if sem is not None:
        if not isinstance(sem, dict):
            raise HTTPException(status_code=400, detail="chunk.semantic must be an object")
        mode = sem.get("mode")
        if mode is not None and mode not in ("pack", "embedding"):
            raise HTTPException(status_code=400, detail="semantic.mode must be pack or embedding")
        sthr = sem.get("similarity_threshold")
        if sthr is not None:
            v = float(sthr)
            if not (0.0 <= v <= 1.0):
                raise HTTPException(
                    status_code=400,
                    detail="semantic.similarity_threshold must be in [0, 1]",
                )
    smt = cfg.get("smart")
    if smt is not None:
        if not isinstance(smt, dict):
            raise HTTPException(status_code=400, detail="chunk.smart must be an object")
        mc = smt.get("max_chunk_chars")
        if mc is not None and (not isinstance(mc, int) or not (64 <= mc <= 500_000)):
            raise HTTPException(
                status_code=400,
                detail="smart.max_chunk_chars must be int in [64, 500000] or omitted",
            )
        oc = smt.get("overlap_chars")
        if oc is not None and (not isinstance(oc, int) or not (0 <= oc <= 50_000)):
            raise HTTPException(
                status_code=400,
                detail="smart.overlap_chars must be int in [0, 50000] or omitted",
            )
    return cfg


def _sanitize_upload_filename(name: str) -> str:
    base = Path(name).name
    if not base or base in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not _SAFE_NAME_RE.match(base):
        raise HTTPException(status_code=400, detail="Unsupported filename characters")
    if len(base) > 240:
        raise HTTPException(status_code=400, detail="Filename too long")
    return base


def _sse_payload(obj: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8")


def _upload_result_dict(
    kb_id: str,
    dest: Path,
    safe: str,
    contents_len: int,
    pdf_converted: bool,
) -> dict[str, Any]:
    out_name = safe
    out_bytes = contents_len
    if pdf_converted:
        md_path = dest.with_suffix(".md")
        if md_path.is_file():
            out_name = md_path.name
            try:
                out_bytes = md_path.stat().st_size
            except OSError:
                out_bytes = contents_len
    return {
        "ok": True,
        "path": f"bases/{kb_id}/raw/{out_name}",
        "bytes": out_bytes,
        "pdf_converted_to_markdown": pdf_converted,
    }


@router.post("/bases/{kb_id}/upload")
async def upload_knowledge_file(
    kb_id: str,
    file: Annotated[UploadFile, File()],
    stream: Annotated[
        bool,
        Query(description="If true, response is text/event-stream with progress + final JSON"),
    ] = False,
):
    reg = _get_registry()
    if not reg.get(kb_id):
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    raw_name = file.filename or "upload.txt"
    safe = _sanitize_upload_filename(raw_name)

    raw_dir = base_dir(kb_id) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / safe

    try:
        contents = await file.read()
        if len(contents) > 50 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="File larger than 50 MiB")
        dest.write_bytes(contents)
    finally:
        await file.close()

    if stream:

        async def event_stream() -> AsyncIterator[bytes]:
            yield _sse_payload({"event": "saved", "filename": safe, "bytes": len(contents)})
            pdf_to_md = False
            if safe.lower().endswith(".pdf"):
                loop = asyncio.get_running_loop()
                q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
                conv: dict[str, Any] = {}

                def on_phase(phase: str, data: dict[str, Any]) -> None:
                    asyncio.run_coroutine_threadsafe(
                        q.put({"event": "progress", "phase": phase, **data}),
                        loop,
                    )

                def worker() -> None:
                    try:
                        from hermes_cli.knowledge_mineru import try_convert_uploaded_pdf

                        conv["pdf_to_md"] = try_convert_uploaded_pdf(dest, progress=on_phase)
                    except BaseException as exc:
                        conv["error"] = f"{type(exc).__name__}: {exc}"
                    finally:
                        asyncio.run_coroutine_threadsafe(q.put({"event": "__end__"}), loop)

                fut = loop.run_in_executor(None, worker)
                ended = False
                while not ended:
                    try:
                        msg = await asyncio.wait_for(q.get(), timeout=1.0)
                    except asyncio.TimeoutError:
                        yield _sse_payload({"event": "heartbeat"})
                        continue
                    if msg.get("event") == "__end__":
                        ended = True
                    else:
                        yield _sse_payload(msg)
                await fut
                if conv.get("error"):
                    reg.update_meta(kb_id, indexing_status="idle", clear_error=True)
                    yield _sse_payload({"event": "error", "message": conv["error"]})
                    return
                pdf_to_md = bool(conv.get("pdf_to_md"))
            reg.update_meta(kb_id, indexing_status="idle", clear_error=True)
            body = _upload_result_dict(kb_id, dest, safe, len(contents), pdf_to_md)
            yield _sse_payload({"event": "final", **body})

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream; charset=utf-8",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    pdf_to_md = False
    if safe.lower().endswith(".pdf"):
        from hermes_cli.knowledge_mineru import try_convert_uploaded_pdf

        converted = await asyncio.to_thread(try_convert_uploaded_pdf, dest)
        if converted:
            pdf_to_md = True

    reg.update_meta(kb_id, indexing_status="idle", clear_error=True)

    return _upload_result_dict(kb_id, dest, safe, len(contents), pdf_to_md)


def _clear_kb_raw_directory(kb_id: str, reg: KnowledgeRegistry) -> int:
    """Remove all files under ``bases/<kb_id>/raw/`` and recreate an empty ``raw/``.

    Returns an approximate count of files removed (before deletion walk).
    """
    raw_dir = base_dir(kb_id) / "raw"
    removed = 0
    if raw_dir.is_dir():
        removed = sum(1 for p in raw_dir.rglob("*") if p.is_file())
        shutil.rmtree(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    reg.update_meta(kb_id, indexing_status="idle", clear_error=True)
    return removed


@router.delete("/bases/{kb_id}/raw")
async def clear_knowledge_raw(kb_id: str):
    """Delete every document under ``raw/`` (replace-corpus workflow). Keeps the KB."""
    reg = _get_registry()
    if not reg.get(kb_id):
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    n = await asyncio.to_thread(_clear_kb_raw_directory, kb_id, reg)
    return {"ok": True, "removed_files": n}


@router.post("/bases/{kb_id}/reindex")
async def reindex_knowledge_base(
    request: Request,
    kb_id: str,
    stream: Annotated[int, Query(description="1 = SSE progress + final JSON in stream")] = 0,
    full: Annotated[
        int,
        Query(
            description="GraphRAG only: 1 = force full rebuild (ignore prior output); 0 = default auto incremental when output exists",
        ),
    ] = 0,
):
    reg = _get_registry()
    rec = reg.get(kb_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    force_graphrag_full = bool(full) if rec.mode == "graphrag" else False
    if rec.mode == "graphrag":
        if stream:
            loop = asyncio.get_running_loop()
            q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
            cancel_event = threading.Event()

            def on_progress(msg: dict[str, Any]) -> None:
                payload = {"event": "progress", **msg}
                asyncio.run_coroutine_threadsafe(q.put(payload), loop)

            async def event_stream_gr() -> AsyncIterator[bytes]:
                holder: dict[str, Any] = {}

                def worker_gr() -> None:
                    try:
                        holder["stats"] = run_graphrag_reindex(
                            kb_id,
                            reg,
                            progress=on_progress,
                            cancel_event=cancel_event,
                            force_full=force_graphrag_full,
                        )
                    except KnowledgeReindexCancelled:
                        holder["cancelled"] = True
                    except BaseException as exc:
                        holder["exc"] = exc
                    finally:
                        asyncio.run_coroutine_threadsafe(q.put(None), loop)

                fut = loop.run_in_executor(None, worker_gr)
                # Long GraphRAG runs: avoid sub-second busy loops (heartbeats + is_disconnected checks).
                _hb_sec = 1.25
                while True:
                    disconnected = await request.is_disconnected()
                    if disconnected:
                        cancel_event.set()
                    try:
                        msg = await asyncio.wait_for(q.get(), timeout=_hb_sec)
                    except asyncio.TimeoutError:
                        if not disconnected and await request.is_disconnected():
                            cancel_event.set()
                        yield _sse_payload({"event": "heartbeat"})
                        continue
                    if msg is None:
                        break
                    yield _sse_payload(msg)
                await fut
                if holder.get("cancelled"):
                    yield _sse_payload(
                        {"event": "cancelled", "message": "Reindex cancelled"},
                    )
                    return
                exc = holder.get("exc")
                if exc is not None:
                    if isinstance(exc, GraphRAGNotInstalledError):
                        yield _sse_payload(
                            {"event": "error", "message": str(exc)},
                        )
                        return
                    if isinstance(exc, ValueError):
                        yield _sse_payload({"event": "error", "message": str(exc)})
                        return
                    yield _sse_payload(
                        {"event": "error", "message": f"{type(exc).__name__}: {exc}"},
                    )
                    return
                updated = reg.get(kb_id)
                assert updated is not None
                yield _sse_payload(
                    {
                        "event": "final",
                        "base": augment_base_dict(kb_id, updated.to_dict()),
                        "stats": holder["stats"],
                    },
                )

            return StreamingResponse(
                event_stream_gr(),
                media_type="text/event-stream; charset=utf-8",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        try:
            stats = await asyncio.to_thread(
                run_graphrag_reindex,
                kb_id,
                reg,
                force_full=force_graphrag_full,
            )
        except GraphRAGNotInstalledError as exc:
            raise HTTPException(
                status_code=501,
                detail=str(exc),
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        updated = reg.get(kb_id)
        assert updated is not None
        return {"base": augment_base_dict(kb_id, updated.to_dict()), "stats": stats}

    if stream:
        loop = asyncio.get_running_loop()
        q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        cancel_event = threading.Event()

        def on_progress(msg: dict[str, Any]) -> None:
            payload = {"event": "progress", **msg}
            asyncio.run_coroutine_threadsafe(q.put(payload), loop)

        async def event_stream() -> AsyncIterator[bytes]:
            holder: dict[str, Any] = {}

            def worker() -> None:
                try:
                    holder["stats"] = run_vector_reindex(
                        kb_id,
                        reg,
                        progress=on_progress,
                        cancel_event=cancel_event,
                    )
                except KnowledgeReindexCancelled:
                    holder["cancelled"] = True
                except BaseException as exc:
                    holder["exc"] = exc
                finally:
                    asyncio.run_coroutine_threadsafe(q.put(None), loop)

            fut = loop.run_in_executor(None, worker)
            while True:
                if await request.is_disconnected():
                    cancel_event.set()
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        cancel_event.set()
                    yield _sse_payload({"event": "heartbeat"})
                    continue
                if msg is None:
                    break
                yield _sse_payload(msg)
            await fut
            if holder.get("cancelled"):
                yield _sse_payload(
                    {"event": "cancelled", "message": "Reindex cancelled"},
                )
                return
            exc = holder.get("exc")
            if exc is not None:
                if isinstance(exc, KnowledgeEmbeddingError):
                    yield _sse_payload({"event": "error", "message": str(exc)})
                elif isinstance(exc, ValueError):
                    yield _sse_payload({"event": "error", "message": str(exc)})
                elif isinstance(exc, RuntimeError):
                    yield _sse_payload({"event": "error", "message": str(exc)})
                else:
                    yield _sse_payload(
                        {"event": "error", "message": f"{type(exc).__name__}: {exc}"},
                    )
                return
            updated = reg.get(kb_id)
            assert updated is not None
            yield _sse_payload(
                {
                    "event": "final",
                    "base": augment_base_dict(kb_id, updated.to_dict()),
                    "stats": holder["stats"],
                },
            )

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream; charset=utf-8",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    try:
        stats = await asyncio.to_thread(run_vector_reindex, kb_id, reg)
    except KnowledgeEmbeddingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        # e.g. faiss not installed
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    updated = reg.get(kb_id)
    assert updated is not None
    return {"base": augment_base_dict(kb_id, updated.to_dict()), "stats": stats}


@router.post("/query")
def knowledge_query(body: KnowledgeQueryBody) -> dict:
    reg = _get_registry()
    modes: list[str] = []
    for kb_id in body.kb_ids:
        rec = reg.get(kb_id)
        if not rec:
            raise HTTPException(status_code=404, detail=f"Knowledge base not found: {kb_id}")
        modes.append(rec.mode)
    if len(set(modes)) > 1:
        raise HTTPException(
            status_code=400,
            detail="Cannot mix vector and graphrag knowledge bases in one query.",
        )
    if modes[0] == "graphrag":
        if len(body.kb_ids) != 1:
            raise HTTPException(
                status_code=400,
                detail="GraphRAG debug query supports exactly one knowledge base per request.",
            )
        kb_id = body.kb_ids[0]
        rec = reg.get(kb_id)
        assert rec is not None
        if rec.indexing_status != "ready":
            raise HTTPException(
                status_code=400,
                detail="GraphRAG index is not ready for this knowledge base; run reindex first.",
            )
        gmeth = body.graphrag_method
        if gmeth is None:
            g = (load_config().get("knowledge") or {}).get("graphrag") or {}
            gmeth = (
                (g.get("query_method") or "local").strip().lower()
                if isinstance(g, dict)
                else "local"
            )
        if gmeth not in ("local", "global", "basic", "drift"):
            raise HTTPException(status_code=400, detail=f"Invalid graphrag_method: {gmeth!r}")
        if gmeth == "drift":
            raise HTTPException(
                status_code=501,
                detail="GraphRAG drift search is not enabled in this build.",
            )
        try:
            from hermes_cli.knowledge_graphrag_query import query_graphrag_base

            hit = query_graphrag_base(kb_id, body.query.strip(), gmeth)
        except GraphRAGNotInstalledError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"results": [hit]}

    try:
        results = query_vector_bases(body.kb_ids, body.query, body.top_k)
    except KnowledgeEmbeddingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"results": results}


@router.post("/debug/embedding")
def debug_embedding(body: DebugEmbedBody) -> dict:
    """Verify OPENAI_API_KEY / OPENAI_BASE_URL + embedding model before indexing."""
    try:
        return probe_embedding(body.input.strip())
    except KnowledgeEmbeddingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
