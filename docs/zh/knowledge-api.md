# 知识库 Dashboard API 契约（草案）

> **状态**：草案 — **以下路径与 JSON 形状以实现仓库合并后的代码为准**。前端 Mock、后端实现变更须先更新本文档再改调用方。  
> **基路径**：`/api/knowledge`（由 `hermes dashboard` 托管的 FastAPI 应用）。  
> **鉴权**：与现有 Dashboard 一致 — 请求头 **`X-Hermes-Session-Token`**（或与既有 Bearer 兼容逻辑一致）；未携带有效令牌返回 **401**。  
> **不在** `_PUBLIC_API_PATHS` 白名单中。  
> **GraphRAG（轨道 B）**：设计与上游 API 备忘见 **`docs/zh/graphrag-pipeline.md`**（索引 `build_index`、增量、`input_documents`、查询函数等）。

---

## 1. 枚举与约定

### 1.1 `mode`（知识库类型）

| 值 | 含义 |
|----|------|
| `vector` | 分块 + FAISS 向量检索（Hermes 原生管线） |
| `graphrag` | Microsoft GraphRAG：索引产物在 **`bases/<id>/graphrag/output/`**（Parquet）；需安装 **`[knowledge-graphrag]`**。未安装依赖时 **`POST .../reindex`** 返回 **501**。详见 **`docs/zh/graphrag-pipeline.md`**。 |

### 1.2 `indexing_status`

| 值 | 含义 |
|----|------|
| `idle` | 未建索引或文件已变但未触发重建 |
| `indexing` | 正在构建索引 |
| `ready` | 索引可用 |
| `error` | 上次索引或查询失败；详见 `error_message` |

### 1.3 存储路径（服务端）

- 注册表：`{HERMES_HOME}/knowledge/registry.sqlite`  
- 每个库：`{HERMES_HOME}/knowledge/bases/<kb_id>/`（含 `raw/` 上传文件、`chunks.sqlite`、`vectors.faiss` 等）  
- **路由摘要文件**：`{HERMES_HOME}/knowledge/bases/<kb_id>/routing_summary.txt` — 在 **`summary_routing_mode`** 为 **`auto`** 且全局 `knowledge.routing_summary.enabled` 未关闭时，每次向量重建索引末尾由 LLM 生成（UTF-8）。**`manual`** 模式不写该文件；**`GET /bases`** 始终返回磁盘上的 `routing_summary`（若有）；Agent 工具 **`knowledge_catalog`** 在 **`manual`** 下将 **`routing_summary` 置为 `null`**，仅用手写 **`agent_summary`** 路由。
- **注册表字段 `summary_routing_mode`**：`manual` | `auto`（默认 **`auto`**）；`POST/PATCH /bases` 可设置。历史 **`both`** 在打开注册表时会迁移为 **`auto`**。

会话勾选外挂：**环境变量 `HERMES_ACTIVE_KB_IDS`**（逗号分隔 `kb_id`，由嵌入式 Chat PTY 注入；规划项）。

### 1.4 向量查询管线（常规检索 / 非 GraphRAG）

`POST /api/knowledge/query` 与 Agent 工具 **`knowledge_vector_query`** 共用 **`hermes_cli/knowledge_index.query_vector_bases`**：

- **`knowledge.retrieval.two_stage` = true（默认）**：**阶段一**按 `recall_per_kb` 拉宽各库 FAISS 召回并合并去重，截断至 `max_candidates`；**阶段二**在候选集上对查询句与各 chunk 文本做 **BM25**，与向量分数归一化后按 **`lexical_weight`** 线性混合，再取请求的 **`top_k`**。实现见 **`hermes_cli/knowledge_rerank.py`**。
- **`lexical_weight`** 表示 BM25 在混合分中的权重（如 `0.3` ≈ 30% BM25 + 70% 向量），**不是**命中率阈值。
- **`two_stage` = false**：与早期版本一致——每库最多取 **`top_k`** 条向量命中再全局合并截断，不做 BM25。
- 响应中 **`score`** 在两阶段且 `lexical_weight > 0` 时为混合排序分；可选 **`recall_score`** 为阶段一向量分。

