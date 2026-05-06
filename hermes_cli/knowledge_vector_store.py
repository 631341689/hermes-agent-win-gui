"""Per–knowledge-base FAISS index + SQLite chunk store."""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

CHUNKS_DB = "chunks.sqlite"
FAISS_NAME = "vectors.faiss"
MANIFEST_NAME = "vector_manifest.json"


def _kb_root(kb_id: str) -> Path:
    from hermes_cli.knowledge_registry import base_dir

    return base_dir(kb_id)


def _manifest_path(kb_id: str) -> Path:
    return _kb_root(kb_id) / MANIFEST_NAME


def _faiss_path(kb_id: str) -> Path:
    return _kb_root(kb_id) / FAISS_NAME


def _db_path(kb_id: str) -> Path:
    return _kb_root(kb_id) / CHUNKS_DB


def _init_chunks_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS chunks (
            ord INTEGER PRIMARY KEY,
            chunk_id TEXT NOT NULL UNIQUE,
            source_file TEXT NOT NULL,
            text TEXT NOT NULL
        );
        """
    )


def rebuild_vector_store(
    kb_id: str,
    rows: list[tuple[str, str, list[float]]],
    *,
    embedding_model: str,
) -> dict[str, Any]:
    """Replace chunks + FAISS for *kb_id*.

    *rows* — (source_file, text, embedding) in row order (ord = 0..n-1).
    """
    try:
        import faiss  # type: ignore[import-not-found]
        import numpy as np
    except Exception as exc:
        raise RuntimeError(
            "FAISS could not be loaded. Install compatible packages, e.g. "
            "pip install 'hermes-agent[knowledge]' (uses numpy<2 for typical faiss wheels). "
            f"Original error: {exc!r}"
        ) from exc

    root = _kb_root(kb_id)
    root.mkdir(parents=True, exist_ok=True)

    if not rows:
        # Empty index: still write manifest for dimension from config next query
        dim = 0
        if _faiss_path(kb_id).exists():
            _faiss_path(kb_id).unlink()
        if _db_path(kb_id).exists():
            _db_path(kb_id).unlink()
        manifest = {
            "embedding_model": embedding_model,
            "dimension": 0,
            "chunk_count": 0,
        }
        _manifest_path(kb_id).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest

    dim = len(rows[0][2])
    arr = np.array([r[2] for r in rows], dtype=np.float32)
    faiss.normalize_L2(arr)
    index = faiss.IndexFlatIP(dim)
    index.add(arr)

    db_path = _db_path(kb_id)
    if db_path.exists():
        db_path.unlink()
    with sqlite3.connect(db_path) as conn:
        _init_chunks_db(conn)
        for ord_, (src, text, _) in enumerate(rows):
            cid = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO chunks (ord, chunk_id, source_file, text) VALUES (?, ?, ?, ?)",
                (ord_, cid, src, text),
            )
        conn.commit()

    faiss.write_index(index, str(_faiss_path(kb_id)))
    manifest = {
        "embedding_model": embedding_model,
        "dimension": dim,
        "chunk_count": len(rows),
    }
    _manifest_path(kb_id).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def load_manifest(kb_id: str) -> dict[str, Any] | None:
    p = _manifest_path(kb_id)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def search_kb(kb_id: str, query_vector: list[float], top_k: int) -> list[dict[str, Any]]:
    """Return top chunks with cosine similarity as *score* (higher is better)."""
    try:
        import faiss  # type: ignore[import-not-found]
        import numpy as np
    except Exception as exc:
        raise RuntimeError(f"FAISS could not be loaded: {exc!r}") from exc

    man = load_manifest(kb_id)
    if not man or man.get("chunk_count", 0) == 0:
        return []
    dim = int(man["dimension"])
    if len(query_vector) != dim:
        raise ValueError(
            f"Query dimension {len(query_vector)} does not match index dimension {dim} for kb {kb_id}"
        )
    idx_path = _faiss_path(kb_id)
    if not idx_path.exists():
        return []
    index = faiss.read_index(str(idx_path))
    n = min(top_k, int(index.ntotal))
    if n <= 0:
        return []
    q = np.array([query_vector], dtype=np.float32)
    faiss.normalize_L2(q)
    scores, indices = index.search(q, n)
    flat_scores = scores[0].tolist()
    flat_idx = indices[0].tolist()

    with sqlite3.connect(_db_path(kb_id)) as conn:
        conn.row_factory = sqlite3.Row
        out: list[dict[str, Any]] = []
        for score, ord_ in zip(flat_scores, flat_idx):
            if ord_ < 0:
                continue
            row = conn.execute(
                "SELECT chunk_id, source_file, text FROM chunks WHERE ord = ?",
                (int(ord_),),
            ).fetchone()
            if not row:
                continue
            out.append(
                {
                    "chunk_id": row["chunk_id"],
                    "text": row["text"],
                    "source_path": f"bases/{kb_id}/raw/{row['source_file']}",
                    "score": float(score),
                }
            )
    return out
