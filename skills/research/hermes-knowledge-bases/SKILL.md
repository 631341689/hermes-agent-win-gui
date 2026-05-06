---
name: hermes-knowledge-bases
description: "Use Hermes Dashboard knowledge bases (vector FAISS + GraphRAG) from the agent: list bases, run semantic or graph search, respect indexing status."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [Research, Knowledge, RAG, Hermes, Dashboard, Vector, GraphRAG, PDF]
    related_skills: [ocr-and-documents]
---

# Hermes 知识库（向量 + GraphRAG）

在对话中**主动**使用本机 `~/.hermes`（或当前 profile）下与 **Dashboard → 知识库** 相同的数据：先列库（`knowledge_catalog` 含 **`mode`**），再对 `ready` 的 **vector** 库调用 **`knowledge_vector_query`**，或对 **graphrag** 库调用 **`knowledge_graphrag_query`**（每次**恰好一个** `kb_id`）。

## 前置条件

1. **`summary_routing_mode`（二选一）**：在 Dashboard 为每个库选择 — **`manual`**（仅手写 `agent_summary`，索引**不**跑摘要 LLM，**不**写 `routing_summary.txt`；`knowledge_catalog` 里 **`routing_summary` 恒为 null**）、**`auto`**（索引成功后由 LLM 写入 `routing_summary.txt`，手写字段不参与路由）。默认 **`auto`**。全局开关 **`knowledge.routing_summary.enabled: false`** 时，`auto` 也不会调用摘要 LLM。
2. **`routing_summary.txt`（自动生成）**：在 **`auto`** 且全局未关闭时，每次成功向量重建索引末尾由 LLM 写入 **`knowledge/bases/<kb_id>/routing_summary.txt`**。REST **`GET /bases`** 始终返回磁盘内容（便于调试）；**`knowledge_catalog`** 在 **`manual`** 下不把该文件放进 **`routing_summary`**。
3. **`agent_summary`（手写）**：注册表字段；仅在 **`manual`** 下用于 Agent 选库（配合名称）。
4. **工具**：默认 **`hermes-cli`** / **`hermes-cron`** 工具集已通过 `includes` 并入 **`knowledge`**（含 `knowledge_catalog`、`knowledge_list_bases`、`knowledge_vector_query`、`knowledge_graphrag_query`）。若你的 `toolsets` 里**没有**使用 `hermes-cli`，或显式用了其它组合，再按需加上 **`knowledge`** 工具集。
5. **向量**：需要 **embedding**（如 `OPENAI_API_KEY`）与 **FAISS**（`pip install -e ".[web,knowledge]"` 等）；不满足时 **`knowledge_vector_query`** 会从 schema 中隐藏。**GraphRAG**：需 **`[knowledge-graphrag]`** 与 **`OPENAI_*` / `GRAPHRAG_API_KEY`**；不满足时 **`knowledge_graphrag_query`** 隐藏。索引 **`auto`** 且全局未关时，重建还需 **聊天补全**。
6. 目标库 **`indexing_status` 为 `ready`**；**vector** 走 FAISS 工具，**graphrag** 走 GraphRAG 工具；未就绪时让用户在 Dashboard 上传并「重建索引」。
7. **`config.yaml` → `knowledge.retrieval`**（与 Dashboard / CLI 共用）：默认 **`two_stage: true`** — 服务端先按 **`recall_per_kb`** 加宽各库向量召回，合并去重至 **`max_candidates`**，再在候选上做 **BM25 + 向量分**混合（**`lexical_weight`** 为 BM25 权重，不是分数阈值）；**`two_stage: false`** 与早期行为一致（每库只取请求的 **`top_k`** 再合并）。工具返回里 **`score`** 为最终排序分；若启用混合，常有 **`recall_score`** 表示粗排向量分。详见 **`docs/zh/knowledge-api.md`** §1.4、§2.9、§4。

### 与联网检索（`web_search` 等）的关系

- 知识库工具**只在模型主动调用时**运行；**没有**在每轮对话前自动注入整库内容（横切 `pre_llm_call` 注入仍为规划项）。
- 检索范围是 **本机已上传并建索引的文档**，不是公网全文；需要**实时新闻、官网说明、股价**等应使用 **`web_search` / `web_extract`**（或浏览器工具），与知识库**互补**，不是二选一互斥，但**不要**用 `knowledge_vector_query` 代替公网搜索。
- 调用 `knowledge_vector_query` 时会走 **embedding API**（与 Dashboard 一致），这是访问嵌入服务端点的网络请求，与「网页搜索」不是同一路能力。

## 推荐流程（先摘要选库，再按 mode 检索）

**先读轻量路由信息，再 RAG**：**`knowledge_catalog`** 返回 **`mode`**、**`summary_routing_mode`**、**`routing_summary`**（按模式可能为 `null`）、**`agent_summary`**。按 **`hint`** 与摘要选库后：**`mode=vector`** → **`knowledge_vector_query`**（可多库）；**`mode=graphrag`** → **`knowledge_graphrag_query`**（**单次调用只能一个** `kb_id`；`graphrag_method` 常用 **`auto`**，由 `knowledge.graphrag.auto_method` 在 local/global/basic 间启发式选择，响应里带 **`resolved_graphrag_method`**）。

**与联网的关系（软性）**：若问题**有可能**落在已索引材料里，可先 **`knowledge_catalog` → 对应查询工具**，再视需要补 **`web_search` / `web_extract`**。

| 步骤 | 工具 | 说明 |
|------|------|------|
| 1 | **`knowledge_catalog`** | 含 `mode`、`summary_routing_mode`；`manual` 时只用 `agent_summary`；`auto` 用 `routing_summary` |
| 2 | `knowledge_vector_query` 或 `knowledge_graphrag_query` | vector：多 `kb_ids` + `query`；graphrag：单 id + `query` + 可选 `graphrag_method` |
| （可选） | `knowledge_list_bases` | 调试分块等完整元数据 |

若某库 **`manual`** 且 **`agent_summary`** 为空，则主要依赖 **`name`**。

- **`kb_ids` 为空**：若运行环境设置了 **`HERMES_ACTIVE_KB_IDS`**（逗号分隔），向量工具可使用多个 id；**GraphRAG 工具仅支持恰好一个 id**（多库请分次调用或显式传一个 uuid）。
- **`top_k`**（向量）：默认 8；回答时注明来源与相关性。

## 与纯网页操作的区别

- 工具走 **本机 Python 管线**（`query_vector_bases`），不经过浏览器 HTTP，适合 CLI / TUI / Gateway。
- 若用户只在 Dashboard 勾选知识库而未设置环境变量，CLI 中需**自行从列表选 id** 填入 `kb_ids`。

## 不要做的事

- 不要在 **`indexing_status` 不是 `ready`** 的库上反复查询（先提醒用户重建索引）。
- 不要把整段工具返回无筛选地贴进回答；选取与问题最相关的几条并摘要。
- 不要把知识库当成 **公网实时检索**；用户问「网上最新」「官网」时用 **`web_search`**。