---

## 2. REST 端点

### 2.1 `GET /api/knowledge/bases`

列出当前 profile 下全部知识库。

**响应 200**

```json
{
  "bases": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "我的文档",
      "mode": "vector",
      "indexing_status": "idle",
      "error_message": null,
      "created_at": "2026-05-03T12:00:00+00:00",
      "updated_at": "2026-05-03T12:00:00+00:00",
      "chunk_config": null,
      "agent_summary": null,
      "routing_summary": null,
      "summary_routing_mode": "auto"
    }
  ]
}
```

---

### 2.2 `POST /api/knowledge/bases`

创建知识库。

**请求体**

```json
{
  "name": "我的文档",
  "mode": "vector",
  "agent_summary": "一两句话说明本库内容与适用问题，供 Agent 先选库再检索（可选，类似技能描述）。",
  "summary_routing_mode": "auto"
}
```

- `name`：必填，非空字符串，建议上限 256 字符。  
- `mode`：可选，默认 `vector`；`graphrag` 需 **`[knowledge-graphrag]`**，否则重建索引返回 **501**。  
- **`agent_summary`**：可选；给模型的**手写路由摘要**（上限约 4096 字符）。  
- **`summary_routing_mode`**：可选，默认 **`auto`**；取值 **`manual`** | **`auto`**（见 §1.3）。Dashboard **知识库**页在「摘要」对话框中编辑。

**响应 201 / 200**

```json
{
  "base": {
    "id": "…",
    "name": "我的文档",
    "mode": "vector",
    "indexing_status": "idle",
    "error_message": null,
    "created_at": "…",
    "updated_at": "…"
  }
}
```

**错误**：400（校验失败）。

---

### 2.3 `GET /api/knowledge/bases/{id}`

**响应 200**：`{ "base": { … } }`  
**404**：知识库不存在。

---

### 2.4 `PATCH /api/knowledge/bases/{id}`

部分更新；未出现的字段不变。**当前实现**：若请求修改 `mode`，且当前 `indexing_status === "ready"`，返回 **400**（错误文案：`Cannot change mode while indexing_status is ready; delete index first`）。仅改名不受影响。

**请求体**（字段均可选；**空 JSON `{}`** 返回 **400** `No fields to update`）

```json
{
  "name": "新名称",
  "mode": "vector",
  "agent_summary": "更新后的摘要；传 null 可清空",
  "summary_routing_mode": "manual",
  "chunk_config": {
    "strategy": "delimiter",
    "size_tokens": 512,
    "overlap_tokens": 64,
    "delimiter": {
      "separators": ["\n\n", "\n", "。"],
      "merge_under_chars": 40,
      "max_chunk_chars": 8000
    }
  }
}
```

- **`agent_summary`**：可选；更新或清空（**`null`**）手写路由摘要。  
- **`summary_routing_mode`**：可选；切换 **`manual` / `auto`**。  
- **`chunk_config`**：仅对本知识库覆盖 `config.yaml` 的 `knowledge.chunk`；与全局配置 **深度合并**（`delimiter` / `semantic` / `smart` 子对象合并）。传 **`null`** 或 **`{}`** 表示清除覆盖（恢复仅全局默认）。  
- **`strategy`**：`window`（滑动窗口）| `delimiter`（按分隔符层级切分）| `semantic`（`semantic.mode`: `pack` 按句打包，或 `embedding` 用向量相似度与句长预算聚句；重建索引时会调用 embedding）| **`smart`**（智能分割：面向 Markdown / PDF→MD，在代码围栏外按 `#` / `##` 切块；围栏内代码、≥2 行的管道表、`![…](…)` 图片行尽量整块；过长正文再按字符滑动窗口重叠切分；可选 `smart.max_chunk_chars`、`smart.overlap_chars`，未设时分别回退 `size_tokens` 与 `overlap_tokens` 的字符换算）。  
- **校验**：非法 `strategy`、JSON 超过约 32KiB、`delimiter.separators` 列表过长等返回 **400**。

