# PolyAgent 借鉴 ALS Accelerator Assistant「大装置 Agent」的编排与受限执行设计

日期：2026-08-20
状态：架构设计建议 / 待评审
适用范围：ResearchEngine 编排器、产品内助手工具注入、计算适配器、实验下发与统一安全层

前置与参考：

- ALS Accelerator Assistant 论文范式（劳伦斯伯克利国家实验室先进光源）：自然语言 → 结构化计划 → 受限工具 → 容器化执行 → 全链路制品
- PolyAgent 总览：`README.md`
- ResearchEngine 技术方案：`doc/research-engine-and-auto-research-design.md`
- 实验下发设计：`doc/experiment-dispatch.md`
- 借鉴分析原文：ALS「大装置 Agent」对 Poly Agent 设计的借鉴分析（本设计依据其优先级建议展开高、中优先级五项）

## 1. 背景与判断

ALS Accelerator Assistant 是一套已落地生产环境的智能体系统，把自然语言请求转化为可复现的多阶段物理实验。其可迁移精华是三大架构支柱与若干配套机制：

- **Plan-first 编排**：调用任何工具前，先生成一份含显式输入输出依赖的完整可审查执行计划，计划本身即天然的安全门检查点。
- **Bounded tool access（受限工具访问）**：工具只暴露严格受限的 API，全流程可审计，禁止裸写底层通道。
- **Dynamic capability selection（动态能力选择）**：每次迭代独立评估每个能力的相关性（few-shot 二元分类），只把相关工具描述注入 prompt，避免 prompt 膨胀、解耦任务复杂度与工具清单规模。
- 配套机制：PV Finder 中间层（统一数据模型 → 受限 API → NL 拆原子意图 → 解析为具体通道）、三段式代码生成（plan → JSON schema → minimal code）、容器化 Jupyter 内核的只读/可写双模式、写操作默认审批 + 边界限制 + 写黑/白名单 + 全链路审计。

PolyAgent 与 ALS 定位高度同构——同样是「大型科研设施 + 多子系统分散知识 + 多阶段实验流程 + 高风险安全约束」，只是把「束流/磁铁/RF」换成「聚合物计算/合成/表征」，把「EPICS PV」换成「SpecLabOS 实验条件」。

**总体判断**：PolyAgent 在「受限工具 API」和「声明式参数下发」上已有扎实甚至更优的基础（下发引擎 `experiment_dispatch_profile_engine.py` 完全非脚本，只解释固定操作符）；最值得补齐的是 Plan-first 的「显式依赖计划」（让现有 Gate 有可审查对象）和 Dynamic capability selection（应对工具清单膨胀），这两点是 ALS 反复强调的「随功能增长仍保持透明、可移植」的规模化关键。中优先级的只读/可写双模式、统一安全层、NL 驱动参数解析器则在安全闭环与体验升级上补齐短板。

本设计聚焦分析中标注的**高优先级两项**与**中优先级三项**，低优先级（三段式生成、混合推理敏感路由）不在本设计范围，后续单独评估。

## 2. 设计目标与非目标

### 2.1 目标

1. 让 ResearchEngine 的 Stage/Gate 在调用工具前生成一份含显式输入输出依赖的结构化执行计划，并把该计划作为 Gate 的可审查对象。
2. 给能力体系增加「按任务相关性动态筛选工具」一层，只把相关工具 schema 注入助手 prompt，解耦任务复杂度与工具清单规模。
3. 统一计算/下发执行的只读/可写分级，与现有 dispatch 确认机制对齐，并把制品覆盖范围扩展到实验下发全链路。
4. 构建配置级的统一安全层：参数边界限制 + 写黑/白名单 + 全链路审计，复用现有 target 契约载体，不改框架。
5. 在现有声明式下发之上叠加 NL 驱动参数解析，从「用户手选 profile + 手填 manual_values」走向「自然语言驱动解析」，且安全不降级。

### 2.2 非目标

- 不引入裸脚本/任意代码执行通道；下发引擎继续保持非脚本、只解释固定操作符。
- 不替换现有声明式 profile/target 契约，而是在其上扩展与叠加。
- 不在本设计中落地低优先级的三段式生成与混合推理敏感路由。
- 不改变 P0 已固化的阶段序列语义，仅在推进前插入「计划生成」子阶段。

## 3. 总体范式与支柱映射

ALS 范式落到 PolyAgent 现有模块的映射如下，作为后续逐项设计的索引：

