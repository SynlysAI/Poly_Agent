# 独立文献 RAG 服务设计与运行说明

## 当前边界

文献下载、授权 PDF 导入、元数据核验、PDF 清洗、分块、实体抽取、向量索引和 Neo4j 图谱均由
`services/literature-rag/` 负责。Poly_Agent 只通过查询 API 使用已准备好的知识资产，不直接访问该服务的
MongoDB、MinIO 或 Neo4j。

首个 corpus 为 `krf_photoresist`，覆盖 KrF 248 nm 光刻胶树脂、PAG、显影与工艺性能。旧
`refer/pdf_requirement` notebook 只提供 DOI 候选，不使用其中的第三方镜像 URL。

## 服务组成

- FastAPI API：管理 corpus、候选、授权 PDF 和 ingestion job，并提供查询、流式回答和子图接口。
- ingestion worker：通过 MongoDB 原子领取任务，从 MinIO 读取 PDF，使用 PyMuPDF 清洗分块并写回资产。
- MongoDB：保存 corpus、候选、文档、job 和 chunk 状态。
- MinIO：保存原始 PDF、规范化 Markdown 和解析 JSON。
- Neo4j：保存 Paper、Chunk 和 KrF 领域实体，使用 BGE-M3 embedding 建立向量索引。

服务支持 OpenAI-compatible LLM 生成带证据编号的回答并扩展实体抽取；未配置或调用失败时返回可追溯的
证据摘录，不生成无来源结论。

## Poly_Agent 接入

Poly_Agent 保持 `/api/v1/knowledge-bases/*`、前端结构和 ResearchEngine adapter 契约不变。配置：

```dotenv
LITERATURE_RAG_BASE_URL=http://127.0.0.1:8200
LITERATURE_RAG_API_KEY=<query-service-key>
KNOWLEDGE_DEFAULT_SYSTEM_ID=krf_photoresist
```

旧 `KNOWLEDGE_RAG_BASE_URL` 和 `KNOWLEDGE_RAG_API_KEY` 仅作为环境变量兼容别名保留。
`KNOWLEDGE_DEFAULT_SYSTEM_ID` 只是前端首选选中项；Poly_Agent 不会基于该变量创建本地 fallback 知识源。

知识库页面的数据源列表来自独立 RAG 服务的 `/api/v1/corpora`。新增或下线 corpus 时，只需要在
literature-rag 服务的 corpus registry 中完成注册或状态更新，前端会通过 Poly_Agent 后端
`/api/v1/knowledge-bases/systems` 动态加载，不在 UI 代码中硬编码体系 ID、名称或数据源。

## Corpus 生成

`services/literature-rag/scripts/build_krf_manifest.py` 使用 OpenAlex 主题检索、Crossref DOI 核验和 Unpaywall
OA 回填生成 `data/corpus_manifest.json`。排序先保证标题级 KrF/248 nm 相关性，再比较期刊、引用、时间和
全文可用性。只有 `selected=true` 且 `approval_status=approved` 的记录可自动导入；其他记录必须提供已授权 PDF。

当前 manifest 目标为 30 篇。实际完成“至少 20 篇全文索引”仍取决于授权 PDF 的提供数量和 OA URL 的
下载可用性，服务不会用摘要或未授权来源伪装全文。
