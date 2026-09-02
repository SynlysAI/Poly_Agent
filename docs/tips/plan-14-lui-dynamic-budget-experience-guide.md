# Plan 14：LUI 动态计算预算体验指南与环境配置

> 适用版本：2026-08-28 Plan 14 完成版本
>
> 关联计划：[Plan 14：LUI 动态计算预算与分级路由工作计划](../../doc/research-engine-plan-14-lui-dynamic-compute-budget-plan.md)

## 一、这个功能做了什么

Plan 14 给 `/dialogue` 科研问答装了一个"智能分诊台"：系统会先判断问题是**简单、复杂还是高风险**，再自动决定用哪一档配置干活，同时平衡**效果、速度、成本、安全**。

```text
用户提问 → 难度 / 风险 / 证据需求分类 → 选择模型、检索与执行档位
         → 用户显式选择优先 → 安全策略兜底 → Execution Trace 记录
```

| 问题类型 | 模型档位 | 检索档位 | 执行档位 | 预期效果 |
| --- | --- | --- | --- | --- |
| 简单事实（入口、导航） | 轻量快模型 | Vector Search | One-shot 一次回答 | 延迟和成本更低 |
| 复杂推理（多来源比较、证据综合） | 深度模型 | Hybrid + Reranker | Planning 规划执行 | 证据更完整，等待时间可能增加 |
| 高风险（算法执行、提交、正式报告） | 深度模型 | Hybrid + Reranker | Planning + 验证 + 人工确认 | 不以降本为由绕过审批 |

几条重要规则：

- 用户手动选择的模型、知识库、联网检索和工具**永远优先**于自动建议。
- `/plan`、`/permission`、RBAC、AgentTool policy 和审批状态**始终优先**于预算策略。
- 高风险任务的验证 / 审批 / 人工确认节点**不可被降本逻辑移除**。
- 分类不确定或预算系统异常时，自动回退到旧的 `qa` / `deep` 静态路由，请求不会失败。

## 二、环境配置

### 1. 修改 `backend/.env`

在文件末尾追加以下配置：

```bash
# Plan 14 动态计算预算：启用灰度（仅白名单用户生效）
ASSISTANT_BUDGET_MODE=enabled
ASSISTANT_BUDGET_ROLLOUT_PERCENT=0
ASSISTANT_BUDGET_ALLOWED_USER_IDS=fangyikai,u_7515dfc26c81
```

配置项说明：

| 配置项 | 说明 |
| --- | --- |
| `ASSISTANT_BUDGET_MODE` | `disabled` / `shadow`（默认，只记录建议不改行为）/ `enabled`（真实生效） |
| `ASSISTANT_BUDGET_ROLLOUT_PERCENT` | 百分比灰度，`0` 表示只走白名单，`100` 表示全量 |
| `ASSISTANT_BUDGET_ALLOWED_USER_IDS` | 白名单用户，逗号分隔 |

### 2. 白名单身份的重要说明

白名单匹配的是**应用登录账号的 `user_id`**（形如 `u_7515dfc26c81`），不是操作系统用户名。

- 本地默认管理员账号为 `admin`，对应 `user_id = u_7515dfc26c81`。
- 用 `admin` 登录即可命中白名单。
- 如果要给其他账号开通，先查询该用户的 `user_id` 再加入白名单。

查询 `user_id` 的方法（本地 SQLite）：

```bash
python3 - <<'EOF'
import sqlite3, json
conn = sqlite3.connect('.runtime/poly-agent.sqlite3')
rows = conn.execute(
    "SELECT document_json FROM documents WHERE collection_name='users'"
).fetchall()
for r in rows:
    d = json.loads(r[0])
    print(d.get('username'), d.get('user_id'), d.get('role'))
EOF
```

### 3. 重启服务

```bash
bash scripts/restart_poly_agent_services.sh
```

验证服务健康：

```bash
curl -s http://127.0.0.1:5201/api/v1/health   # 后端
curl -I -s http://127.0.0.1:5200/             # 前端
```

### 4. 验证配置是否生效

```bash
cd backend && conda run --no-capture-output -n poly_agent python -c "
from app.core.config import settings
from app.services.assistant_budget_service import assistant_budget_service
print('mode:', settings.assistant_budget_mode)
print('allowed_users:', settings.assistant_budget_allowed_user_ids)
d = assistant_budget_service.decide(
    '请比较两种方法的证据、成本和风险，并给出可解释建议。',
    preset_id='research_qa', context={},
    current_user={'user_id': 'u_7515dfc26c81', 'username': 'admin'},
)
print('rollout_eligible:', d.rollout_eligible)
print('effective:', d.effective_model_tier, d.effective_retrieval_tier, d.effective_execution_tier)
print('fallback_reason:', d.fallback_reason)
"
```

生效的判断标准：

- `rollout_eligible: True`（白名单命中）
- `fallback_reason: None`（不再是 `shadow_observation`，策略真实生效）
- 复杂问题的实际档位为 `complex hybrid_reranker planning`

## 三、用户界面体验路径

打开 **http://127.0.0.1:5200/dialogue**，用 `admin` 登录，分别提以下三类问题：

### 1. 简单问题

```text
知识库设计文档入口在哪里？
```

预期：轻量模型 + 向量检索 + One-shot，回复速度快。

### 2. 复杂问题

```text
请比较两种方法的证据、成本和风险，并给出可解释建议。
```

预期：

- 升级为深度模型 + 混合检索 / 重排 + 规划执行。
- 回复动作区会出现"**切换深度科研**"按钮。

### 3. 高风险问题

```text
运行算法并把结果提交到正式报告。
```

预期：

- 走规划 + 验证 + 人工确认档位。
- 回复开头会出现说明："该任务按高风险档位执行：先规划证据与验证步骤，再等待人工确认。"

### 查看预算决策详情

每条回复下方 / 侧边的"**会话统一回放**"面板中，点开"**动态计算预算**"事件卡片，可以看到：

- 分类结果（simple / complex / high_risk）与置信度
- 建议档位 vs 实际档位（灰度生效后两者一致）
- 模型 / 检索 / 执行三档、用户覆盖、安全兜底、成本估算
- `fallback_reason`（生效后为空；影子模式下为 `shadow_observation`）

### 查看质量看板（管理员）

进入 `/tools` 页面的 **LLM 质量卡**，可以看到预算决策看板：

- 分类 / 模型 / 检索 / 执行档位分布表
- 决策总数、用户覆盖率、回退率
- 发布门槛与回滚提示

## 四、回滚方法

体验完想恢复默认影子观测，任选其一：

1. 把 `backend/.env` 中 `ASSISTANT_BUDGET_MODE` 改为 `shadow`（或 `disabled`），再重启服务。
2. 直接删除这三行预算配置（默认即为 `shadow` + 0%），再重启服务。

```bash
bash scripts/restart_poly_agent_services.sh
```
