# hermes-agent-win-gui v0.13.0 (2026-05-06)

**Fork / 分发说明**：本标签对应仓库 [hermes-agent-win-gui](https://github.com/631341689/hermes-agent-win-gui)，在 [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) 上游能力之上合并 **Dashboard 知识库** 相关改动。

## 相对上游云端的版本区分

| 项目 | 说明 |
|------|------|
| **Python 包版本** | `0.13.0`（`pyproject.toml` / `hermes_cli.__version__`） |
| **向量 RAG** | FAISS 索引、两阶段召回 + BM25 混合重排（`knowledge.retrieval`） |
| **GraphRAG** | Microsoft GraphRAG 索引与查询；可选 extra **`[knowledge-graphrag]`**（PyPI `graphrag`） |
| **MinerU** | 可选 PDF→Markdown（`knowledge.mineru` / `HERMES_MINERU_ROOT`）；本 fork 在 **`MinerU-master/MinerU-master/`** 附带上游源码树 |
| **Agent 工具** | `knowledge_catalog` / `knowledge_vector_query` / `knowledge_graphrag_query`（`toolsets` → `knowledge`） |
| **Skills** | `skills/research/hermes-knowledge-bases/` 按需加载与路由说明 |
| **文档** | `docs/zh/knowledge-api.md`、`docs/zh/graphrag-pipeline.md` |

安装示例：`pip install -e ".[web,knowledge]"`；GraphRAG：`pip install -e ".[web,knowledge,knowledge-graphrag]"`。
