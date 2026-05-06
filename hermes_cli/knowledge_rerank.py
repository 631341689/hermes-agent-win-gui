"""Second-stage rerank for knowledge vector retrieval (BM25 + vector score blend).

No extra PyPI deps — complements dense recall with lexical overlap on the
candidate pool only (small N), then returns top_k.
"""

from __future__ import annotations

import math
import re
from typing import Any

_TOKEN_RE = re.compile(r"[A-Za-z0-9\u4e00-\u9fff]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _bm25_scores(query: str, documents: list[str], *, k1: float = 1.5, b: float = 0.75) -> list[float]:
    """BM25 scores for *documents* against *query* (corpus = candidate set only)."""
    q_terms = _tokenize(query)
    if not q_terms:
        return [0.0] * len(documents)

    doc_tokens = [_tokenize(d) for d in documents]
    doc_lens = [max(1, len(t)) for t in doc_tokens]
    avgdl = sum(doc_lens) / max(1, len(doc_lens))

    df: dict[str, int] = {}
    for terms in doc_tokens:
        seen = set(terms)
        for t in seen:
            df[t] = df.get(t, 0) + 1

    n_docs = len(documents)
    idf: dict[str, float] = {}
    for t in set(q_terms):
        f = df.get(t, 0)
        # BM25 idf (Robertson–Walker)
        idf[t] = math.log((n_docs - f + 0.5) / (f + 0.5) + 1.0)

    scores: list[float] = []
    for terms, dl in zip(doc_tokens, doc_lens):
        tf: dict[str, int] = {}
        for t in terms:
            tf[t] = tf.get(t, 0) + 1
        s = 0.0
        for t in q_terms:
            if t not in tf:
                continue
            freq = tf[t]
            denom = freq + k1 * (1.0 - b + b * (dl / avgdl))
            s += idf.get(t, 0.0) * (freq * (k1 + 1.0)) / denom
        scores.append(s)
    return scores


def _min_max_norm(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def hybrid_vector_lexical_rerank(
    query: str,
    hits: list[dict[str, Any]],
    *,
    top_k: int,
    lexical_weight: float,
) -> list[dict[str, Any]]:
    """Re-rank *hits* (each must have ``text`` and ``score`` = dense recall score).

    ``lexical_weight`` in [0, 1]: contribution of BM25 vs (1-w) dense score after
    min–max normalization on the candidate pool.
    """
    if not hits or top_k <= 0:
        return []
    w = max(0.0, min(1.0, float(lexical_weight)))
    if w <= 0.0:
        ordered = sorted(hits, key=lambda h: -float(h.get("score") or 0.0))
        return [dict(h) for h in ordered[:top_k]]

    texts = [str(h.get("text") or "") for h in hits]
    vec_raw = [float(h.get("score") or 0.0) for h in hits]
    bm_raw = _bm25_scores(query, texts)

    nv = _min_max_norm(vec_raw)
    nb = _min_max_norm(bm_raw)

    scored: list[tuple[float, dict[str, Any]]] = []
    for i, h in enumerate(hits):
        combined = (1.0 - w) * nv[i] + w * nb[i]
        out = dict(h)
        out["score"] = float(combined)
        out["recall_score"] = vec_raw[i]
        scored.append((combined, out))

    scored.sort(key=lambda x: -x[0])
    return [h for _, h in scored[:top_k]]
