# Plan 14：LUI 动态计算预算体验指南

> 适用版本：2026-09-07 收尾版
>
> 关联计划：[Plan 14：LUI 动态计算预算与分级路由工作计划](../../doc/research-engine-plan-14-lui-dynamic-compute-budget-plan.md)

## 一、功能定位与收尾状态

Plan 14 已完成并关闭。它给 `/dialogue` 提供一个可审计的“分诊台”：先识别问题难度、风险与证据需求，再给出模型、检索和执行档位的默认建议；用户显式选择与系统安全策略始终优先。

```text
用户提问 → 难度 / 风险 / 证据需求分类 → 模型 / 检索 / 执行默认档位
         → 用户显式选择优先 → 安全策略兜底 → Execution Trace 记录
```

| 问题类型 | 模型档位 | 检索档位 | 执行档位 | 预期效果 |
| --- | --- | --- | --- | --- |
| 简单事实 / 导航 | 轻量快模型 | Vector Search | One-shot | 降低延迟与成本 |
| 复杂推理 / 多来源比较 | 深度模型 | Hybrid + Reranker | Planning | 提升证据完整性，等待可能增加 |
| 高风险执行 / 提交 / 正式报告 | 深度模型 | Hybrid + Reranker | Planning + Verification + Human | 不因降本绕过审批 |

收尾后的默认状态：

- `ASSISTANT_BUDGET_MODE=shadow`：只记录预算建议，不改变实际模型与检索行为。
- `ASSISTANT_BUDGET_ROLLOUT_PERCENT=0`：不进入百分比灰度。
- 后续阈值、默认模型档位、Hybrid 触发条件或执行档位调整，必须另立变更记录并附 Plan 13 指标对比。

## 二、默认安全观察路径

默认无需修改 `backend/.env`。启动服务后，系统即处于影子观测模式：

```bash
bash scripts/restart_poly_agent_services.sh
curl -s http://127.0.0.1:5201/api/v1/health
curl -I -s http://127.0.0.1:5200/
```

可检查当前配置与服务决策对象：

```bash
cd backend && conda run --no-capture-output -n poly_agent python -c "
from app.core.config import settings
from app.services.assistant_budget_service import assistant_budget_service
print('mode:', settings.assistant_budget_mode)
print('rollout_percent:', settings.assistant_budget_rollout_percent)
d = assistant_budget_service.decide(
    '请比较两种方法的证据、成本和风险，并给出可解释建议。',
    preset_id='research_qa', context={},
    current_user={'user_id': 'u_7515dfc26c81', 'username': 'admin'},
)
print('classification:', d.classification)
print('recommended:', d.recommended_model_tier, d.recommended_retrieval_tier, d.recommended_execution_tier)
print('effective:', d.effective_model_tier, d.effective_retrieval_tier, d.effective_execution_tier)
print('fallback_reason:', d.fallback_reason)
"
```

影子模式预期：

- `mode: shadow`。
- 能看到分类结果与建议档位。
- 实际行为仍按既有 `qa` / `deep` 静态路由执行。
- `fallback_reason` 含 `shadow_observation` 时表示建议未被真实启用，不是异常。

## 三、页面体验路径

打开 `http://127.0.0.1:5200/dialogue`，分别尝试三类问题。

### 1. 简单问题

```text
知识库设计文档入口在哪里？
```

预期分类为 simple，建议轻量模型 + Vector + One-shot；影子模式下仅记录建议，实际回复仍走原静态路由。

### 2. 复杂问题

```text
请比较两种方法的证据、成本和风险，并给出可解释建议。
```

预期分类为 complex，建议深度模型 + Hybrid/Reranker + Planning；回复动作区可能提供“切换深度科研”。

### 3. 高风险问题

```text
运行算法并把结果提交到正式报告。
```

预期分类为 high_risk，走 Planning + Verification + Human；必须等待验证、审批或人工确认，不能因预算策略降档或跳过安全节点。

### 查看预算事件

在会话统一回放中打开“动态计算预算”事件，可查看：

- 分类结果与置信度。
- 建议档位 vs 实际档位。
- 模型 / 检索 / 执行三档、用户覆盖、安全兜底与成本估算。
- `fallback_reason`：影子观测、用户覆盖、分类不确定或系统回退的原因。

管理员还可在 `/tools` 的 LLM 质量卡查看分类分布、档位分布、覆盖率、回退率与发布门槛提示。

## 四、可选：临时白名单灰度验证

只有需要验证预算策略真实生效时才配置，且只建议在本地或测试环境使用。不要把该配置写入长期生产默认值。

```bash
# 临时验证：只允许指定应用 user_id 命中
ASSISTANT_BUDGET_MODE=enabled
ASSISTANT_BUDGET_ROLLOUT_PERCENT=0
ASSISTANT_BUDGET_ALLOWED_USER_IDS=<application_user_id>
```

注意：

- 白名单匹配应用登录账号的 `user_id`，不是操作系统用户名。
- 未认证请求不进入百分比灰度；百分比灰度按用户级稳定哈希分组。
- 启用前应确认 Plan 13 smoke 门禁通过，并保留静态 / 预算双档对比与回滚方案。
- 高风险任务、审批、RBAC、AgentTool policy、Permission Mode 与用户显式选择不受灰度影响。

## 五、回滚

体验完成后恢复默认安全态：

1. 删除临时预算配置，或将 `ASSISTANT_BUDGET_MODE` 改回 `shadow`。
2. 保持 `ASSISTANT_BUDGET_ROLLOUT_PERCENT=0`。
3. 重启服务并确认 `mode: shadow`。

```bash
bash scripts/restart_poly_agent_services.sh
```

`shadow + 0%` 是收尾后的默认安全态；扩大灰度属于独立运维发布决策，不属于 Plan 14 的默认行为。
