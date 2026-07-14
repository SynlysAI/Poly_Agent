# PolyAgent 知识库 RAG + 知识图谱产品设计

## 当前状态

知识库能力已从早期 LightRAG 方案调整为 Poly Agent 后端统一适配 `services/literature-rag/` 独立服务。当前默认 corpus 为 `krf_photoresist`，用于 KrF 248 nm 光刻胶文献问答、证据核查和图谱子图浏览。

当前图谱能力已经接入：memory demo 返回 Paper/Chunk 子图，production 路径使用 MongoDB + MinIO + Neo4j，worker 在索引阶段写入 Paper/Chunk/Entity 节点。

## 产品入口

前端路由为 `/knowledge`，通过 `?module=rag|graph` 切换：

- `知识增强检索问答`：选择知识库体系，输入问题，选择 `hybrid/local/global/naive/mix` 模式和 Top K，展示回答、命中证据、引用来源和图谱上下文入口。
- `知识图谱`：按实体、论文、性质或方法关键词加载子图，展示节点、关系、节点属性和关联关系。

图谱 tab 初次进入时使用当前体系的默认关键词自动加载子图；未加载、无结果和服务不可用使用不同空态文案。

## 后端接口

Poly Agent 后端提供稳定 API，前端和 ResearchEngine 不直接访问独立服务。

| Method | Path | 用途 |
| --- | --- | --- |
| GET | `/api/v1/knowledge-bases/systems` | 列出可用知识库体系 |
| GET | `/api/v1/knowledge-bases/health` | 返回 Literature RAG 服务可用性 |
| POST | `/api/v1/knowledge-bases/query` | RAG 问答 |
| POST | `/api/v1/knowledge-bases/query/stream` | 流式 RAG 问答 |
| GET | `/api/v1/knowledge-bases/{system_id}/graph` | 保留入口；当前要求提供查询词后加载子图 |
| GET | `/api/v1/knowledge-bases/{system_id}/graph/subgraph` | 获取查询相关子图 |

RAG 请求字段：

- `system_id`: 知识库体系 ID，当前默认 `krf_photoresist`
- `question`: 必填问题
- `mode`: `hybrid` 默认，可选 `local`、`global`、`naive`、`mix`
- `top_k`: 默认 5，范围 1-20
- `include_graph_context`: 默认 true

RAG 响应字段保持稳定：

- `answer`
- `hits`
- `citations`
- `graph_context`
- `configured`
- `message`

`message` 当前可能为：

- `ok`: 正常问答命中证据
- `document_inventory`: 文档清单类查询
- `insufficient_evidence`: 现有索引证据不足

## 检索与图谱行为

- 中文/中英混合查询会扩展 KrF 光刻胶常见领域词，例如 `光刻胶 -> photoresist/resist`、`文献/论文/文档 -> paper/document/literature`。
- 文档清单意图，例如“帮我找全部的文档”，返回最多 20 篇已索引文献清单；当前 KrF memory demo 可覆盖 15 篇文献。
- 无 LLM 配置时，服务返回基于命中 chunk 的可追溯证据摘要；不会编造 DOI 或论文。
- 明显离域且缺少 KrF/photoresist/lithography/sensitivity 等领域锚点的问题保守返回 `insufficient_evidence`。
- 图谱子图响应统一为 `nodes`、`edges`、`stats`、`provenance`，前端只展示安全元数据。

## ResearchEngine 挂载

ResearchEngine 通过算法注册和 AlgorithmRun 调用知识能力：

- `literature_rag_adapter`：调用 `KnowledgeService.query`。
- `knowledge_graph_adapter`：调用 `KnowledgeService.get_subgraph`，返回 nodes/edges/stats。
- 两者均为 `algorithm_family="knowledge"`、`type="retriever"`、`task_scope=["KNOWLEDGE_RETRIEVAL"]`。
- AutoResearch 的 `KNOWLEDGE_RETRIEVAL` 阶段可附带 `graph_context`，供后续报告和追溯使用。

## 部署与配置

独立服务默认端口：

- Literature RAG：`http://127.0.0.1:8200`
- Poly Agent 后端：`http://127.0.0.1:5201`
- Poly Agent 前端：`http://127.0.0.1:5200`

Poly Agent 后端环境变量：

- `LITERATURE_RAG_BASE_URL`: 独立服务地址；本地 dev 可自动探测 `127.0.0.1:8200`
- `LITERATURE_RAG_QUERY_API_KEY`: 查询 API key
- `LITERATURE_RAG_DEFAULT_CORPUS_ID`: 默认 corpus，当前为 `krf_photoresist`

独立服务环境变量见 `services/literature-rag/README.md`。

## 验收标准

- `/knowledge?module=rag` 能用中文问题 `KrF光刻胶是什么？` 返回命中证据和引用。
- `帮我找全部的文档` 返回已索引文献清单，而不是证据不足。
- `/knowledge?module=graph` 初次进入会自动加载默认子图或明确显示待加载状态。
- `/api/v1/knowledge-bases/*` 不暴露 API key、`storage_uri`、`object_key`、`content_hash` 或 embedding。
- `services/literature-rag/tests`、`backend/tests/test_knowledge_base_api.py` 和 `frontend` build 均通过。
