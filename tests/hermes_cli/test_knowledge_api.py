"""Tests for /api/knowledge REST API."""

import importlib.util
import io

import pytest


def _have_faiss() -> bool:
    return importlib.util.find_spec("faiss") is not None


def _faiss_runtime_ok() -> bool:
    """True only if faiss imports and a minimal index add works (NumPy ABI)."""
    if not _have_faiss():
        return False
    try:
        import faiss  # noqa: F401
        import numpy as np

        idx = faiss.IndexFlatIP(2)
        idx.add(np.array([[0.7, 0.7]], dtype=np.float32))
    except Exception:
        return False
    return True


@pytest.fixture
def knowledge_client(monkeypatch, _isolate_hermes_home):
    try:
        from starlette.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi/starlette not installed")

    import hermes_state
    from hermes_constants import get_hermes_home
    import hermes_cli.knowledge_api as knowledge_api_mod
    from hermes_cli.knowledge_registry import registry_db_path
    from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN

    monkeypatch.setattr(knowledge_api_mod, "_REGISTRY", None)
    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", get_hermes_home() / "state.db")
    reg_path = registry_db_path()
    if reg_path.exists():
        reg_path.unlink()

    client = TestClient(app)
    client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
    return client


@pytest.fixture
def fake_embed_4d(monkeypatch):
    """Deterministic 4-D embeddings (FAISS IndexFlatIP + normalize)."""

    def _fake(texts: list[str], **_kwargs: object) -> list[list[float]]:
        return [[0.25, 0.25, 0.25, 0.25] for _ in texts]

    monkeypatch.setattr("hermes_cli.knowledge_index.embed_texts", _fake)


class TestKnowledgeApiUnauthorized:
    def test_bases_requires_token(self, monkeypatch, _isolate_hermes_home):
        try:
            from starlette.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi/starlette not installed")

        import hermes_state
        from hermes_constants import get_hermes_home
        from hermes_cli.web_server import app

        monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", get_hermes_home() / "state.db")
        client = TestClient(app)
        resp = client.get("/api/knowledge/bases")
        assert resp.status_code == 401


