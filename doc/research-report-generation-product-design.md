# 自动研发报告导出产品设计

版本：v0.1  
日期：2026-07-11  
适用模块：ResearchEngine、AlgorithmRun、ResearchRun、ComputationRun、LLM Provider、Agent Skill 编排

## 1. 背景与目标

当前很多算法报告 PDF 由人工协作完成：先把研发引擎运行数据交给 LLM/Agent，再调用对应的 Nature/科研写作 skill，生成报告正文，转成 LaTeX，最后导出 PDF。这个流程质量可控，但不可产品化复用，用户需要在每次研发引擎运行结束后人工整理输入、输出、追溯链、图表和结论。

本设计目标是在 Poly_Agent 内新增“自动出报告”能力：用户在每个研发引擎的结束位置，也就是“追溯/结果汇总”页面，直接发起报告生成任务；后端自动收集 run 上下文，通过通用 LLM provider 和可配置 skill 流水线生成结构化报告正文，导出 Markdown、LaTeX 和 PDF，并把报告任务、产物和审计事件纳入现有追溯体系。Codex 只是可选执行 provider，不是唯一后端。

成功标准：

- ResearchEngine 步骤 5 支持对 `AlgorithmRun` 和 `ResearchRun` 一键生成报告。
- 报告任务异步执行，可查看状态、失败原因、重试、下载 PDF/LaTeX/Markdown。
- 报告生成只读取后端环境变量中的密钥，前端不接触 API key。
- 报告输入数据来自现有 traceability 聚合接口，输出可追溯到具体 run、stage、algorithm、computation 和 observation。
- 后端支持多类型 LLM provider；Codex 仅作为可选 provider，和 OpenAI Responses、OpenAI-compatible、Ollama/local、未来 Anthropic/Gemini 等 provider 处在同一抽象层。
- 报告正文优先使用 Nature/科研写作 skill 编排，按报告类型选择写作、润色、引用、图表、数据可用性、审稿式自检等步骤。

## 2. 现状调研

### 2.1 现有产品入口

前端 ResearchEngine 主工作流在 `frontend/src/views/ResearchEngineView.vue` 中定义 5 个步骤，其中步骤 5 为“追溯/结果汇总”。当前步骤 5 已经展示：

- `AlgorithmRunDetail :show-traceability="true"`：单算法运行详情。
- `ResearchRun` 阶段追溯：stage timeline、输入/输出/审批、关联 AlgorithmRun、关联 ComputationRun、Observation、Audit event。

这正是报告生成的最佳入口。报告生成按钮应放在步骤 5 标题栏右侧，不应出现在步骤 1-4，以避免 run 尚未稳定时导出不完整报告。

### 2.2 现有数据契约

已有核心对象：

- `AlgorithmRun`：包含 `input_snapshot`、`output_summary`、`artifact_refs`、`linked_computation_run_id`、`research_run_id`、`stage_run_id`。
- `ResearchRun`：包含 `stage_runs`、`linked_algorithm_runs`、`summary`、`checkpoint`。
- `ResearchStageRun`：包含 `input_snapshot`、`output_summary`、`decisions`、`linked_algorithm_runs`、`artifact_ids`。
- `ResearchRunTraceability`：聚合 `research_run`、`linked_algorithm_runs`、`linked_computations`、`linked_observations`、`audit_events`。
- `AlgorithmRunTraceability`：聚合 `algorithm_run`、`linked_computation`、`audit_events`。

这些字段足以形成报告上下文，不需要前端拼接复杂关系。报告服务应复用后端现有 traceability service。

### 2.3 现有 LLM 配置

后端已有 `backend/app/core/config.py`：

```python
self.llm_api_key = os.getenv("LLM_API_KEY", "")
self.llm_base_url = os.getenv("LLM_BASE_URL", "")
self.llm_model = os.getenv("LLM_MODEL", "")
```

后端已有 `backend/app/core/llm_client.py`，当前基于 OpenAI 兼容 Chat Completions：

```python
OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)
client.chat.completions.create(model=settings.llm_model, messages=messages)
```

这能满足简单问答，但报告生成更需要结构化输出、长上下文、后台任务、可替换模型、可编排 skill 和稳定的产物状态机。建议新增 `ReportGenerationProvider` 与 `ReportSkillOrchestrator` 抽象，不直接复用 `/api/v1/llm/chat`。

### 2.4 Provider 与 skill 能力调研

OpenAI API 当前推荐用 Responses API 做直接模型请求，支持文本、结构化输出、工具和多模态工作流；API reference 中 `POST /responses` 可提供文本、图片或文件输入，并生成文本或 JSON 输出。Structured Outputs 支持让模型输出符合 JSON Schema 的结果，优先于旧 JSON mode。  
参考：<https://developers.openai.com/api/reference/resources/responses/methods/create/>、<https://developers.openai.com/api/docs/guides/structured-outputs>

Codex 官方文档提供非交互模式 `codex exec`，适合脚本或 CI 场景；它支持 JSONL 事件流、`-o/--output-last-message` 写出最终消息、`--output-schema` 约束最终 JSON 结构。自动化认证方面，官方建议 `CODEX_API_KEY` 只对单次 `codex exec` 调用内联注入，不要在会运行不可信仓库代码的任务环境中长期暴露。  
参考：<https://developers.openai.com/codex/noninteractive>、<https://developers.openai.com/codex/cli/reference>

Codex SDK 更适合把 Codex 深度嵌入自有服务端应用；如果 v1 只需要自动生成报告，`codex exec` provider 足够。后续如果需要长线程、流式事件和更强控制，再升级到 Codex SDK。  
参考：<https://developers.openai.com/codex/sdk>

报告质量不应只依赖某一个模型。更稳定的方式是把 LLM 当成执行引擎，把写作方法论沉淀为 skill pipeline。当前可优先编排的常用科研报告 skill：

