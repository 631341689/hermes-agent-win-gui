# Hermes × Microsoft GraphRAG — 流程与接口梳理

> **目的**：为轨道 B 开发提供单一技术备忘：上游 GraphRAG 在做什么、有哪些稳定编程接口、Hermes 如何在 **`bases/<kb_id>/`** 下挂载工作区，以及与向量轨道（MinerU、`routing_summary`、增量）的关系。  
> **契约入口**：REST 仍以 **`docs/zh/knowledge-api.md`** 为准；本文不替代 API 草案，实现变更时需双向同步。

---

## 1. 上游 GraphRAG 在仓库中的位置

**推荐**：`pip install "graphrag>=3.0.9,<4"`（本仓库 **`[knowledge-graphrag]`** extra）。若需对照源码，可在本机任意目录 **clone** 官方单体仓库（与 PyPI **`graphrag`** 包同源结构），例如本地路径 **`graphrag-main/graphrag-main/`**（该路径默认 **不** 随 Hermes 仓库提交，见根目录 **`.gitignore`**）。

| 组件 | 路径 / 说明 |
|------|-------------|
| 索引进口 | **`packages/graphrag/graphrag/api/index.py`** — **`build_index(...)`** |
| 查询入口 | **`packages/graphrag/graphrag/api/query.py`** — **`global_search`**, **`local_search`**, **`basic_search`**, **`drift_search`**（及 streaming 变体） |
| 工程初始化 | **`packages/graphrag/graphrag/cli/initialize.py`** — **`initialize_project_at(...)`** 写入 **`settings.yaml`**、**`.env`**、**`prompts/`** |
| 增量合并工具 | **`packages/graphrag/graphrag/index/update/incremental_index.py`** — **`get_delta_docs`**（按 **`documents.title`** 比较新增/删除） |
| 管线调度 | **`packages/graphrag/graphrag/index/run/run_pipeline.py`** — **`is_update_run`**、`**input_documents**` 注入时跳过 **`load_input_documents` / `load_update_documents`** |
| 官方文档 | **`graphrag-main/graphrag-main/docs/`**（如 **`get_started.md`**, **`index/architecture.md`**, **`config/yaml.md`**） |

**Python 版本**：上游包声明 **`>=3.11,<3.14`**（与 Hermes **≥3.11** 对齐）。安装方式：`pip install "graphrag>=3.0.9,<4"`（**`[knowledge-graphrag]`** extra）或使用本地 editable 安装 vendor 单体仓库。

---

## 2. 索引管线（全量 vs 增量）

### 2.1 概念流程（标准方法）

与官方 **`docs/index/architecture.md`** 一致，核心阶段包括：**加载文档 → 分块 → 构图抽取（实体/关系/可选声明）→ 社区检测 → 社区报告 → 嵌入** 等（Fast 方法用 NLP 替代部分 LLM 构图）。

**默认产物**：**Parquet 表**写在配置的 **`output_storage.base_dir`**（常见为工程根下 **`output/`**），例如 **`entities.parquet`**、**`relationships.parquet`**、**`communities.parquet`**、**`community_reports.parquet`**、**`text_units.parquet`** 等 — **不是**必须先部署 Neo4j。

### 2.2 编程接口：`build_index`

```text
graphrag.api.build_index(
    config: GraphRagConfig,
    method: IndexingMethod | str = Standard | Fast | ...,
    is_update_run: bool = False,
    callbacks: list[WorkflowCallbacks] | None = None,
    additional_context: dict | None = None,
    verbose: bool = False,
    input_documents: pd.DataFrame | None = None,
) -> list[PipelineRunResult]
```

要点：

- **`is_update_run=False`**：全量索引；内部管线名为 **`standard`** / **`fast`** 等。
- **`is_update_run=True`**：增量；内部会将方法切换为 **`standard-update`** / **`fast-update`**（见 **`api/index.py`** 的 **`_get_method`**）。
- **`input_documents`**：若提供，则会 **预先写入 `documents` 表** 并从管线中 **移除** 对应的加载步骤（全量时去掉 **`load_input_documents`**，增量时去掉 **`load_update_documents`**），适合 Hermes **直接从 `raw/` 组表**、避免再维护一份 `input/` 拷贝。

### 2.3 增量语义（与 Hermes `raw/` 对齐）

- 上游 **`get_delta_docs`** 用 **`documents.title`** 作为稳定键：  
  - 输入里 **新的 title** → 新文档；  
  - 上一索引里有、本次输入里没有的 title → 视为删除。  
- **Hermes 约定**：**`title` = `raw/` 下相对路径**（POSIX 风格，与 **`iter_raw_documents`** 的 `rel` 一致），保证「同名路径」在多次索引间稳定，增量判定才可靠。
- **前提**：增量必须在 **已有完整输出**（例如已有 **`output/entities.parquet`**）的前提下运行；首次建立索引始终是全量。