| ALS 支柱/机制 | PolyAgent 现状模块 | 已具备 | 本设计补齐项 | 优先级 |
| --- | --- | --- | --- | --- |
| Plan-first 编排 | `research_engine_orchestrator.py` 的 Stage/Gate 状态机；`assistant_service.py` 的 `blocked_approval` | 阶段审批门 `approve_stage`/`reject_stage`、`blocked_approval` 概念 | 显式输入输出依赖的 `StageExecutionPlan`，作为 Gate 审查对象 | 高 |
| Dynamic capability selection | `capability_service.py` 的 `get_capabilities`；`assistant_service.py` 工具注入 | 能力就绪状态聚合（configured/healthy/demo_fallback） | 能力相关性筛选层，按任务动态注入工具 | 高 |
| 容器化 + 只读/可写双模式 + 制品 | `computation_adapters/base.py` 的 `ArtifactSpec`/`AdapterRunResult`/`build_steps`；`computation_worker.py` | 步骤时间线、制品产出、error/log 落盘 | `AdapterContext` 访问模式分级，制品覆盖实验下发 | 中 |
| 统一安全层 | `alchemist_core/audit_log.py`；dispatch 的 `preview_digest` 防篡改 + `branches` 阻断 + 用户确认 | 审计、摘要防篡改、条件阻断 | 配置级边界限制 + 写黑/白名单 | 中 |
| PV Finder 中间层 | `experiment_dispatch_profile` 的 `source_contract`/`target_contract` 字段映射 | 版本化声明式配置、字段映射、`branches` 条件阻断 | NL → 原子意图 → 通道解析 | 中 |

## 4. 借鉴点与 PolyAgent 落地设计

### 4.1 【高】Plan-first 显式依赖计划：让 Gate 拥有可审查的执行计划

#### 4.1.1 现状

ResearchEngine 编排器 `backend/app/services/research_engine_orchestrator.py` 已有阶段状态机：

- `_advance_stages`（`:425`）按固定序列推进，非 gate 阶段用 mock runner 自动生成输出，遇到 gate 阶段进入 `blocked_approval` 并停止。
- `_run_stage_algorithm`（`:708`）通过 `AlgorithmRun` 执行阶段并回写追溯关联，未配置时回退 mock。
- `approve_stage`（`:926`）批准 gate 阶段，记录 `StageGateDecision`，从 `blocked_approval` 转 `completed` 并继续推进。

阶段契约定义在 `backend/app/services/research_engine_defaults.py`：`DEFAULT_STAGE_SEQUENCE`（`:73`，10 阶段）、`P0_GATE_STAGES`（`:87`，`PROBLEM_SPEC`/`RECOMMENDATION_ASK`/`EXPERIMENT_EXECUTION`）、`DEFAULT_STAGE_CONTRACTS`（`:97`，每个 `StageGate` 含 `required_inputs`/`expected_outputs`/`gate_policy`/`artifact_policy`）。

#### 4.1.2 差距

- 现有 `StageGate.required_inputs`/`expected_outputs` 是**静态契约**（声明本阶段需要/产出什么），不是「本次运行要调用哪个工具、输入来自哪条 AlgorithmRun 的输出、产出哪些 artifact、是否触发 dispatch」的**可执行计划**。
- P0 阶段多为 mock 推进，`approve_stage` 审批时缺少一份结构化的审查对象，审批决策缺少「对照计划核验」的依据。
- 计划对象缺失导致 Gate 退化成「阶段边界」而非「安全门检查点」。

#### 4.1.3 目标设计

在 stage 推进前插入一个 `plan_generation` 子阶段，输出一份 `StageExecutionPlan`，作为 Gate 的审查对象。计划通过后才进入实际执行。

数据结构草案（沿用现有 pydantic 风格，`model_config = ConfigDict(extra="forbid")`）：