| Skill | 角色 | 在报告流水线中的用法 |
| --- | --- | --- |
| `nature-writing` | Nature 风格科研写作 | 从 run context、结果和结论草拟摘要、方法、结果、讨论和下一步建议 |
| `nature-polishing` | 学术润色与 LaTeX 排版修正 | 对正文做 Nature-leaning English/中文科研表达润色，处理 LaTeX 稀疏页、浮动体和版式问题 |
| `nature-citation` | 严格引用补全 | 对需要外部文献支撑的 claim 做分段引用、CNS/Nature 子刊范围检索和引用导出 |
| `nature-figure` | 高水平科研图表 | 从算法输出、计算结果、观测数据生成或审查报告图表、multi-panel figure 和导出格式 |
| `nature-data` | 数据可用性与 FAIR | 生成数据可用性、artifact/source data、FAIR metadata 和 repository 建议 |
| `nature-academic-search` | 多源文献检索 | 为报告背景、相关工作、引用验证提供 PubMed/CrossRef/arXiv 等检索编排 |
| `nature-reviewer` | 审稿式质量自检 | 生成报告草稿后做 Reviewer-style 风险检查，标记证据不足、过度声明和技术缺口 |
| `nature-reader` | 文献/补充材料读取 | 当报告需要读取用户上传论文、PDF、补充材料时，先结构化提取事实和图表位置 |
| `nature-paper2ppt` | 汇报材料衍生 | 非 PDF 报告主链路；可作为后续“从报告生成组会 PPT”的扩展能力 |

v1 报告主链路建议默认使用：`nature-writing -> nature-polishing -> nature-data -> nature-reviewer`。当用户选择“带引用/带图表/带文献背景”时，再按需插入 `nature-academic-search`、`nature-citation`、`nature-figure` 和 `nature-reader`。

## 3. 产品范围

### 3.1 V1 做什么

- 在 ResearchEngine 步骤 5 增加“生成报告”入口。
- 支持 `AlgorithmRun` 报告和 `ResearchRun` 报告。
- 支持中文报告模板，预留英文模板。
- 支持输出 Markdown、LaTeX、PDF。
- 支持异步报告任务、任务状态查看、失败重试、产物下载。
- 支持报告上下文包下载或后台保留，便于复现。
- 支持后端环境变量配置 LLM provider、模型、超时、输出目录和 skill pipeline。
- 支持 OpenAI Responses、OpenAI-compatible、本地/私有模型、Codex exec 等 provider 二选一或多 provider fallback。
- 支持按模板自动编排科研写作 skill，默认优先使用 Nature 风格报告流水线。

### 3.2 V1 不做什么

- 不在前端配置或保存密钥。
- 不自动发布到外部论文投稿系统。
- 不承诺 Nature 投稿级最终排版，只提供 Nature 风格的研发报告草稿和 PDF。
- 不修改现有 ResearchRun/AlgorithmRun 核心状态机。
- 不把报告生成阻塞 ResearchRun 完成状态。
- 不在 v1 引入复杂模板市场；模板先内置。
- 不把 Codex 作为必需运行时；没有 Codex 时仍可用其他 LLM provider 出报告。

## 4. 用户流程

### 4.1 AlgorithmRun 报告

1. 用户运行单个算法或人工 Workflow。
2. 进入步骤 5“追溯/结果汇总”。
3. 点击“生成报告”。
4. 抽屉中选择：
   - 报告类型：算法运行报告。
   - 内容范围：输入参数、输出摘要、关联计算、审计事件。
   - 输出格式：PDF、LaTeX、Markdown，默认三者都生成。
   - 语言：中文。
5. 点击“开始生成”。
6. 页面出现报告任务条，显示 `排队中 -> 生成正文 -> 转换 LaTeX -> 编译 PDF -> 完成`。
7. 完成后可下载 PDF、LaTeX、Markdown，也可查看失败日志并重试。

### 4.2 ResearchRun 报告

1. 用户完成或失败结束一个 AutoResearch ResearchRun。
2. 进入步骤 5。
3. 点击“生成报告”。
4. 抽屉中选择：
   - 报告类型：AutoResearch 全流程报告。
   - 内容范围：阶段追溯、候选推荐、人工审批、计算预测、观测回填、审计事件。
   - 是否包含失败阶段诊断。
5. 后端收集 `ResearchRunTraceability`，按阶段生成报告。
6. 报告完成后在追溯页显示“最近报告”列表。

## 5. 信息架构与 UI 设计

### 5.1 入口位置

在 `ResearchEngineView.vue` 步骤 5 的 header 中增加右侧操作区：

- 主按钮：`生成报告`
- 图标：Element Plus `Document` 或 `Tickets`
- 按钮状态：
  - 无 run：禁用。
  - run 未完成但已有输出：可点击，抽屉中提示“当前报告可能不完整”。
  - 有正在运行的报告任务：显示 `生成中`，点击打开任务详情。
  - 最近报告已完成：显示 `下载报告` 次级按钮或 dropdown。

### 5.2 报告配置抽屉

抽屉字段：

| 字段 | 控件 | 默认值 | 说明 |
| --- | --- | --- | --- |
| 报告对象 | 只读摘要 | 当前 run | `AlgorithmRun` 或 `ResearchRun` |
| 报告模板 | Select | `research_summary_zh` | v1 内置模板 |
| Skill 流水线 | Select | `nature_research_report_zh` | 高级配置，默认自动选择 |
| LLM provider | Select | `auto` | 高级配置，默认由后端 readiness 决定 |
| 语言 | Segmented | `zh-CN` | 预留 `en-US` |
| 输出格式 | Checkbox group | `pdf, latex, markdown` | 至少选择一个 |
| 内容范围 | Checkbox group | 全选 | 阶段、输入、输出、计算、观测、审计 |
| 增强能力 | Checkbox group | 空 | 引用、图表、文献背景、失败诊断 |
| 附录级别 | Radio | `standard` | `compact/standard/full` |
| 备注指令 | Textarea | 空 | 用户可补充报告关注点 |

### 5.3 报告任务状态组件

状态条显示：

- 当前状态：queued/running/converting/completed/failed。
- 进度阶段：context、draft、latex、pdf、persist。
- 耗时、创建人、创建时间。
- 失败时展示可读错误，不展示密钥、绝对私有路径或完整 prompt。