**响应 200**：`{ "base": { …, "chunk_config": … } }`（`chunk_config` 可为 `null`）  
**404**：不存在。

---

### 2.5 `DELETE /api/knowledge/bases/{id}`

删除注册表记录并递归删除 `knowledge/bases/<id>/`。

**响应 200**

```json
{ "ok": true }
```

**404**：不存在。

---

### 2.6 `POST /api/knowledge/bases/{id}/upload`

`multipart/form-data`，字段名 **`file`**（单文件）。

**限制（建议默认值，实现可配置）**

- 单文件最大 **50 MiB**（超出返回 **413**）。  
- 文件名 sanitize：禁止路径分隔符、`..`、非法字符；仅保留 basename。

**响应 200**

```json
{
  "ok": true,
  "path": "bases/<id>/raw/<filename>",
  "bytes": 12345,
  "pdf_converted_to_markdown": false
}
```

- **`pdf_converted_to_markdown`**：当上传文件为 **`.pdf`** 且已在 `config.yaml` 中启用 **MinerU**（`knowledge.mineru.enabled` + 有效 `root` / `HERMES_MINERU_ROOT`）并成功解析时，为 **`true`**。此时原始 PDF 会从 `raw/` 中删除，同目录生成 **`<stem>.md`**，图片目录 **`<stem>_mineru_images/`**（Markdown 内图片链接已改写为相对该目录）。后续分块/索引只处理 Markdown。未启用或解析失败时保持 PDF，`path` / `bytes` 仍对应上传文件。  
  **权重来源**：若配置了 **`knowledge.mineru.local_models`**（或 **`HERMES_MINERU_LOCAL_PIPELINE` / `HERMES_MINERU_LOCAL_VLM`**）且路径为已存在的目录，Hermes 会强制 **`MINERU_MODEL_SOURCE=local`** 并注入与 `~/mineru.json` 中 **`models-dir`** 相同语义的本地根路径，**不再联网下载**版面/OCR/VLM 权重。默认 **`auto_local_models_from_mineru_json: true`**：若你已在用户目录写好 **`mineru.json`**（例如 `mineru-models-download` 成功后的「The configuration file has been successfully configured」），且其中 **`models-dir.pipeline` / `vlm`** 指向的目录存在，Hermes 会自动复用，无需在 `config.yaml` 里重复填路径。设为 `false` 可关闭该探测。  
  **关于下载日志里的 “Fail”**：在 Windows 上 ModelScope 有时会尝试创建**符号链接**（如 `PDF-Extract-Kit-1.0` 指向带版本后缀的目录），无管理员权限或未开启「开发人员模式」时可能打出 **Fail to create symlink** 一类信息；只要后续仍显示 **100% / Finish downloading** 且 `mineru.json` 已写入，模型文件通常已在 `~/.cache/modelscope/hub` 下，可忽略该 symlink 失败。  
  未命中上述本地路径时，仍由 `model_source`（`huggingface` \| `modelscope` \| `local`）决定；与 Hermes 对话用的 `model` 不是同一概念。  
  **LLM 辅助标题**（MinerU `title_aided`）：默认 `llm_aided_use_hermes_openai: true` 时，按 **`knowledge.mineru.llm_aided_model.provider`** 读密钥：`openai` → `OPENAI_*`；`deepseek` → `DEEPSEEK_*`。模型名为 **`llm_aided_model.default`**；若为空则回退 **`config.yaml` 顶层 `model`**（可为字符串，或与主对话相同的 **`model: { provider, default }`** 结构，取其中的 `default`）。未配置对应密钥或模型名时跳过该步（仍可得到 Markdown）。`llm_aided_use_hermes_openai: false` 时改读上游 `mineru.json` 的 `llm-aided-config`。

上传成功后可将 `indexing_status` 置为 `idle`（表示需重建）。  
**404**：知识库不存在。

---

### 2.6b `DELETE /api/knowledge/bases/{id}/raw`

