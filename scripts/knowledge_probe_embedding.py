#!/usr/bin/env python3
"""Probe OpenAI-compatible embeddings using ~/.hermes/.env (OPENAI_*).

Usage (from repo root, with venv activated):
  python scripts/knowledge_probe_embedding.py
  python scripts/knowledge_probe_embedding.py "你的测试句"
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo not in sys.path:
        sys.path.insert(0, repo)

    from hermes_cli.knowledge_embedding import KnowledgeEmbeddingError, probe_embedding

    text = (sys.argv[1] if len(sys.argv) > 1 else "测试文本").strip() or "测试文本"
    try:
        info = probe_embedding(text)
    except KnowledgeEmbeddingError as exc:
        print("ERROR:", exc, file=sys.stderr)
        return 1
    except Exception as exc:
        print("ERROR:", type(exc).__name__, exc, file=sys.stderr)
        return 2
    print("OK:", info)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
