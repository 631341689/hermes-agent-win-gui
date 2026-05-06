"""Optional MinerU PDF → Markdown for knowledge ``raw/`` uploads.

MinerU lives in a separate checkout (heavy deps: ``mineru[pipeline]`` etc.).
Configure ``knowledge.mineru.root`` to the directory that contains the
``mineru`` package (e.g. ``.../MinerU-master/MinerU-master``), or set
``HERMES_MINERU_ROOT``. Public surfaces upstream:

- **CLI**: ``mineru`` → ``mineru.cli.client:main``
- **HTTP**: ``mineru-api`` → FastAPI (e.g. ``POST /file_parse``, ``POST /tasks``)
- **Python**: ``mineru.cli.common.do_parse`` (used here in-process when root is set)

**Weights (layout/OCR/VLM)**: ``MINERU_MODEL_SOURCE`` comes from ``knowledge.mineru.model_source``
unless you set ``knowledge.mineru.local_models`` (or ``HERMES_MINERU_LOCAL_*`` env vars) to
absolute directories of **pre-downloaded** trees — then Hermes forces ``local`` for that
conversion and injects MinerU's ``models-dir`` (no network). Same layout as ``~/mineru.json``.
When Hermes does not set ``local_models``, it can **reuse** existing directories from the
user's MinerU config file (``~/mineru.json`` or ``MINERU_TOOLS_CONFIG_JSON``) if
``auto_local_models_from_mineru_json`` is true — so a successful ``mineru-models-download``
run is picked up without duplicating paths in ``config.yaml``.

**LLM title aid (optional)**: when ``llm_aided_use_hermes_openai`` is true, credentials
come from ``knowledge.mineru.llm_aided_model.provider`` — ``openai`` uses
``OPENAI_API_KEY`` / ``OPENAI_BASE_URL``; ``deepseek`` uses ``DEEPSEEK_API_KEY`` /
``DEEPSEEK_BASE_URL``. The model id is ``llm_aided_model.default``, or the top-level
``model`` string when ``default`` is empty (independent of the main chat ``model`` block).

See upstream ``MinerU-master`` README / ``pyproject.toml`` ``[project.scripts]``.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterator

_log = logging.getLogger(__name__)

# ``phase`` is a stable machine key; ``data`` is JSON-serializable metadata for dashboards / SSE.
MineruUploadProgress = Callable[[str, dict[str, Any]], None]


def _mineru_progress(cb: MineruUploadProgress | None, phase: str, **data: Any) -> None:
    if cb:
        cb(phase, data)


def _mineru_root_from_config() -> str:
    from hermes_cli.config import load_config

    env = (os.environ.get("HERMES_MINERU_ROOT") or "").strip()
    if env:
        return env
    cfg = load_config()
    k = cfg.get("knowledge") or {}
    m = k.get("mineru") or {}
    return str(m.get("root") or "").strip()


def _top_level_chat_model_id(cfg: dict[str, Any]) -> str:
    """Resolve Hermes primary ``model`` setting (string or ``{ default: ... }``)."""
    raw = cfg.get("model")
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, dict):
        return str(raw.get("default") or raw.get("name") or "").strip()
    return ""


def _mineru_json_config_path() -> Path:
    name = (os.environ.get("MINERU_TOOLS_CONFIG_JSON") or "mineru.json").strip() or "mineru.json"
    if os.path.isabs(name):
        return Path(name)
    return Path.home() / name


def _discover_local_models_from_user_mineru_json() -> dict[str, str]:
    """Return ``pipeline`` / ``vlm`` roots from ``~/mineru.json`` ``models-dir`` if directories exist."""
    cfg_path = _mineru_json_config_path()
    if not cfg_path.is_file():
        return {}
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    md = data.get("models-dir")
    if not isinstance(md, dict):
        return {}
    out: dict[str, str] = {}
    for k in ("pipeline", "vlm"):
        v = str(md.get(k) or "").strip()
        if not v:
            continue
        try:
            rp = str(Path(v).expanduser().resolve())
        except OSError:
            rp = str(Path(v).expanduser())
        if Path(rp).is_dir():
            out[k] = rp
    return out


def _merge_local_models(mineru: dict[str, Any]) -> dict[str, str]:
    """Merge ``knowledge.mineru.local_models`` with ``HERMES_MINERU_LOCAL_*`` (env wins)."""
    out: dict[str, str] = {}
    raw = mineru.get("local_models")
    if isinstance(raw, dict):
        for k in ("pipeline", "vlm"):
            v = str(raw.get(k) or "").strip()
            if v:
                out[k] = v
    pl = (os.environ.get("HERMES_MINERU_LOCAL_PIPELINE") or "").strip()
    vl = (os.environ.get("HERMES_MINERU_LOCAL_VLM") or "").strip()
    if pl:
        out["pipeline"] = pl
    if vl:
        out["vlm"] = vl
    resolved: dict[str, str] = {}
    for k, v in out.items():
        try:
            resolved[k] = str(Path(v).expanduser().resolve())
        except OSError:
            resolved[k] = str(Path(v).expanduser())
    return resolved


def _prepare_local_models_override(paths: dict[str, str], backend: str) -> dict[str, str] | None:
    """Return MinerU ``models-dir`` dict for ``get_local_models_dir`` patch, or ``None``."""
    if not paths:
        return None
    b = (backend or "pipeline").strip().lower()
    need_pipeline = b.startswith("pipeline") or b.startswith("hybrid")
    need_vlm = b.startswith("vlm") or b.startswith("hybrid")
    pl = paths.get("pipeline", "").strip()
    vl = paths.get("vlm", "").strip()
    if need_pipeline and not pl:
        raise ValueError(
            "MinerU local weights: set knowledge.mineru.local_models.pipeline or "
            "HERMES_MINERU_LOCAL_PIPELINE to your PDF-Extract-Kit (pipeline) directory",
        )
    if need_vlm and not vl:
        raise ValueError(
            "MinerU local weights: set knowledge.mineru.local_models.vlm or "
            "HERMES_MINERU_LOCAL_VLM to your VLM model directory",
        )
    for label, p in (("pipeline", pl), ("vlm", vl)):
        if not p:
            continue
        pp = Path(p)
        if not pp.is_dir():
            raise ValueError(f"MinerU local_models.{label} is not an existing directory: {p}")
    return {"pipeline": pl, "vlm": vl}


def _normalize_mineru_llm_aided_model(mineru: dict[str, Any]) -> tuple[str, str]:
    """Return ``(provider, model_id)`` for MinerU ``title_aided`` (OpenAI-compatible call)."""
    raw = mineru.get("llm_aided_model")
    if isinstance(raw, str):
        return ("openai", raw.strip())
    if isinstance(raw, dict):
        p = str(raw.get("provider") or "openai").strip().lower() or "openai"
        d = str(raw.get("default") or "").strip()
        return (p, d)
    return ("openai", "")


def _mineru_options() -> dict[str, Any]:
    from hermes_cli.config import load_config

    cfg = load_config()
    k = cfg.get("knowledge") or {}
    m = k.get("mineru") or {}
    prov, mid = _normalize_mineru_llm_aided_model(m)
    local_models = _merge_local_models(m)
    if bool(m.get("auto_local_models_from_mineru_json", True)):
        for k, v in _discover_local_models_from_user_mineru_json().items():
            if k not in local_models and v:
                local_models[k] = v
    return {
        "enabled": bool(m.get("enabled")),
        "backend": str(m.get("backend") or "pipeline").strip() or "pipeline",
        "parse_method": str(m.get("parse_method") or "auto").strip() or "auto",
        "lang": str(m.get("lang") or "ch").strip() or "ch",
        "model_source": str(m.get("model_source") or "huggingface").strip().lower() or "huggingface",
        "local_models": local_models,
        "llm_aided_use_hermes_openai": bool(m.get("llm_aided_use_hermes_openai", True)),
        "llm_aided_provider": prov,
        "llm_aided_model_id": mid,
    }


def _mineru_title_aid_credentials(provider: str) -> tuple[str, str] | None:
    """``(api_key, base_url)`` for OpenAI-compatible MinerU client, or ``None`` if no key."""
    from hermes_cli.config import get_env_value

    p = (provider or "openai").strip().lower()
    if p == "deepseek":
        api_key = (get_env_value("DEEPSEEK_API_KEY") or "").strip()
        base = (get_env_value("DEEPSEEK_BASE_URL") or "").strip().rstrip("/")
        if not base:
            base = "https://api.deepseek.com/v1"
    elif p == "openai":
        api_key = (get_env_value("OPENAI_API_KEY") or "").strip()
        base = (get_env_value("OPENAI_BASE_URL") or "").strip().rstrip("/")
        if not base:
            base = "https://api.openai.com/v1"
    else:
        _log.warning(
            "knowledge.mineru.llm_aided_model.provider=%r unsupported; using OPENAI_* env vars",
            p,
        )
        api_key = (get_env_value("OPENAI_API_KEY") or "").strip()
        base = (get_env_value("OPENAI_BASE_URL") or "").strip().rstrip("/")
        if not base:
            base = "https://api.openai.com/v1"
    if not api_key:
        return None
    return (api_key, base)


def _hermes_llm_aided_config_for_mineru(opts: dict[str, Any]) -> dict[str, Any] | None:
    """Return ``llm-aided-config`` shape for MinerU when using Hermes env credentials."""
    if not opts.get("llm_aided_use_hermes_openai", True):
        return None
    from hermes_cli.config import load_config

    creds = _mineru_title_aid_credentials(str(opts.get("llm_aided_provider") or "openai"))
    if creds is None:
        return None
    api_key, base = creds
    cfg = load_config()
    model = str(opts.get("llm_aided_model_id") or "").strip() or _top_level_chat_model_id(cfg)
    if not model:
        _log.info(
            "MinerU LLM title aid skipped: set knowledge.mineru.llm_aided_model.default "
            "or top-level model / model.default in config.yaml",
        )
        return None
    return {
        "title_aided": {
            "api_key": api_key,
            "base_url": base,
            "model": model,
            "enable": True,
        }
    }


@contextlib.contextmanager
def _mineru_runtime_context(
    opts: dict[str, Any],
    hermes_llm: dict[str, Any] | None,
    models_dir_override: dict[str, str] | None = None,
) -> Iterator[None]:
    """Set ``MINERU_MODEL_SOURCE``; optionally patch ``get_llm_aided_config`` / ``get_local_models_dir``."""
    prev_ms = os.environ.get("MINERU_MODEL_SOURCE")
    force_local = bool(models_dir_override)
    if force_local:
        os.environ["MINERU_MODEL_SOURCE"] = "local"
        _log.info("MinerU using pre-downloaded local weights (Hermes local_models / HERMES_MINERU_LOCAL_*)")
    else:
        src = opts.get("model_source") or "huggingface"
        if src in ("huggingface", "modelscope", "local"):
            os.environ["MINERU_MODEL_SOURCE"] = src

    _mcr: Any = None
    _orig_ga: Callable[..., Any] | None = None
    _orig_gld: Callable[..., Any] | None = None

    if hermes_llm is not None or models_dir_override is not None:
        import mineru.utils.config_reader as _mcr  # type: ignore[no-redef]

        if hermes_llm is not None:
            _orig_ga = _mcr.get_llm_aided_config

            def _merged() -> Any:
                return hermes_llm

            _mcr.get_llm_aided_config = _merged  # type: ignore[method-assign]
        if models_dir_override is not None:
            _orig_gld = _mcr.get_local_models_dir

            def _local_dir() -> Any:
                return models_dir_override

            _mcr.get_local_models_dir = _local_dir  # type: ignore[method-assign]
    try:
        yield
    finally:
        if _mcr is not None:
            if _orig_ga is not None:
                _mcr.get_llm_aided_config = _orig_ga  # type: ignore[method-assign]
            if _orig_gld is not None:
                _mcr.get_local_models_dir = _orig_gld  # type: ignore[method-assign]
        if prev_ms is None:
            os.environ.pop("MINERU_MODEL_SOURCE", None)
        else:
            os.environ["MINERU_MODEL_SOURCE"] = prev_ms


def _inject_mineru_sys_path(root: Path) -> None:
    s = str(root.resolve())
    if s not in sys.path:
        sys.path.insert(0, s)


def _rewrite_md_image_refs(md: str, stem: str) -> str:
    """Point ``images/...`` at ``{stem}_mineru_images/...`` (sibling of the .md)."""
    folder = f"{stem}_mineru_images"
    out = md
    out = out.replace("](./images/", f"](./{folder}/")
    out = out.replace("](images/", f"]({folder}/")
    out = re.sub(
        r"!\[([^\]]*)\]\(images/",
        rf"![\1]({folder}/",
        out,
    )
    return out


def try_convert_uploaded_pdf(
    pdf_path: Path,
    *,
    progress: MineruUploadProgress | None = None,
) -> bool:
    """If MinerU is enabled and importable, convert *pdf_path* to Markdown next to it.

    On success: writes ``<stem>.md``, copies ``images/`` to ``<stem>_mineru_images/``,
    deletes the PDF. On failure: leaves the PDF unchanged and logs.

    *progress* (optional) receives ``(phase, data)`` for dashboard SSE — phases are
    stable lowercase_snake strings (e.g. ``mineru_parsing`` during ``do_parse``, when
    weights may download on first run).

    Returns ``True`` if the PDF was replaced by Markdown.
    """
    opts = _mineru_options()
    if not opts["enabled"]:
        _mineru_progress(progress, "skip_mineru_disabled")
        return False
    root_s = _mineru_root_from_config()
    if not root_s:
        _log.info("MinerU enabled but knowledge.mineru.root / HERMES_MINERU_ROOT is empty — skipping PDF conversion")
        _mineru_progress(progress, "skip_mineru_no_root")
        return False
    root = Path(root_s)
    if not (root / "mineru").is_dir():
        _log.warning("MinerU root invalid (no mineru package dir): %s", root)
        _mineru_progress(progress, "skip_mineru_bad_root", root=str(root))
        return False

    stem = pdf_path.stem
    if not pdf_path.is_file() or pdf_path.suffix.lower() != ".pdf":
        _mineru_progress(progress, "skip_non_pdf")
        return False

    try:
        pdf_bytes = pdf_path.read_bytes()
    except OSError as exc:
        _log.warning("Could not read PDF for MinerU: %s", exc)
        _mineru_progress(progress, "read_error", error=str(exc))
        return False

    tmp = Path(tempfile.mkdtemp(prefix="hermes-mineru-"))
    try:
        _inject_mineru_sys_path(root)
        try:
            from mineru.cli.common import do_parse  # type: ignore[import-untyped]
            from mineru.cli.output_paths import resolve_parse_dir  # type: ignore[import-untyped]
        except ImportError as exc:
            _log.warning("MinerU import failed (%s). Install mineru in this venv or fix knowledge.mineru.root.", exc)
            _mineru_progress(progress, "mineru_import_failed", error=str(exc))
            return False

        backend = opts["backend"]
        parse_method = opts["parse_method"]
        lang = opts["lang"]

        _mineru_progress(
            progress,
            "mineru_prepare",
            backend=backend,
            parse_method=parse_method,
            lang=lang,
        )

        hermes_llm = _hermes_llm_aided_config_for_mineru(opts)

        try:
            models_override = _prepare_local_models_override(
                opts.get("local_models") or {},
                backend,
            )
        except ValueError as exc:
            _log.warning("%s", exc)
            _mineru_progress(progress, "mineru_local_models_invalid", error=str(exc))
            return False

        _mineru_progress(
            progress,
            "mineru_parsing",
            backend=backend,
            parse_method=parse_method,
            first_run_models_hint=not bool(models_override),
            local_weights=bool(models_override),
        )
        with _mineru_runtime_context(opts, hermes_llm, models_override):
            do_parse(
                str(tmp),
                [stem],
                [pdf_bytes],
                [lang],
                backend=backend,
                parse_method=parse_method,
                f_draw_layout_bbox=False,
                f_draw_span_bbox=False,
                f_dump_md=True,
                f_dump_middle_json=False,
                f_dump_model_output=False,
                f_dump_orig_pdf=False,
                f_dump_content_list=False,
            )

        _mineru_progress(progress, "mineru_parse_done")

        parse_dir = resolve_parse_dir(
            tmp,
            stem,
            backend,
            parse_method,
            is_office=False,
            allow_office_fallback=True,
        )
        md_src = parse_dir / f"{stem}.md"
        if not md_src.is_file():
            _log.warning("MinerU finished but expected markdown missing: %s", md_src)
            _mineru_progress(progress, "mineru_missing_md", expected=str(md_src))
            return False
        md_text = md_src.read_text(encoding="utf-8", errors="replace")
        img_src = parse_dir / "images"
        raw_dir = pdf_path.parent
        _mineru_progress(progress, "mineru_writing")
        if img_src.is_dir():
            img_dst = raw_dir / f"{stem}_mineru_images"
            if img_dst.exists():
                shutil.rmtree(img_dst, ignore_errors=True)
            shutil.copytree(img_src, img_dst)
            md_text = _rewrite_md_image_refs(md_text, stem)

        md_out = raw_dir / f"{stem}.md"
        md_out.write_text(md_text, encoding="utf-8")
        pdf_path.unlink(missing_ok=True)
        _log.info("MinerU converted PDF to markdown: %s", md_out.name)
        _mineru_progress(progress, "mineru_complete", converted=True)
        return True
    except Exception as exc:
        _log.exception("MinerU PDF conversion failed for %s", pdf_path.name)
        _mineru_progress(progress, "mineru_error", error=f"{type(exc).__name__}: {exc}")
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