删除该库 **`bases/<id>/raw/`** 下全部文件与子目录，并重建空的 **`raw/`**；**不删除**注册表记录与 **`graphrag/`**、向量索引等产物。用于 Dashboard「整套替换」流程：清空物料后再上传新文件。

**响应 200**

```json
{ "ok": true, "removed_files": 42 }
```

- **`removed_files`**：删除前统计的大致文件数（用于观测）。  
- 成功后注册表 **`indexing_status`** 置为 **`idle`**（需重建索引）。  
**404**：知识库不存在。

---

### 2.7 `POST /api/knowledge/bases/{id}/reindex`（轨道 A/B）

触发索引构建；请求体可为空 JSON `{}`。线程池内跑分块、embedding 与 FAISS 写入；完成后返回最新 `base` 与统计。

- **`full`**（query，**仅 `mode=graphrag`**）：**`0`**（默认）— 若已有 **`graphrag/output/entities.parquet`** 则走上游 **增量**索引；**`1`** — **强制全量**重建（`force_full`，忽略既有输出上的增量路径）。向量库忽略该参数。
- **默认**（无 query）：**同步 JSON** 响应（整段请求结束后一次性返回下方 JSON）。  
- **`?stream=1`**：**SSE**（`text/event-stream`），与上传 `?stream=1` 相同帧格式：`data: {JSON}\n\n`。事件包括：  
  - `{"event":"heartbeat"}` — 长耗时阶段保活；  
  - `{"event":"progress","phase":"chunking",...}` — 分块进度（`current` / `total` / `path`）；  
  - `{"event":"progress","phase":"embedding","chunk_count":N}`；  
  - `{"event":"progress","phase":"writing_index"}`；  
  - 成功末尾 `{"event":"final","base":{...},"stats":{...}}`；失败 `{"event":"error","message":"..."}`；用户终止或客户端断开导致协作取消时 `{"event":"cancelled","message":"..."}`（无 `final`）。  

**索引是否替换**：每次成功重建都会**重新生成**该库下的 `chunks.sqlite`、`vectors.faiss` 与 `vector_manifest.json`（空库时会删除旧的 FAISS/SQLite 并写入零条 manifest）。因此 **`indexing_status` 已是 `ready` 时再次点击重建仍然有效**，会按当前 `raw/` 与分块策略覆盖旧向量索引。

**响应 200**（非流式）

```json
{
  "base": {
    "id": "…",
    "name": "…",
    "mode": "vector",
    "indexing_status": "ready",
    "error_message": null,
    "created_at": "…",
    "updated_at": "…"
  },
  "stats": {
    "chunk_count": 42,
    "embedding_model": "text-embedding-3-small",
    "dimension": 1536
  }
}
```

- **向量模式**：分块 + embedding（`config.yaml` 的 `knowledge.embedding` + 环境变量 `OPENAI_API_KEY` / `OPENAI_BASE_URL`）+ FAISS。  
- **GraphRAG 模式**：未实现时返回 **501** + `detail` 说明。  
- **依赖缺失**（如 FAISS/NumPy ABI 问题）：可能返回 **501**，`detail` 为可读错误信息。

---

### 2.8 `POST /api/knowledge/debug/embedding`（前置调试）

在正式 `reindex` 前验证 OpenAI 兼容端点能否完成一次 embedding 调用；**不返回**原始向量（避免日志泄露）。

**请求体**

```json
{ "input": "测试文本" }
```

**响应 200**

```json
{
  "ok": true,
  "model": "text-embedding-3-small",
  "dimension": 1536,
  "base_url_set": true
}
```

**错误**：400（缺密钥、模型名非法等）；502（上游不可达等）。

---

### 2.9 `POST /api/knowledge/query`（调试 / 外挂检索）

**请求体**

```json
{
  "kb_ids": ["550e8400-e29b-41d4-a716-446655440000"],
  "query": "用户问题原文",
  "top_k": 8,
  "graphrag_method": "local"
}
```