class TestKnowledgeApiCrud:
    def test_create_list_delete(self, knowledge_client):
        r = knowledge_client.post("/api/knowledge/bases", json={"name": "Test KB", "mode": "vector"})
        assert r.status_code == 200
        data = r.json()
        assert "base" in data
        kb_id = data["base"]["id"]
        assert data["base"]["name"] == "Test KB"
        assert data["base"]["mode"] == "vector"
        assert data["base"]["indexing_status"] == "idle"

        r2 = knowledge_client.get("/api/knowledge/bases")
        assert r2.status_code == 200
        bases = r2.json()["bases"]
        assert len(bases) == 1
        assert bases[0]["id"] == kb_id
        assert "chunk_config" in bases[0]
        assert "agent_summary" in bases[0]
        assert bases[0]["agent_summary"] is None
        assert "routing_summary" in bases[0]
        assert bases[0].get("summary_routing_mode") == "auto"

        r3 = knowledge_client.delete(f"/api/knowledge/bases/{kb_id}")
        assert r3.status_code == 200

        r4 = knowledge_client.get("/api/knowledge/bases")
        assert r4.json()["bases"] == []

    def test_upload(self, knowledge_client):
        r = knowledge_client.post("/api/knowledge/bases", json={"name": "Up"})
        kb_id = r.json()["base"]["id"]
        files = {"file": ("note.txt", io.BytesIO(b"hello"), "text/plain")}
        up = knowledge_client.post(f"/api/knowledge/bases/{kb_id}/upload", files=files)
        assert up.status_code == 200
        j = up.json()
        assert j["bytes"] == 5
        assert j.get("pdf_converted_to_markdown") is False

    def test_clear_raw(self, knowledge_client):
        from hermes_constants import get_hermes_home

        r = knowledge_client.post("/api/knowledge/bases", json={"name": "Clr"})
        kb_id = r.json()["base"]["id"]
        files = {"file": ("keep.txt", io.BytesIO(b"x"), "text/plain")}
        knowledge_client.post(f"/api/knowledge/bases/{kb_id}/upload", files=files)
        raw_file = get_hermes_home() / "knowledge" / "bases" / kb_id / "raw" / "keep.txt"
        assert raw_file.is_file()
        clr = knowledge_client.delete(f"/api/knowledge/bases/{kb_id}/raw")
        assert clr.status_code == 200
        body = clr.json()
        assert body.get("ok") is True
        assert body.get("removed_files") == 1
        assert not raw_file.exists()
        assert (get_hermes_home() / "knowledge" / "bases" / kb_id / "raw").is_dir()

    def test_upload_stream_sse(self, knowledge_client):
        r = knowledge_client.post("/api/knowledge/bases", json={"name": "StreamUp"})
        kb_id = r.json()["base"]["id"]
        files = {"file": ("note.txt", io.BytesIO(b"hello"), "text/plain")}
        with knowledge_client.stream(
            "POST",
            f"/api/knowledge/bases/{kb_id}/upload?stream=1",
            files=files,
        ) as resp:
            assert resp.status_code == 200
            body = resp.read().decode("utf-8")
        assert "event" in body
        assert '"event": "saved"' in body or '"event":"saved"' in body.replace(" ", "")
        assert "final" in body
        assert '"ok": true' in body or '"ok":true' in body.replace(" ", "")

    def test_reindex_graphrag_empty_raw_returns_400(self, knowledge_client):
        r = knowledge_client.post("/api/knowledge/bases", json={"name": "G", "mode": "graphrag"})
        kb_id = r.json()["base"]["id"]
        r2 = knowledge_client.post(f"/api/knowledge/bases/{kb_id}/reindex", json={})
        assert r2.status_code == 400
        assert "raw" in r2.json()["detail"].lower()

    def test_patch_chunk_config(self, knowledge_client):
        r = knowledge_client.post("/api/knowledge/bases", json={"name": "Chunky", "mode": "vector"})
        kb_id = r.json()["base"]["id"]
        p = knowledge_client.patch(
            f"/api/knowledge/bases/{kb_id}",
            json={
                "chunk_config": {
                    "strategy": "delimiter",
                    "delimiter": {"separators": ["|"], "merge_under_chars": 0},
                },
            },
        )
        assert p.status_code == 200
        assert p.json()["base"]["chunk_config"]["strategy"] == "delimiter"
        assert "|" in p.json()["base"]["chunk_config"]["delimiter"]["separators"]

    def test_patch_chunk_config_invalid_strategy(self, knowledge_client):
        r = knowledge_client.post("/api/knowledge/bases", json={"name": "Bad", "mode": "vector"})
        kb_id = r.json()["base"]["id"]
        p = knowledge_client.patch(
            f"/api/knowledge/bases/{kb_id}",
            json={"chunk_config": {"strategy": "magic"}},
        )
        assert p.status_code == 400

    def test_patch_chunk_config_smart(self, knowledge_client):
        r = knowledge_client.post("/api/knowledge/bases", json={"name": "SmartKB", "mode": "vector"})
        kb_id = r.json()["base"]["id"]
        p = knowledge_client.patch(
            f"/api/knowledge/bases/{kb_id}",
            json={
                "chunk_config": {
                    "strategy": "smart",
                    "smart": {"max_chunk_chars": 8000, "overlap_chars": 128},
                },
            },
        )
        assert p.status_code == 200
        cfg = p.json()["base"]["chunk_config"]
        assert cfg["strategy"] == "smart"
        assert cfg["smart"]["max_chunk_chars"] == 8000
        assert cfg["smart"]["overlap_chars"] == 128

    def test_patch_chunk_config_smart_invalid_overlap(self, knowledge_client):
        r = knowledge_client.post("/api/knowledge/bases", json={"name": "S2", "mode": "vector"})
        kb_id = r.json()["base"]["id"]
        p = knowledge_client.patch(
            f"/api/knowledge/bases/{kb_id}",
            json={"chunk_config": {"strategy": "smart", "smart": {"overlap_chars": -1}}},
        )
        assert p.status_code == 400

    def test_patch_no_fields_400(self, knowledge_client):
        r = knowledge_client.post("/api/knowledge/bases", json={"name": "Nop", "mode": "vector"})
        kb_id = r.json()["base"]["id"]
        p = knowledge_client.patch(f"/api/knowledge/bases/{kb_id}", json={})
        assert p.status_code == 400

    def test_patch_summary_routing_mode(self, knowledge_client):
        r = knowledge_client.post("/api/knowledge/bases", json={"name": "ModeKB", "mode": "vector"})
        kb_id = r.json()["base"]["id"]
        assert r.json()["base"]["summary_routing_mode"] == "auto"
        p = knowledge_client.patch(
            f"/api/knowledge/bases/{kb_id}",
            json={"summary_routing_mode": "manual"},
        )
        assert p.status_code == 200
        assert p.json()["base"]["summary_routing_mode"] == "manual"

    def test_create_patch_agent_summary(self, knowledge_client):
        r = knowledge_client.post(
            "/api/knowledge/bases",
            json={"name": "Sum", "mode": "vector", "agent_summary": "  API docs  "},
        )
        assert r.status_code == 200
        kb_id = r.json()["base"]["id"]
        assert r.json()["base"]["agent_summary"] == "API docs"

        p = knowledge_client.patch(
            f"/api/knowledge/bases/{kb_id}",
            json={"agent_summary": None},
        )
        assert p.status_code == 200
        assert p.json()["base"]["agent_summary"] is None