```python
class PlanDependency(BaseModel):
    """计划项的输入依赖声明。"""
    field: str                      # 本阶段输入字段名（对应 expected_outputs 中的 key）
    source_kind: Literal["algorithm_run", "stage_output", "problem_spec", "manual"]
    source_ref: str | None = None   # algorithm_run_id / stage_run_id / problem_spec_id
    source_path: str | None = None  # JSON Pointer，取自 source 的哪个字段
    required: bool = True

class PlanStep(BaseModel):
    """计划中的单个执行步骤。"""
    step_key: str
    kind: Literal["computation", "knowledge", "llm", "dispatch", "manual_review"]
    tool_ref: str | None = None     # computation_adapter 标识 / dispatch_profile_id 等
    inputs: list[PlanDependency] = field(default_factory=list)
    expected_artifacts: list[str] = field(default_factory=list)
    triggers_dispatch: bool = False
    safety_note: str | None = None  # 该步骤的安全提示（供 Gate 审查）

class StageExecutionPlan(BaseModel):
    """某次 ResearchRun 在某阶段执行前的可审查计划。"""
    plan_id: str
    research_run_id: str
    stage_key: ResearchStageKey
    stage_run_id: str
    steps: list[PlanStep]
    data_sensitivity: Literal["public", "internal", "sensitive"] = "internal"
    generated_at: datetime
    generated_by: str               # "llm" / "rule" / "hybrid"
    review_status: Literal["draft", "approved", "rejected", "modified"] = "draft"
```

执行流程变更（伪流程）：

```text
_advance_stages 遇到待执行阶段
  → 若该阶段为 gate 阶段或需要调用工具：
      1) 调用 plan_generation 子阶段，基于 stage contract + 上游 AlgorithmRun 输出快照
         生成 StageExecutionPlan（LLM 生成 steps + 规则补全 inputs 依赖）
      2) 将 plan 挂到 stage_run.plan，状态置 blocked_approval（带 plan 审查对象）
      3) approve_stage 时核验 plan：实际执行 step 与 plan 一致才放行；
         reject_stage / modified 可回退到 plan 重生成
  → 若为非 gate 的自动阶段：仍生成 plan 但自动通过，仅留痕审计
```

#### 4.1.4 集成点

- `research_engine_orchestrator.py:425` `_advance_stages`：在推进循环中，对需要工具的阶段先调用 `_generate_stage_plan` 生成 `StageExecutionPlan`，gate 阶段置 `blocked_approval` 并携带 plan。
- `research_engine_orchestrator.py:708` `_run_stage_algorithm`：执行前校验 `AlgorithmRun` 的 `input_snapshot` 与 plan 的 `PlanDependency` 一致，执行后回写 `expected_artifacts` 完成情况。
- `research_engine_orchestrator.py:926` `approve_stage`：审批时把 `StageExecutionPlan` 作为审查对象返回前端，记录「计划 vs 实际」核验结果到 `StageGateDecision`。
- `backend/app/schemas/research_engine.py`：新增 `StageExecutionPlan`/`PlanStep`/`PlanDependency`，并在 `ResearchStageRun` 上扩展 `plan: StageExecutionPlan | None`。
- `research_engine_defaults.py:97` `DEFAULT_STAGE_CONTRACTS`：`StageGate` 可新增 `plan_policy`（是否需要 plan、生成方式），作为 plan 生成的约束输入。

#### 4.1.5 实施步骤

1. 在 `schemas/research_engine.py` 新增 `StageExecutionPlan` 及依赖类型，`ResearchStageRun` 增加可选 `plan` 字段（向后兼容）。
2. 在 `research_engine_defaults.py` 的 `StageGate` 增加 `plan_policy`（`require_plan`/`generation_mode`），为 gate 阶段默认开启。
3. 在编排器实现 `_generate_stage_plan`：优先规则补全 `inputs` 依赖（从上游 `AlgorithmRun.output_summary` 解析），LLM 补全 `steps`/`safety_note`。
4. 改造 `_advance_stages`：gate 阶段先生成 plan 再 `blocked_approval`；`approve_stage` 返回 plan 并记录核验结果。
5. 补充单测：plan 生成、依赖解析、计划与实际一致性核验、reject 回退重生成。

#### 4.1.6 风险与缓解

- **风险**：plan 生成增加一次 LLM 调用，拉长 gate 等待。**缓解**：`inputs` 依赖优先规则补全，LLM 仅补 `steps`；非 gate 阶段 plan 自动通过不阻塞。
- **风险**：plan 与实际执行漂移导致审查失真。**缓解**：执行后做「计划 vs 实际」核验并写入 `StageGateDecision`，漂移即告警。

### 4.2 【高】动态能力选择：按任务相关性筛选注入的工具

#### 4.2.1 现状

- `backend/app/services/capability_service.py:22` `get_capabilities` 产出面向前端的能力就绪矩阵（知识库/LLM/报告/计算/BO/xtb/orca 各自 `configured`/`healthy`/`demo_fallback`，由 `_level` 静态方法分级）。它回答「哪些能力可用」，不回答「当前任务该注入哪些工具」。
- `backend/app/services/assistant_service.py:1391` `_build_function_tools` 把 `selected_tool_ids`（`algorithm:` 前缀）解析为 function schema 并注入；`:1437` 用 `estimate_native_tool_schema_tokens`（`:46` 导入）估算工具 schema token，`:1641` `_resolve_selected_tools` 解析可见工具目录。当前 `selected_tool_ids` 来自请求上下文，倾向全量注入。

