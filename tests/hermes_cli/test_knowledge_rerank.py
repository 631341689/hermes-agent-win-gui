"""BM25 + dense hybrid rerank for knowledge retrieval."""

from hermes_cli.knowledge_rerank import hybrid_vector_lexical_rerank


def test_hybrid_prefers_lexical_match_when_dense_tied():
    hits = [
        {
            "chunk_id": "a",
            "kb_id": "kb1",
            "text": "unrelated fluff about cats",
            "source_path": "x",
            "score": 0.9,
        },
        {
            "chunk_id": "b",
            "kb_id": "kb1",
            "text": "product manual paragraph two details",
            "source_path": "y",
            "score": 0.88,
        },
    ]
    out = hybrid_vector_lexical_rerank(
        "paragraph two manual",
        hits,
        top_k=2,
        lexical_weight=0.6,
    )
    assert out[0]["chunk_id"] == "b"
    assert "recall_score" in out[0]


def test_lexical_weight_zero_preserves_dense_order_and_scores():
    hits = [
        {"chunk_id": "1", "kb_id": "k", "text": "a", "source_path": "s", "score": 0.5},
        {"chunk_id": "2", "kb_id": "k", "text": "b", "source_path": "s", "score": 0.9},
    ]
    out = hybrid_vector_lexical_rerank("q", hits, top_k=1, lexical_weight=0.0)
    assert len(out) == 1
    assert out[0]["chunk_id"] == "2"
    assert out[0]["score"] == 0.9
    assert "recall_score" not in out[0]