- **`top_k`**：仅 **`mode=vector`** 时生效；GraphRAG 单库查询忽略（保留字段仅为共用请求体）。  
- **`graphrag_method`**（可选）：当所选知识库均为 **`graphrag`** 且 **`indexing_status=ready`** 时使用；取值 **`local`** | **`global`** | **`basic`**。缺省时读取 **`knowledge.graphrag.query_method`**（默认 **`local`**）。**`drift`** 暂未实现，请求将返回 **501**。  
- **混选**：同一请求中 **`kb_ids` 不得同时包含 vector 与 graphrag**；GraphRAG 调试路径 **仅支持单个 `kb_id`**（多库返回 **400**）。

**响应 200（向量模式示意）**

```json
{
  "results": [
    {
      "chunk_id": "…",
      "text": "片段正文…",
      "source_path": "bases/…/raw/doc.md",
      "score": 0.82,
      "kb_id": "550e8400-e29b-41d4-a716-446655440000",
      "recall_score": 0.79
    }
  ]
}
```

**响应 200（GraphRAG 模式，单条合成答案）**

```json
{
  "results": [
    {
      "kb_id": "550e8400-e29b-41d4-a716-446655440000",
      "chunk_id": null,
      "text": "模型根据 GraphRAG 检索上下文生成的完整回答…",
      "source_path": null,
      "score": null,
      "kind": "graphrag",
      "graphrag_method": "local"
    }
  ]
}
```

- **`score`**：当 `knowledge.retrieval.two_stage` 为 **true**（默认）且 `lexical_weight` &gt; 0 时，为 **BM25 + 向量分数混合**后的最终排序分（0–1 量级，与旧版原始 cosine IP 不可直接对比）。  
- **`recall_score`**（可选）：同一命中在 **仅向量粗排** 阶段的分数，便于对照。`lexical_weight: 0` 时行为与旧版一致，结果中通常不含该字段。

**`config.yaml` → `knowledge.retrieval`（常规向量，不含 GraphRAG）**

| 键 | 默认 | 含义 |
|----|------|------|
| `two_stage` | `true` | `false` 时完全退回旧逻辑（每库只取 `top_k` 条再合并）。 |
| `recall_per_kb` | `48` | 阶段一每库 FAISS 召回条数（下限为 `top_k`，上限 128）。 |
| `max_candidates` | `96` | 合并去重后进入重排的最大候选数（上限 256）。 |
| `lexical_weight` | `0.3` | **BM25 在混合分中的权重**（与向量分归一化后加权：`0` = 只用向量排序，`1` = 只用 BM25）；**不是**「分数门槛」或最低相似度。 |

GraphRAG 查询实现见 **`hermes_cli/knowledge_graphrag_query.py`**（加载 **`bases/<id>/graphrag/output/*.parquet`** 并调用上游 **`graphrag.api`**）。未安装 **`[knowledge-graphrag]`** 时 **`POST /query`** 对 graphrag 库返回 **501**。

---

## 3. HTTP 错误码汇总

| 状态码 | 场景 |
|--------|------|
| 401 | 未授权 |
| 400 | 参数或文件名非法 |
| 404 | 知识库不存在 |
| 413 | 上传过大 |
| 501 | GraphRAG 等功能未启用（可选） |
| 500 | 服务器内部错误 |

---

## 4. 配置与环境变量（与 `config.yaml` 对齐）

实现阶段在 `DEFAULT_CONFIG` 中增加 `knowledge` 节，示意：

