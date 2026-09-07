# 动态能力选择 few-shot 灰度增强计划

日期：2026-09-07
状态：待启动
前置设计：[plan-als-orchestration-and-bounded-execution.md](plan-als-orchestration-and-bounded-execution.md)（ALS 范式，已收尾）

## 1. 背景与目标

ALS 设计 P0 落地的 `CapabilityRelevanceService` 采用确定性规则：中英文轻量分词、泛化词降权、领域词匹配与置信度排序，零额外模型调用、行为可解释。评审结论要求：规则分类作为基线保留，few-shot LLM 二元分类作为**可灰度、可回滚**的增强路径，并用线上准确率回放指标验证，不纳入 P0 首次落地验收。

本计划承接该项遗留增强，目标：

- 在不改变 `CapabilityRelevanceAssessment` / `CapabilityRelevanceItem` 契约与 `tool.relevance.assessed` 事件语义的前提下，引入 few-shot LLM 二元分类（relevant / not relevant）。
- 规则分类始终作为兜底：LLM 不可用、超时、输出不合法或置信度不足时回退规则结果，助手链路不新增硬失败面。
- 建立线上准确率回放指标与灰度开关，默认关闭，按用户/比例逐步放量。

## 2. 实施步骤

- [ ] 配置与开关：新增 few-shot 分类灰度配置（默认关闭），支持按比例与用户 allowlist 放量；超时与失败计数接入结构化日志。
- [ ] Few-shot 分类器：在 `CapabilityRelevanceService` 内新增 few-shot 二元分类路径（few-shot 示例 + 工具元数据 + 任务摘要 → relevant 布尔值与置信度），输出仍写入 `CapabilityRelevanceItem`，`reason` 标注生成方式（rule/few_shot/fallback_rule）。
- [ ] 兜底与预算：LLM 失败/超时/低置信度回退规则得分；用户显式 `selected_tool_ids` 保护与 `ASSISTANT_TOOL_SCHEMA_TOKEN_BUDGET` 预算裁剪逻辑保持不变。
- [ ] 回放指标：基于历史 `tool.relevance.assessed` 事件与后续工具调用结果构建准确率回放（规则 vs few-shot 对比），产出精确率、召回率与误裁必要工具计数。
- [ ] 观测与放量：灰度期间双跑影子评估（不影响实际注入），指标达标后再切换实际注入；提供一键回滚开关。
- [ ] 回归与验收：相关性、显式优先、预算裁剪、SSE 注入与灰度开关测试全量通过。

## 3. 验收标准

- 灰度关闭时行为与现有规则基线逐字段一致；开启后仅 `reason` / 评估方式留痕变化。
- LLM 分类失败、超时或输出不合法时自动回退规则结果，助手请求成功率不下降。
- 回放报告能给出 few-shot 相对规则的准确率提升与必要工具误裁率，误裁率不高于规则基线。
- 显式选择保护、schema token 预算与审计事件语义不变。

## 4. 风险与回滚

- **风险**：LLM 分类延迟或误判导致必要工具漏注入。**缓解**：影子模式先行、超时兜底规则、显式选择保护、误裁率指标门禁。
- **回滚**：关闭灰度开关即回到纯规则路径，无数据迁移与契约变更。
