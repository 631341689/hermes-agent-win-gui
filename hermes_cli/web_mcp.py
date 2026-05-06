"""Dashboard REST API for MCP servers (``config.yaml`` → ``mcp_servers``)."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

import httpx
from fastapi import APIRouter, Body, HTTPException

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

_RELOAD_HINT = (
    "Restart CLI, TUI, or the messaging gateway for MCP changes to take effect "
    "in running sessions."
)

_NAME_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")

_MCP_PARSE_RAW_MAX = 12_000

_PARSE_SYSTEM = """You help configure MCP servers for Hermes Agent (YAML key mcp_servers).
The user pastes a shell command, docs, or URL. Return ONLY a single JSON object (no markdown) with keys:
- recommended_transport: "stdio" | "http" | "unclear"
- confidence: "high" | "medium" | "low"
- server_name_suggestion: string matching [a-zA-Z0-9_.-]+ or empty
- stdio: {"command": string, "args": array of strings} — argv after command; use [] if not applicable
- http: {"url": string, "headers": object (string values only), "auth": string} — empty url if N/A; auth e.g. oauth or empty
- notes: one short helpful sentence (Chinese is fine)

Rules: Hermes persists EITHER stdio (command+args) OR http (url), never both. If the paste is npx/uvx/node/deno running a CLI, use stdio with command as first token and args as the rest. Preserve URL query strings. Do not invent API keys."""

_USER_PARSE_TEMPLATE = "Parse this for Hermes mcp_servers YAML:\n\n{raw}\n"

_ALLOWED_KEYS = frozenset({
    "enabled",
    "command",
    "args",
    "env",
    "url",
    "headers",
    "timeout",
    "connect_timeout",
    "tools",
    "auth",
    "oauth",
    "sampling",
})


def _mask_sensitive_string(val: str) -> str:
    if len(val) <= 8:
        return "***"
    return val[:4] + "***" + val[-4:]


def _should_mask_header_key(key: str) -> bool:
    low = key.lower()
    return any(
        x in low
        for x in ("auth", "token", "secret", "password", "api-key", "apikey", "bearer")
    )


def _sanitize_mcp_server_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Return a copy safe to send to the browser (mask likely secrets)."""
    out = copy.deepcopy(cfg)
    headers = out.get("headers")
    if isinstance(headers, dict):
        for hk, hv in list(headers.items()):
            if isinstance(hv, str) and (_should_mask_header_key(hk) or len(hv) > 24):
                headers[hk] = _mask_sensitive_string(hv)
    env = out.get("env")
    if isinstance(env, dict):
        for ek, ev in list(env.items()):
            if isinstance(ev, str) and ev:
                env[ek] = _mask_sensitive_string(ev)
    oauth = out.get("oauth")
    if isinstance(oauth, dict) and isinstance(oauth.get("client_secret"), str):
        cs = oauth["client_secret"]
        if isinstance(cs, str) and cs:
            oauth["client_secret"] = _mask_sensitive_string(cs)
    return out