## 6. 后端架构

### 6.1 模块划分

新增模块建议：

```text
backend/app/schemas/reports.py
backend/app/services/report_service.py
backend/app/services/report_context_service.py
backend/app/services/report_skill_orchestrator.py
backend/app/services/report_renderers/
backend/app/services/report_providers/
backend/app/services/report_skills/
backend/app/infra/report_repositories.py
backend/app/api/v1/endpoints/reports.py
backend/tests/test_report_*.py
```

职责：

- `report_context_service`：从现有 ResearchEngine/Computation/Optimization service 收集上下文。
- `report_service`：管理 ReportJob 状态机、调用 skill orchestrator/provider、持久化产物、写 audit。
- `report_skill_orchestrator`：按模板选择 skill pipeline，生成每个 skill 的输入、执行顺序、输出 schema 和质量门禁。
- `report_providers/openai_responses.py`：OpenAI Responses API provider。
- `report_providers/openai_compatible.py`：复用 OpenAI-compatible 网关、本地部署或私有模型。
- `report_providers/local_ollama.py`：本地 Ollama/离线模型 provider，适合内网和低成本草稿。
- `report_providers/codex_exec.py`：可选 Codex 非交互 provider，不作为默认依赖。
- `report_skills/*`：对 Nature/科研写作 skill 的产品化适配层，负责将 context 映射到 skill 输入和结构化输出。
- `report_renderers/latex.py`：Markdown/JSON -> LaTeX -> PDF。
- `report_repositories.py`：Mongo-first + demo JSON 双模存储。

### 6.2 数据模型

`ReportJob`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `report_id` | string | 主键，建议 `report_...` |
| `subject_type` | enum | `algorithm_run/research_run/workflow_run/computation_run` |
| `subject_id` | string | 被报告对象 ID |
| `problem_spec_id` | string? | 可选关联 |
| `campaign_id` | string? | 可选关联 |
| `template_id` | string | 模板 ID |
| `language` | string | `zh-CN/en-US` |
| `formats` | list | `markdown/latex/pdf` |
| `status` | enum | `queued/running/converting/completed/failed/cancelled` |
| `stage` | enum | `context/draft/latex/pdf/persist` |
| `progress` | int | 0-100 |
| `input_snapshot` | dict | 报告请求参数 |
| `context_ref` | dict | 上下文包 artifact 引用 |
| `provider` | string | `openai_responses/openai_compatible/local_ollama/codex_exec/custom_http/mock` |
| `model` | string | 实际模型名 |
| `skill_pipeline_id` | string | 实际采用的 skill 流水线 |
| `skill_runs` | list | 每个 skill 的输入摘要、输出 artifact、状态和耗时 |
| `artifact_refs` | list | Markdown/LaTeX/PDF/log/context |
| `error` | dict? | 失败摘要 |
| `created_by` | string | 创建人 |
| `created_at/updated_at/started_at/finished_at` | datetime | 生命周期时间 |

`ReportArtifact`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `artifact_id` | string | 主键 |
| `report_id` | string | 所属报告 |
| `artifact_type` | enum | `context_json/markdown/latex/pdf/log` |
| `filename` | string | 下载文件名 |
| `storage_uri` | string | 后端本地或对象存储路径 |
| `size_bytes` | int | 文件大小 |
| `sha256` | string | 完整性校验 |
| `created_at` | datetime | 创建时间 |

Mongo 集合建议：

- `report_jobs`
- `report_artifacts`

`demo_store.py` 需增加同名数组，保持本地 demo 模式可运行。

### 6.3 状态机

```text
queued
  -> running(context)
  -> running(skill_plan)
  -> running(draft)
  -> running(polish)
  -> running(quality_check)
  -> converting(latex)
  -> converting(pdf)
  -> completed

任意非终态 -> failed
queued/running -> cancelled
failed -> queued (retry 新建或复用同 report_id 需明确)
```

建议 retry 创建新 `report_id`，并在 `input_snapshot.retry_of` 记录来源，避免覆盖历史失败证据。

## 7. API 设计

统一放在 `/api/v1/reports`，不把报告接口塞进 ResearchEngine endpoint。ResearchEngine 前端只通过 subject_type/subject_id 调用通用报告能力。

### 7.1 创建报告

`POST /api/v1/reports`

请求：

```json
{
  "subject_type": "research_run",
  "subject_id": "rrun_123",
  "template_id": "research_summary_zh",
  "language": "zh-CN",
  "formats": ["markdown", "latex", "pdf"],
  "provider": "auto",
  "skill_pipeline_id": "nature_research_report_zh",
  "scope": {
    "include_stages": true,
    "include_algorithm_runs": true,
    "include_computations": true,
    "include_observations": true,
    "include_audit_events": true,
    "include_citations": false,
    "include_figures": false,
    "include_literature_background": false,
    "include_failure_analysis": false,
    "appendix_level": "standard"
  },
  "user_instructions": "重点解释候选推荐依据和失败阶段。"
}
```

响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "report_id": "report_123",
    "status": "queued",
    "stage": "context",
    "skill_pipeline_id": "nature_research_report_zh"
  }
}
```

### 7.2 查询报告

`GET /api/v1/reports/{report_id}`

返回完整 `ReportJob`，包含 artifact refs。

### 7.3 列表查询

`GET /api/v1/reports?subject_type=research_run&subject_id=rrun_123&page=1&page_size=20`

用于步骤 5 展示“最近报告”。

### 7.4 下载产物

`GET /api/v1/reports/{report_id}/artifacts/{artifact_id}/download`

返回文件流。后端需校验当前用户对 subject 的访问权限。

### 7.5 取消与重试

- `POST /api/v1/reports/{report_id}/cancel`
- `POST /api/v1/reports/{report_id}/retry`

### 7.6 就绪检查

`GET /api/v1/reports/readiness`

返回：

- LLM provider 是否配置。
- skill pipeline 是否可用。
- 选定 skill 是否在 allowlist 中。
- LaTeX 工具链是否可用。
- 输出目录是否可写。
- 如果选择 `codex_exec`，Codex CLI 是否可用。
- 当前默认模板是否存在。

## 8. LLM Provider 与 Skill 编排设计

### 8.1 Provider 抽象

```python
class ReportGenerationProvider(Protocol):
    def complete_json(self, messages: list[dict], schema: dict, options: dict) -> dict:
        ...
