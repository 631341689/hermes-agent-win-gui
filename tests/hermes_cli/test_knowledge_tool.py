"""Tests for tools/knowledge_tool.py (registry + list; vector query optional FAISS)."""

import importlib.util
import json

import pytest

from tools import knowledge_tool  # noqa: F401 — registers tools


def test_parse_kb_ids_comma():
    assert knowledge_tool._parse_kb_ids("a, b") == ["a", "b"]


def test_parse_kb_ids_json_array():
    assert knowledge_tool._parse_kb_ids('["x", "y"]') == ["x", "y"]


def test_knowledge_list_bases_empty_registry(_isolate_hermes_home):
    out = knowledge_tool.knowledge_list_bases()
    data = json.loads(out)
    assert data["success"] is True
    assert data["bases"] == []


def test_knowledge_catalog_empty_registry(_isolate_hermes_home):
    out = knowledge_tool.knowledge_catalog()
    data = json.loads(out)
    assert data["success"] is True
    assert data["bases"] == []
    assert "hint" in data


def test_knowledge_catalog_compact_shape(_isolate_hermes_home):
    from hermes_cli.knowledge_registry import KnowledgeRegistry

    reg = KnowledgeRegistry()
    reg.create("Cat", mode="vector", agent_summary="For routing tests")
    out = knowledge_tool.knowledge_catalog()
    data = json.loads(out)
    assert data["success"] is True
    assert len(data["bases"]) == 1
    b = data["bases"][0]
    assert set(b.keys()) == {
        "id",
        "name",
        "mode",
        "indexing_status",
        "summary_routing_mode",
        "routing_summary",
        "agent_summary",
    }
    assert b["name"] == "Cat"
    assert b["agent_summary"] == "For routing tests"


@pytest.mark.skipif(importlib.util.find_spec("faiss") is None, reason="faiss not installed")
def test_knowledge_catalog_manual_hides_routing_file(_isolate_hermes_home):
    from hermes_cli.knowledge_registry import KnowledgeRegistry
    from hermes_cli.knowledge_routing_summary import write_routing_summary_file

    reg = KnowledgeRegistry()
    r = reg.create("M", mode="vector", agent_summary="hand", summary_routing_mode="manual")
    write_routing_summary_file(r.id, "SECRET AUTO", 900)
    out = knowledge_tool.knowledge_catalog()
    data = json.loads(out)
    b = data["bases"][0]
    assert b["summary_routing_mode"] == "manual"
    assert b["routing_summary"] is None
    assert b["agent_summary"] == "hand"


def test_knowledge_vector_query_requires_ids(_isolate_hermes_home):
    out = knowledge_tool.knowledge_vector_query(query="hello", kb_ids="", top_k=3)
    data = json.loads(out)
    assert data["success"] is False
    err = (data.get("error") or "").lower()
    assert "kb_ids" in err or "hermes_active" in err


def test_knowledge_graphrag_query_rejects_vector_base(_isolate_hermes_home):
    from hermes_cli.knowledge_registry import KnowledgeRegistry

    reg = KnowledgeRegistry()
    r = reg.create("VecOnly", mode="vector")
    out = knowledge_tool.knowledge_graphrag_query(
        query="hello",
        kb_ids=r.id,
        graphrag_method="local",
    )
    data = json.loads(out)
    assert data["success"] is False
    assert "vector" in (data.get("error") or "").lower()


def test_knowledge_graphrag_query_requires_single_id(_isolate_hermes_home):
    from hermes_cli.knowledge_registry import KnowledgeRegistry

    reg = KnowledgeRegistry()
    a = reg.create("G1", mode="graphrag")
    b = reg.create("G2", mode="graphrag")
    out = knowledge_tool.knowledge_graphrag_query(
        query="hello",
        kb_ids=f"{a.id},{b.id}",
        graphrag_method="auto",
    )
    data = json.loads(out)
    assert data["success"] is False
    assert "exactly one" in (data.get("error") or "").lower()


def test_knowledge_graphrag_query_success_mock(_isolate_hermes_home, monkeypatch):
    from hermes_cli.knowledge_registry import KnowledgeRegistry

    reg = KnowledgeRegistry()
    rec = reg.create("Gmock", mode="graphrag")
    reg.update_meta(rec.id, indexing_status="ready")

    def fake_base(kb_id, q, method, **_kw):
        return {
            "kb_id": kb_id,
            "chunk_id": None,
            "text": f"hit:{method}",
            "source_path": None,
            "score": None,
            "kind": "graphrag",
            "graphrag_method": method,
        }

    monkeypatch.setattr(
        "hermes_cli.knowledge_graphrag_query.query_graphrag_base",
        fake_base,
    )
    out = knowledge_tool.knowledge_graphrag_query(
        query="总结全文结构",
        kb_ids=rec.id,
        graphrag_method="auto",
    )
    data = json.loads(out)
    assert data["success"] is True
    assert data["resolved_graphrag_method"] == "global"
    assert data["results"][0]["text"].startswith("hit:global")