#### 4.2.2 差距

- 缺少「按当前 stage/task 相关性动态筛选工具」的层；随着电解液/催化/合成/表征等流程增多（`doc/experiment-dispatch.md` 的「PI 迁移」已预示），工具清单持续膨胀，全量注入会导致 prompt 膨胀和模型选错工具。
- `capability_service` 的就绪状态与 `assistant` 的工具注入是两套独立逻辑，没有「相关性 → 注入」的衔接。

#### 4.2.3 目标设计

新增轻量的「能力相关性评估」层，对当前任务用 few-shot 二元分类判断每个 `computation_adapter` / `dispatch_profile` / 知识库是否相关，只把相关工具的 schema 注入 assistant 的 function tool 列表，并用 `estimate_native_tool_schema_tokens` 做筛选后的预算校验。

数据结构草案：

```python
class CapabilityRelevanceItem(BaseModel):
    """单个能力/工具与当前任务的相关性评估结果。"""
    capability_id: str              # 适配器标识 / dispatch_profile_id / 知识库 id
    capability_kind: Literal["computation_adapter", "dispatch_profile", "knowledge_base"]
    relevant: bool
    confidence: float               # 0~1
    reason: str | None = None

class CapabilityRelevanceAssessment(BaseModel):
    """一次任务的相关性评估结果。"""
    task_summary: str               # 当前 stage/task 的摘要（供审计）
    items: list[CapabilityRelevanceItem]
    assessed_at: datetime
    token_budget_used: int = 0      # 筛选后注入的 schema token 估算
    token_budget_limit: int = 0
```

流程：

```text
助手收到工具请求 → 取当前任务/stage 上下文
  → CapabilityRelevanceService.assess(task, candidate_capabilities)
      · 候选集 = capability_service.get_capabilities() 中 healthy/configured 的能力
        × computation_adapters.registry.supported_workflow_engine_pairs()
        × 已发布 dispatch_profile
      · 对每个候选用 few-shot 二元分类判断 relevant
      · 只保留 relevant=True 的，调用 estimate_native_tool_schema_tokens 做预算校验
        （超预算则按 confidence 降序裁剪）
  → 把筛选后的 capability_id 映射为 selected_tool_ids 注入 _build_function_tools
```

#### 4.2.4 集成点

- `capability_service.py:22`：新增 `CapabilityRelevanceService`（或同级方法），输入任务上下文 + 候选能力，输出 `CapabilityRelevanceAssessment`。复用 `get_capabilities` 的就绪过滤作为候选集来源。
- `computation_adapters/registry.py` `supported_workflow_engine_pairs`：作为计算工具候选清单的数据源。
- `assistant_service.py:1641` `_resolve_selected_tools` / `:1660` `_propose_tool_calls`：在构建 `selected_tool_ids` 前插入相关性筛选，用 `estimate_native_tool_schema_tokens`（`:1437`）做预算校验，超预算按 `confidence` 裁剪。
- `assistant_service.py:1391` `_build_function_tools`：保持不变，只接收筛选后的 `selected_tool_ids`。

#### 4.2.5 实施步骤

1. 在 `schemas/capabilities.py` 新增 `CapabilityRelevanceItem`/`CapabilityRelevanceAssessment`。
2. 实现 `CapabilityRelevanceService.assess`：few-shot prompt 二元分类，候选集来自 `get_capabilities` + `supported_workflow_engine_pairs` + 已发布 profile。
3. 在 `_propose_tool_calls` 链路插入筛选：原始 `selected_tool_ids` → 相关性筛选 → 预算校验裁剪 → `_build_function_tools`。
4. 落地评估审计：把 `CapabilityRelevanceAssessment` 写入助手事件，便于回放与调优。
5. 单测：相关性判定、预算裁剪、与全量注入的 token 对比回归。

#### 4.2.6 风险与缓解

- **风险**：相关性误判导致漏注入必要工具。**缓解**：保留「用户显式 `selected_tool_ids` 优先」语义，显式选择不被筛选裁掉；对高置信相关但被预算裁剪的工具在上下文里提示模型「可按需追问」。
- **风险**：增加一次分类调用延迟。**缓解**：分类用轻量模型/本地路由；对简单任务走规则兜底（如任务摘要命中关键词直接判定）。

