#!/usr/bin/env python3
"""
ZIP uploads for Dashboard skills install — parse archives into SkillBundle and run the hub pipeline.

Security: member paths validated like ClawHub ZIP downloads; aggregate caps reduce zip-bomb risk.
"""

from __future__ import annotations

import io
import logging
import re
import shutil
import zipfile
from typing import Any, Dict, List, Union

import yaml

from tools.skills_hub import (
    SkillBundle,
    HubLockFile,
    SKILLS_DIR,
    append_audit_log,
    ensure_hub_dirs,
    install_from_quarantine,
    quarantine_bundle,
    _validate_bundle_rel_path,
    _validate_category_name,
    _validate_skill_name,
)
from tools.skills_guard import format_scan_report, scan_skill, should_allow_install

logger = logging.getLogger(__name__)


def list_skill_install_categories() -> List[str]:
    """
    Subdirectory names under ``SKILLS_DIR`` that behave like **category buckets**
    (same heuristic as CLI ``_existing_categories``): not a top-level skill folder
    (no ``SKILL.md`` directly in that subdir), but contains at least one nested
    ``SKILL.md``. Used to populate Dashboard ZIP import category dropdown.

    Install layout: ``skills/<category>/<skill_name>/`` when category is set, else
    ``skills/<skill_name>/``.
    """
    out: List[str] = []
    try:
        for entry in SKILLS_DIR.iterdir():
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            if (entry / "SKILL.md").exists():
                continue
            try:
                if any(entry.rglob("SKILL.md")):
                    out.append(entry.name)
            except OSError:
                continue
    except (FileNotFoundError, OSError):
        return []
    return sorted(set(out))


# Upload / extraction limits (dashboard-only — tweak if needed).
MAX_ZIP_BYTES = 12 * 1024 * 1024  # 12 MiB compressed
MAX_ZIP_MEMBERS = 600
MAX_TOTAL_UNCOMPRESSED = 48 * 1024 * 1024  # sum of declared uncompressed sizes
MAX_SINGLE_MEMBER_BYTES = 24 * 1024 * 1024

_VALID_SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


def _parse_frontmatter_quick(content: str) -> Dict[str, Any]:
    """YAML frontmatter from SKILL.md (same idea as GitHubSource._parse_frontmatter_quick)."""
    if not content.startswith("---"):
        return {}
    match = re.search(r"\n---\s*\n", content[3:])
    if not match:
        return {}
    yaml_text = content[3 : match.start() + 3]
    try:
        parsed = yaml.safe_load(yaml_text)
        return parsed if isinstance(parsed, dict) else {}
    except yaml.YAMLError:
        return {}


def _normalize_zip_member_name(raw: str) -> str:
    s = raw.replace("\\", "/").strip()
    while "//" in s:
        s = s.replace("//", "/")
    # Strip leading ./ segments
    parts = [p for p in s.split("/") if p and p != "."]
    if any(p == ".." for p in parts):
        raise ValueError(f"Unsafe ZIP path: {raw!r}")
    return "/".join(parts)


def _skill_roots_from_paths(paths: List[str]) -> List[str]:
    roots: List[str] = []
    for p in paths:
        if p == "SKILL.md":
            roots.append("")
        elif p.endswith("/SKILL.md"):
            roots.append(p[: -len("/SKILL.md")])
    return roots


