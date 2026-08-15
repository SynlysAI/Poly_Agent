# Plan 08 收尾计划

> 状态：已完成
>
> 日期：2026-08-15
>
> 前置文档：[research-engine-plan-08-lui-runtime-and-tool-calling-workplan.md](research-engine-plan-08-lui-runtime-and-tool-calling-workplan.md)

## 1. 范围

本计划承接 Plan 08 评审清单中尚未完成的 P08-F2–F8，专注收口已知技术债；新一轮 LUI 增强只处理新增能力，不把既有缺口继续混入新功能计划。

已完成的 P08-F1（事件观测闭环）和 P08-F9（测试覆盖修正）不纳入本计划，仅在回归矩阵中持续跟踪。

## 2. 剩余项

| ID | 类型 | 目标 | 主要产出 | 状态 |
|---|---|---|---|---|
| P08-F2 | 上下文预算 | section 内截断、native tool schema 计入预算、token 估算可解释 | `AssistantContextAssembler` v2 + manifest 字段 + 测试 | 已完成 |
| P08-F3 | 工具契约 | 显式字段类型 / 数组对象约束 | schema 规范化与契约测试 | 已完成 |
| P08-F4 | 并行工具 | 可配置并发上限、多工具执行与失败回滚 | 执行层配置、多工具卡片与续答策略 | 已完成 |
| P08-F5 | 续答可靠性 | 退避、尝试计数、终态死信、旧数据回退语义 | continuation outbox 字段 + worker 重试策略 | 已完成 |
| P08-F6 | 质量指标 | 时间窗口、聚合缓存、细分分母 | 指标查询参数、缓存与统计口径 | 已完成 |
| P08-F7 | 受管资产 | 上传附件转为受管 runtime asset | 大小/生命周期/清理策略与迁移 | 已完成 |
| P08-F8 | 回放深度 | sanitized prompt snapshot 或可恢复 prompt log | 脱敏边界、TTL 快照方案 | 已完成 |

## 3. 建议顺序

1. P08-F5（续答可靠性）与 P08-F7（受管资产）优先，避免用户数据继续依赖临时文件和不可重试续答。
2. P08-F2、P08-F3、P08-F4 属于上下文与工具契约主线，可作为一个连续切片。
3. P08-F6 在 P08-F2 / P08-F3 / P08-F5 落地后统一校准指标。
4. P08-F8 在确认脱敏与存储边界后做轻量 TTL 快照，避免过早扩大敏感日志范围。

## 4. 完成定义

- 每个条目有对应后端或前端自动化测试。
- 回归矩阵新增或更新对应测试文件与验证命令。
- 不扩大敏感信息落库范围；受管资产有明确大小、生命周期和清理策略。
- 本计划状态更新为已完成前，Plan 08 主计划仍保持“主体完成，待收尾”。

## 5. 状态记录

- 2026-08-15：建立本收尾计划，承接 P08-F2–F8；P08-F1、P08-F9 已优先完成。
- 2026-08-15：P08-F2 已完成：上下文装配器支持 section 内截断、native tool schema token 计入预算，并在 manifest 中记录估算方法、native token 与截断状态。
- 2026-08-15：P08-F3 已完成：`AlgorithmIOSchema` 新增 `field_types`；工具契约支持显式 array/object 类型、`minItems` / `maxItems` 与数组长度校验，schema digest 同步覆盖显式类型。
- 2026-08-15：P08-F4 已完成：并行工具调用上限通过 `ASSISTANT_MAX_PARALLEL_TOOL_CALLS` 配置，模型和工具支持并行时最多 3 个；多工具卡片续答沿用现有消息构造，单条失败会回滚同批 pending 调用。
- 2026-08-15：P08-F5 已完成：`AssistantToolCall` 新增 `continuation_attempts`、`continuation_next_retry_at`、`continuation_dead_letter_reason`；活动 run 冲突按指数退避重试，超过上限转 `dead_letter`；旧数据 `context_manifest_digest` 不再误用 `schema_digest`。
- 2026-08-15：P08-F6 已完成：质量指标接口新增 `since` / `until` 时间窗口与 60 秒 TTL 缓存；fallback 与 proposal validation 分母修正为更准确口径。
- 2026-08-15：P08-F7 已完成：新增 `assistant_runtime_assets` 受管附件仓储与服务，上传文件从临时路径迁移到 runtime asset，具备大小校验、24h TTL、清理与旧 `_path` 兼容读取。
- 2026-08-15：P08-F8 已完成：LLM client 边界自动保存脱敏 prompt snapshot，敏感字段与凭据赋值统一脱敏，快照带 TTL 并限制最大条数。