def _normalize_server_payload(raw: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {}
    for k, v in raw.items():
        if k in _ALLOWED_KEYS:
            body[k] = v
    return body


def _validate_transport(body: dict[str, Any]) -> None:
    command = body.get("command")
    url = body.get("url")
    has_cmd = isinstance(command, str) and command.strip()
    has_url = isinstance(url, str) and url.strip()
    if has_cmd and has_url:
        raise HTTPException(
            status_code=400,
            detail="Specify either command (stdio) or url (HTTP), not both",
        )
    if not has_cmd and not has_url:
        raise HTTPException(
            status_code=400,
            detail="Either command or url is required",
        )


def _require_valid_name(name: str) -> None:
    if not name or not _NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid server name")


@router.get("/servers")
async def list_mcp_servers() -> dict[str, Any]:
    from hermes_cli.mcp_config import _get_mcp_servers

    servers = _get_mcp_servers()
    rows = [
        {"name": n, "config": _sanitize_mcp_server_config(c)}
        for n, c in sorted(servers.items())
    ]
    return {"servers": rows, "reload_hint": _RELOAD_HINT}


@router.get("/servers/{name}")
async def get_mcp_server(name: str) -> dict[str, Any]:
    _require_valid_name(name)
    from hermes_cli.mcp_config import _get_mcp_servers

    cfg = _get_mcp_servers().get(name)
    if not cfg:
        raise HTTPException(status_code=404, detail="Server not found")
    return {"name": name, "config": _sanitize_mcp_server_config(cfg)}


@router.put("/servers/{name}")
async def put_mcp_server(name: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    _require_valid_name(name)
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")
    body = _normalize_server_payload(body)
    _validate_transport(body)
    from hermes_cli.mcp_config import _save_mcp_server

    _save_mcp_server(name, body)
    return {"ok": True, "name": name, "reload_hint": _RELOAD_HINT}


@router.delete("/servers/{name}")
async def delete_mcp_server(name: str) -> dict[str, Any]:
    _require_valid_name(name)
    from hermes_cli.mcp_config import _remove_mcp_server

    if not _remove_mcp_server(name):
        raise HTTPException(status_code=404, detail="Server not found")
    return {"ok": True, "name": name}


@router.post("/servers/{name}/test")
async def post_mcp_server_test(name: str) -> dict[str, Any]:
    _require_valid_name(name)
    from hermes_cli.mcp_config import _get_mcp_servers, _probe_single_server

    servers = _get_mcp_servers()
    cfg = servers.get(name)
    if not cfg:
        raise HTTPException(status_code=404, detail="Server not found")
    if not _parse_boolish(cfg.get("enabled", True), default=True):
        raise HTTPException(status_code=400, detail="Server is disabled")
    connect_timeout = float(cfg.get("connect_timeout", 30) or 30)
    try:
        tools = await asyncio.to_thread(
            _probe_single_server, name, cfg, connect_timeout
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "ok": True,
        "tools": [{"name": t[0], "description": t[1]} for t in tools],
        "elapsed_ms": None,
    }


@router.post("/servers/{name}/oauth-login")
async def post_mcp_server_oauth_login(name: str) -> dict[str, Any]:
    _require_valid_name(name)
    from hermes_cli.mcp_config import _get_mcp_servers, _probe_single_server

    servers = _get_mcp_servers()
    cfg = servers.get(name)
    if not cfg:
        raise HTTPException(status_code=404, detail="Server not found")
    if not cfg.get("url"):
        raise HTTPException(
            status_code=400,
            detail="OAuth applies to HTTP servers only",
        )
    if str(cfg.get("auth", "")).lower() != "oauth":
        raise HTTPException(
            status_code=400,
            detail="Server is not configured with auth: oauth",
        )
    try:
        from tools.mcp_oauth_manager import get_manager

        get_manager().remove(name)
    except Exception:
        pass
    connect_timeout = float(cfg.get("connect_timeout", 30) or 30)
    try:
        tools = await asyncio.to_thread(
            _probe_single_server, name, cfg, connect_timeout
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "ok": True,
        "message": "OAuth session updated.",
        "tool_count": len(tools),
    }


def _parse_boolish(val: Any, *, default: bool = True) -> bool:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    s = str(val).strip().lower()
    if s in ("0", "false", "no", "off", ""):
        return False
    if s in ("1", "true", "yes", "on"):
        return True
    return default


def _resolve_mcp_parse_llm() -> tuple[str, str, str, float, str]:
    """Return (base_url_with_v1, api_key, model, timeout, source_label)."""
    from hermes_cli.config import get_env_value, load_config

    cfg = load_config() or {}
    aux_root = cfg.get("auxiliary")
    aux = aux_root.get("mcp") if isinstance(aux_root, dict) else None
    if not isinstance(aux, dict):
        aux = {}

    api_key = (
        str(aux.get("api_key") or "").strip()
        or (get_env_value("OPENAI_API_KEY") or "")
        or os.getenv("OPENAI_API_KEY", "")
    ).strip()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="No API key for MCP parse: set OPENAI_API_KEY or auxiliary.mcp.api_key",
        )

    base = (
        str(aux.get("base_url") or "").strip()
        or (get_env_value("OPENAI_BASE_URL") or "")
        or os.getenv("OPENAI_BASE_URL", "")
        or "https://api.openai.com/v1"
    ).strip().rstrip("/")
    if not base.endswith("/v1"):
        base = f"{base}/v1"

    model = str(aux.get("model") or "").strip()
    src = "auxiliary.mcp"
    if not model:
        model = (get_env_value("OPENAI_MODEL") or os.getenv("OPENAI_MODEL", "")).strip()
        src = "OPENAI_MODEL"
    if not model:
        model = "gpt-4o-mini"
        src = "default(gpt-4o-mini)"

    timeout = float(aux.get("timeout") or 45)
    timeout = max(5.0, min(timeout, 120.0))
    return base, api_key, model, timeout, src


def _extract_json_object(text: str) -> dict[str, Any]:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s*```\s*$", "", t)
    try:
        obj = json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", t)
        if not m:
            raise
        obj = json.loads(m.group(0))
    if not isinstance(obj, dict):
        raise ValueError("LLM output is not a JSON object")
    return obj


def _normalize_llm_parse(obj: dict[str, Any]) -> dict[str, Any]:
    rec = str(obj.get("recommended_transport") or "unclear").lower().strip()
    if rec not in ("stdio", "http", "unclear"):
        rec = "unclear"
    conf = str(obj.get("confidence") or "low").lower().strip()
    if conf not in ("high", "medium", "low"):
        conf = "low"
    name_sug = str(obj.get("server_name_suggestion") or "").strip()
    if name_sug and not _NAME_RE.match(name_sug):
        name_sug = ""

    stdio_raw = obj.get("stdio") if isinstance(obj.get("stdio"), dict) else {}
    cmd = str(stdio_raw.get("command") or "").strip()
    args_raw = stdio_raw.get("args")
    args: list[str] = []
    if isinstance(args_raw, list):
        for a in args_raw:
            if isinstance(a, (str, int, float)):
                args.append(str(a))

    http_raw = obj.get("http") if isinstance(obj.get("http"), dict) else {}
    url = str(http_raw.get("url") or "").strip()
    headers_out: dict[str, str] = {}
    hdr = http_raw.get("headers")
    if isinstance(hdr, dict):
        for k, v in hdr.items():
            if isinstance(k, str) and isinstance(v, (str, int, float)):
                headers_out[k] = str(v)
    auth = str(http_raw.get("auth") or "").strip()

    notes = str(obj.get("notes") or "").strip()
    if len(notes) > 500:
        notes = notes[:497] + "..."

    return {
        "recommended_transport": rec,
        "confidence": conf,
        "server_name_suggestion": name_sug,
        "stdio": {"command": cmd, "args": args},
        "http": {"url": url, "headers": headers_out, "auth": auth},
        "notes": notes,
    }


def _call_openai_parse_sync(raw: str) -> dict[str, Any]:
    base, api_key, model, timeout, src = _resolve_mcp_parse_llm()
    endpoint = f"{base.rstrip('/')}/chat/completions"
    user_msg = _USER_PARSE_TEMPLATE.format(raw=raw)
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _PARSE_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    with httpx.Client(timeout=httpx.Timeout(timeout, connect=15.0)) as client:
        r = client.post(endpoint, headers=headers, json=payload)
        if r.status_code == 400 and "response_format" in (r.text or "").lower():
            payload.pop("response_format", None)
            r = client.post(endpoint, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"Unexpected chat response shape: {data!r}") from exc
    if not isinstance(content, str):
        raise ValueError("Empty model content")
    parsed = _extract_json_object(content)
    out = _normalize_llm_parse(parsed)
    out["model_used"] = model
    out["credential_source"] = src
    return out


def _llm_parse_mcp_install_sync(raw: str) -> dict[str, Any]:
    return _call_openai_parse_sync(raw)


@router.post("/parse-install")
async def post_mcp_parse_install(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """LLM-assisted parse of pasted install commands / docs into stdio + HTTP drafts."""
    raw = body.get("raw")
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(status_code=400, detail="JSON body must include non-empty string field 'raw'")
    raw = raw.strip()
    if len(raw) > _MCP_PARSE_RAW_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"Field raw too long (max {_MCP_PARSE_RAW_MAX} characters)",
        )
    try:
        return await asyncio.to_thread(_llm_parse_mcp_install_sync, raw)
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text if exc.response is not None else str(exc)
        logger.warning("MCP parse-install upstream HTTP error: %s", detail[:500])
        raise HTTPException(status_code=502, detail=f"Upstream LLM error: {detail[:2000]}") from exc
    except Exception as exc:
        logger.warning("MCP parse-install failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