```

Provider 只负责“给定 prompt/messages/schema，产出结构化 JSON”。它不负责编排报告逻辑，也不直接决定报告章节。报告业务逻辑放在 `ReportSkillOrchestrator` 中。

首批 provider：

| Provider | 用途 | 说明 |
| --- | --- | --- |
| `openai_responses` | 生产默认候选 | 使用 Responses API + Structured Outputs，适合稳定 JSON 输出 |
| `openai_compatible` | 私有网关/第三方模型 | 兼容现有 `LLM_BASE_URL`、`LLM_MODEL` 配置 |
| `local_ollama` | 本地/内网草稿 | 适合无外网、低成本草稿；质量门禁要更严格 |
| `codex_exec` | 可选 Agent 执行器 | 需要复用 Codex skill、本地 LaTeX 修复或文件型任务时启用 |
| `custom_http` | 后续扩展 | 预留给内部模型服务、Anthropic/Gemini 代理或企业 LLM 网关 |
| `mock` | 开发和测试 | 仅用于本地 demo、单测和前端联调，不作为生产 provider |

所有 provider 输出必须是结构化 JSON，而不是直接自由文本。建议 schema 包含：

- `title`
- `abstract`
- `key_findings`
- `methods`
- `results`
- `traceability`
- `limitations`
- `next_steps`
- `tables`
- `figure_placeholders`
- `appendices`

随后由 renderer 将结构化 JSON 渲染为 Markdown/LaTeX。

### 8.2 Skill Orchestrator 抽象

```python
class ReportSkillOrchestrator:
    def build_plan(self, report_request: dict, context: dict) -> SkillPlan:
        ...

    def run_plan(self, plan: SkillPlan, provider: ReportGenerationProvider) -> StructuredReport:
        ...
```

`SkillPlan` 由模板和用户选项决定，至少包含：

- `pipeline_id`
- `steps`
- 每个 step 的 `skill_id`
- 输入 context selector
- 输出 schema
- 质量门禁
- 失败 fallback

默认 pipeline：

```text
nature_research_report_zh
  1. context_summarizer
  2. nature-writing
  3. nature-polishing
  4. nature-data
  5. nature-reviewer
  6. markdown_latex_renderer
```

带引用 pipeline：

```text
nature_research_report_with_citations_zh
  1. context_summarizer
  2. nature-academic-search
  3. nature-writing
  4. nature-citation
  5. nature-polishing
  6. nature-data
  7. nature-reviewer
  8. markdown_latex_renderer
```

带图表 pipeline：

```text
nature_research_report_with_figures_zh
  1. context_summarizer
  2. figure_data_extractor
  3. nature-figure
  4. nature-writing
  5. nature-polishing
  6. nature-data
  7. nature-reviewer
  8. markdown_latex_renderer
```

失败分析 pipeline：

```text
research_run_failure_analysis_zh
  1. failure_context_summarizer
  2. nature-writing
  3. nature-reviewer
  4. nature-polishing
  5. markdown_latex_renderer
```

### 8.3 Skill 适配层

Skill 适配层不直接暴露 agent 内部实现给前端，只输出产品化、可测试的数据：

| Adapter | 输入 | 输出 |
| --- | --- | --- |
| `NatureWritingAdapter` | context summary、结果表、关键结论、模板 | 结构化 report draft |
| `NaturePolishingAdapter` | report draft、语言、期刊风格 | polished sections、LaTeX layout notes |
| `NatureCitationAdapter` | claims、背景段落、引用范围 | citation map、RIS/BibTeX artifact、unsupported claims |
| `NatureFigureAdapter` | figure specs、数据 artifact | figure files、caption、QA notes |
| `NatureDataAdapter` | artifact inventory、source data | data availability、FAIR checklist |
| `NatureReviewerAdapter` | draft report | reviewer-style risk report、required revisions |
| `AcademicSearchAdapter` | search questions、scope | literature candidates、support grades |

每个 adapter 必须记录：

- `skill_id`
- `input_artifact_id`
- `output_artifact_id`
- `provider`
- `model`
- `status`
- `started_at/finished_at`
- `warnings`

### 8.4 OpenAI Responses Provider

适用场景：稳定服务端 API 调用、结构化输出、可控超时和重试。

建议使用：

- `OPENAI_API_KEY` 或 `REPORT_LLM_API_KEY`
- `REPORT_LLM_MODEL`
- Responses API `text.format = json_schema`
- `store=false`，除非明确需要平台侧留存

### 8.5 OpenAI-Compatible / Local Provider

适用场景：已有企业网关、国产/第三方兼容 API、本地 Ollama 或内网模型。

约束：

- 如果 provider 不支持严格 JSON Schema，服务层必须做 JSON parse + schema validate + 自动重试。
- 本地模型默认只用于草稿，不直接跳过 `nature-reviewer` 质量检查。
- 对 citation、data availability、审稿式自检等高风险步骤，优先使用支持结构化输出和较强推理能力的 provider。

### 8.6 Codex Exec Provider

适用场景：希望复用 Codex 的本地 agent 能力、Nature skill 路由、LaTeX 修复和文件型任务。它是可选 provider，不是默认架构依赖。

执行方式：

```bash
CODEX_API_KEY=... codex exec \
  --json \
  --output-schema ./schemas/report_outline.schema.json \
  -o .runtime/reports/<report_id>/report_outline.json \
  "基于 context.json 生成研发报告结构化草稿..."
