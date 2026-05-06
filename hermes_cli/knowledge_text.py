"""Read raw knowledge files and chunk text (track A — vector pipeline)."""

from __future__ import annotations

import copy
import logging
import math
import re
from pathlib import Path
from typing import Any, Callable

_log = logging.getLogger(__name__)

CHUNK_STRATEGIES = frozenset({"window", "delimiter", "semantic", "smart"})

# Markdown ATX headings (level 1–2) at line start — not ### or inside ``##`` false positives.
_MD_H1_LINE = re.compile(r"^\s{0,3}#\s+(?!#)")
_MD_H2_LINE = re.compile(r"^\s{0,3}##\s+(?!#)")

# Sentence boundaries (CJK + Latin + ellipsis + newlines as hard breaks).
_SENTENCE_SPLIT_RE = re.compile(
    r"(?<=[。．！？!?…]|\.)\s+|\s*\n\s*",
)


def read_raw_file_text(path: Path) -> str | None:
    """Return UTF-8 text for supported types, or None to skip."""
    suf = path.suffix.lower()
    try:
        if suf in {".txt", ".md", ".markdown", ".json", ".yaml", ".yml"}:
            return path.read_text(encoding="utf-8", errors="replace")
        if suf == ".pdf":
            try:
                from pypdf import PdfReader
            except ImportError:
                _log.warning("pypdf not installed — skipping PDF: %s", path.name)
                return None
            reader = PdfReader(str(path))
            parts: list[str] = []
            for page in reader.pages:
                t = page.extract_text() or ""
                if t.strip():
                    parts.append(t)
            return "\n\n".join(parts) if parts else None
    except OSError as exc:
        _log.warning("Failed to read %s: %s", path, exc)
        return None
    return None


def iter_raw_documents(raw_dir: Path) -> list[tuple[str, str]]:
    """Yield (relative_path, text) for every readable file under raw_dir."""
    if not raw_dir.is_dir():
        return []
    out: list[tuple[str, str]] = []
    for path in sorted(raw_dir.rglob("*")):
        if not path.is_file():
            continue
        text = read_raw_file_text(path)
        if text and text.strip():
            rel = str(path.relative_to(raw_dir)).replace("\\", "/")
            out.append((rel, text.strip()))
    return out


def _is_md_table_row_line(line: str) -> bool:
    """Heuristic: MinerU-style pipe table row (avoid single-| prose)."""
    s = line.strip()
    if len(s) < 2 or s.startswith("#"):
        return False
    if s.count("|") < 2:
        return False
    return "|" in s


def _split_markdown_structure_blocks(text: str) -> list[str]:
    """Split on ``#`` / ``##`` line boundaries outside fenced ``` blocks."""
    lines = text.splitlines(keepends=True)
    blocks: list[str] = []
    cur: list[str] = []
    in_fence = False

    def flush() -> None:
        nonlocal cur
        joined = "".join(cur)
        if joined.strip():
            blocks.append(joined)
        cur = []

    for line in lines:
        if line.strip().startswith("```"):
            cur.append(line)
            in_fence = not in_fence
            continue
        if in_fence:
            cur.append(line)
            continue
        if _MD_H1_LINE.match(line) or _MD_H2_LINE.match(line):
            flush()
        cur.append(line)
    flush()
    return blocks


def _segment_block_smart(block: str) -> list[str]:
    """One structure block → ordered segments: code fences, tables, image lines, prose runs."""
    lines = block.splitlines(keepends=True)
    segments: list[str] = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        if line.strip().startswith("```"):
            j = i + 1
            buf = [line]
            while j < n:
                buf.append(lines[j])
                if lines[j].strip().startswith("```"):
                    break
                j += 1
            segments.append("".join(buf))
            i = j + 1
            continue
        if _is_md_table_row_line(line):
            j = i
            buf: list[str] = []
            while j < n and lines[j].strip() and _is_md_table_row_line(lines[j]):
                buf.append(lines[j])
                j += 1
            if len(buf) >= 2:
                segments.append("".join(buf))
                i = j
                continue
            # Single pipe-heavy line (e.g. LaTeX ``| \\vartheta |``) — not a Markdown pipe table.
            # Without this branch, prose collection below breaks immediately on the same line
            # and ``i`` never advances (infinite loop).
            if len(buf) == 1:
                segments.append(buf[0])
                i = j
                continue
        stripped = line.lstrip()
        if stripped.startswith("![") and "](" in line:
            segments.append(line)
            i += 1
            continue
        j = i
        buf2: list[str] = []
        while j < n:
            ln = lines[j]
            if ln.strip().startswith("```"):
                break
            if _is_md_table_row_line(ln) and ln.strip():
                break
            st = ln.lstrip()
            if st.startswith("![") and "](" in ln:
                break
            buf2.append(ln)
            j += 1
        piece = "".join(buf2)
        if piece.strip():
            segments.append(piece)
        i = j
    return segments