```yaml
knowledge:
  enabled: true
  attach_strategy: auto   # auto | off | tool_only（后续）
  mineru:
    enabled: false
    # MinerU 源码根目录（内含 mineru 包），例如 .../MinerU-master/MinerU-master
    root: ""
    backend: pipeline       # pipeline | vlm-* | hybrid-*（与上游 MinerU 一致）
    parse_method: auto
    lang: ch
    model_source: huggingface   # 未配置 local_models 时：huggingface | modelscope | local
    # 已用 ModelScope/HF 提前下载到本机时填写绝对路径；填写后 Hermes 会强制走 local，不再联网拉权重
    auto_local_models_from_mineru_json: true  # 为 true 且未填 local_models 时，尝试读 ~/mineru.json 的 models-dir
    local_models:
      pipeline: ""   # 如 ModelScope 缓存下 OpenDataLab/PDF-Extract-Kit-* 目录
      vlm: ""        # pipeline 后端可留空；vlm / hybrid 需填 VLM 模型目录
    llm_aided_use_hermes_openai: true
    # 与顶层 model 块同形：仅作用于 MinerU 标题辅助；可与主对话（如 deepseek）不同
    llm_aided_model:
      provider: openai
      default: gpt-4o-mini      # 空则回退顶层 model / model.default
  embedding:
    provider: ""
    model: ""
  chunk:
    strategy: window   # window | delimiter | semantic | smart
    size_tokens: 512
    overlap_tokens: 64
    smart:
      max_chunk_chars: null   # 可选；omit 时用 size_tokens 换算
      overlap_chars: null     # 可选；omit 时用 overlap_tokens 换算
  # 向量查询：加宽召回 + 候选集 BM25/向量混合重排（实现：knowledge_index + knowledge_rerank）
  retrieval:
    two_stage: true           # false = 完全退回旧逻辑（每库仅 top_k 条再合并）
    recall_per_kb: 48         # 阶段一每库 FAISS 条数（下限 top_k，上限实现侧封顶）
    max_candidates: 96        # 合并去重后参与重排的上限
    lexical_weight: 0.3       # BM25 权重；0 = 仅向量（仍可两阶段加宽召回）
  graphrag:
    query_method: local       # 预留：DEBUG query / Agent 封装 local | global | basic | drift
    indexing_method: standard # standard | fast（映射上游 IndexingMethod）
    completion_model: ""      # 空 → 顶层 model / routing_summary.model；首次初始化 GraphRAG settings.yaml 用
    embedding_model: ""       # 空 → knowledge.embedding.model
  # 向量重建成功后：抽样分块 → 调用聊天模型写 routing_summary.txt（与 embedding 共用 OPENAI_*）
  routing_summary:
    enabled: true
    model: ""              # 空则回退顶层 model.default / model 字符串；如 gpt-4o-mini
    max_source_chars: 24000
    max_output_chars: 900
    max_completion_tokens: 320
```

环境变量：

| 变量 | 说明 |
|------|------|
| `HERMES_ACTIVE_KB_IDS` | 嵌入式 Chat 当前勾选的知识库 ID，逗号分隔 |
| `HERMES_MINERU_ROOT` | 可选；覆盖 `knowledge.mineru.root`（MinerU 检出根路径） |
| `HERMES_MINERU_LOCAL_PIPELINE` | 可选；覆盖 `local_models.pipeline`（pipeline/hybrid 用） |
| `HERMES_MINERU_LOCAL_VLM` | 可选；覆盖 `local_models.vlm`（vlm/hybrid 用） |

**CLI / TUI（默认 `toolsets` 含 `hermes-cli`）**：已随 **`hermes-cli`** / **`hermes-cron`** 一并包含 **`knowledge`** 工具集：**`knowledge_catalog`**（轻量目录：`routing_summary` 文件摘要 + `agent_summary`，建议先调用）、**`knowledge_list_bases`**（含 `chunk_config` 的完整元数据）、**`knowledge_vector_query`**（向量库）、**`knowledge_graphrag_query`**（GraphRAG 单库；`graphrag_method` 含 **`auto`**，规则见 **`knowledge.graphrag.auto_method`**）。其它自定义 `toolsets` 组合若未引用 `hermes-cli`，可再单独加入 **`knowledge`**。`kb_ids` 为空时读取 **`HERMES_ACTIVE_KB_IDS`**（GraphRAG 工具要求**恰好一个** id）。流程说明见 **`skills/research/hermes-knowledge-bases/SKILL.md`**。

---

## 5. 依赖安装（开发）

```bash
pip install -e ".[web,knowledge]"
```

