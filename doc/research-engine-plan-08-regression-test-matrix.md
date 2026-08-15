# Plan 08 LUI Runtime 回归测试矩阵

> 状态：2026-08-15，PR-08 完成时建立；同日评审修正测试归因与状态，并完成 P08-F2–F8 收尾验证。
>
> 本文用于把 Plan 08 的测试计划与当前实际测试文件、命令和验收结果对应起来。

## 1. 后端单元与 API 测试

| 测试目标 | 覆盖文件 | 主要断言 | 状态 |
|---|---|---|---|
| 字符串 model 配置兼容 | `backend/tests/test_llm_model_management_api.py` | `models: ["id"]` normalize 为 object | 通过 |
| object model 配置解析 | `backend/tests/test_llm_model_management_api.py` | per-model capabilities / context_window 等保留 | 通过 |
| 远端模型能力不继承 | `backend/tests/test_llm_model_management_api.py` | remote-only-model 标记 `inferred` 且无 `tool_calling` | 通过 |
| requested / resolved route | `backend/tests/test_llm_model_management_api.py`、`backend/tests/test_assistant_runs_api.py` | route reason 与两个模型字段区分 | 通过 |
| Tool Contract 约束 | `backend/tests/test_assistant_tool_contract.py` | enum/min/max/default/pattern/required | 通过 |
| malformed raw arguments | `backend/tests/test_assistant_tool_calls_api.py`、`test_assistant_tool_orchestration_api.py` | parse error 保留，参数不伪装为空 | 通过 |
| provider 错误分类 | `backend/tests/test_assistant_tool_orchestration_api.py` | 鉴权、超时、模型不存在分类 | 通过 |
| request manifest / context digest | `backend/tests/test_assistant_context_assembler.py` | sections、预算、omitted reason | 通过 |
| assistant event seq / 双写 / backfill | `backend/tests/test_assistant_event_log.py` | seq 连续、幂等回填 | 通过 |
| continuation 幂等 | `backend/tests/test_assistant_runs_api.py` | tool call 只触发一次续答 | 通过 |
| LLM 请求生命周期事件 | `backend/tests/test_assistant_llm_events.py` | started / failed / usage 统一落事件并关联 run/call | 通过 |
| LLM 配置 schema 目录 | `backend/tests/test_llm_model_management_api.py` | 字段说明、类型、默认值、错误路径 | 通过 |
| LUI 质量指标 | `backend/tests/test_assistant_quality_metrics.py` | 路由/工具/续答指标、context token 分布、事件重放异常 | 通过 |
| 上下文截断与 native schema 预算 | `backend/tests/test_assistant_context_assembler.py` | section 截断、native tool schema token、估算方式 | 通过 |
| 显式字段类型与数组约束 | `backend/tests/test_assistant_tool_contract.py` | `field_types`、`minItems` / `maxItems`、object 类型 | 通过 |
| 并行工具并发预算 | `backend/tests/test_assistant_tool_orchestration_api.py` | 配置上限、模型/工具能力判定 | 通过 |
| 续答退避与死信 | `backend/tests/test_assistant_runs_api.py` | `continuation_attempts`、退避与 `dead_letter` | 通过 |
| 质量指标时间窗口与缓存 | `backend/tests/test_assistant_quality_metrics.py` | `since` / `until`、TTL cache | 通过 |
| 受管 runtime asset | `backend/tests/test_assistant_runtime_assets.py` | 上传存储、读取、释放 | 通过 |
| 脱敏 prompt snapshot | `backend/tests/test_assistant_llm_events.py` | 敏感字段脱敏、TTL 快照 | 通过 |

执行命令：

```bash
cd backend
python -m pytest tests/test_llm_model_management_api.py \
  tests/test_assistant_quality_metrics.py \
  tests/test_assistant_context_assembler.py \
  tests/test_assistant_tool_contract.py \
  tests/test_assistant_runs_api.py \
  tests/test_assistant_event_log.py \
  tests/test_assistant_tool_calls_api.py \
  tests/test_assistant_tool_orchestration_api.py \
  tests/test_assistant_llm_events.py \
  tests/test_assistant_runtime_assets.py \
  tests/test_agent_tools_api.py -q
```

## 2. 前端测试

| 测试目标 | 覆盖文件 | 状态 |
|---|---|---|
| 默认模型选择优先级 | `frontend/src/utils/llmModels.test.mjs` | 通过 |
| URL / 历史会话模型恢复优先级 | `frontend/src/utils/llmModels.test.mjs` | 通过 |
| 用户手动选择不被模式切换覆盖 | `frontend/src/utils/llmModels.test.mjs`、`e2e/dialogue_e2e.py` | 通过 |
| `tool_calling` 标签展示 | `frontend/src/utils/llmModels.test.mjs` | 通过 |
| 模型无工具能力时 warning | `frontend/src/utils/llmModels.test.mjs` | 通过 |
| event reducer 合并 route / context / tool / answer | `frontend/src/utils/assistantEvents.test.mjs` | 通过 |
| stale phase 防降级 | `frontend/src/utils/assistantEvents.test.mjs` | 通过 |
| raw arguments 与 parse error 展示 | `frontend/src/utils/assistantToolCalls.test.mjs` | 通过 |
| 上下文摘要与模型 meta | `frontend/src/utils/assistantContext.test.mjs`、`assistantUi.test.mjs` | 通过 |
| 工具菜单与自动选择 | `frontend/src/utils/assistantToolMenu.test.mjs`、`assistantToolAutoSelect.test.mjs` | 通过 |
| LLM 模型配置 | `frontend/src/utils/llmModels.test.mjs` | 通过 |
| 320 / 768 / 1440 响应式布局 | `e2e/dialogue_e2e.py` | 通过 |