@pytest.fixture
def mock_routing_llm(monkeypatch):
    import hermes_cli.knowledge_routing_summary as krs

    monkeypatch.setattr(krs, "_chat_summarize", lambda **kwargs: "Stub KB routing summary for tests.")


@pytest.mark.usefixtures("mock_routing_llm")
@pytest.mark.skipif(
    not _faiss_runtime_ok(),
    reason="faiss not usable (install hermes-agent[knowledge] or fix NumPy/faiss ABI)",
)
class TestKnowledgeVectorPipeline:
    def test_reindex_manual_skips_routing_summary_file(self, knowledge_client, fake_embed_4d):
        r = knowledge_client.post(
            "/api/knowledge/bases",
            json={"name": "ManVec", "mode": "vector", "summary_routing_mode": "manual"},
        )
        kb_id = r.json()["base"]["id"]
        body = b"only manual routing mode test"
        files = {"file": ("doc.txt", io.BytesIO(body), "text/plain")}
        assert knowledge_client.post(f"/api/knowledge/bases/{kb_id}/upload", files=files).status_code == 200
        r2 = knowledge_client.post(f"/api/knowledge/bases/{kb_id}/reindex", json={})
        assert r2.status_code == 200
        from hermes_cli.knowledge_routing_summary import routing_summary_path

        assert not routing_summary_path(kb_id).exists()

    def test_reindex_and_query(self, knowledge_client, fake_embed_4d):
        r = knowledge_client.post("/api/knowledge/bases", json={"name": "Vec", "mode": "vector"})
        kb_id = r.json()["base"]["id"]
        body = ("paragraph one. " * 80 + "\n\n" + "paragraph two. " * 80).encode()
        files = {"file": ("doc.txt", io.BytesIO(body), "text/plain")}
        assert knowledge_client.post(f"/api/knowledge/bases/{kb_id}/upload", files=files).status_code == 200

        r2 = knowledge_client.post(f"/api/knowledge/bases/{kb_id}/reindex", json={})
        assert r2.status_code == 200
        j = r2.json()
        assert j["base"]["indexing_status"] == "ready"
        assert j["stats"]["chunk_count"] >= 1
        assert j["base"].get("routing_summary")
        assert "Stub KB routing summary" in j["base"]["routing_summary"]

        q = knowledge_client.post(
            "/api/knowledge/query",
            json={"kb_ids": [kb_id], "query": "paragraph two", "top_k": 3},
        )
        assert q.status_code == 200
        results = q.json()["results"]
        assert len(results) >= 1
        assert results[0]["kb_id"] == kb_id
        assert "text" in results[0]

    def test_query_empty_index(self, knowledge_client, fake_embed_4d):
        r = knowledge_client.post("/api/knowledge/bases", json={"name": "Empty", "mode": "vector"})
        kb_id = r.json()["base"]["id"]
        r2 = knowledge_client.post(f"/api/knowledge/bases/{kb_id}/reindex", json={})
        assert r2.status_code == 200
        assert r2.json()["stats"]["chunk_count"] == 0
        assert "No indexed text" in (r2.json()["base"].get("routing_summary") or "")
        q = knowledge_client.post(
            "/api/knowledge/query",
            json={"kb_ids": [kb_id], "query": "anything", "top_k": 5},
        )
        assert q.status_code == 200
        assert q.json()["results"] == []

    def test_reindex_stream_includes_progress_and_final(self, knowledge_client, fake_embed_4d):
        r = knowledge_client.post("/api/knowledge/bases", json={"name": "StreamRe", "mode": "vector"})
        kb_id = r.json()["base"]["id"]
        body = b"hello stream reindex chunk text"
        files = {"file": ("doc.txt", io.BytesIO(body), "text/plain")}
        assert knowledge_client.post(f"/api/knowledge/bases/{kb_id}/upload", files=files).status_code == 200
        resp = knowledge_client.post(
            f"/api/knowledge/bases/{kb_id}/reindex?stream=1",
            json={},
        )
        assert resp.status_code == 200
        raw = resp.text
        assert '"event": "final"' in raw or '"event":"final"' in raw.replace(" ", "")
        assert "chunking" in raw or "embedding" in raw
        assert "routing_summary" in raw or "Stub KB routing" in raw