def extract_skill_files_from_zip(zip_bytes: bytes) -> Dict[str, Union[str, bytes]]:
    """
    Extract normalized skill-relative paths from a ZIP byte blob.

    Raises:
        ValueError: invalid archive, unsafe paths, layout violations, or limits exceeded.
    """
    if len(zip_bytes) > MAX_ZIP_BYTES:
        raise ValueError(
            f"ZIP too large ({len(zip_bytes)} bytes); max {MAX_ZIP_BYTES // (1024 * 1024)} MiB."
        )

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise ValueError("Invalid or corrupted ZIP file.") from exc

    try:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > MAX_ZIP_MEMBERS:
            raise ValueError(f"Too many ZIP members ({len(infos)}); max {MAX_ZIP_MEMBERS}.")

        total_unc = 0
        raw_paths: List[str] = []
        zip_name_by_norm: Dict[str, str] = {}

        for info in infos:
            total_unc += int(info.file_size)
            if total_unc > MAX_TOTAL_UNCOMPRESSED:
                raise ValueError("ZIP declares excessive uncompressed size (possible zip bomb).")
            if info.file_size > MAX_SINGLE_MEMBER_BYTES:
                raise ValueError(f"ZIP member too large: {info.filename!r}")

            norm = _normalize_zip_member_name(info.filename)
            if not norm:
                continue
            try:
                safe = _validate_bundle_rel_path(norm)
            except ValueError:
                raise ValueError(f"Unsafe ZIP member path: {info.filename!r}") from None

            if safe in zip_name_by_norm:
                raise ValueError(f"Duplicate path after normalization: {safe!r}")
            zip_name_by_norm[safe] = info.filename
            raw_paths.append(safe)

        if not raw_paths:
            raise ValueError("ZIP contains no files.")

        roots = _skill_roots_from_paths(raw_paths)
        unique_roots = sorted(set(roots))
        if not unique_roots:
            raise ValueError("ZIP must contain exactly one SKILL.md at the skill root.")
        if len(unique_roots) > 1:
            raise ValueError(
                "ZIP must contain only one skill (single SKILL.md tree); "
                f"found multiple roots: {unique_roots!r}"
            )

        root_prefix = unique_roots[0]

        def read_norm(norm_key: str) -> Union[str, bytes]:
            arc = zip_name_by_norm[norm_key]
            data = zf.read(arc)
            try:
                return data.decode("utf-8")
            except UnicodeDecodeError:
                return data

        if root_prefix:
            prefix = root_prefix + "/"
            out: Dict[str, Union[str, bytes]] = {}
            for p in raw_paths:
                if not p.startswith(prefix):
                    raise ValueError(
                        f"File {p!r} is outside skill folder {root_prefix!r} (expected prefix {prefix!r})."
                    )
                rel = p[len(prefix) :]
                if not rel:
                    continue
                try:
                    rel_safe = _validate_bundle_rel_path(rel)
                except ValueError as exc:
                    raise ValueError(f"Invalid path after strip: {rel!r}") from exc
                out[rel_safe] = read_norm(p)
        else:
            out = {}
            for p in raw_paths:
                out[_validate_bundle_rel_path(p)] = read_norm(p)

        if "SKILL.md" not in out:
            raise ValueError("After normalization, SKILL.md is missing from the skill bundle.")

        return out
    finally:
        try:
            zf.close()
        except Exception:
            pass


def resolve_install_skill_name(skill_md_text: str, name_override: str) -> str:
    fm = _parse_frontmatter_quick(skill_md_text)
    raw = (name_override or "").strip() or str(fm.get("name") or "").strip()
    if not raw:
        raise ValueError(
            "Skill name missing: add `name:` to SKILL.md YAML frontmatter, "
            "or pass the name field when uploading."
        )
    candidate = raw.lower()
    if not _VALID_SKILL_NAME_RE.match(candidate):
        raise ValueError(
            f"Invalid skill name {raw!r}: use lowercase letters, digits, hyphens, underscores; "
            "must start with a letter."
        )
    return _validate_skill_name(candidate)