def _likely_atomic_segment(seg: str) -> bool:
    """Tables, fenced code, and standalone image lines are never sub-split by length."""
    if "```" in seg:
        return True
    ls = [ln for ln in seg.splitlines() if ln.strip()]
    if len(ls) >= 2 and sum(1 for ln in ls if _is_md_table_row_line(ln)) >= 2:
        return True
    one = seg.strip()
    if one.startswith("![") and "](" in one and one.count("\n") <= 1:
        return True
    return False


def chunk_structure_smart(
    text: str,
    *,
    max_chars: int,
    overlap_chars: int,
) -> list[str]:
    """Structure-aware chunking for Markdown (MinerU PDF output and similar).

    - Splits on top-level ``#`` and ``##`` headings (outside ``` fences).
    - Keeps fenced code, pipe tables (≥2 rows), and ``![…](…)`` image lines atomic.
    - Sub-splits long prose with :func:`chunk_text` (sliding window + overlap).
    """
    max_chars = max(128, int(max_chars))
    overlap_chars = max(0, min(int(overlap_chars), max_chars - 1))
    out: list[str] = []
    for block in _split_markdown_structure_blocks(text):
        for seg in _segment_block_smart(block):
            s = seg.strip()
            if not s:
                continue
            if len(s) <= max_chars or _likely_atomic_segment(seg):
                out.append(s)
                continue
            out.extend(chunk_text(s, size_chars=max_chars, overlap_chars=overlap_chars))
    return [c for c in out if c.strip()]