### 4.3 【中】只读/可写双模式：统一执行分级与容器隔离

#### 4.3.1 现状

- `backend/app/computation_adapters/base.py` 定义 `AdapterContext`（`run`/`worker_id`/`workdir`/`started_at`/`timeout_seconds`）、`ArtifactSpec`、`AdapterRunResult`（`status`/`steps`/`artifact_specs`/`result_summary`/`error`）、`ComputationAdapter` Protocol（`validate_input`/`run`/`collect_artifacts`/`parse_result`）与 `build_steps`。
- `backend/app/workers/computation_worker.py` 负责计算执行。已有步骤时间线、制品产出、error/log 落盘，但制品主要面向计算，未覆盖实验下发全链路。

#### 4.3.2 差距

- 缺统一的只读/可写分级：计算适配器与实验下发共用「执行」概念，但无显式的访问模式声明，难以按模式施加不同安全约束。
- 缺容器化隔离的统一抽象（ALS 用容器化 Jupyter 内核的只读/可写双模式）。

#### 4.3.3 目标设计

给 `AdapterContext` 增加访问模式分级，并把制品口径扩展到实验下发，与现有 dispatch 确认机制对齐。

```python
AccessMode = Literal["read_only", "writable"]

@dataclass(frozen=True)
class AdapterContext:
    """单次计算/下发运行的运行时上下文。"""
    run: ComputationRun
    worker_id: str
    workdir: Path
    started_at: datetime
    timeout_seconds: int
    access_mode: AccessMode = "writable"   # 新增：默认可写，下发预览/只读查询置 read_only
    sandbox_profile: str | None = None     # 新增：容器隔离配置标识，留作后续容器化扩展
```

模式语义：

- `read_only`：只允许查询/预览，不落盘可写制品、不触发外部下发；对应 dispatch 的 `preview`（`experiment_dispatch_service.py:102`，`persist=False`，`status="preview"`）。
- `writable`：允许产出制品、持久化、触发外部下发；对应 dispatch 的 `create`（`:118`，`persist=True`），且必须经过 `preview_digest` 确认（`:329`/`:342`）。

制品口径扩展：把 `ArtifactSpec` 的产出记录从「计算专属」扩展为「计算 + 下发」统一制品链，下发 manifest（`ExperimentDispatchManifest`，`schemas/experiment_dispatch.py:176`）也作为可追溯制品登记。

#### 4.3.4 集成点

- `computation_adapters/base.py` `AdapterContext`：新增 `access_mode`/`sandbox_profile` 字段（带默认值，向后兼容）。
- `computation_adapters/base.py` `ComputationAdapter.validate_input`：在 `read_only` 模式下校验「不触发写操作」，违反即返回失败 `AdapterRunResult`。
- `experiment_dispatch_service.py:102` `preview` / `:118` `create`：preview 路径置 `access_mode="read_only"`，create 路径置 `"writable"` 并复用 `preview_digest` 确认门。
- `computation_worker.py`：按 `access_mode` 决定是否落盘可写制品与是否允许外部调用。

#### 4.3.5 实施步骤

1. `AdapterContext` 增加 `access_mode`/`sandbox_profile`（默认值兼容现有调用）。
2. 在 `validate_input` 中按模式施加约束，`read_only` 禁止写制品/外部下发。
3. 把 dispatch 的 preview/create 与 `access_mode` 对齐，下发 manifest 纳入统一制品登记。
4. 单测：`read_only` 试图写操作被拒、`writable` 经确认后落盘。

#### 4.3.6 风险与缓解

- **风险**：现有适配器调用未传 `access_mode` 导致默认行为变化。**缓解**：默认 `writable` 保持现状，仅显式预览/只读路径置 `read_only`。
- **风险**：容器化隔离（`sandbox_profile`）当前无后端实现。**缓解**：本设计先落地模式分级与约束，`sandbox_profile` 作为预留字段，容器化在后续迭代接入。

### 4.4 【中】统一安全层：配置级边界限制 + 写黑/白名单

#### 4.4.1 现状

安全机制分散在各模块：

