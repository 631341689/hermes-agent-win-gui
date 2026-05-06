# hermes-agent-win-gui

在 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 上游基础上的自用维护分支：**可在纯 Windows 环境下本地运行**，带 **浏览器中的 Web 仪表盘（Dashboard）**，并包含对 **飞书（Lark）交互卡片审批** 等场景的适配与修复说明。

---

## 界面预览（Web Dashboard）

以下为 **Windows 本机** 运行仪表盘后的示意（侧边栏、终端区、模型与工具状态等）。

![Hermes Web Dashboard on Windows](assets/readme-dashboard-windows.png)

---

## 本仓库在做什么

| 方向 | 说明 |
|------|------|
| **纯 Windows** | 使用 **PowerShell + Python 虚拟环境** 安装与运行，无需 WSL 即可使用 CLI、Dashboard、网关等能力（具体能力取决于你安装的 pip extra）。 |
| **可视化** | 通过下方 **`dashboard`** 命令在浏览器中打开管理界面（配置、会话、内嵌 Chat 等）。 |
| **消息网关** | 通过 **`gateway run`** 前台运行网关，连接飞书 / Telegram 等平台时需安装 **`[messaging]`** 或 **`[feishu]`** 等依赖，并完成开放平台机器人配置。 |
| **知识库** | 在 Dashboard 侧栏打开 **「知识库」**，管理 **向量（FAISS）** 与 **GraphRAG** 库；数据在 **`{HERMES_HOME}/knowledge/`**（默认即 **`%USERPROFILE%\.hermes\knowledge\`**）。除安装 **`[web,knowledge]`**（及可选 **`[knowledge-graphrag]`**）外，请配置 **`.env` 密钥**与 **`config.yaml`** 中的 **`terminal.cwd`**、**`knowledge.mineru` / `retrieval`**、**`web.backend`** 等，可直接照抄 **[安装与启动指南](docs/zh/安装与启动指南.md)** 文内 **第 6.1–6.3 节**示例；REST 与行为说明见 **[knowledge-api.md](docs/zh/knowledge-api.md)**，GraphRAG 与上游对照见 **[graphrag-pipeline.md](docs/zh/graphrag-pipeline.md)**。 |
| **分发版本** | 当前发布线：**v0.13.0**。相对上游主线，本分支合并了 **Dashboard 知识库**（向量 RAG + **GraphRAG**）、**MinerU** 可选 PDF→Markdown、**`knowledge_*` 工具集**与 **`skills/research/hermes-knowledge-bases/`** 按需加载说明；安装见 **`pip install -e ".[web,knowledge]"`**，GraphRAG 见 **`[knowledge-graphrag]`**，契约 **`docs/zh/knowledge-api.md`**。 |

更细的排障与发布清单见：**[docs/zh/安装与启动指南.md](docs/zh/安装与启动指南.md)**（含 **`.env` / `config.yaml`** 快速配置）。  
目录与开发约定见：**[AGENTS.md](AGENTS.md)**。

---

## 环境要求（Windows）

- **Windows 10 / 11**（64 位）
- **Python** ≥ 3.11（安装时勾选 *Add python.exe to PATH* 更方便）
- **Git**（克隆本仓库）
- **Node.js** ≥ 20：仅当你需要 **单独开发 / 构建 `web/` 前端** 或 **`ui-tui/`** 时再装

---

## 安装环境

在 **仓库根目录**（含有 `pyproject.toml`）打开 **PowerShell**。

### 1. 创建并激活虚拟环境

下面示例使用目录名 **`venv`**。若你习惯用 **`.venv`**，请把路径里的 `venv` 改成 `.venv`。

```powershell
cd D:\path\to\hermes-agent-win-gui
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -U pip setuptools wheel
```

若提示无法执行脚本，可先执行：`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`。

### 2. 安装 Hermes（可编辑安装）

**推荐**（Web 仪表盘 + 内嵌终端所需依赖，含 Windows **pywinpty**）：

```powershell
pip install -e ".[web]"
```

若使用 **Dashboard 知识库**（向量索引 / FAISS / 可选 MinerU PDF→Markdown），请额外安装 **`[knowledge]`**（与文档 `docs/zh/knowledge-api.md` 一致；`faiss-cpu` 常见 wheel 需 **NumPy 1.x**）：

```powershell
pip install -e ".[web,knowledge]"
```

若还要跑 **飞书 / Telegram 等消息网关**，建议一并安装（体积更大）：

```powershell
pip install -e ".[web,messaging,feishu]"
```

仅核心 CLI（无 Dashboard）：

```powershell
pip install -e "."
```

安装完成后检查：

```powershell
.\venv\Scripts\hermes.exe --help
```

### 3. 首次配置

```powershell
.\venv\Scripts\hermes.exe setup
```

- 配置与 **`%USERPROFILE%\.hermes`**（或环境变量 **`HERMES_HOME`**）下的 `config.yaml`、`.env` 相关。  
- **API Key、Token 只写入 `HERMES_HOME\.env`**，不要提交到 Git（仓库已用 `.gitignore` 忽略 `.env`）。

```powershell
.\venv\Scripts\hermes.exe doctor
```

---

## 启动（两条常用命令）

以下均假设当前目录为项目根，且虚拟环境在 **`venv`**（否则请改路径）。

### ① Web 仪表盘（指定端口 9120）

```powershell
.\venv\Scripts\hermes.exe dashboard --no-open --port 9120
```

在浏览器打开：**http://127.0.0.1:9120**（若改了 `--host` 则以实际为准）。

### ② 消息网关（前台 + 详细日志）

```powershell
.\venv\Scripts\hermes.exe gateway run -v
```

**说明（当前环境经验）：** 在 **纯 Windows** 下，网关进程 **目前需要以「管理员身份」运行 PowerShell / 终端**，再执行上述 `gateway run` 命令，否则可能因权限或端口策略无法正常监听。**Dashboard 一般无需管理员**。

---

## 其它常用命令

```powershell
.\venv\Scripts\hermes.exe                    # 经典交互 CLI
.\venv\Scripts\hermes.exe model              # 选择模型与供应商
.\venv\Scripts\hermes.exe tools              # 工具开关
.\venv\Scripts\hermes.exe --tui            # 终端 TUI（需按文档构建 ui-tui）
```

---

## 知识库（Dashboard · 向量模式与 GraphRAG 模式）

本节汇总：**两种知识库模式**的能力、**环境与依赖**、**配置文件**、存储位置及与本分支相关的 **Dashboard / 工具**行为。  
更细的 REST 契约、上传限制与 MinerU 细节见：**[docs/zh/knowledge-api.md](docs/zh/knowledge-api.md)**；GraphRAG 与上游管线对照见：**[docs/zh/graphrag-pipeline.md](docs/zh/graphrag-pipeline.md)**。

### 两种模式对照

| 项目 | **向量模式 `vector`** | **GraphRAG 模式 `graphrag`** |
|------|------------------------|------------------------------|
| **用途** | 分块 + 嵌入 + **FAISS** 检索；适合常规文档问答、与 **`knowledge.retrieval`**（两阶段向量 + 可选 BM25）配合。 | Microsoft **GraphRAG**：实体/关系/社区报告等管线，产物为 **`bases/<id>/graphrag/output/`** 下 Parquet（无需必先部署 Neo4j）。 |
| **Python 依赖** | **`[knowledge]`**（`faiss-cpu`、`numpy<2`、`pypdf` 等） | 在向量依赖基础上增加 **`[knowledge-graphrag]`**（`graphrag>=3.0.9,<4`） |
| **未装依赖时** | 知识库 FAISS 相关 API 不可用 | 创建库可选，但 **`POST .../reindex`** 对 GraphRAG 库返回 **501** |
| **物料目录** | 与其它库相同：**`raw/`** 存上传文件；向量索引写在库目录下（如 `chunks.sqlite`、`vectors.faiss`） | **`raw/`** 与向量库相同；工程根在 **`graphrag/`**（`settings.yaml`、`output/`、`prompts/` 等） |
| **Dashboard** | 上传、分块策略、重建索引（SSE 进度）、检索调试（向量） | 同上上传；重建索引走 GraphRAG **`build_index`**（SSE 进度）；检索调试可选 **local / global / basic**（及 Agent 侧 **`auto`** 启发式） |
| **Agent 工具** | **`knowledge_vector_query`**（多库 `kb_ids`） | **`knowledge_graphrag_query`**（`graphrag_method`：`local` \| `global` \| `basic` \| `auto`） |
| **检索配置** | **`knowledge.embedding`** + **`knowledge.retrieval`** | 查询侧见 **`knowledge.graphrag`**（如默认 **`query_method`**、**`community_level`**）；索引用 **`indexing_method`**（如 `standard` / `fast`） |

创建库时在 Dashboard 选择模式；**已在 `indexing_status === ready` 的库上不能直接 PATCH 改 `mode`**（需按 API 说明处理索引后再改）。

---

### 所需环境与安装

| 层级 | 说明 |
|------|------|
| **系统** | 与本 README 前文一致：Windows 10/11，**Python ≥ 3.11** |
| **Hermes 安装** | **Dashboard + 知识库向量能力**：`pip install -e ".[web,knowledge]"` |
| **GraphRAG** | 追加 extra：**`pip install -e ".[web,knowledge,knowledge-graphrag]"`** |
| **NumPy** | `faiss-cpu` 常见 wheel 依赖 **NumPy 1.x**；`pyproject.toml` 中 `[knowledge]` 已约束 **`numpy>=1.24,<2`** |
| **前端（可选）** | 仅当要改 Dashboard 前端源码时：`web/` 下 **Node ≥ 20**，`npm install` / `npm run dev`；日常使用 **`hermes dashboard`** 内置构建产物即可 |

首次向导与密钥：

```powershell
.\venv\Scripts\hermes.exe setup
.\venv\Scripts\hermes.exe doctor
```

---

### 密钥与环境变量（`.env` / 运行时）

写入 **`%USERPROFILE%\.hermes\.env`**（或当前 **`HERMES_HOME`**），勿提交 Git。

| 用途 | 典型变量 |
|------|-----------|
| **向量嵌入与路由摘要 LLM** | 与 **`knowledge.embedding`** 一致的 **OpenAI 兼容**端点：**`OPENAI_API_KEY`**、可选 **`OPENAI_BASE_URL`** |
| **GraphRAG 对话/嵌入** | 优先 **`GRAPHRAG_API_KEY`**；未设置时可回退 **`OPENAI_API_KEY`**（与 Dashboard 常见部署一致）；Azure / 自定义 **`api_base`** 可能需在库的 **`graphrag/settings.yaml`** 中按上游文档调整 |
| **MinerU（可选）** | PDF→Markdown 时按需配置；说明见 **`docs/zh/knowledge-api.md`**（含 **`HERMES_MINERU_ROOT`** 等） |
| **嵌入式 Chat 默认勾选库** | **`HERMES_ACTIVE_KB_IDS`**（逗号分隔 `kb_id`）；向量工具在 **`kb_ids` 为空**时可读 |

---

### `config.yaml` 中与知识库相关的配置（摘要）

配置合并自仓库默认值与用户 **`HERMES_HOME/config.yaml`**。下列键在 **`hermes_cli/config.py`** 的 **`DEFAULT_CONFIG["knowledge"]`** 中有完整默认值，可按需覆盖。

**通用 / 向量**

- **`knowledge.enabled`**：是否启用知识库 API（默认 `true`）。
- **`knowledge.embedding`**：`provider`、`model`（默认 `text-embedding-3-small`）；与 **`OPENAI_*`** 配合。
- **`knowledge.routing_summary`**：向量重建成功后是否用 LLM 写 **`routing_summary.txt`**（**`auto`** 路由摘要）。
- **`knowledge.chunk`**：全局分块默认（**`window` / `delimiter` / `semantic` / `smart`**）；单库可通过 PATCH **`chunk_config`** 覆盖。
- **`knowledge.retrieval`**：**仅向量检索** — `two_stage`、`recall_per_kb`、`max_candidates`、`lexical_weight`（BM25 与向量混合）。
- **`knowledge.mineru`**：PDF→MD（**`enabled`**、`root`、`backend`、`local_models` 等）。

**GraphRAG**

- **`knowledge.graphrag.query_method`**：调试/API 默认查询风格（如 **`local`**）。
- **`knowledge.graphrag.community_level`**：**local** 检索时的社区层级（整数）。
- **`knowledge.graphrag.indexing_method`**：索引管线 **`standard`** / **`fast`** 等。
- **`knowledge.graphrag.completion_model`** / **`embedding_model`**：空字符串表示回退顶层对话模型 / **`knowledge.embedding`** / **`routing_summary.model`**。
- **`knowledge.graphrag.auto_method`**：Agent 工具 **`knowledge_graphrag_query`** 在 **`graphrag_method: auto`** 时的启发式（**`enabled`**、**`basic_max_chars`**、**`default_method`**、**`global_keywords`**）。

完整字段树与注释以实现仓库 **`hermes_cli/config.py`** 为准。

---

### 数据落盘位置

- **注册表**：**`{HERMES_HOME}/knowledge/registry.sqlite`**
- **每个库**：**`{HERMES_HOME}/knowledge/bases/<kb_id>/`**
  - **`raw/`**：上传的文本 / Markdown / PDF（及 MinerU 生成的 `.md`）
  - **向量模式**：`chunks.sqlite`、`vectors.faiss` 等
  - **GraphRAG 模式**：额外 **`graphrag/`** 目录（含 **`output/`** Parquet）

---

### Dashboard 知识库页：功能与本分支行为摘要

| 能力 | 说明 |
|------|------|
| **库管理** | 创建（选 **向量 / GraphRAG**）、摘要对话框（**`agent_summary`**、**`summary_routing_mode`**）、删除 |
| **替换 vs 追加（Dashboard）** | **上方栏**：「重新上传」会先 **`DELETE .../raw`** 清空 **`raw/`**（已上传过才触发）；GraphRAG 下「重建索引」带 **`full=1`** 强制全量。**仅 GraphRAG** 显示下方折叠「追加文档与增量索引」（追加上传 + **`full=0`** 增量）。向量库无该折叠，仍只用顶栏上传与「重建索引」。 |
| **上传与索引** | 上传文件；**重建索引**带 SSE 进度；支持 **后台运行**、最小化停靠卡片、取消/终止 |
| **全局任务与刷新** | 上传/索引/检索调试任务状态挂在 **`KnowledgeTasksProvider`**（换路由不丢最小化条）；**`sessionStorage`** 记录最小化快照；刷新后对 **索引中**的库可 **轮询 API** 恢复提示（上传/检索流无法跨刷新接续时会 toast 提示） |
| **按钮与列表状态** | 首次上传 / 重新上传、首次索引 / 重建索引等文案与 **`localStorage`** + 服务端 **`indexing_status`** 对齐；任务进行中对应行的上传/重建按钮会禁用；检索结束后「再次检索」与 **`queryHits !== null`** 对齐（含 0 条结果） |
| **向量专属** | **分块策略**折叠面板（**`chunk_config`**）、Embedding 探测 |
| **检索调试** | 向量：**`top_k`**；GraphRAG：**local / global / basic**；请求可取消 |

---

### Agent 工具与技能

| 名称 | 说明 |
|------|------|
| **`knowledge_list_bases`** | 列出已注册知识库（供选型） |
| **`knowledge_vector_query`** | 向量检索（多 **`kb_ids`**；可与 **`HERMES_ACTIVE_KB_IDS`** 配合） |
| **`knowledge_graphrag_query`** | GraphRAG 检索（**`graphrag_method`**：`local` / `global` / `basic` / **`auto`**） |

工具集 **`knowledge`** 默认包含在 **`hermes-cli`** includes 中；也可在 Dashboard **技能/工具 → 工具集** 中开关 **「Knowledge Bases」**。  
流程说明技能：**`skills/research/hermes-knowledge-bases/SKILL.md`** — 可复制到 **`%USERPROFILE%\.hermes\skills\`** 或通过 **`skills.external_dirs`** 指向仓库 **`skills/`**，执行 **`/reload-skills`** 后使用 **`/hermes-knowledge-bases`**。

---

### 相关源码与文档入口（便于排查）

| 主题 | 路径或文档 |
|------|------------|
| REST 与枚举 | **`docs/zh/knowledge-api.md`** |
| GraphRAG 管线 | **`docs/zh/graphrag-pipeline.md`** |
| Web API / 查询分支 | **`hermes_cli/knowledge_api.py`** |
| 向量索引与检索 | **`hermes_cli/knowledge_index.py`**、**`hermes_cli/knowledge_rerank.py`** |
| GraphRAG 索引/查询封装 | **`hermes_cli/knowledge_graphrag.py`**、**`hermes_cli/knowledge_graphrag_query.py`**、**`hermes_cli/knowledge_graphrag_method.py`** |
| Dashboard 前端 | **`web/src/pages/KnowledgePage.tsx`**、全局任务 **`web/src/contexts/KnowledgeTasksContext.tsx`** |
| Agent 工具 | **`tools/knowledge_tool.py`** |

---

## 隐私与仓库内容说明（已帮你做过静态检查）

已对仓库内 **会被 Git 跟踪** 的配置类模板做了静态检查，结论如下：

| 检查项 | 结论 |
|--------|------|
| **`.env.example`** | 仅为注释与占位说明，无真实密钥赋值。 |
| **`cli-config.yaml.example`** | 使用占位说明（如 `your-key-here`），无有效密钥。 |
| **根目录 `.env`** | 若你本机存在该文件，**属于个人密钥**，且应在 **`.gitignore`** 中；**切勿** `git add` 后推送。 |
| **测试代码中的 `sk-xxx`** | 多为单元测试用假字符串，非真实 API Key。 |

---

## 上游与许可证

- 上游：**[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)**  
- 许可证：**MIT**，见 **[LICENSE](LICENSE)**。