### 2.4 `update_output_storage`

**`docs/config/yaml.md`** 中的 **`update_output_storage`**：增量运行时可使用 **次要存储** 再合并回主输出，避免破坏已有产物。Hermes 可在后续迭代将用户配置模板化；首版可采用上游默认，仅在文档中保留扩展点。

---

## 3. 查询接口（调试 / Agent 封装预留）

查询函数均在 **`graphrag.api.query`**，签名模式为：（**`config`**）+ **从索引输出的 DataFrame 读入的表**（**`entities`**, **`communities`**, **`community_reports`** 等）+ **查询字符串** + 若干策略参数。

| 函数 | 典型用途 |
|------|----------|
| **`global_search`** | 全局/高层概括性问题（地图-归约社区报告） |
| **`local_search`** | 围绕局部实体与文本单元的细化问题 |
| **`basic_search`** | 更偏「向量/文本单元」的基线检索（具体行为以上游实现为准） |
| **`drift_search`** | Drift 变体（见上游文档） |

**说明**：这些是 **async** API；Hermes 在同步 HTTP 处理器中需 **`asyncio.run`** 或后台任务封装。  
**与向量轨道的关系**：**`knowledge.retrieval`**（两阶段 FAISS + BM25）**仅适用于 `mode=vector`**；GraphRAG 查询配置建议单独落在 **`knowledge.graphrag.*`**（已有 **`query_method`** 占位），避免语义混用。

---

## 4. Hermes 挂载策略（与规划文档一致）

### 4.1 目录布局

对每个 **`kb_id`**：

- **`{HERMES_HOME}/knowledge/bases/<kb_id>/raw/`** — 与向量库 **共用**（上传、MinerU PDF→MD **不变**）。
- **`{HERMES_HOME}/knowledge/bases/<kb_id>/graphrag/`** — GraphRAG **工程根**（**`settings.yaml`**、**`.env`**、**`prompts/`**、**`output/`**、**`cache/`** 等），由 **`initialize_project_at`** 或 Hermes 首次索引时惰性创建。

### 4.2 配置与环境

- 首次在无 **`settings.yaml`** 时调用 **`initialize_project_at`**（近年 PyPI 版仅为 **`(path, force)`**；旧版另有 **`model` / `embedding_model`** 关键字）。Hermes 用 **`inspect.signature`** 兼容两种签名；新建完成后若模板未写入所选模型，则用 PyYAML 修补 **`models.default_chat_model.model`** / **`default_embedding_model.model`**（或旧式 **`completion_models` / `embedding_models`**）以对齐 **`knowledge.graphrag`** 与 **`knowledge.embedding`**。
- 运行时若未设置 **`GRAPHRAG_API_KEY`**，Hermes 可回退 **`OPENAI_API_KEY`**（与 Dashboard 常见部署一致）。**Azure / 自定义 base_url** 需通过生成的 **`settings.yaml`** 或上游支持的 env 对齐（首版可在运维文档中标明「需手改 settings」）。

### 4.3 路由摘要（`routing_summary`）

与向量库一致：**`agent_summary` / `summary_routing_mode`** 注册表字段不变；**`auto`** 时可在索引成功后，用 **`raw/` 抽样文本**（或后续用社区报告摘录）调用现有 **`knowledge.routing_summary`** LLM 管线写入 **`routing_summary.txt`**，供 **`knowledge_catalog`** 使用。

---

## 5. REST 映射（实现迭代清单）

| Hermes 端点 | GraphRAG 行为（目标） |
|-------------|----------------------|
| **`POST .../reindex`** | 无索引产物 → **`build_index(..., is_update_run=False)`**；已有产物 → **`is_update_run=True`**（后续可增加 **`?full=1`** 强制全量）。 |
| **`POST .../query`** | 扩展 **`method`**：**`global`** / **`local`** / **`basic`** / **`drift`**；仅 **`kb_ids`** 指向 **`mode=graphrag`** 且 **`ready`** 时走 GraphRAG。 |
| **`POST .../upload`** | 不变；仅将物料写入 **`raw/`**。 |

---

## 6. 风险与后续工作

- **依赖体积**：`graphrag` 引入 **pandas**、Azure SDK、分块/向量子包等；CI 默认可不安装 **`[knowledge-graphrag]`**，相关测试用 **`pytest.importorskip("graphrag")`** 或 **`integration`** 标记。  
- **取消与 SSE**：上游管线取消需 **`WorkflowCallbacks`** 级协作；可与向量 SSE **分阶段**对齐。  
- **OPENAI_BASE_URL**：若与上游默认 OpenAI 端点不一致，需在 **`settings.yaml`** 中为 completion/embedding 配置 **`api_base`**（具体键名以上游 **`GraphRagConfig`** 为准）。

---

## 7. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-05-04 | 初稿：索引/查询 API、`input_documents` 与增量语义、Hermes 目录与 REST 映射 |