- `backend/app/alchemist_core/audit_log.py`：append-only 审计日志，记录优化决策以保证可复现与可追溯。
- 实验下发：`schemas/experiment_dispatch.py:189` `ExperimentDispatchManifest.preview_digest` 防篡改；`schemas/experiment_dispatch_profile.py:203` `DispatchBranch.stop_on_match` + `DispatchBranchAction.kind="block"` 条件阻断；`experiment_dispatch_profile_engine.py:25` `evaluate` 执行 `branches` 阻断并产出 `errors`；下发需 `preview_digest` 确认（`:329`/`:342`）+ 用户确认。
- 计算：`computation_adapters/registry.py` `get_adapter` 按 workflow/engine 白名单注册，不支持的组合直接 400。
- `experiment_dispatch_profile_engine.py:211` `_validate_target`：校验目标字段类型与必填。

#### 4.4.2 差距

- 安全分散，缺统一的「参数边界限制（数值上下限）+ 写白/黑名单（哪些 target 字段允许下发、哪些禁止）」配置级机制。
- 不同实验场景各自硬编码安全范围，无法「只改配置文件即可定义安全范围」。

#### 4.4.3 目标设计

借鉴 ALS OSPREY 的配置级安全：构建跨模块的安全层，提供可配置的参数边界限制 + 写白/黑名单 + 全链路审计，配置级、不改框架。PolyAgent 的 `DispatchTargetDefinition`/`DispatchTargetField`（`schemas/experiment_dispatch_profile.py`）已是天然的边界声明载体，在其上扩展。

```python
class BoundaryLimit(BaseModel):
    """单个数值字段的边界限制。"""
    min: float | None = None
    max: float | None = None
    min_inclusive: bool = True
    max_inclusive: bool = True
    message: str | None = None

class FieldSecurityPolicy(BaseModel):
    """单个 target 字段的安全策略。"""
    path: str
    write_allowed: bool = True          # 写白/黑名单：False 即禁止下发该字段
    boundary: BoundaryLimit | None = None
    allowed_values: list[Any] | None = None   # 枚举白名单
    audit_level: Literal["default", "verbose"] = "default"

class TargetSecurityPolicy(BaseModel):
    """一个 target 的整体安全策略（配置级）。"""
    target_id: str
    version: str
    field_policies: list[FieldSecurityPolicy] = field(default_factory=list)
    default_write_allowed: bool = True   # 未显式声明的字段默认是否可写
```

校验接入：在 `experiment_dispatch_profile_engine.py:211` `_validate_target` 中，类型校验之后追加安全策略校验——边界越界、枚举不匹配、`write_allowed=False` 的字段被赋值即记 `errors`，阻断下发。安全策略作为 target 的可选配置文件存放于 `backend/config/experiment_dispatch_targets/` 同级（如 `speclabos_external.security.v1.json`），与 target 契约解耦但同目录可发现。

#### 4.4.4 集成点

- `schemas/experiment_dispatch_profile.py`：新增 `BoundaryLimit`/`FieldSecurityPolicy`/`TargetSecurityPolicy`；`DispatchTargetField` 可选挂 `security` 引用。
- `experiment_dispatch_profile_engine.py:211` `_validate_target`：类型校验后追加边界/枚举/写白黑名单校验，违规入 `errors`。
- `experiment_dispatch_profile_engine.py:25` `evaluate`：`branches` 阻断与安全策略校验结果统一汇入 `DispatchEvaluationResult.errors`/`warnings`。
- `alchemist_core/audit_log.py`：安全校验命中的阻断/越界事件统一写入审计，形成全链路安全审计。
- `backend/config/experiment_dispatch_targets/`：新增安全策略配置文件，配置级定义边界与白黑名单。

#### 4.4.5 实施步骤

1. 新增安全策略 schema（`BoundaryLimit`/`FieldSecurityPolicy`/`TargetSecurityPolicy`）。
2. 在 `_validate_target` 接入边界/枚举/写白黑名单校验，违规入 `errors` 阻断。
3. 安全策略配置文件落地，按 target 维度配置（如 SpecLabOS 温度/压力等关键参数边界）。
4. 安全校验事件接入 `audit_log`，统一审计口径。
5. 单测：越界阻断、枚举不匹配、黑名单字段被赋值阻断、白名单内放行。

#### 4.4.6 风险与缓解

- **风险**：安全策略与 target 契约解耦可能导致配置遗漏。**缓解**：`default_write_allowed` 提供兜底默认；启动时校验「已注册 target 是否有对应安全策略」，缺失则告警。
- **风险**：边界配置过严误伤合法下发。**缓解**：违规统一走 `errors`/`warnings` 两档，非关键越界可配为 `warn` 放行但留痕。

### 4.5 【中】NL 驱动参数解析器：从人工映射走向自然语言驱动下发