```

关键约束：

- `CODEX_API_KEY` 只在单次子进程环境中注入，不作为全局环境长期暴露。
- 子进程工作目录限定到 `.runtime/reports/<report_id>/workspace`。
- prompt 中只引用上下文包路径，不把密钥、后端 `.env`、用户私有路径传入。
- 使用 `--output-schema` 约束最终 JSON，失败时保留 JSONL/log artifact。
- v1 不允许 Codex provider 改写仓库源码，只允许写报告工作目录。

### 8.7 Provider 选择策略

默认建议：

```text
REPORT_LLM_PROVIDER=openai_responses
REPORT_SKILL_PIPELINE_DEFAULT=nature_research_report_zh
```

当部署环境明确希望“后端能力由 Codex agent 执行”时：

```text
REPORT_LLM_PROVIDER=codex_exec
```

当部署环境有本地模型或私有网关时：

```text
REPORT_LLM_PROVIDER=openai_compatible
REPORT_LLM_BASE_URL=http://...
REPORT_LLM_MODEL=...
```

服务启动时 readiness 应显示当前 provider、模型、skill pipeline 和缺失配置，但不显示 key。

## 9. 环境变量设计

新增报告专用环境变量，允许兼容现有 `LLM_*`：

```dotenv
# ---- Report generation ----
REPORTS_ENABLED=true
REPORT_OUTPUT_ROOT=.runtime/reports
REPORT_LLM_PROVIDER=openai_responses   # openai_responses | openai_compatible | local_ollama | codex_exec | custom_http | mock(dev/test only)
REPORT_LLM_FALLBACK_PROVIDERS=openai_compatible,local_ollama
REPORT_SKILL_PIPELINE_DEFAULT=nature_research_report_zh
REPORT_SKILL_ALLOWLIST=nature-writing,nature-polishing,nature-data,nature-reviewer,nature-academic-search,nature-citation,nature-figure,nature-reader
REPORT_SKILL_STRICT_MODE=true

# OpenAI Responses / OpenAI-compatible / Custom provider
REPORT_LLM_API_KEY=                    # 未设置时回退 LLM_API_KEY 或 OPENAI_API_KEY
REPORT_LLM_BASE_URL=                   # 官方 OpenAI 可留空；兼容网关时填写
REPORT_LLM_MODEL=                      # 未设置时回退 LLM_MODEL
REPORT_LLM_TIMEOUT_SECONDS=180
REPORT_LLM_MAX_RETRIES=2
REPORT_LLM_STORE=false

# Local provider
REPORT_OLLAMA_BASE_URL=http://127.0.0.1:11434
REPORT_OLLAMA_MODEL=

# Optional Codex provider
REPORT_CODEX_BIN=codex
REPORT_CODEX_API_KEY=                  # 推荐只由进程 secret 注入；未设置时可回退 CODEX_API_KEY
REPORT_CODEX_MODEL=
REPORT_CODEX_TIMEOUT_SECONDS=600
REPORT_CODEX_SANDBOX_WORKDIR=.runtime/reports

# Rendering
REPORT_LATEX_ENGINE=xelatex
REPORT_PDF_TIMEOUT_SECONDS=120
REPORT_KEEP_INTERMEDIATE=true
```

安全要求：

- 不把任何 `*_API_KEY` 返回给前端。
- 不把真实 `.env` 内容写入报告上下文。
- 不把本地绝对路径暴露给用户下载文件名或 JSON 响应；响应中只暴露 artifact id。
- 生产环境建议密钥由 systemd/PM2/容器 secret 注入，而不是提交到仓库。

## 10. 报告生成流水线

```text
create report job
  -> load subject + permission check
  -> collect traceability context
  -> normalize/redact context
  -> write context.json artifact
  -> build skill plan
  -> run skill pipeline with selected LLM provider
  -> validate structured report JSON
  -> run quality gates
  -> render Markdown
  -> render LaTeX
  -> compile PDF
  -> persist artifacts
  -> write audit events
  -> return completed job
