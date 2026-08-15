# Plan 08 LUI Runtime 回归测试矩阵

> 状态：2026-08-15，PR-08 完成时建立。
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
| LLM 配置 schema 目录 | `backend/tests/test_llm_model_management_api.py` | 字段说明、类型、默认值、错误路径 | 通过 |
| LUI 质量指标 | `backend/tests/test_assistant_quality_metrics.py` | 路由/工具/续答指标、context token 分布、事件重放异常 | 通过 |

执行命令：

```bash
cd backend
python -m pytest tests/test_llm_model_management_api.py \
  tests/test_assistant_quality_metrics.py \
  tests/test_assistant_runs_api.py \
  tests/test_assistant_event_log.py \
  tests/test_assistant_tool_calls_api.py \
  tests/test_assistant_tool_orchestration_api.py \
  tests/test_agent_tools_api.py -q
```

## 2. 前端测试

| 测试目标 | 覆盖文件 | 状态 |
|---|---|---|
| 默认模型选择优先级 | `frontend/src/utils/llmModels.test.mjs` | 通过 |
| 历史会话恢复与用户选择不覆盖 | `frontend/src/utils/dialoguePreferences.test.mjs` | 通过 |
| event reducer 合并 route / context / tool / answer | `frontend/src/utils/assistantEvents.test.mjs` | 通过 |
| stale phase 防降级 | `frontend/src/utils/assistantEvents.test.mjs` | 通过 |
| 上下文摘要与模型 meta | `frontend/src/utils/assistantContext.test.mjs`、`assistantUi.test.mjs` | 通过 |
| 工具菜单与自动选择 | `frontend/src/utils/assistantToolMenu.test.mjs`、`assistantToolAutoSelect.test.mjs` | 通过 |
| LLM 模型配置 | `frontend/src/utils/llmModels.test.mjs` | 通过 |

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
| 选择 tool-capable 模型完成工具调用 | `e2e/dialogue_e2e.py` | 已接入 |
| 工具运行中刷新页面恢复状态 | `assistantEvents` reducer + SSE 恢复 | 已覆盖 |
| 浏览器关闭后服务端 continuation | `backend/tests/test_assistant_runs_api.py` | 已覆盖 |
| 管理员查看 run trace | `GET /assistant/run-metrics/summary`、`GET /assistant/quality-metrics/summary` | 已覆盖 |

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