def install_skill_zip_archive(
    zip_bytes: bytes,
    *,
    category: str = "",
    name_override: str = "",
    force: bool = False,
    invalidate_cache: bool = True,
) -> Dict[str, Any]:
    """
    Full pipeline: ZIP → SkillBundle → quarantine → scan → optional install.

    Returns a JSON-serializable dict (for Dashboard API). Does not raise for policy blocks —
    returns ok=False with blocked_reason.
    """
    ensure_hub_dirs()

    try:
        files = extract_skill_files_from_zip(zip_bytes)
    except ValueError as exc:
        return {"ok": False, "detail": str(exc), "errors": [str(exc)]}

    skill_md_raw = files["SKILL.md"]
    if isinstance(skill_md_raw, bytes):
        try:
            skill_md_text = skill_md_raw.decode("utf-8")
        except UnicodeDecodeError:
            return {
                "ok": False,
                "detail": "SKILL.md must be UTF-8 text.",
                "errors": ["SKILL.md must be UTF-8 text."],
            }
    else:
        skill_md_text = skill_md_raw

    safe_category = ""
    if category and category.strip():
        try:
            safe_category = _validate_category_name(category.strip())
        except ValueError as exc:
            return {"ok": False, "detail": str(exc), "errors": [str(exc)]}

    try:
        resolved_name = resolve_install_skill_name(skill_md_text, name_override)
    except ValueError as exc:
        return {"ok": False, "detail": str(exc), "errors": [str(exc)]}

    bundle = SkillBundle(
        name=resolved_name,
        files=files,
        source="dashboard-zip",
        identifier="zip:upload",
        trust_level="community",
        metadata={"upload": True},
    )

    lock = HubLockFile()
    existing = lock.get_installed(bundle.name)
    if existing and not force:
        return {
            "ok": False,
            "detail": f"Skill '{bundle.name}' is already installed. Use force to reinstall.",
            "errors": ["already_installed"],
            "installed_path": existing.get("install_path"),
        }

    target_install = (
        SKILLS_DIR / safe_category / bundle.name if safe_category else SKILLS_DIR / bundle.name
    )
    if target_install.exists() and not existing and not force:
        # Folder on disk but not in hub lock (e.g. manual copy)
        return {
            "ok": False,
            "detail": f"Path already exists: {target_install.relative_to(SKILLS_DIR)}. Use force to overwrite.",
            "errors": ["path_exists"],
        }

    try:
        q_path = quarantine_bundle(bundle)
    except ValueError as exc:
        append_audit_log(
            "BLOCKED",
            bundle.name,
            bundle.source,
            bundle.trust_level,
            "invalid_path",
            str(exc),
        )
        return {"ok": False, "detail": str(exc), "errors": [str(exc)]}

    scan_source = "zip:upload"
    result = scan_skill(q_path, source=scan_source)
    scan_summary = {
        "verdict": result.verdict,
        "summary": result.summary,
        "findings_count": len(result.findings),
        "report_lines": format_scan_report(result).splitlines(),
    }

    allowed, reason = should_allow_install(result, force=force)
    if not allowed:
        shutil.rmtree(q_path, ignore_errors=True)
        append_audit_log(
            "BLOCKED",
            bundle.name,
            bundle.source,
            bundle.trust_level,
            result.verdict,
            f"{len(result.findings)}_findings",
        )
        return {
            "ok": False,
            "detail": reason,
            "blocked_reason": reason,
            "scan": scan_summary,
            "errors": ["policy_blocked"],
        }

    try:
        install_dir = install_from_quarantine(q_path, bundle.name, safe_category, bundle, result)
    except ValueError as exc:
        shutil.rmtree(q_path, ignore_errors=True)
        append_audit_log(
            "BLOCKED",
            bundle.name,
            bundle.source,
            bundle.trust_level,
            "invalid_path",
            str(exc),
        )
        return {"ok": False, "detail": str(exc), "errors": [str(exc)], "scan": scan_summary}

    rel_path = str(install_dir.relative_to(SKILLS_DIR)).replace("\\", "/")

    reload_hint = (
        "Skill files are on disk. Start a new chat session or restart the CLI/TUI "
        "if the skill does not appear immediately in the agent context."
    )
    if invalidate_cache:
        try:
            from agent.prompt_builder import clear_skills_system_prompt_cache

            clear_skills_system_prompt_cache(clear_snapshot=True)
            reload_hint = (
                "Prompt cache cleared — the skill should be visible to new turns in this dashboard session; "
                "existing CLI/TUI sessions may still need a restart."
            )
        except Exception:
            pass

    return {
        "ok": True,
        "skill_name": bundle.name,
        "installed_path": rel_path,
        "scan": scan_summary,
        "reload_hint": reload_hint,
    }
