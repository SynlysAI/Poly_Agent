# LUI Agent 离线评测

本目录实现 [Plan 13](../../../doc/research-engine-plan-13-lui-agent-evaluation-plan.md) 定义的 `/dialogue` 受控 LUI 八项指标评测体系。

## 评估边界

- 只覆盖受控 LUI 链路：意图路由、上下文装配、检索、工具提案、确认/补参/权限、服务端续答与最终回答。
- **计算任务不参与本评测**：xTB / CREST / ORCA / 本地结构生成等计算类工具，以及 ComputeEngine 完整计算任务，全部排除在 Golden Set 与运行矩阵之外。
- 工具类任务仅覆盖非计算 LUI 工具（垂类预测、知识检索、优化推荐）的提案层行为：选择、参数、确认、补参、权限与续答；不评估计算执行结果的数值质量。
- 不替代 Playwright 功能回归与 `assistant_quality_service` 链路指标。

## 目录结构

```text
backend/evaluation/lui/
  README.md          本说明
  schemas.py         Golden Set 与观测事实契约（Pydantic）
  dataset/           8 个分桶、共 80 条 Golden 任务（YAML）
  fixtures/          录制事实目录（captured facts，按 task_id 存放 JSON）
  baselines/         受控回归基线
  reports/           本地报告输出（不入库）
```

## 快速开始

```bash
# 离线 fixture 快速集（不调用真实模型）
PYTHONPATH=backend conda run -n poly_agent python scripts/run_lui_eval.py \
  --dataset backend/evaluation/lui/dataset --mode smoke \
  --report-dir backend/evaluation/lui/reports

# 基于录制事实的完整评测（任务先经产品链路执行并按 evaluation_id 抓取）
PYTHONPATH=backend conda run -n poly_agent python scripts/run_lui_eval.py \
  --dataset backend/evaluation/lui/dataset --mode full \
  --facts-dir backend/evaluation/lui/fixtures \
  --report-dir backend/evaluation/lui/reports
```

## Golden 任务标注规范

1. 每条任务必须有稳定 `id`（`LUI-<桶前缀>-<序号>`）、`category`、`difficulty`、`mode` 与 `messages`。
2. 工具类任务必须声明 `requires_model_capability: tool_calling`，且期望工具仅允许：
   - `algorithm:vertical_predictor_adapter`
   - `algorithm:weknora_adapter`
   - `algorithm:mobo_alchemist_adapter`
3. 数值参数必须给出 `argument_tolerance`（exact / absolute / relative / significant_figures / ignore）。
4. 拒绝题必须说明什么回答算正确拒绝；信息不足题必须声明不确定，不得伪装完整证据。
5. 涉及真实算法、模型、机构的字段必须复用项目事实，禁止标注无来源的外部声称。
6. Golden Set 变更必须递增数据集版本（`schemas.DATASET_VERSION`），历史报告保留对应版本，不允许静默改答案。

## 评测模型矩阵

| 角色 | 要求 | 示例 |
| --- | --- | --- |
| tool-capable 主模型 | 支持 function calling，qa/deep 双模式 | deepseek-chat / glm-4 系列任一已配置主模型 |
| 非 tool-capable 模型 | 不支持 function calling，验证降级与说明 | 项目内 chat 兼容模型任选 |
| 备选模型 | 与主模型不同 provider，验证路由稳定性 | 任一第二 provider 模型 |

具体模型以模型管理当前配置为准；录制事实评测时在 `context.model` 中固定 provider/model，保证同一报告内可比。

## 人工抽检规则

1. 每轮完整评测至少抽检 20% 的 M4（回答准确）与 M5（幻觉）判定，分层按分桶等比例抽取。
2. 抽检人只看任务、最终回答与判定理由，先独立判定再对照机器结果。
3. 分类型不一致率 = 该类型机器与人工判定不一致数 / 该类型抽检数；超过 5% 时该类型判定器不可上线，需修口径或修任务。
4. 抽检结论记录在报告 `manual_review` 字段：抽样任务 ID、判定一致与否、原因归类（任务歧义 / 判定器误判 / 判定器漏判）。

## 报告与基线

- `report.json`：机器可读的逐任务结果与 M1–M8 汇总。
- `report.md`：人类可读总结，按指标 / 分桶 / 模式拆解。
- `cases/*.md`：失败、幻觉与人工兜底样例。
- `baseline.json`：受控基线，入库 `baselines/`，后续回归对比使用。
