"""Resolve GraphRAG query method (explicit vs ``auto`` heuristics for agent tools)."""

from __future__ import annotations

from typing import Any, Literal

from hermes_cli.config import load_config

GraphragSearchMethod = Literal["local", "global", "basic"]

_BUILTIN_GLOBAL_KEYWORDS_ZH: tuple[str, ...] = (
    "整体",
    "主题",
    "总结",
    "概述",
    "大纲",
    "全景",
    "主要脉络",
    "主线",
    "总体",
    "概括",
    "宏观",
    "全文",
    "整套",
    "跨章节",
    "跨文档",
    "全书",
    "有哪些类型",
    "整体上",
    "高层",
    "归纳",
)
_BUILTIN_GLOBAL_KEYWORDS_EN: tuple[str, ...] = (
    "overview",
    "summarize",
    "summary",
    "themes",
    "big picture",
    "across the",
    "across all",
    "overall",
    "high-level",
    "holistic",
    "entire document",
    "whole corpus",
    "whole document",
    "at a high level",
    "top-level",
)


def _auto_method_settings() -> dict[str, Any]:
    k = load_config().get("knowledge") or {}
    g = k.get("graphrag") if isinstance(k.get("graphrag"), dict) else {}
    raw = g.get("auto_method")
    return raw if isinstance(raw, dict) else {}


def _merged_global_keywords() -> list[str]:
    am = _auto_method_settings()
    extra = am.get("global_keywords")
    out: list[str] = list(_BUILTIN_GLOBAL_KEYWORDS_ZH) + list(_BUILTIN_GLOBAL_KEYWORDS_EN)
    if isinstance(extra, list):
        for x in extra:
            if isinstance(x, str) and (s := x.strip()):
                out.append(s)
    return out


def resolve_graphrag_query_method(query: str, requested: str) -> tuple[GraphragSearchMethod, str]:
    """Pick *local* | *global* | *basic* for ``graphrag_method``.

    Returns ``(method, reason_tag)`` where *reason_tag* is for logs / tool JSON
    (``explicit``, ``auto_global_keyword``, ``auto_short_query``, ``auto_default``, …).
    """
    req = (requested or "auto").strip().lower()
    if req in ("local", "global", "basic"):
        return req, "explicit"
    if req not in ("", "auto"):
        return "local", "fallback_invalid_explicit"

    q = (query or "").strip()
    am = _auto_method_settings()
    if am.get("enabled") is False:
        dm = (am.get("default_method") or "local").strip().lower()
        if dm in ("local", "global", "basic"):
            return dm, "auto_disabled_config_default"
        return "local", "auto_disabled_fallback"

    basic_max = am.get("basic_max_chars")
    try:
        basic_max_i = int(basic_max) if basic_max is not None else 24
    except (TypeError, ValueError):
        basic_max_i = 24
    basic_max_i = max(8, min(basic_max_i, 160))

    q_lower = q.lower()
    for kw in _merged_global_keywords():
        if not kw:
            continue
        if any("\u4e00" <= c <= "\u9fff" for c in kw):
            if kw in q:
                return "global", f"auto_global_keyword:{kw[:24]}"
        else:
            if kw.lower() in q_lower:
                return "global", f"auto_global_keyword:{kw[:24]}"

    if 1 <= len(q) <= basic_max_i:
        return "basic", "auto_short_query"

    dm = (am.get("default_method") or "local").strip().lower()
    if dm in ("local", "global", "basic"):
        return dm, "auto_default"
    return "local", "auto_default_fallback"