class TestKnowledgeQueryModes:
    def test_mixed_vector_graphrag_rejected(self, knowledge_client):
        r1 = knowledge_client.post("/api/knowledge/bases", json={"name": "Vmix", "mode": "vector"})
        r2 = knowledge_client.post("/api/knowledge/bases", json={"name": "Gmix", "mode": "graphrag"})
        assert r1.status_code == 200 and r2.status_code == 200
        id1, id2 = r1.json()["base"]["id"], r2.json()["base"]["id"]
        resp = knowledge_client.post(
            "/api/knowledge/query",
            json={"kb_ids": [id1, id2], "query": "x"},
        )
        assert resp.status_code == 400
        assert "mix" in resp.json()["detail"].lower()

    def test_graphrag_query_not_ready(self, knowledge_client):
        r = knowledge_client.post("/api/knowledge/bases", json={"name": "Gidle", "mode": "graphrag"})
        kb_id = r.json()["base"]["id"]
        resp = knowledge_client.post(
            "/api/knowledge/query",
            json={"kb_ids": [kb_id], "query": "hi", "graphrag_method": "local"},
        )
        assert resp.status_code == 400
        assert "ready" in resp.json()["detail"].lower()

    def test_graphrag_query_mocked(self, knowledge_client, monkeypatch):
        def fake_query_graphrag_base(kb_id, q, method, **_kw):
            return {
                "kb_id": kb_id,
                "chunk_id": None,
                "text": f"ok:{method}:{q[:4]}",
                "source_path": None,
                "score": None,
                "kind": "graphrag",
                "graphrag_method": method,
            }

        monkeypatch.setattr(
            "hermes_cli.knowledge_graphrag_query.query_graphrag_base",
            fake_query_graphrag_base,
        )
        r = knowledge_client.post("/api/knowledge/bases", json={"name": "Gmock", "mode": "graphrag"})
        kb_id = r.json()["base"]["id"]
        from hermes_cli.knowledge_registry import KnowledgeRegistry

        KnowledgeRegistry().update_meta(kb_id, indexing_status="ready")
        resp = knowledge_client.post(
            "/api/knowledge/query",
            json={"kb_ids": [kb_id], "query": "hello", "graphrag_method": "global"},
        )
        assert resp.status_code == 200
        hit = resp.json()["results"][0]
        assert hit["kind"] == "graphrag"
        assert "ok:global" in hit["text"]

    def test_graphrag_two_ids_rejected(self, knowledge_client, monkeypatch):
        def fake(kb_id, q, method, **_kw):
            return {
                "kb_id": kb_id,
                "chunk_id": None,
                "text": "x",
                "source_path": None,
                "score": None,
                "kind": "graphrag",
                "graphrag_method": method,
            }

        monkeypatch.setattr("hermes_cli.knowledge_graphrag_query.query_graphrag_base", fake)
        r1 = knowledge_client.post("/api/knowledge/bases", json={"name": "Ga", "mode": "graphrag"})
        r2 = knowledge_client.post("/api/knowledge/bases", json={"name": "Gb", "mode": "graphrag"})
        id1, id2 = r1.json()["base"]["id"], r2.json()["base"]["id"]
        from hermes_cli.knowledge_registry import KnowledgeRegistry

        KnowledgeRegistry().update_meta(id1, indexing_status="ready")
        KnowledgeRegistry().update_meta(id2, indexing_status="ready")
        resp = knowledge_client.post(
            "/api/knowledge/query",
            json={"kb_ids": [id1, id2], "query": "x"},
        )
        assert resp.status_code == 400
        assert "one" in resp.json()["detail"].lower()

    def test_graphrag_drift_returns_501(self, knowledge_client):
        r = knowledge_client.post("/api/knowledge/bases", json={"name": "Gdrift", "mode": "graphrag"})
        kb_id = r.json()["base"]["id"]
        from hermes_cli.knowledge_registry import KnowledgeRegistry

        KnowledgeRegistry().update_meta(kb_id, indexing_status="ready")
        resp = knowledge_client.post(
            "/api/knowledge/query",
            json={"kb_ids": [kb_id], "query": "x", "graphrag_method": "drift"},
        )
        assert resp.status_code == 501


class TestKnowledgeDebugEmbedding:
    def test_debug_mock(self, knowledge_client, monkeypatch):
        monkeypatch.setattr(
            "hermes_cli.knowledge_embedding.embed_texts",
            lambda texts: [[0.1, 0.2, 0.3] for _ in texts],
        )
        r = knowledge_client.post("/api/knowledge/debug/embedding", json={"input": "ping"})
        assert r.status_code == 200
        out = r.json()
        assert out["ok"] is True
        assert out["dimension"] == 3