#### 4.5.1 现状

- `schemas/experiment_dispatch_profile.py` 已有声明式映射体系：`DispatchSourceContract`（源契约）、`DispatchTargetField`/`DispatchTargetDefinition`（目标契约，`backend/config/experiment_dispatch_targets/speclabos_external.v1.json` 为例）、`DispatchValueSource`（`kind` 为 `path`/`constant`/`coalesce`/`manual`/`target`）、`DispatchTransform`（`cast`/`scale`/`lookup`/`concat`/`array_item`/`default`）、`DispatchMapping`、`DispatchBranch`（条件分支 + `stop_on_match`）。
- `experiment_dispatch_profile_engine.py:25` `evaluate` 按 mappings 解析源 → transforms → manual override → branches 阻断，产出 `DispatchEvaluationResult`（payload/trace/matched_rules/warnings/errors）。
- 现状是「用户手选 profile + 手填 `manual_values`」（`ExperimentDispatchProfileEvaluationRequest.manual_values`，`:325`）。

#### 4.5.2 差距

- 是人工声明式映射，缺「NL → 原子意图 → 通道解析」的动态解析能力；用户需懂 profile 字段才能填 `manual_values`。

#### 4.5.3 目标设计

在现有声明式配置之上叠加 NL 驱动参数解析：自然语言 → 拆解为原子意图（抽取关键参数）→ 映射为具体字段路径与值 → 仍走现有 `evaluate` 的 contract 校验 + branches 阻断，安全不降级。

```python
class AtomicIntent(BaseModel):
    """从自然语言拆解出的单个原子意图。"""
    intent_id: str
    description: str                  # 如「设定反应温度为 80℃」
    target_path: str | None = None    # 解析到的 target 字段路径（JSON Pointer）
    value: Any = None
    unit: str | None = None
    confidence: float = 0.0
    resolved: bool = False            # 是否已解析到具体字段

class NLDispatchParseResult(BaseModel):
    """NL 参数解析结果，作为 manual_values 的来源。"""
    raw_text: str
    intents: list[AtomicIntent]
    unresolved: list[AtomicIntent] = field(default_factory=list)  # 未解析到的意图，需人工确认
    manual_values: dict[str, Any] = field(default_factory=dict)   # 解析结果，喂给 evaluate
    profile_id: str | None = None     # 推荐匹配的 profile
```

流程：

```text
用户自然语言请求
  → NLDispatchParser.parse(text, candidate_profiles)
      · LLM 拆解为 AtomicIntent 列表（抽取参数 + 单位）
      · 用 profile 的 target_fields + mappings 做字段解析（关键词/同义词 → target_path）
      · 未解析到的 intent 进 unresolved，需人工确认（不静默丢弃）
      · 输出 manual_values + 推荐 profile_id
  → 把 manual_values 喂给 experiment_dispatch_profile_engine.evaluate（:25）
      · 仍走 contract 校验 + transforms + branches 阻断 + 安全策略校验（4.4）
      · 解析结果不绕过任何现有安全门
  → 预览（preview_digest）→ 用户确认 → create
```

关键约束：NL 解析只产出 `manual_values` 候选，**不直接生成 payload**，最终 payload 仍由 `evaluate` 按 mappings/transforms/branches/安全策略生成，保证声明式配置作为可审计的约束底座不被绕过。

#### 4.5.4 集成点

- 新增 `backend/app/services/experiment_dispatch_nl_parser.py`：`NLDispatchParser.parse`，候选 profile 来自已发布 profile + `DispatchTargetField` 字段语义。
- `schemas/experiment_dispatch_profile.py`：新增 `AtomicIntent`/`NLDispatchParseResult`。
- `experiment_dispatch_profile_engine.py:25` `evaluate`：保持不变，仅消费解析产出的 `manual_values`；`_manual_override`（evaluate 内）已有 manual 覆盖逻辑可直接复用。
- `experiment_dispatch_service.py:102` `preview`：在 preview 前可选接入 NL 解析，把 `NLDispatchParseResult.manual_values` 作为 preview 输入，`unresolved` 意图在前端提示用户确认。
- 安全策略（4.4）与 `branches` 阻断对 NL 解析产出一视同仁，确保安全不降级。

#### 4.5.5 实施步骤

