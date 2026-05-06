"""Tests for auto routing_summary (file + sampling helpers)."""

from hermes_cli.knowledge_registry import KnowledgeRegistry
from hermes_cli.knowledge_routing_summary import (
    augment_base_dict,
    build_summary_source_material,
    read_routing_summary_file,
    routing_summary_for_catalog,
    write_routing_summary_file,
)


def test_build_summary_source_material_respects_budget(_isolate_hermes_home):
    rows = [(f"f{i}.md", "x" * 500, []) for i in range(100)]
    blob = build_summary_source_material(rows, max_chars=2500)
    assert len(blob) <= 2600
    assert "### f0.md" in blob


def test_registry_migrates_legacy_both_to_auto(_isolate_hermes_home):
    reg = KnowledgeRegistry()
    r = reg.create("Legacy", mode="vector")
    with reg._connect() as conn:
        conn.execute("UPDATE knowledge_bases SET summary_routing_mode = 'both' WHERE id = ?", (r.id,))
        conn.commit()
    reg2 = KnowledgeRegistry()
    assert reg2.get(r.id).summary_routing_mode == "auto"


def test_routing_summary_for_catalog_respects_mode(_isolate_hermes_home):
    reg = KnowledgeRegistry()
    r = reg.create("M", mode="vector", summary_routing_mode="manual")
    write_routing_summary_file(r.id, "disk", 900)
    assert routing_summary_for_catalog("manual", r.id) is None
    assert routing_summary_for_catalog("auto", r.id) == "disk"


def test_write_read_augment_roundtrip(_isolate_hermes_home):
    reg = KnowledgeRegistry()
    r = reg.create("RT", mode="vector")
    write_routing_summary_file(r.id, "  hello world  ", 900)
    assert read_routing_summary_file(r.id) == "hello world"
    d = augment_base_dict(r.id, r.to_dict())
    assert d["routing_summary"] == "hello world"
    assert d["name"] == "RT"


def test_try_generate_fallback_when_llm_returns_none(monkeypatch, _isolate_hermes_home):
    import hermes_cli.knowledge_routing_summary as krs

    monkeypatch.setattr(krs, "_chat_summarize", lambda **kwargs: None)
    from hermes_cli.knowledge_routing_summary import try_generate_and_write_routing_summary

    reg = KnowledgeRegistry()
    r = reg.create("NoKey", mode="vector")
    rows = [("a.md", "chunk one two three", [0.1, 0.2])]
    try_generate_and_write_routing_summary(r.id, r.name, rows)
    text = read_routing_summary_file(r.id)
    assert text is not None
    assert "Auto-summary unavailable" in text
