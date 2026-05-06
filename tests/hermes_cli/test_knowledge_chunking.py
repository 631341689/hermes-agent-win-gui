"""Unit tests for knowledge chunk strategies (no FAISS)."""

from pathlib import Path

from hermes_cli.knowledge_text import (
    chunk_delimiter,
    chunk_document,
    chunk_semantic_pack,
    chunk_structure_smart,
    chunk_text,
    resolve_chunk_settings,
    split_sentences_semantic,
)


def test_resolve_merge_kb_override():
    global_k = {
        "chunk": {
            "strategy": "window",
            "size_tokens": 512,
            "overlap_tokens": 64,
            "delimiter": {"separators": ["\n\n"], "merge_under_chars": 10},
            "semantic": {"mode": "pack"},
        }
    }
    r = resolve_chunk_settings(global_k, {"strategy": "delimiter"})
    assert r["strategy"] == "delimiter"
    assert "\n\n" in (r.get("delimiter") or {}).get("separators", [])


def test_resolve_smart_subdict_merge():
    global_k = {
        "chunk": {
            "strategy": "window",
            "smart": {"max_chunk_chars": 4000, "overlap_chars": 100},
        }
    }
    r = resolve_chunk_settings(global_k, {"strategy": "smart", "smart": {"overlap_chars": 50}})
    assert r["strategy"] == "smart"
    sm = r.get("smart") or {}
    assert sm.get("max_chunk_chars") == 4000
    assert sm.get("overlap_chars") == 50


def test_window_chunker():
    t = "a" * 100
    parts = chunk_text(t, size_chars=30, overlap_chars=5)
    assert len(parts) >= 3
    assert all(len(p) <= 30 for p in parts)


def test_delimiter_splits_paragraphs():
    text = "para one\n\npara two\n\npara three"
    parts = chunk_delimiter(
        text,
        separators=["\n\n", "\n"],
        max_chars=500,
        merge_under_chars=0,
    )
    assert len(parts) == 3


def test_semantic_pack_cjk():
    text = "第一句。第二句很长" + "字" * 200 + "。第三句。"
    parts = chunk_semantic_pack(text, max_chars=120, overlap_sentences=0)
    assert len(parts) >= 2
    assert all(len(p) <= 200 for p in parts)


def test_chunk_document_window():
    g = {"chunk": {"strategy": "window", "size_tokens": 32, "overlap_tokens": 4}}
    r = resolve_chunk_settings(g, None)
    out = chunk_document("x" * 500, r)
    assert len(out) >= 2


def test_chunk_document_delimiter():
    g = {"chunk": {"strategy": "delimiter", "size_tokens": 512, "overlap_tokens": 64}}
    kb = {"delimiter": {"separators": ["|"], "merge_under_chars": 0}}
    r = resolve_chunk_settings(g, kb)
    out = chunk_document("a|b|c", r)
    assert out == ["a", "b", "c"]


def test_chunk_document_semantic_embedding_fallback_without_embed_fn():
    g = {"chunk": {"strategy": "semantic", "semantic": {"mode": "embedding"}}}
    r = resolve_chunk_settings(g, None)
    out = chunk_document("Hello. World.", r, embed_fn=None)
    assert len(out) >= 1


def test_smart_splits_on_headings():
    md = "# Chapter\nintro\n## Section\ndetail"
    parts = chunk_structure_smart(md, max_chars=500, overlap_chars=0)
    assert len(parts) >= 2
    joined = "\n".join(parts)
    assert "Chapter" in joined and "Section" in joined


def test_smart_table_kept_atomic():
    md = "# T\n|a|b|\n|---|---|\n|1|2|\n"
    parts = chunk_structure_smart(md, max_chars=40, overlap_chars=0)
    assert any("|a|" in p and "|1|" in p for p in parts)


def test_smart_long_prose_windowed():
    md = "# X\n" + ("word " * 200)
    parts = chunk_structure_smart(md, max_chars=120, overlap_chars=20)
    assert len(parts) >= 2


def test_smart_sample_markdown_fixture():
    """Regression: bundled MD fixture (headings / table / fence / image / prose)."""
    root = Path(__file__).resolve().parents[1]
    md_path = root / "fixtures" / "knowledge_smart_sample.md"
    text = md_path.read_text(encoding="utf-8")
    parts = chunk_structure_smart(text, max_chars=400, overlap_chars=40)
    joined = "\n\n---\n\n".join(parts)
    assert "# Sample" in joined or "Sample PDF" in joined
    assert "| Col A |" in joined and "| 1 |" in joined
    assert "```python" in joined
    assert "![diagram]" in joined


def test_chunk_document_smart():
    g = {"chunk": {"strategy": "smart", "size_tokens": 32, "overlap_tokens": 4}}
    r = resolve_chunk_settings(g, None)
    md = "# H\n" + "x" * 400
    out = chunk_document(md, r)
    assert len(out) >= 2


def test_split_sentences():
    s = split_sentences_semantic("A. B! C?\nD")
    assert len(s) >= 3