1. 新增 `AtomicIntent`/`NLDispatchParseResult` schema。
2. 实现 `NLDispatchParser.parse`：LLM 拆解原子意图 + 规则做字段解析（target_fields 关键词/同义词匹配）。
3. 接入 preview 链路：解析产出 `manual_values` 喂给 `evaluate`，`unresolved` 前端提示确认。
4. 全链路审计：NL 原文 + 解析结果 + 最终 payload 都入审计，保证可追溯。
5. 单测：典型参数解析、单位归一、未解析意图不静默丢弃、解析结果仍受 branches/安全策略阻断。

#### 4.5.6 风险与缓解

- **风险**：NL 解析误映射到错误字段导致危险参数下发。**缓解**：解析结果只产出 `manual_values` 候选，最终经 `evaluate` 的 contract/branches/安全策略三重校验；`unresolved` 不静默填充，必须人工确认。
- **风险**：工作量较大，影响面广。**缓解**：分阶段——先支持单 profile 的关键字段解析，再扩展多 profile 推荐；解析层与现有引擎解耦，可独立灰度。

## 5. 分期路线

### P0：Plan-first + 动态能力选择（高优先级，规模化关键）

- 落地 `StageExecutionPlan` 与 `_generate_stage_plan`，gate 阶段先计划后审批（4.1）。
- 落地 `CapabilityRelevanceService` 与助手工具注入筛选（4.2）。
- 收益：现有 Stage/Gate 获得可审查对象；工具清单膨胀得到治理。改动集中在编排器与助手注入链路，安全收益大。

### P1：统一安全层 + 只读/可写双模式（安全闭环）

- 落地 `TargetSecurityPolicy` 配置级安全与 `_validate_target` 校验接入（4.4）。
- 落地 `AdapterContext.access_mode` 分级与 dispatch preview/create 对齐（4.3）。
- 收益：安全从分散收敛为配置级统一；执行分级与现有确认机制对齐。

### P2：NL 驱动参数解析器（体验升级，分阶段）

- 落地 `NLDispatchParser`，先支持单 profile 关键字段解析，再扩展多 profile 推荐（4.5）。
- 收益：从「手选 profile + 手填参数」走向「自然语言驱动」，安全不降级。

## 6. 验收标准

- **Plan-first**：每个 gate 阶段在 `blocked_approval` 时携带 `StageExecutionPlan`，`approve_stage` 返回计划并记录「计划 vs 实际」核验结果；reject 可回退重生成。
- **动态能力选择**：助手工具注入按任务相关性筛选，注入前有 `CapabilityRelevanceAssessment` 留痕；与全量注入相比 token 显著下降且必要工具不被误裁（用户显式选择优先）。
- **只读/可写双模式**：`read_only` 模式下写操作/外部下发被拒并返回失败结果；`writable` 经 `preview_digest` 确认后落盘；下发 manifest 纳入统一制品登记。
- **统一安全层**：参数越界、枚举不匹配、黑名单字段被赋值均被 `_validate_target` 阻断并入 `errors`；安全事件写入 `audit_log`；配置级——不同实验场景只改配置文件。
- **NL 驱动参数解析器**：自然语言能解析为 `manual_values` 并经 `evaluate` 三重校验生成 payload；`unresolved` 意图不静默丢弃，前端提示确认；NL 原文与解析结果全链路审计。

## 7. 边界与不做事项

- 不引入裸脚本/任意代码执行；下发引擎保持非脚本、只解释固定操作符。
- 不替换声明式 profile/target 契约，只在其上扩展（安全策略、plan、NL 解析均为叠加层）。
- 不在本设计落地低优先级的三段式生成与混合推理敏感路由，后续单独评估。
- `sandbox_profile` 容器化隔离作为预留字段，容器化实现在后续迭代接入，本设计只落地模式分级与约束。
- NL 解析只产出 `manual_values` 候选，不直接生成 payload，不绕过任何现有安全门。

## 8. 来源与引用

- ALS Accelerator Assistant：先进光源（劳伦斯伯克利国家实验室）落地的大装置智能体，提供「自然语言 → 结构化计划 → 受限工具 → 容器化执行 → 全链路制品」范式与 OSPREY 配置级安全机制。本设计借鉴其编排与受限执行范式，PolyAgent 为本项目适配实现，落地时把「束流/EPICS PV」替换为「聚合物计算/SpecLabOS 实验条件」。
- PolyAgent ResearchEngine 设计：`doc/research-engine-and-auto-research-design.md`
- PolyAgent 实验下发设计：`doc/experiment-dispatch.md`
- PolyAgent 来源矩阵：`doc/polyagent-attribution-source-matrix.md`（落地实现时需将 ALS 作为框架参考登记入来源矩阵）
