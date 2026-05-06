"""SQLite registry for dashboard knowledge bases (Hermes home–scoped)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes_constants import get_hermes_home


def knowledge_root() -> Path:
    """Root directory for all knowledge-base data under the active profile."""
    root = get_hermes_home() / "knowledge"
    root.mkdir(parents=True, exist_ok=True)
    return root


def registry_db_path() -> Path:
    return knowledge_root() / "registry.sqlite"


def base_dir(kb_id: str) -> Path:
    return knowledge_root() / "bases" / kb_id


_SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge_bases (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'vector',
    indexing_status TEXT NOT NULL DEFAULT 'idle',
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    chunk_config TEXT,
    agent_summary TEXT,
    summary_routing_mode TEXT NOT NULL DEFAULT 'auto'
);
"""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_SUMMARY_ROUTING_MODES = frozenset({"manual", "auto"})


@dataclass
class KnowledgeBaseRecord:
    id: str
    name: str
    mode: str
    indexing_status: str
    error_message: str | None
    created_at: str
    updated_at: str
    chunk_config: dict[str, Any] | None = None
    agent_summary: str | None = None
    summary_routing_mode: str = "auto"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "mode": self.mode,
            "indexing_status": self.indexing_status,
            "error_message": self.error_message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "chunk_config": self.chunk_config,
            "agent_summary": self.agent_summary,
            "summary_routing_mode": self.summary_routing_mode,
        }


class KnowledgeRegistry:
    """CRUD for knowledge base metadata."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or registry_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute("PRAGMA table_info(knowledge_bases)").fetchall()
        col_names = {r[1] for r in rows}
        if "chunk_config" not in col_names:
            conn.execute("ALTER TABLE knowledge_bases ADD COLUMN chunk_config TEXT")
        if "agent_summary" not in col_names:
            conn.execute("ALTER TABLE knowledge_bases ADD COLUMN agent_summary TEXT")
        if "summary_routing_mode" not in col_names:
            conn.execute("ALTER TABLE knowledge_bases ADD COLUMN summary_routing_mode TEXT DEFAULT 'auto'")
            conn.execute(
                "UPDATE knowledge_bases SET summary_routing_mode = 'auto' "
                "WHERE summary_routing_mode IS NULL OR TRIM(summary_routing_mode) = ''"
            )
        # Legacy "both" and unknown values → auto (single auto-generated routing file path).
        conn.execute(
            "UPDATE knowledge_bases SET summary_routing_mode = 'auto' "
            "WHERE LOWER(TRIM(COALESCE(summary_routing_mode, ''))) NOT IN ('manual', 'auto')"
        )

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(_SCHEMA)
            self._migrate_schema(conn)
            conn.commit()
        finally:
            conn.close()

    def create(
        self,
        name: str,
        mode: str = "vector",
        agent_summary: str | None = None,
        summary_routing_mode: str = "auto",
    ) -> KnowledgeBaseRecord:
        kb_id = str(uuid.uuid4())
        now = _utc_now_iso()
        srm = (summary_routing_mode or "auto").strip().lower()
        if srm not in _SUMMARY_ROUTING_MODES:
            srm = "auto"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_bases
                    (id, name, mode, indexing_status, error_message, created_at, updated_at, chunk_config, agent_summary,
                     summary_routing_mode)
                VALUES (?, ?, ?, 'idle', NULL, ?, ?, NULL, ?, ?)
                """,
                (kb_id, name.strip(), mode, now, now, agent_summary, srm),
            )
            conn.commit()
        d = base_dir(kb_id)
        (d / "raw").mkdir(parents=True, exist_ok=True)
        got = self.get(kb_id)
        assert got is not None
        return got

    def list_all(self) -> list[KnowledgeBaseRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, mode, indexing_status, error_message, created_at, updated_at, chunk_config, "
                "agent_summary, summary_routing_mode FROM knowledge_bases ORDER BY created_at DESC"
            ).fetchall()
        return [_row_to_record(r) for r in rows]

    def get(self, kb_id: str) -> KnowledgeBaseRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, name, mode, indexing_status, error_message, created_at, updated_at, chunk_config, "
                "agent_summary, summary_routing_mode FROM knowledge_bases WHERE id = ?",
                (kb_id,),
            ).fetchone()
        return _row_to_record(row) if row else None

    def update_meta(
        self,
        kb_id: str,
        *,
        name: str | None = None,
        mode: str | None = None,
        indexing_status: str | None = None,
        error_message: str | None = None,
        clear_error: bool = False,
        chunk_config: Any = Ellipsis,
        agent_summary: Any = Ellipsis,
        summary_routing_mode: Any = Ellipsis,
    ) -> KnowledgeBaseRecord | None:
        cur = self.get(kb_id)
        if not cur:
            return None
        sets: list[str] = []
        params: list[Any] = []
        if name is not None:
            sets.append("name = ?")
            params.append(name.strip())
        if mode is not None:
            sets.append("mode = ?")
            params.append(mode)
        if indexing_status is not None:
            sets.append("indexing_status = ?")
            params.append(indexing_status)
        if clear_error:
            sets.append("error_message = NULL")
        elif error_message is not None:
            sets.append("error_message = ?")
            params.append(error_message)
        if chunk_config is not Ellipsis:
            sets.append("chunk_config = ?")
            params.append(None if chunk_config is None else json.dumps(chunk_config))
        if agent_summary is not Ellipsis:
            sets.append("agent_summary = ?")
            params.append(agent_summary)
        if summary_routing_mode is not Ellipsis:
            srm = (summary_routing_mode or "auto").strip().lower()
            if srm not in _SUMMARY_ROUTING_MODES:
                srm = "auto"
            sets.append("summary_routing_mode = ?")
            params.append(srm)
        if not sets:
            return cur
        sets.append("updated_at = ?")
        params.append(_utc_now_iso())
        params.append(kb_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE knowledge_bases SET {', '.join(sets)} WHERE id = ?",
                params,
            )
            conn.commit()
        return self.get(kb_id)

    def delete(self, kb_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM knowledge_bases WHERE id = ?", (kb_id,))
            conn.commit()
            deleted = cur.rowcount > 0
        if deleted:
            import shutil

            p = base_dir(kb_id)
            if p.exists():
                shutil.rmtree(p, ignore_errors=True)
        return deleted


def _parse_chunk_config(raw: Any) -> dict[str, Any] | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, dict):
        return raw
    try:
        out = json.loads(raw)
        return out if isinstance(out, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def _row_to_record(row: sqlite3.Row) -> KnowledgeBaseRecord:
    keys = row.keys()
    raw_summary = row["agent_summary"] if "agent_summary" in keys else None
    summary = raw_summary if isinstance(raw_summary, str) and raw_summary.strip() else None
    raw_mode = row["summary_routing_mode"] if "summary_routing_mode" in keys else "auto"
    srm = (raw_mode or "auto").strip().lower() if isinstance(raw_mode, str) else "auto"
    if srm not in _SUMMARY_ROUTING_MODES:
        srm = "auto"
    return KnowledgeBaseRecord(
        id=row["id"],
        name=row["name"],
        mode=row["mode"],
        indexing_status=row["indexing_status"],
        error_message=row["error_message"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        chunk_config=_parse_chunk_config(row["chunk_config"] if "chunk_config" in keys else None),
        agent_summary=summary,
        summary_routing_mode=srm,
    )