def chunk_text(
    text: str,
    *,
    size_chars: int,
    overlap_chars: int,
) -> list[str]:
    """Sliding window chunker by character count (overlap < size)."""
    if size_chars <= 0:
        return [text] if text else []
    if overlap_chars >= size_chars:
        overlap_chars = max(0, size_chars // 8)
    step = max(1, size_chars - overlap_chars)
    chunks: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        piece = text[i : i + size_chars]
        if piece.strip():
            chunks.append(piece)
        i += step
    return chunks


def _tokens_to_chars(size_t: int, ov_t: int) -> tuple[int, int]:
    size_t = max(32, int(size_t or 512))
    ov_t = max(0, int(ov_t or 0))
    size_c = max(128, size_t * 4)
    ov_c = min(max(0, ov_t * 4), max(0, size_c - 1))
    return size_c, ov_c


def _cosine_dense(a: list[float], b: list[float]) -> float:
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _mean_vec(vecs: list[list[float]], idxs: list[int]) -> list[float]:
    if not idxs:
        return []
    dim = len(vecs[idxs[0]])
    acc = [0.0] * dim
    for j in idxs:
        v = vecs[j]
        for k in range(dim):
            acc[k] += v[k]
    n = float(len(idxs))
    return [x / n for x in acc]


def split_sentences_semantic(text: str) -> list[str]:
    """Split into coarse sentences / clauses for semantic chunking."""
    if not text.strip():
        return []
    parts = _SENTENCE_SPLIT_RE.split(text)
    return [p.strip() for p in parts if p and p.strip()]


def _merge_tiny_parts(parts: list[str], merge_under: int) -> list[str]:
    if merge_under <= 0 or not parts:
        return parts
    out: list[str] = []
    buf = ""
    for p in parts:
        if not out and len(p) < merge_under:
            buf = p
            continue
        if len(p) < merge_under and (buf or out):
            if buf:
                buf = f"{buf}\n{p}"
            else:
                prev = out.pop()
                buf = f"{prev}\n{p}"
            if len(buf) >= merge_under:
                out.append(buf)
                buf = ""
            continue
        if buf:
            out.append(buf)
            buf = ""
        out.append(p)
    if buf:
        if out and len(buf) < merge_under:
            out[-1] = f"{out[-1]}\n{buf}"
        else:
            out.append(buf)
    return [x for x in out if x.strip()]


def chunk_delimiter(
    text: str,
    *,
    separators: list[str],
    max_chars: int,
    merge_under_chars: int,
) -> list[str]:
    """Split by ordered separators (structure first); recurse when a part exceeds *max_chars*."""
    if not text.strip():
        return []
    seps = [s for s in separators if s]
    if not seps:
        return chunk_text(text, size_chars=max_chars, overlap_chars=max(0, max_chars // 8))

    def refine(part: str, sep_idx: int) -> list[str]:
        part = part.strip()
        if not part:
            return []
        if sep_idx >= len(seps):
            if len(part) <= max_chars:
                return [part]
            return chunk_text(
                part,
                size_chars=max_chars,
                overlap_chars=max(0, max_chars // 8),
            )
        sep = seps[sep_idx]
        if sep not in part:
            return refine(part, sep_idx + 1)
        bits = [b.strip() for b in part.split(sep) if b.strip()]
        if len(bits) <= 1:
            return refine(part, sep_idx + 1)
        out: list[str] = []
        for b in bits:
            if len(b) > max_chars:
                out.extend(refine(b, sep_idx + 1))
            else:
                out.append(b)
        return out

    pieces = refine(text.strip(), 0)
    pieces = _merge_tiny_parts(pieces, merge_under_chars)
    return [p for p in pieces if p.strip()]


def chunk_semantic_pack(
    text: str,
    *,
    max_chars: int,
    overlap_sentences: int,
) -> list[str]:
    """Greedy pack sentences into chunks under max_chars; optional sentence overlap."""
    sents = split_sentences_semantic(text)
    if not sents:
        return [text] if text.strip() else []
    ov = max(0, min(overlap_sentences, 8))
    chunks: list[str] = []
    buf: list[str] = []
    buf_len = 0

    def join_buf(xs: list[str]) -> str:
        return "\n".join(xs) if len(xs) > 1 else (xs[0] if xs else "")

    for s in sents:
        extra = 1 if buf else 0
        if buf and buf_len + extra + len(s) > max_chars:
            chunks.append(join_buf(buf))
            if ov and len(buf) >= ov:
                buf = buf[-ov:]
                buf_len = sum(len(x) + 1 for x in buf) - 1 if buf else 0
            else:
                buf = []
                buf_len = 0
            buf.append(s)
            buf_len += len(s)
        else:
            buf.append(s)
            buf_len += len(s) + extra
    if buf:
        chunks.append(join_buf(buf))
    # Oversized single sentence → window
    out: list[str] = []
    for c in chunks:
        if len(c) <= max_chars:
            if c.strip():
                out.append(c)
        else:
            out.extend(
                chunk_text(c, size_chars=max_chars, overlap_chars=max(0, max_chars // 8)),
            )
    return out


def chunk_semantic_embedding(
    text: str,
    *,
    max_chars: int,
    similarity_threshold: float,
    embed_fn: Callable[[list[str]], list[list[float]]],
    max_sentences: int = 400,
) -> list[str]:
    """Merge sentences while cosine(sentence, chunk centroid) >= threshold and under max_chars."""
    sents = split_sentences_semantic(text)
    if not sents:
        return [text] if text.strip() else []
    if len(sents) > max_sentences:
        _log.warning(
            "Semantic embedding chunker: %d sentences > cap %d — falling back to pack",
            len(sents),
            max_sentences,
        )
        return chunk_semantic_pack(text, max_chars=max_chars, overlap_sentences=0)

    vecs = embed_fn(sents)
    if len(vecs) != len(sents):
        return chunk_semantic_pack(text, max_chars=max_chars, overlap_sentences=0)

    chunks: list[str] = []
    cur_idxs: list[int] = []
    cur_len = 0

    def flush() -> None:
        nonlocal cur_idxs, cur_len
        if cur_idxs:
            chunks.append("\n".join(sents[i] for i in cur_idxs))
        cur_idxs = []
        cur_len = 0

    for i, s in enumerate(sents):
        add_len = len(s) + (1 if cur_idxs else 0)
        if not cur_idxs:
            cur_idxs = [i]
            cur_len = len(s)
            continue
        if cur_len + add_len > max_chars:
            flush()
            cur_idxs = [i]
            cur_len = len(s)
            continue
        centroid = _mean_vec(vecs, cur_idxs)
        sim = _cosine_dense(vecs[i], centroid)
        if sim < float(similarity_threshold):
            flush()
            cur_idxs = [i]
            cur_len = len(s)
        else:
            cur_idxs.append(i)
            cur_len += add_len
    flush()

    out: list[str] = []
    for c in chunks:
        if len(c) <= max_chars:
            if c.strip():
                out.append(c)
        else:
            out.extend(
                chunk_text(c, size_chars=max_chars, overlap_chars=max(0, max_chars // 8)),
            )
    return out


def resolve_chunk_settings(
    knowledge_section: dict[str, Any] | None,
    kb_chunk_override: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge global ``knowledge.chunk`` with per-KB ``chunk_config`` (PATCH)."""
    base = copy.deepcopy((knowledge_section or {}).get("chunk") or {})
    if kb_chunk_override:
        for k, v in kb_chunk_override.items():
            if k in ("delimiter", "semantic", "smart") and isinstance(v, dict):
                sub = dict(base.get(k) or {})
                sub.update(v)
                base[k] = sub
            elif v is not None:
                base[k] = v
    base.setdefault("strategy", "window")
    base.setdefault("size_tokens", 512)
    base.setdefault("overlap_tokens", 64)
    base.setdefault("delimiter", {})
    base.setdefault("semantic", {})
    base.setdefault("smart", {})
    delim = base["delimiter"]
    delim.setdefault("separators", ["\n\n", "\n", "。", ". "])
    delim.setdefault("merge_under_chars", 40)
    sem = base["semantic"]
    sem.setdefault("mode", "pack")
    sem.setdefault("overlap_sentences", 0)
    sem.setdefault("similarity_threshold", 0.55)
    st = base.get("size_tokens", 512)
    ot = base.get("overlap_tokens", 64)
    size_c, ov_c = _tokens_to_chars(int(st or 512), int(ot or 0))
    base["_size_chars"] = size_c
    base["_overlap_chars"] = ov_c
    strat = str(base.get("strategy") or "window").lower()
    if strat not in CHUNK_STRATEGIES:
        _log.warning("Unknown chunk strategy %r — using window", strat)
        base["strategy"] = "window"
    return base


def chunk_document(
    text: str,
    resolved: dict[str, Any],
    *,
    embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
) -> list[str]:
    """Split *text* into chunk strings according to *resolved* settings."""
    if not text.strip():
        return []
    strategy = str(resolved.get("strategy") or "window").lower()
    max_c = int(resolved.get("_size_chars") or 2048)
    ov_c = int(resolved.get("_overlap_chars") or 0)

    if strategy == "window":
        return chunk_text(text, size_chars=max_c, overlap_chars=ov_c)

    if strategy == "delimiter":
        delim = resolved.get("delimiter") or {}
        seps = delim.get("separators") or ["\n\n", "\n"]
        if not isinstance(seps, list):
            seps = ["\n\n", "\n"]
        merge_u = int(delim.get("merge_under_chars") or 0)
        max_d = delim.get("max_chunk_chars")
        max_use = int(max_d) if max_d else max_c
        max_use = max(128, max_use)
        return chunk_delimiter(
            text,
            separators=[str(s) for s in seps],
            max_chars=max_use,
            merge_under_chars=max(0, merge_u),
        )

    if strategy == "semantic":
        sem = resolved.get("semantic") or {}
        mode = str(sem.get("mode") or "pack").lower()
        ov_s = int(sem.get("overlap_sentences") or 0)
        max_s = sem.get("max_chunk_chars")
        max_use = int(max_s) if max_s else max_c
        max_use = max(128, max_use)
        thr = float(sem.get("similarity_threshold") or 0.55)
        if mode == "embedding":
            if embed_fn is None:
                _log.warning("semantic.embedding requested without embed_fn — using pack")
                return chunk_semantic_pack(
                    text,
                    max_chars=max_use,
                    overlap_sentences=ov_s,
                )
            return chunk_semantic_embedding(
                text,
                max_chars=max_use,
                similarity_threshold=thr,
                embed_fn=embed_fn,
            )
        return chunk_semantic_pack(
            text,
            max_chars=max_use,
            overlap_sentences=ov_s,
        )

    if strategy == "smart":
        sm = resolved.get("smart") or {}
        max_s = sm.get("max_chunk_chars")
        max_use = int(max_s) if max_s else max_c
        max_use = max(128, max_use)
        ov_use = ov_c
        ot = sm.get("overlap_chars")
        if ot is not None:
            ov_use = max(0, min(int(ot), max_use - 1))
        return chunk_structure_smart(text, max_chars=max_use, overlap_chars=ov_use)

    return chunk_text(text, size_chars=max_c, overlap_chars=ov_c)


def chunk_config_chars() -> tuple[int, int]:
    """Backward-compatible: global config only (no per-KB)."""
    from hermes_cli.config import load_config

    cfg = load_config()
    k = cfg.get("knowledge") or {}
    resolved = resolve_chunk_settings(k, None)
    return int(resolved["_size_chars"]), int(resolved["_overlap_chars"])