执行命令：

```bash
npm --prefix frontend run test:llm-models
npm --prefix frontend run test:assistant-events
npm --prefix frontend run test:assistant-ui
npm --prefix frontend run test:assistant-tool-menu
npm --prefix frontend run test:assistant-tool-auto-select
npm --prefix frontend run build
```

## 3. E2E 场景

| 场景 | 入口 | 状态 |
|---|---|---|
| 普通问答显示实际模型 | `e2e/dialogue_e2e.py` | 已接入；依赖真实模型与 PI Mock 环境 |
| qa/deep 模式切换默认模型 | `frontend/src/utils/llmModels.test.mjs` + DialogueView | 已覆盖 |
| 用户手动选择模型后切换模式不覆盖 | `e2e/dialogue_e2e.py` `run_manual_model_selection_flow` | 已接入 |
| 选择 tool-capable 模型完成工具调用 | `e2e/dialogue_e2e.py` | 已接入 |
| 选择非 tool-capable 模型时显示 warning 且不误调用 | DialogueView warning + 后端硬拦截 | 待补 E2E |
| 模型返回 malformed tool arguments | `backend/tests/test_assistant_tool_orchestration_api.py` + 前端展示单测 | 后端已覆盖，E2E 待补 |
| 工具运行中刷新页面恢复状态 | `assistantEvents` reducer + SSE 恢复 | 已覆盖 |
| 浏览器关闭后服务端 continuation | `backend/tests/test_assistant_runs_api.py` | 已覆盖 |
| 管理员查看 run trace | `GET /assistant/run-metrics/summary`、`GET /assistant/quality-metrics/summary` | 指标接口已覆盖；细粒度事件 trace UI 待补 |

## 4. PR-08 增量验证

本次 PR-08 新增：

- `GET /llm/config-schema`：从 Pydantic schema 生成字段目录。
- `GET /assistant/quality-metrics/summary`：聚合 LUI 调用质量指标。
- `scripts/generate_llm_config_schema.py`：生成 `docs/llm-provider-config-schema.md/json`。
- `AttributionService` 新增 `llm` 模块来源，`ToolServicesView` 的 LLM 模型标签接入来源横幅与配置/质量面板。

本地验证命令：

```bash
python scripts/generate_llm_config_schema.py
cd backend && python -m pytest tests/test_llm_model_management_api.py tests/test_assistant_quality_metrics.py -q
npm --prefix frontend run build
```

## 5. P08-F1 / P08-F9 增量验证

本次优先收尾新增：

- P08-F1：`LLMModelService` 统一发出 `llm.request.started`、`llm.request.failed`、`llm.usage.recorded`，`assistant_run_service` 通过 observation scope 关联 `run_id`；工具提案在创建 `AssistantToolCall` 后补写关联 `call_id` 的 usage 事件。
- P08-F9：`llmModels.js` 抽取 `shouldKeepManualModelSelection`、`modelLacksToolCalling` 纯函数并接入 `DialogueView`；`dialogue_e2e.py` 增加手动模型选择持久化、320/768/1440 模型选择器与 warning 边界断言。

本地验证命令：

```bash
PYTHONPATH=backend python -m pytest backend/tests/test_assistant_llm_events.py \
  backend/tests/test_assistant_event_log.py backend/tests/test_assistant_runs_api.py -q
npm --prefix frontend run test:llm-models
npm --prefix frontend run build
python -m py_compile e2e/dialogue_e2e.py
```

## 6. P08-F2–F8 收尾验证

本次收尾新增：

- P08-F2：`AssistantContextAssembler` 支持 section 内截断、native tool schema token 预算与 manifest 估算说明。
- P08-F3：`AlgorithmIOSchema.field_types` 显式类型、数组 `minItems` / `maxItems` 约束。
- P08-F4：`ASSISTANT_MAX_PARALLEL_TOOL_CALLS` 配置并行上限，多工具失败时回滚同批 pending 调用。
- P08-F5：续答冲突退避、`continuation_attempts` / `continuation_next_retry_at` / `dead_letter` 状态。
- P08-F6：`GET /assistant/quality-metrics/summary` 支持 `since` / `until` 与 60 秒聚合缓存。
- P08-F7：新增 `assistant_runtime_assets` 受管附件服务，上传附件带大小校验、TTL 和清理策略。
- P08-F8：LLM client 边界保存脱敏 prompt snapshot，敏感字段与凭据统一脱敏，带 TTL。

本地验证命令：

```bash
PYTHONPATH=backend python -m pytest \
  backend/tests/test_assistant_context_assembler.py \
  backend/tests/test_assistant_tool_contract.py \
  backend/tests/test_assistant_quality_metrics.py \
  backend/tests/test_assistant_llm_events.py \
  backend/tests/test_assistant_runtime_assets.py \
  backend/tests/test_assistant_runs_api.py \
  backend/tests/test_assistant_tool_orchestration_api.py -q
npm --prefix frontend run test:llm-models
npm --prefix frontend run test:assistant-events
npm --prefix frontend run test:assistant-ui
npm --prefix frontend run test:assistant-tool-menu
npm --prefix frontend run test:assistant-tool-auto-select
npm --prefix frontend run build
python -m py_compile e2e/dialogue_e2e.py
```