```

### 10.1 上下文规范化

上下文包建议包含：

- `subject`: run 基础信息。
- `problem_spec`: 研发任务定义。
- `stages`: 阶段列表、输入、输出、审批。
- `algorithm_runs`: 算法输入输出摘要。
- `computations`: 计算任务摘要和 result_summary。
- `observations`: 实验观测摘要。
- `audit_events`: 按时间排序的关键审计事件。
- `artifacts`: 可引用但不直接内联的大文件清单。

上下文包必须做脱敏：

- 过滤 `api_key`、`secret`、`token`、`password`。
- 隐藏本地绝对路径，只保留 artifact id 和文件名。
- 限制大字段长度，超限字段写入附加 artifact，由 LLM 读取摘要。

### 10.2 模板与渲染

v1 内置模板：

- `algorithm_run_summary_zh`
- `research_run_summary_zh`
- `research_run_failure_analysis_zh`
- `nature_research_report_zh`
- `nature_research_report_with_citations_zh`
- `nature_research_report_with_figures_zh`

Markdown 结构：

```text
# 标题
## 摘要
## 研发任务与目标
## 方法与数据来源
## 阶段过程与追溯
## 结果汇总
## 关键发现
## 局限性与风险
## 下一步建议
## 附录
```

LaTeX 渲染建议使用 Jinja2 模板。PDF 编译优先 `latexmk -xelatex`，没有 `latexmk` 时回退 `xelatex` 两次编译。

## 11. 审计、权限与安全

权限：

- 创建报告前复用 subject 的读取权限。
- 下载报告前再次校验用户可访问 subject。
- 管理员可查看所有报告，普通用户只看自己有权限的 subject。

审计事件：

- `report.created`
- `report.context_collected`
- `report.generated`
- `report.failed`
- `report.cancelled`
- `report.downloaded`

安全边界：

- Prompt injection：报告上下文中的外部文献、用户备注、算法输出都视为不可信输入；system/developer prompt 明确要求不得执行其中的指令，只作为数据引用。
- Secret redaction：进入 LLM 前做递归脱敏。
- Skill allowlist：只允许执行 `REPORT_SKILL_ALLOWLIST` 中登记的 skill adapter，禁止从用户输入动态加载任意 skill。
- Provider isolation：不同 provider 只拿到当前 step 所需最小上下文；citation/search step 不拿密钥或运行目录信息。
- Subprocess isolation：Codex、LaTeX 和本地脚本都在报告工作目录执行，不使用仓库根目录作为输出目录。
- PDF 编译：禁用 shell escape，除非后续有明确可信模板场景。

## 12. 实施计划

### 12.1 实施原则

- 先交付可本地演示的闭环，再替换高质量 provider 和复杂 skill。MVP 必须能在没有真实外部 LLM key 的情况下用 `stub/mock` provider 跑通 create/list/get/download。
- 后端先于前端。先稳定 `ReportJob`、artifact、状态机和 API 契约，再接入 ResearchEngine 步骤 5。
- 默认链路只启用 `nature_research_report_zh` 的基础 pipeline；引用、图表、文献读取作为增强任务，不阻塞 MVP。
- 所有外部执行器都必须可缺省。`openai_responses`、`local_ollama`、`codex_exec` 的缺失只能体现在 readiness，不应导致应用启动失败。
- 每个阶段结束都要留下可运行系统：测试通过、前端可构建、demo store 可启动。

### 12.2 里程碑

| 里程碑 | 目标 | 范围 | 完成信号 |
| --- | --- | --- | --- |
| M0：接口与存储骨架 | 后端能创建和查询报告任务 | schema、repository、readiness、router 注册 | `GET /api/v1/reports/readiness` 可用，demo/Mongo 双模式测试通过 |
| M1：上下文与脱敏 | 能从现有 run 生成安全 context artifact | `algorithm_run`、`research_run`、secret/path/长字段处理 | context 单测覆盖敏感字段和 traceability 输入 |
| M2：最小报告闭环 | 不依赖真实 LLM 生成 Markdown/LaTeX/PDF artifact | mock provider、默认 pipeline、renderer、download | API 测试可创建报告并下载 artifact |
| M3：真实 provider 接入 | OpenAI-compatible 和 OpenAI Responses 可用于结构化输出 | provider registry、schema validation、重试和错误日志 | mock 单测稳定，真实 API 只做手工 smoke |
| M4：ResearchEngine UI | 用户在步骤 5 发起、查看、下载报告 | API client、抽屉、任务状态面板、下载入口 | `npm run build` 通过，浏览器 smoke 跑通 |
| M5：增强能力 | 引用、图表、文献背景和 Codex exec 可选接入 | enhanced pipeline、adapter、readiness、失败 fallback | 增强选项有 plan 单测，不影响默认链路 |

### 12.3 推荐实施顺序

```text
M0 schema/repository/readiness
  -> M1 context/redaction
  -> M2 mock provider + default pipeline + renderer + API
  -> M4 frontend integration
  -> M3 real provider hardening
  -> M5 optional enhanced pipelines