- **`[knowledge]`**：向量索引（含 `faiss-cpu` 等）；见根目录 `pyproject.toml`；extra 内将 **NumPy 约束为 `numpy<2`**，以降低与部分 `faiss-cpu` wheel 的 ABI 不兼容风险。  
- 若本机已装 **NumPy 2.x** 且 FAISS 在 `import faiss` 或建索引时报错，请使用独立 venv 并 `pip install -e ".[web,knowledge]"`，勿与旧全局包混用。  
- **GraphRAG**：`pip install -e ".[web,knowledge,knowledge-graphrag]"`（`pyproject` extra **`[knowledge-graphrag]`**，引入 **`graphrag`**）。亦可本地 editable 安装 vendor **`graphrag-main`**；流程说明 **`docs/zh/graphrag-pipeline.md`**。

---

## 6. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-05-03 | 初版草案（前置文档） |
| 2026-05-03 | 轨道 A：挂载 `/api/knowledge`；`PATCH` ready 态禁改 `mode`；`reindex` 暂返回 501 |
| 2026-05-03 | 轨道 A：`reindex` 返回 `stats`；新增 `POST /debug/embedding`；`query` 结果含 `kb_id`；依赖说明（NumPy/FAISS） |
| 2026-05-03 | 轨道 A：`PATCH` 支持 `chunk_config`；`strategy` window/delimiter/semantic；注册表列 `chunk_config` |
| 2026-05-03 | 分块策略增加 **`smart`（智能分割）**；`chunk_config.smart`；`knowledge.chunk.smart` 默认键 |
| 2026-05-03 | `reindex?stream=1`：SSE 分块 / 嵌入 / 写库进度；文档说明重建会覆盖旧索引文件 |
| 2026-05-03 | 工具集 **`knowledge`**：`knowledge_list_bases` / `knowledge_vector_query`；技能 `hermes-knowledge-bases` |
| 2026-05-03 | 注册表 **`agent_summary`**；API 创建/PATCH；工具 **`knowledge_catalog`**（先摘要选库再 `knowledge_vector_query`） |
| 2026-05-03 | 索引结束生成 **`bases/<id>/routing_summary.txt`**；`routing_summary` 字段；`knowledge.routing_summary` 配置 |
| 2026-05-03 | 注册表 **`summary_routing_mode`**（manual/auto；弃用 both→auto）；`knowledge_catalog` 在 manual 下隐藏 `routing_summary` |
| 2026-05-03 | 轨道 A：可选 MinerU PDF→Markdown 上传管线；`pdf_converted_to_markdown`；`knowledge.mineru` |
| 2026-05-03 | MinerU：`model_source`；`title_aided` 复用 Hermes `OPENAI_*` 与 `model` / `llm_aided_model` |
| 2026-05-03 | MinerU：`llm_aided_model` 为 `{ provider, default }`；支持 `DEEPSEEK_*`；顶层 `model` 可为对象 |
| 2026-05-03 | MinerU：`local_models` + 环境变量；预下载权重时强制 `local` 并注入 `models-dir` |
| 2026-05-03 | MinerU：`auto_local_models_from_mineru_json`；自动读 `~/mineru.json` 的 `models-dir`；说明 Windows symlink 日志 |
| 2026-05-04 | **`knowledge.retrieval`**：默认两阶段检索（加宽 FAISS + BM25/向量混合）；`two_stage: false` 恢复旧行为；响应可选 **`recall_score`** |
| 2026-05-04 | GraphRAG：`[knowledge-graphrag]`；**`mode=graphrag`** 时 **`POST .../reindex`** 调用上游 **`build_index`**（无依赖仍 **501**）；备忘 **`docs/zh/graphrag-pipeline.md`** |
| 2026-05-03 | GraphRAG：**`POST /query`** 支持 **`graphrag_method`**（local/global/basic）；单库、禁 vector+graphrag 混选；**`drift`** → **501**；实现 **`hermes_cli/knowledge_graphrag_query.py`**；`knowledge.graphrag.community_level` |
| 2026-05-04 | Agent：**`knowledge_graphrag_query`**（单 GraphRAG 库；**`graphrag_method`** 含 **auto**，规则 **`knowledge.graphrag.auto_method`**）；工具集 **`knowledge`** 已注册 |
