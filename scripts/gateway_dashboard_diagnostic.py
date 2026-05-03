#!/usr/bin/env python3
"""Gateway + Dashboard coexistence diagnostic (read-only for default HERMES_HOME).

Writes a report under repo ``diagnostics/gateway_dashboard_check.log`` and prints
the same to stdout. Does not start/stop the messaging gateway.

Optional: ``--temp-home`` runs an isolated HERMES_HOME and exercises /api/status
with a fake gateway.pid (no long-running gateway).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# Repo root = parent of scripts/
REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "diagnostics"
OUT_FILE = OUT_DIR / "gateway_dashboard_check.log"


def _log(lines: list[str], msg: str) -> None:
    lines.append(msg)
    print(msg, flush=True)


def _read_json(path: Path) -> Any | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        return {"_error": str(exc)}


def _stress_get_running_pid(n: int, lines: list[str]) -> None:
    from gateway.status import get_running_pid

    first = get_running_pid(cleanup_stale=False)
    flips: list[tuple[int, int | None]] = []
    prev: int | None = first
    for i in range(n):
        cur = get_running_pid(cleanup_stale=False)
        if cur != prev:
            flips.append((i, cur))
        prev = cur
        time.sleep(0.02)
    if flips:
        _log(lines, f"  [stress] get_running_pid changed during {n} polls: {flips[:20]}")
    else:
        _log(lines, f"  [stress] stable across {n} polls: {first}")


def _api_status_snapshot(lines: list[str]) -> None:
    os.environ.setdefault("HERMES_WEB_DIST", str(REPO_ROOT / "hermes_cli" / "web_dist"))
    from fastapi.testclient import TestClient
    from hermes_cli import web_server

    # Sync call — TestClient runs the async route
    with TestClient(web_server.app) as client:
        r = client.get("/api/status")
    _log(lines, f"  /api/status HTTP {r.status_code}")
    if r.status_code != 200:
        _log(lines, f"  body: {r.text[:2000]}")
        return
    data = r.json()
    _log(
        lines,
        "  gateway_running={gw} gateway_pid={pid} gateway_state={st}".format(
            gw=data.get("gateway_running"),
            pid=data.get("gateway_pid"),
            st=data.get("gateway_state"),
        ),
    )
    if data.get("gateway_exit_reason"):
        _log(lines, f"  gateway_exit_reason={data.get('gateway_exit_reason')!r}")
    plats = data.get("gateway_platforms") or {}
    if plats:
        for name, info in list(plats.items())[:12]:
            _log(
                lines,
                f"    platform {name}: state={info.get('state')!r} err={str(info.get('error_message') or '')[:120]}",
            )


def run_live_probe(hermes_home: Path, lines: list[str], *, with_api: bool) -> None:
    os.environ["HERMES_HOME"] = str(hermes_home)

    # Reload-dependent imports after env
    import importlib

    import hermes_constants

    importlib.reload(hermes_constants)

    _log(lines, "--- Live probe (HERMES_HOME=%s) ---" % hermes_home)
    _log(lines, f"  sys.executable={sys.executable}")
    _log(lines, f"  cwd={os.getcwd()}")

    from gateway.status import (
        get_running_pid,
        is_gateway_runtime_lock_active,
        _get_pid_path,
        _get_gateway_lock_path,
    )

    pid_path = _get_pid_path()
    lock_path = _get_gateway_lock_path()
    _log(lines, f"  gateway.pid path: {pid_path} exists={pid_path.is_file()}")
    _log(lines, f"  gateway.lock path: {lock_path} exists={lock_path.is_file()}")
    _log(lines, f"  lock active: {is_gateway_runtime_lock_active(lock_path)}")

    if pid_path.is_file():
        raw = pid_path.read_text(errors="replace")
        _log(lines, f"  gateway.pid raw (first 500 chars): {raw[:500]!r}")

    from gateway.status import read_runtime_status

    rt = read_runtime_status()
    _log(lines, f"  read_runtime_status keys: {list(rt.keys()) if isinstance(rt, dict) else type(rt)}")
    if isinstance(rt, dict):
        for k in ("gateway_state", "pid", "exit_reason", "updated_at"):
            if k in rt:
                _log(lines, f"    {k}={rt.get(k)!r}")

    from gateway.status import (
        _get_pid_path,
        _pid_from_record,
        _read_pid_record,
        pid_alive_best_effort,
    )

    rec = _read_pid_record(_get_pid_path())
    file_pid = _pid_from_record(rec) if isinstance(rec, dict) else None
    if file_pid is not None:
        alive = pid_alive_best_effort(file_pid)
        _log(lines, f"  pid from gateway.pid file: {file_pid}  pid_alive_best_effort={alive}")

    gpid = get_running_pid(cleanup_stale=False)
    _log(lines, f"  get_running_pid(cleanup_stale=False) -> {gpid}")

    if file_pid is not None and gpid is None and isinstance(rec, dict):
        if not pid_alive_best_effort(file_pid):
            _log(
                lines,
                "  >>> CONCLUSION: gateway.pid points to a DEAD process (stale metadata). "
                "Dashboard correctly reports gateway off; JSON may still say running until API normalizes.",
            )
        else:
            _log(
                lines,
                "  >>> ANOMALY: PID alive but get_running_pid=None — inspect gateway.lock argv/metadata.",
            )

    if gpid is not None:
        _stress_get_running_pid(100, lines)

    glog = hermes_home / "logs" / "gateway.log"
    if glog.is_file():
        try:
            raw = glog.read_text(encoding="utf-8", errors="replace").splitlines()
            tail = raw[-40:] if len(raw) > 40 else raw
            _log(lines, f"  --- tail {glog} (last {len(tail)} lines) ---")
            for ln in tail:
                _log(lines, "    " + ln[:500])
        except OSError as exc:
            _log(lines, f"  (could not read gateway.log: {exc})")

    if with_api:
        _log(lines, "--- same environment: GET /api/status ---")
        try:
            _api_status_snapshot(lines)
        except Exception as exc:
            _log(lines, f"  /api/status failed: {exc!r}")


def run_isolated_fake_gateway_record(lines: list[str]) -> None:
    """Simulate dead PID in pidfile — expect cleanup or None, without touching real home."""
    import tempfile

    prev_home = os.environ.get("HERMES_HOME")
    tmp = Path(tempfile.mkdtemp(prefix="hermes-diag-"))
    try:
        os.environ["HERMES_HOME"] = str(tmp)
        import importlib

        import hermes_constants

        importlib.reload(hermes_constants)

        from gateway.status import get_running_pid, _get_pid_path

        dead = 9_000_001
        rec = {
            "pid": dead,
            "kind": "hermes-gateway",
            "argv": [sys.executable, "-m", "hermes_cli.main", "gateway", "run"],
            "start_time": None,
        }
        _get_pid_path().write_text(json.dumps(rec), encoding="utf-8")
        g = get_running_pid(cleanup_stale=False)
        _log(
            lines,
            f"--- Isolated HERMES_HOME fake dead PID {dead} -> get_running_pid={g} (expect None) ---",
        )
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)
        if prev_home is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = prev_home
        import importlib
        import hermes_constants

        importlib.reload(hermes_constants)


def main() -> int:
    try:
        from hermes_constants import configure_stdio_utf8_windows

        configure_stdio_utf8_windows()
    except Exception:
        pass
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--hermes-home",
        type=Path,
        help="Override HERMES_HOME (default: env or hermes_constants default)",
    )
    ap.add_argument(
        "--skip-api",
        action="store_true",
        help="Do not call /api/status (faster if web deps missing)",
    )
    args = ap.parse_args()

    lines: list[str] = []
    t0 = time.strftime("%Y-%m-%d %H:%M:%S")
    _log(lines, f"=== gateway_dashboard_diagnostic {t0} ===")

    if args.hermes_home is not None:
        home = args.hermes_home.expanduser().resolve()
    else:
        # Default profile home without importing hermes before setting env
        from hermes_constants import get_hermes_home

        home = get_hermes_home()

    run_isolated_fake_gateway_record(lines)

    if not args.skip_api:
        run_live_probe(home, lines, with_api=True)
    else:
        run_live_probe(home, lines, with_api=False)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines) + "\n"
    try:
        OUT_FILE.write_text(text, encoding="utf-8")
        written = OUT_FILE
    except OSError:
        alt = OUT_DIR / f"gateway_dashboard_check_{time.strftime('%Y%m%d_%H%M%S')}.log"
        alt.write_text(text, encoding="utf-8")
        written = alt
    print(f"Wrote {written}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
