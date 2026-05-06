"""Auto-generated routing summary for knowledge bases (written on each vector reindex).

Stored as UTF-8 text at ``bases/<kb_id>/routing_summary.txt`` so agents can read a
compact overview before RAG. Uses OpenAI-compatible chat (same ``OPENAI_*`` as
embeddings unless overridden). See ``knowledge.routing_summary`` in config.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hermes_cli.config import get_env_value, load_config

_log = logging.getLogger(__name__)

ROUTING_SUMMARY_FILENAME = "routing_summary.txt"

_SYSTEM_PROMPT = (
    "You write a single short paragraph (no bullet list) that helps another AI "
    "decide when to query this knowledge base. Describe topics, document types, "
    "and typical user questions this corpus answers. Use the same dominant "
    "language as the excerpts (Chinese if mostly Chinese). Max ~120 words."
)


def routing_summary_path(kb_id: str) -> Path:
    from hermes_cli.knowledge_registry import base_dir

    return base_dir(kb_id) / ROUTING_SUMMARY_FILENAME


def read_routing_summary_file(kb_id: str) -> str | None:
    p = routing_summary_path(kb_id)
    if not p.is_file():
        return None
    try:
        t = p.read_text(encoding="utf-8").strip()
    except OSError as exc:
        _log.debug("read routing_summary failed: %s", exc)
        return None
    return t or None


def clear_routing_summary_file(kb_id: str) -> None:
    p = routing_summary_path(kb_id)
    if p.is_file():
        try:
            p.unlink()
        except OSError as exc:
            _log.warning("Could not remove stale routing_summary: %s", exc)


def _routing_summary_config() -> dict[str, Any]:
    cfg = load_config()
    k = cfg.get("knowledge") or {}
    return dict(k.get("routing_summary") or {})


def _resolve_chat_model() -> str:
    rs = _routing_summary_config()
    m = (rs.get("model") or "").strip()
    if m:
        return m
    cfg = load_config()
    model_cfg = cfg.get("model")
    if isinstance(model_cfg, dict):
        inner = (model_cfg.get("default") or model_cfg.get("model") or "").strip()
        if inner:
            return inner
    if isinstance(model_cfg, str) and model_cfg.strip():
        return model_cfg.strip()
    return "gpt-4o-mini"


def build_summary_source_material(
    rows: list[tuple[str, str, list[float]]],
    max_chars: int,
) -> str:
    """Stratified sample of chunk texts for the summarizer prompt."""
    if not rows:
        return ""
    n = len(rows)
    step = max(1, n // 48) if n > 48 else 1
    parts: list[str] = []
    total = 0
    for i in range(0, n, step):
        src, text, _ = rows[i]
        snippet = (text or "").strip()
        if not snippet:
            continue
        if len(snippet) > 1400:
            snippet = snippet[:1400] + "…"
        piece = f"### {src}\n{snippet}\n\n"
        if total + len(piece) > max_chars:
            break
        parts.append(piece)
        total += len(piece)
    return "".join(parts)


def _chat_summarize(
    *,
    model: str,
    user_blob: str,
    kb_name: str,
    max_tokens: int,
) -> str | None:
    api_key = (get_env_value("OPENAI_API_KEY") or "").strip()
    if not api_key:
        _log.info("routing_summary: OPENAI_API_KEY missing — skip LLM summary")
        return None
    base = (get_env_value("OPENAI_BASE_URL") or "").strip().rstrip("/") or None
    try:
        from openai import OpenAI
    except ImportError:
        _log.warning("routing_summary: openai package missing")
        return None

    kwargs: dict[str, Any] = {"api_key": api_key}
    if base:
        kwargs["base_url"] = base
    client = OpenAI(**kwargs)
    user_msg = (
        f"Knowledge base display name: {kb_name!r}\n\n"
        f"Excerpts from indexed chunks (may be partial):\n\n{user_blob}"
    )
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=max_tokens,
            temperature=0.25,
        )
    except Exception as exc:
        _log.warning("routing_summary LLM call failed: %s", exc)
        return None
    choice = resp.choices[0].message
    content = (getattr(choice, "content", None) or "").strip()
    return content or None


def write_routing_summary_file(kb_id: str, text: str, max_len: int) -> None:
    p = routing_summary_path(kb_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    t = (text or "").strip()
    if max_len > 0 and len(t) > max_len:
        t = t[: max_len - 1] + "…"
    p.write_text(t, encoding="utf-8")


def try_generate_and_write_routing_summary(
    kb_id: str,
    kb_name: str,
    rows: list[tuple[str, str, list[float]]],
    *,
    cancel_event: threading.Event | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    """Best-effort: write ``routing_summary.txt``; never raises to caller."""
    rs = _routing_summary_config()
    if rs.get("enabled") is False:
        # Keep existing routing_summary.txt (do not delete) when feature is off.
        return

    def _p(payload: dict[str, Any]) -> None:
        if progress:
            progress(dict(payload))

    max_out = max(200, min(8000, int(rs.get("max_output_chars") or 900)))
    max_in = max(2000, min(120000, int(rs.get("max_source_chars") or 24000)))
    max_tokens = max(64, min(2048, int(rs.get("max_completion_tokens") or 320)))

    if cancel_event and cancel_event.is_set():
        return

    if not rows:
        write_routing_summary_file(
            kb_id,
            "(No indexed text in this knowledge base yet.)",
            max_out,
        )
        _p({"phase": "routing_summary", "done": True, "skipped_llm": True})
        return

    blob = build_summary_source_material(rows, max_in)
    if not blob.strip():
        write_routing_summary_file(
            kb_id,
            "(Indexed chunks contained no extractable text.)",
            max_out,
        )
        _p({"phase": "routing_summary", "done": True, "skipped_llm": True})
        return

    _p({"phase": "routing_summary", "current": 1, "total": 1, "path": ROUTING_SUMMARY_FILENAME})
    if cancel_event and cancel_event.is_set():
        return

    model = _resolve_chat_model()
    summary = _chat_summarize(model=model, user_blob=blob, kb_name=kb_name, max_tokens=max_tokens)
    if summary:
        write_routing_summary_file(kb_id, summary, max_out)
        _p({"phase": "routing_summary", "done": True, "skipped_llm": False})
    else:
        # Leave file absent or short fallback so catalog still has something
        fallback = (
            f"Auto-summary unavailable (LLM or API key). Base «{kb_name}» has "
            f"{len(rows)} chunk(s); use knowledge_vector_query for RAG."
        )
        write_routing_summary_file(kb_id, fallback[:max_out], max_out)
        _p({"phase": "routing_summary", "done": True, "skipped_llm": True, "fallback": True})


def routing_summary_for_catalog(summary_routing_mode: str, kb_id: str) -> str | None:
    """Expose ``routing_summary.txt`` to :func:`knowledge_catalog` only when mode is not ``manual``."""
    m = (summary_routing_mode or "auto").strip().lower()
    if m not in ("manual", "auto"):
        m = "auto"
    if m == "manual":
        return None
    return read_routing_summary_file(kb_id)


def augment_base_dict(kb_id: str, d: dict[str, Any]) -> dict[str, Any]:
    """Attach ``routing_summary`` from disk for Dashboard REST (always raw file)."""
    out = dict(d)
    out["routing_summary"] = read_routing_summary_file(kb_id)
    return out
