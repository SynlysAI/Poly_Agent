# Plan 13：LUI Agent 评测体系体验指南

> 适用版本：2026-09-07 收尾版
>
> 关联计划：[Plan 13：LUI Agent 评估与八项指标体系工作计划](../../doc/research-engine-plan-13-lui-agent-evaluation-plan.md)

## 一、收尾后的稳定用法

Plan 13 已关闭为“代码链路与 full 自动判定基线完成”的评测底座，后续按以下分工使用：

| 场景 | 推荐动作 | 说明 |
| --- | --- | --- |
| 日常 LUI 相关 PR | `make test-lui-eval` | 离线 fixture 快速集，不调用真实模型、不花 token |
| 查看历史质量结果 | 管理员打开 `/admin/lui-evaluation` | 查看 smoke / full 基线、分桶结果与 M1–M8 指标 |
| 模型、提示词或关键 LUI 链路变更 | 先试点，再按需 full 重跑 | 真实链路会花 token，并依赖可用模型、知识库和工具目录 |
| M4/M5 开放判定校准 | 后续人工抽检任务 | 当前 full 基线仅代表自动判定口径 |
| 生产观测 | 只读采样或 NDJSON 快照 | 默认 dry-run，不自动连接生产库、不写生产数据 |

```text
Golden Set 标准任务（80 条 / 8 类场景）
    ├─ smoke：内置离线 fixture，日常回归与发布门禁
    └─ full：真实产品链路执行 + 录制事实 + 自动判定 + 人工抽检表
```

## 二、八项指标

| 指标 | 回答的问题 |
| --- | --- |
| 任务成功率（M1） | 用户任务是否端到端完成 |
| 工具调用正确率（M2） | 是否选对工具并给对参数 |
| 检索召回 Recall@K（M3） | 知识库 / 联网证据是否在 Top-K 被找回 |
| 最终回答准确率（M4） | 回答是否满足事实与任务要求 |
| 幻觉率（M5） | 是否出现无依据、虚构或错误来源 |
| P50 / P95 延迟（M6） | 回答、首 token、工具和检索链路耗时 |
| 推理成本（M7） | 每任务消耗多少 token |
| 人工兜底比例（M8） | 多少任务需要人工确认、补参或接管 |

## 三、日常体验路径

### 1. 跑离线回归门禁

```bash
make test-lui-eval
```

该命令使用 `backend/evaluation/lui/baselines/smoke-2026.09.01.json` 做基线对比。若需要临时输出独立报告：

```bash
PYTHONPATH=backend conda run -n poly_agent python scripts/run_lui_eval.py \
  --dataset backend/evaluation/lui/dataset --mode smoke \
  --report-dir backend/evaluation/lui/reports
```

### 2. 查看管理员评测报告

1. 使用管理员账号登录前端。
2. 进入系统管理 → **评测报告**，或访问 `/admin/lui-evaluation`。
3. 切换 smoke / full 基线查看 M1–M8、分桶成功率、模式分布与人工抽检结论。

评测报告为管理员专属能力；普通用户接口返回 403，前端路由也会重定向到工作台。

## 四、按需执行 full 录制事实评测

full 评测只在模型、提示词、检索、工具链路或关键 LUI 行为变更后按需执行。它会调用真实模型、消耗 token，并要求服务栈、模型凭据、知识库和工具目录均可用。

### 1. 启动并检查服务

```bash
bash scripts/restart_poly_agent_services.sh
curl -s http://127.0.0.1:5201/api/v1/health
curl -I -s http://127.0.0.1:5200/
```

assistant run worker 必须加载最新代码；uvicorn 的 API 热载不会自动热载 worker。

### 2. 执行、评分与抽检

```bash
set -a; source backend/.env; set +a
export LUI_EVAL_USERNAME="$AUTH_USERNAME" LUI_EVAL_PASSWORD="$AUTH_PASSWORD"
EVAL_ID="lui-eval-full-$(date +%Y.%m.%d)"

# 先试点，确认链路、模型和工具目录可用
PYTHONPATH=backend conda run -n poly_agent python scripts/run_lui_capture.py \
  --evaluation-id "$EVAL_ID" \
  --provider-id default_openai --model-id deepseek-v4-flash \
  --categories tool_selection,knowledge_retrieval,project_fact

# 试点通过后再去掉 --categories 执行 80 条全量任务
PYTHONPATH=backend conda run -n poly_agent python scripts/run_lui_capture.py \
  --evaluation-id "$EVAL_ID" \
  --provider-id default_openai --model-id deepseek-v4-flash

# 基于录制事实生成报告和抽检表
PYTHONPATH=backend conda run -n poly_agent python scripts/run_lui_eval.py \
  --dataset backend/evaluation/lui/dataset --mode full \
  --facts-dir "backend/evaluation/lui/fixtures/$EVAL_ID" \
  --report-dir backend/evaluation/lui/reports \
  --metadata '{"model": "default_openai/deepseek-v4-flash"}' \
  --export-review-sheet backend/evaluation/lui/reports/full-manual-review-sheet.json
```

常用控制：

- `--only-task <task_id>`：只重跑指定任务，减少 token 消耗。
- `--cleanup-chats`：确认链路可排查后清理 `[LUI-EVAL]` 会话。
- 驱动器只自动确认参数齐全的工具提案；缺参提案保持原样并计入 M2 事实。
- 换模型或改 Golden Set 后，报告的 `dataset_version` 与 `metadata.model` 必须单独记录，不能直接跨口径比较。

### 3. 人工抽检与基线升级

当前入库的 `full-2026.09.01` 是**自动判定基线**。`backend/evaluation/lui/reports/full-manual-review-sheet.json` 中的 16 条 M4/M5 记录还没有人工结论，已转为后续质量任务：

1. 人工补齐 `agree`、`reason_category` 与 `comment`。
2. 使用既有 manual review 流程计算人工一致率。
3. 达到门槛后，才允许基于同一 `evaluation_id` 与 `dataset_version` 生成人工验收版 full 基线。

full 首跑暴露的工具参数、escalation 持久化、检索排序与项目事实问题属于产品缺陷输入，不得通过修改答案、删除样本或放宽 tolerance 掩盖。

## 五、生产侧观测

```bash
# 默认 dry-run，不连接存储；显式数据库模式也仅只读
PYTHONPATH=backend conda run -n poly_agent python scripts/sample_lui_production_metrics.py --help
```

建议在大版本发布前或按固定观测周期执行：导出快照 → 只读聚合 → 匿名化抽样标注 → 与上期对比 → 必要时递增数据集版本并刷新基线。不要把生产采样脚本当成写入口。

## 六、常见问题

| 问题 | 处理 |
| --- | --- |
| full 报告存在 `missing_facts` | 先检查录制驱动器失败清单，补跑对应任务；不要手工编造事实。 |
| M6 / M7 显示未判定 | smoke fixture 没有真实耗时和 token，属预期；full 录制事实才有数值。 |
| 工具任务缺最终回答 | 确认 worker 已加载续答上下文透传修复，并检查提案确认与续答状态。 |
| 报告数字与上期不可比 | 核对 `evaluation_id`、`dataset_version`、模型与执行环境。 |
| 普通用户看不到报告 | 设计如此；评测报告仅管理员可见。 |

## 七、一句话总结

日常变更跑 smoke 门禁，重大变更按需跑 full 录制事实评测；当前 full 结果先按自动判定口径使用，人工验收版等待 16 条抽检补齐后生成。