```

说明：M3 和 M4 可以部分并行，但前端不应等待真实模型。前端先基于 M2 的 mock/fixture 任务接入，真实 provider 后续只改变 readiness 和任务运行结果。

### 12.4 检查点

**Checkpoint A：后端契约冻结**

- [ ] `backend/app/schemas/reports.py` 中请求、响应、状态枚举稳定。
- [ ] `POST /api/v1/reports`、`GET /api/v1/reports/{id}`、`GET /api/v1/reports`、`GET /api/v1/reports/readiness` 的响应结构不再随意变更。
- [ ] demo store 和 Mongo repository 行为一致。

**Checkpoint B：最小闭环**

- [ ] 使用 mock provider 能从 `AlgorithmRunTraceability` 和 `ResearchRunTraceability` 生成 context。
- [ ] 任务状态能从 `queued` 推进到 `completed` 或 `failed`。
- [ ] 至少 Markdown artifact 可下载；如果本机缺 LaTeX，PDF readiness 明确提示并保留 LaTeX/Markdown。

**Checkpoint C：前端可用**

- [ ] 步骤 5 只有存在 run 时显示报告入口。
- [ ] 抽屉提交后能轮询任务状态。
- [ ] 完成后能下载 artifact；失败时展示脱敏后的错误摘要。

**Checkpoint D：生产化前置**

- [ ] provider 输出全部做 JSON schema validate。
- [ ] prompt、error、artifact metadata 不记录密钥和绝对私有路径。
- [ ] cancel/retry/download 都有权限校验和审计事件。

## 13. 任务拆分

### Task 1：定义报告 schema、状态机和 repository

**目标：** 建立 `ReportJob`、`ReportArtifact`、创建请求、列表过滤、状态更新的后端契约。

**验收标准：**
- [ ] `ReportJob` 支持 `queued/running/converting/completed/failed/cancelled`，并记录 `stage/progress/error/artifact_refs`。
- [ ] Mongo/demo 双模式可创建、查询、按 subject 列表查询、更新状态、追加 artifact。
- [ ] retry 采用新 `report_id`，并在 `input_snapshot.retry_of` 记录来源。

**验证：**
- [ ] `python -m pytest backend/tests/test_report_repositories.py`

**预计改动：**
- `backend/app/schemas/reports.py`
- `backend/app/infra/report_repositories.py`
- `backend/app/infra/mongo.py`
- `backend/app/infra/demo_store.py`

**Dependencies:** 无。  
**Estimated scope:** M。

### Task 2：接入 reports router 和 readiness

**目标：** 提供报告服务的基础 API 面，前端和部署检查能先感知能力状态。

**验收标准：**
- [ ] `GET /api/v1/reports/readiness` 返回 reports enabled、输出目录、默认 provider、默认 pipeline、LaTeX、Codex/Ollama 可用性。
- [ ] readiness 不返回任何 key、真实 `.env` 值或本地绝对输出路径。
- [ ] `/api/v1/reports` router 已注册，但创建接口可先返回 `501/not_implemented` 或 mock job，不能破坏现有 API。

**验证：**
- [ ] `python -m pytest backend/tests/test_report_readiness.py`

**预计改动：**
- `backend/app/api/v1/endpoints/reports.py`
- `backend/app/api/v1/router.py`
- `backend/app/services/report_service.py`
- `backend/app/core/config.py`

**Dependencies:** Task 1。  
**Estimated scope:** S。

### Task 3：实现上下文收集与脱敏

**目标：** 复用现有 traceability service，为 `algorithm_run` 和 `research_run` 生成可喂给 LLM 的 context package。

**验收标准：**
- [ ] `algorithm_run` context 包含 run、linked computation、audit events 和 artifact 清单。
- [ ] `research_run` context 包含 stage、linked algorithm runs、computations、observations、audit events。
- [ ] 递归脱敏 `api_key/secret/token/password`，隐藏本地绝对路径，长字段截断并记录截断说明。

**验证：**
- [ ] `python -m pytest backend/tests/test_report_context_service.py`

**预计改动：**
- `backend/app/services/report_context_service.py`
- `backend/app/services/report_service.py`
- `backend/tests/test_report_context_service.py`

**Dependencies:** Task 1。  
**Estimated scope:** M。

### Task 4：实现 artifact 存储与下载

**目标：** 把 context、Markdown、LaTeX、PDF、日志统一保存为后端管理的 artifact，并提供安全下载。

**验收标准：**
- [ ] artifact 文件写入 `REPORT_OUTPUT_ROOT/<report_id>/`，响应只暴露 `artifact_id/filename/size/sha256`。
- [ ] 下载接口按 report subject 权限校验，不暴露真实 `storage_uri`。
- [ ] context artifact 默认可后台保留；是否允许前端下载由后续权限策略控制。

**验证：**
- [ ] `python -m pytest backend/tests/test_report_artifacts.py`

**预计改动：**
- `backend/app/services/report_service.py`
- `backend/app/infra/report_repositories.py`
- `backend/app/api/v1/endpoints/reports.py`
- `backend/tests/test_report_artifacts.py`

**Dependencies:** Task 1、Task 3。  
**Estimated scope:** M。

### Task 5：实现 mock provider 和 provider registry

**目标：** 先用稳定 fake 输出跑通异步任务、skill plan 和 renderer，避免前期被真实模型阻塞。

**验收标准：**
- [ ] `REPORT_LLM_PROVIDER=mock` 时输出符合结构化报告 schema。
- [ ] provider registry 能按配置选择 provider，并在缺失配置时返回可读 readiness。
- [ ] provider 错误转换为脱敏 `ReportJob.error` 和 log artifact。

**验证：**
- [ ] `python -m pytest backend/tests/test_report_providers.py`

**预计改动：**
- `backend/app/services/report_providers/base.py`
- `backend/app/services/report_providers/mock.py`
- `backend/app/services/report_providers/registry.py`
- `backend/tests/test_report_providers.py`

**Dependencies:** Task 2。  
**Estimated scope:** S。

### Task 6：实现默认 Skill Orchestrator

**目标：** 把模板、scope 和 provider 组织成可测试的报告生成步骤。

**验收标准：**
- [ ] `nature_research_report_zh` 默认包含 context summary、draft、polish、data availability、reviewer QA。
- [ ] 每个 step 记录 `skill_id/status/warnings/input_artifact_id/output_artifact_id/duration`。
- [ ] 关闭增强选项时不会执行 citation、figure、reader 类 step。

**验证：**
- [ ] `python -m pytest backend/tests/test_report_skill_orchestrator.py`

**预计改动：**
- `backend/app/services/report_skill_orchestrator.py`
- `backend/app/services/report_skills/base.py`
- `backend/app/services/report_skills/nature_basic.py`
- `backend/tests/test_report_skill_orchestrator.py`

**Dependencies:** Task 3、Task 5。  
**Estimated scope:** M。

### Task 7：实现 Markdown/LaTeX/PDF renderer

**目标：** 将结构化报告 JSON 渲染成稳定文件产物。

**验收标准：**
- [ ] Markdown renderer 输出固定章节顺序和 traceability 引用。
- [ ] LaTeX renderer 使用模板生成 `.tex`，对中文默认支持 `xelatex`。
- [ ] PDF compiler 优先 `latexmk -xelatex`，缺失时回退 `xelatex`；编译失败时保留 `.tex` 和 log。

**验证：**
- [ ] `python -m pytest backend/tests/test_report_renderers.py`
- [ ] 本机具备 LaTeX 时手工 smoke：生成一个 PDF。

**预计改动：**
- `backend/app/services/report_renderers/markdown.py`
- `backend/app/services/report_renderers/latex.py`
- `backend/app/services/report_renderers/pdf.py`
- `backend/app/services/report_renderers/templates/`
- `backend/tests/test_report_renderers.py`

**Dependencies:** Task 4、Task 6。  
**Estimated scope:** M。

### Task 8：实现报告任务执行 API

**目标：** 打通 create/list/get/cancel/retry/download 的后端最小闭环。

**验收标准：**
- [ ] `POST /reports` 创建任务并异步或后台执行；本地 demo 可同步执行但 API 语义保持异步。
- [ ] `GET /reports?subject_type=&subject_id=` 支持步骤 5 最近报告列表。
- [ ] `cancel/retry/download` 可用，失败任务可以 retry 生成新 report。

**验证：**
- [ ] `python -m pytest backend/tests/test_report_api.py`

**预计改动：**
- `backend/app/api/v1/endpoints/reports.py`
- `backend/app/services/report_service.py`
- `backend/tests/test_report_api.py`

**Dependencies:** Task 4、Task 5、Task 6、Task 7。  
**Estimated scope:** M。

### Task 9：实现 OpenAI Responses 和 OpenAI-compatible provider

**目标：** 接入真实结构化 LLM 输出，同时兼容现有 `LLM_*` 配置。

**验收标准：**
- [ ] `openai_responses` 使用 JSON Schema 结构化输出，并支持超时、重试、`store=false`。
- [ ] `openai_compatible` 兼容 `LLM_API_KEY/LLM_BASE_URL/LLM_MODEL` fallback。
- [ ] provider 不支持严格 schema 时执行 parse、validate、一次自动修复重试。

**验证：**
- [ ] `python -m pytest backend/tests/test_report_providers.py`
- [ ] 真实 API smoke 手工执行，不纳入默认 CI。

**预计改动：**
- `backend/app/services/report_providers/openai_responses.py`
- `backend/app/services/report_providers/openai_compatible.py`
- `backend/app/core/config.py`
- `backend/tests/test_report_providers.py`

**Dependencies:** Task 5、Task 8。  
**Estimated scope:** M。

### Task 10：实现 ResearchEngine 步骤 5 前端入口

**目标：** 用户能在追溯/结果汇总页创建、查看并下载报告。

**验收标准：**
- [ ] 步骤 5 header 右侧显示 `生成报告`，无 run 时禁用。
- [ ] 报告配置抽屉支持模板、语言、格式、scope、增强能力、备注指令；高级配置默认折叠。
- [ ] `ReportJobPanel` 轮询状态，显示阶段、失败原因、下载按钮和 retry。

**验证：**
- [ ] `cd frontend && npm run build`
- [ ] 浏览器 smoke：ResearchRun 和 AlgorithmRun 各生成一次 mock 报告。

**预计改动：**
- `frontend/src/views/ResearchEngineView.vue`
- `frontend/src/views/research-engine/ReportGenerateDrawer.vue`
- `frontend/src/views/research-engine/ReportJobPanel.vue`
- `frontend/src/api/polyAgentApi.js`

**Dependencies:** Task 8。  
**Estimated scope:** M。

### Task 11：实现可选本地和 Agent provider

**目标：** 在不影响默认链路的前提下支持 `local_ollama` 和 `codex_exec`。

**验收标准：**
- [ ] `local_ollama` readiness 能识别服务和模型，生成失败不会影响其他 provider。
- [ ] `codex_exec` 只在报告工作目录运行，只允许写 `.runtime/reports/<report_id>/workspace`。
- [ ] Codex prompt 只引用 context 文件路径，不注入 API key、`.env` 或仓库根目录。

**验证：**
- [ ] `python -m pytest backend/tests/test_report_providers.py`
- [ ] 本机 Codex/Ollama smoke 作为可选手工验收。

**预计改动：**
- `backend/app/services/report_providers/local_ollama.py`
- `backend/app/services/report_providers/codex_exec.py`
- `backend/tests/test_report_providers.py`

**Dependencies:** Task 5、Task 8。  
**Estimated scope:** M。

### Task 12：实现增强 pipeline

**目标：** 支持引用、图表、文献背景和失败诊断的按需插入。

**验收标准：**
- [ ] `include_citations` 插入 `nature-academic-search` 和 `nature-citation`，输出 citation map 和 unsupported claims。
- [ ] `include_figures` 插入 figure data extractor 和 `nature-figure`，输出 figure specs/captions/QA notes。
- [ ] `include_literature_background` 可路由到 `nature-reader` 或 academic search adapter。
- [ ] `include_failure_analysis` 使用失败分析 pipeline，并在报告中区分事实、推断和建议。

**验证：**
- [ ] `python -m pytest backend/tests/test_report_skill_orchestrator.py`
- [ ] 外部检索和图表生成只做手工集成 smoke。

**预计改动：**
- `backend/app/services/report_skills/nature_enhanced.py`
- `backend/app/services/report_skill_orchestrator.py`
- `backend/tests/test_report_skill_orchestrator.py`

**Dependencies:** Task 6、Task 9。  
**Estimated scope:** M。

### Task 13：端到端验收和回归

**目标：** 在 demo 数据和至少一个真实/半真实 run 上验证完整用户流程。

**验收标准：**
- [ ] `ResearchRun` 完成后能生成 Markdown/LaTeX/PDF，报告包含阶段追溯和关键结论。
- [ ] `AlgorithmRun` 完成后能生成报告，报告包含输入参数、输出摘要和关联计算。
- [ ] readiness 缺 key、缺 LaTeX、缺 Codex/Ollama 时提示准确，默认功能不崩。
- [ ] 失败重试、下载权限、审计事件均可验证。

**验证：**
- [ ] `python -m pytest backend/tests/test_report_api.py backend/tests/test_report_context_service.py backend/tests/test_report_renderers.py`
- [ ] `cd frontend && npm run build`
- [ ] 浏览器 smoke：ResearchEngine 步骤 5 发起报告、轮询、下载。

**预计改动：**
- `backend/tests/test_report_api.py`
- `backend/tests/test_research_engine_e2e.py`
- `frontend` smoke 记录或 Playwright 后续补充

**Dependencies:** Task 1-12。  
**Estimated scope:** M。

## 14. 风险与对策

| 风险 | 影响 | 对策 |
| --- | --- | --- |
| 报告幻觉 | 用户误信错误结论 | 结构化 schema、上下文引用、报告内标注数据来源和局限性 |
| 上下文过大 | LLM 调用失败或成本过高 | 上下文摘要、artifact 引用、大字段截断 |
| PDF 编译失败 | 用户无法下载 PDF | 保留 Markdown/LaTeX，展示编译日志，支持重试 |
| 可选 Agent 子进程越权 | 修改仓库或读取敏感文件 | 限定工作目录、只传 context path、禁用源码写入场景 |
| 密钥泄露 | 严重安全事故 | 只读环境变量、递归脱敏、不返回 key、不记录 prompt 全量敏感内容 |
| 用户在未完成 run 上生成报告 | 报告不完整 | UI 明确提示，并在报告中写入 run status |

## 15. 待确认问题

- 生产默认 provider 是否使用 `openai_responses`，本地演示默认是否允许 `openai_compatible/local_ollama`。
- Nature skill 在产品化后是否只作为后端 adapter/prompt 模板，还是允许在 `codex_exec` 等 agent provider 中直接路由。
- PDF 样式是否需要学校/课题组模板、页眉页脚、封面和 logo。
- 是否需要把报告写回任务中心，作为一种可检索任务类型。
- 是否需要支持批量报告：一个 ProblemSpec 下多个 ResearchRun 对比报告。
