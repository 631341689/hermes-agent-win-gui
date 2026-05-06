#!/usr/bin/env python3
"""Smoke-test Hermes Dashboard knowledge upload (PDF) + SSE progress.

Uses Starlette TestClient (no need to run ``hermes dashboard``).

Prerequisites for **MinerU** PDF→Markdown on this machine:
  - Working ``mineru`` imports (often needs a healthy ``torch`` / ``onnxruntime``
    stack on Windows — fix DLL errors first).
  - ``knowledge.mineru.enabled: true`` and valid ``knowledge.mineru.root`` in the
    temp ``HERMES_HOME`` used below (or set env ``HERMES_MINERU_ROOT``).

Default PDF: ``docs/hermes-kanban-v1-spec.pdf`` (fetch from upstream with curl if missing).

Usage (repo root, venv activated)::

    python scripts/smoke_knowledge_pdf_upload.py
    python scripts/smoke_knowledge_pdf_upload.py --pdf path/to/file.pdf --mineru-root path/to/MinerU-master/MinerU-master
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path


def _parse_sse(body: str) -> list[dict]:
    events: list[dict] = []
    for block in body.split("\n\n"):
        for line in block.split("\n"):
            line = line.strip("\r")
            if line.startswith("data: "):
                try:
                    events.append(json.loads(line[6:]))
                except json.JSONDecodeError:
                    pass
    return events


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--pdf",
        type=Path,
        default=Path("docs/hermes-kanban-v1-spec.pdf"),
        help="PDF to upload",
    )
    repo = Path(__file__).resolve().parents[1]
    default_mineru = repo / "MinerU-master" / "MinerU-master"
    ap.add_argument(
        "--mineru-root",
        type=Path,
        default=default_mineru if default_mineru.is_dir() else None,
        help="Directory containing the ``mineru`` package (default: bundled MinerU-master if present)",
    )
    ap.add_argument(
        "--enable-mineru",
        action="store_true",
        help="Write knowledge.mineru.enabled=true into temp config (needs working MinerU)",
    )
    args = ap.parse_args()

    if not args.pdf.is_file():
        print(f"PDF not found: {args.pdf.resolve()}")
        return 2

    try:
        from starlette.testclient import TestClient
    except ImportError:
        print("Install fastapi/starlette (web extra) for TestClient")
        return 2

    root = Path(tempfile.mkdtemp(prefix="hermes-smoke-kb-"))
    home = root / ".hermes"
    home.mkdir(parents=True)

    mineru_root = ""
    if args.mineru_root and args.mineru_root.is_dir():
        mineru_root = str(args.mineru_root.resolve())
    elif os.environ.get("HERMES_MINERU_ROOT"):
        mineru_root = os.environ["HERMES_MINERU_ROOT"].strip()

    cfg_lines = [
        "knowledge:",
        "  enabled: true",
        "  mineru:",
        f"    enabled: {str(args.enable_mineru).lower()}",
        f'    root: "{mineru_root.replace(chr(92), "/")}"' if mineru_root else "    root: \"\"",
        "    backend: pipeline",
        "    parse_method: auto",
        "    lang: ch",
    ]
    (home / "config.yaml").write_text("\n".join(cfg_lines) + "\n", encoding="utf-8")

    os.environ["HERMES_HOME"] = str(home)

    import hermes_state
    from hermes_constants import get_hermes_home
    from hermes_cli.knowledge_registry import registry_db_path
    from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN

    hermes_state.DEFAULT_DB_PATH = get_hermes_home() / "state.db"
    p = registry_db_path()
    if p.exists():
        p.unlink()

    client = TestClient(app)
    client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN

    r = client.post("/api/knowledge/bases", json={"name": "smoke-pdf", "mode": "vector"})
    assert r.status_code == 200, r.text
    kb_id = r.json()["base"]["id"]

    with open(args.pdf, "rb") as f:
        files = {"file": (args.pdf.name, f, "application/pdf")}
        with client.stream(
            "POST",
            f"/api/knowledge/bases/{kb_id}/upload?stream=1",
            files=files,
        ) as resp:
            assert resp.status_code == 200, resp.text
            body = resp.read().decode("utf-8")

    events = _parse_sse(body)
    print("SSE events:", len(events))
    for ev in events:
        print(" ", ev.get("event"), ev.get("phase", ""))
    finals = [e for e in events if e.get("event") == "final"]
    assert finals, "no final event"
    fin = finals[-1]
    print("final:", json.dumps(fin, ensure_ascii=False, indent=2))
    raw_dir = home / "knowledge" / "bases" / kb_id / "raw"
    print("raw dir listing:", [p.name for p in sorted(raw_dir.glob("*"))] if raw_dir.is_dir() else "(missing)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
