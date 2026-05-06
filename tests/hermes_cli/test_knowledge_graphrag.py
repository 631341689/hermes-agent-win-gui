"""Unit tests for GraphRAG knowledge-base helpers (no graphrag import required)."""

from pathlib import Path


def test_graphrag_input_records_stable_titles(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    from hermes_constants import get_hermes_home

    from hermes_cli.knowledge_registry import KnowledgeRegistry
    from hermes_cli.knowledge_graphrag import graphrag_input_records_from_kb, graphrag_project_root

    home = get_hermes_home()
    home.mkdir(parents=True, exist_ok=True)
    reg = KnowledgeRegistry()
    rec = reg.create("GR Test", mode="graphrag")
    kb_id = rec.id

    raw = home / "knowledge" / "bases" / kb_id / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "notes.md").write_text("# Hello\nbody", encoding="utf-8")

    rows = graphrag_input_records_from_kb(kb_id)
    assert len(rows) == 1
    assert rows[0]["title"] == "notes.md"
    assert "Hello" in rows[0]["text"]
    assert rows[0]["human_readable_id"] == 0
    assert "id" in rows[0] and len(rows[0]["id"]) > 30

    root = graphrag_project_root(kb_id)
    assert root == Path(home / "knowledge" / "bases" / kb_id / "graphrag")


def test_graphrag_prior_index_detection(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    from hermes_constants import get_hermes_home

    from hermes_cli.knowledge_graphrag import graphrag_project_root
    from hermes_cli.knowledge_registry import KnowledgeRegistry
    import hermes_cli.knowledge_graphrag as kg

    home = get_hermes_home()
    home.mkdir(parents=True, exist_ok=True)
    reg = KnowledgeRegistry()
    rec = reg.create("GR Idx", mode="graphrag")
    root = graphrag_project_root(rec.id)
    assert kg._graphrag_has_prior_index(root) is False
    (root / "output").mkdir(parents=True, exist_ok=True)
    (root / "output" / "entities.parquet").write_bytes(b"dummy")
    assert kg._graphrag_has_prior_index(root) is True
