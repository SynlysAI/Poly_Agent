# ALS 编排与受限执行改进体验指南（Plan-first 验证 · 功能入口 · 环境配置）

> 适用范围：大装置 Agent 编排与受限执行设计（ALS 范式，已收尾）落地后的界面体验验证，覆盖 Plan-first 执行计划、自然语言参数解析、只读/可写双模式、统一安全层与动态能力选择五项改进。
>
> 2026-09-07 收尾说明：Plan-first 逻辑已拆分到独立纯逻辑模块（`backend/app/services/research_engine_plan.py`），API、Schema、DB、前端与审计字段零变更，本指南全部体验路径与验证结论继续有效。

## 一、环境配置

### 1. 本地服务地址

| 服务 | 地址 | 说明 |
| --- | --- | --- |
| 前端 | http://127.0.0.1:5200 | 默认开发端口 |
| 后端 | http://127.0.0.1:5201 | API 服务 |

### 2. 启动与验证

首次启动或依赖变更后，先执行环境初始化脚本：

```bash
bash scripts/setup_poly_agent_env.sh
```

日常启动或重启服务：

```bash
bash scripts/restart_poly_agent_services.sh
```

停止服务：

```bash
bash scripts/stop_poly_agent_services.sh
```

健康检查（两条命令均返回正常即为就绪）：

```bash
curl -s http://127.0.0.1:5201/api/v1/health   # 期望 {"code":0,"message":"ok",...}
curl -I -s http://127.0.0.1:5200/              # 期望 HTTP/1.1 200 OK
```

如启动失败，查看日志定位问题：

```bash
tail -100 /tmp/poly_agent_backend.log
tail -100 /tmp/poly_agent_frontend.log
```

## 二、功能体验入口

四个改进点分布在两块界面：**研发引擎（ResearchEngine）** 和 **任务提交 → 实验方案转发台**。

### 1. Plan-first 执行计划（核心可视化改进）

**路径**：`http://127.0.0.1:5200/#/research-engine`

创建或打开一个研究 Run，推进到带审批门的阶段时：

- 每个阶段会出现 **「执行计划」卡片**，点开「查看计划详情」可看到结构化计划：分几步、每步用什么工具、输入输出如何依赖。
- **审批**：审批决策会携带计划审查结果；若实际执行与计划不一致（mismatched），会按 `block_on_drift` 策略被拦住。
- **拒绝 → 重生成**：拒绝阶段后会出现 **「重生成计划」** 按钮，点击后：
  - 保留被拒计划与决策历史（卡片上可展开「历史被拒计划」）；
  - 生成一份新的草稿计划，**不会自动重试执行**。

### 2. 自然语言参数解析（体验感最强）

**路径**：`http://127.0.0.1:5200/#/optimization/experiment-dispatch`

- 在 **「自然语言实验条件」** 输入框直接写实验描述，例如：`反应温度 80℃；压力 5 MPa；时间 2 小时`。
- 点击解析后系统会：
  - 自动推荐匹配的 profile；
  - 把温度/压力/时间**回填到表单**，并做单位归一；
  - 解析结果仅作为人工参数候选，仍需通过配置与安全校验。
- **安全设计验证**：故意写一个解析不了的意图（如「顺便帮我加热」），系统不会瞎猜填充，而是进入「未解析意图」要求**人工确认**——未确认前无法预览或下发。

### 3. 只读/可写双模式

**路径**：同在实验方案转发台，体验「预览 → 确认 → 下发」两段式流程：

- 点 **「预览」**：生成 read_only 执行快照，不会落盘、不会真的下发；
- 确认预览摘要（preview_digest）后才允许保存/下发，进入 writable 模式；
- 任何篡改预览内容再提交的行为都会被摘要校验拦下。

### 4. 统一安全层

**路径**：同在实验方案转发台的校验结果中：

- 在参数里**故意填越界值**（如温度超出该实验允许上限），预览时会被 `TargetSecurityPolicy` 拦截，错误信息中可见安全事件；
- 安全边界按实验场景配置，拦截逻辑全局统一。

### 5. 动态能力选择（隐形改进）

主要体现在助手对话中：注入给模型的工具已按任务相关性筛选。用户感受是「回答更准、不容易乱调工具」，界面上无专门面板；开发者视角可在 SSE 事件流中看到 `tool.relevance.assessed` 留痕。

当前线上为**规则式基线**（分词 + 领域词匹配 + 置信度排序）；few-shot LLM 二元分类为独立后续计划，默认关闭、尚未上线，体验时不应感知到模型分类调用。

## 三、建议体验顺序

1. **先去实验方案转发台试自然语言解析**（约 5 分钟可看完整闭环）；
2. **再去 ResearchEngine** 推进一个带 Gate 的阶段，查看执行计划卡片与拒绝重生成流程；
3. **最后在转发台故意构造越界参数**，验证统一安全层拦截。

## 四、相关文档

- 设计方案（已收尾）：[plan-als-orchestration-and-bounded-execution.md](../../doc/plan-als-orchestration-and-bounded-execution.md)
- few-shot 灰度增强后续计划：[plan-capability-relevance-fewshot-upgrade.md](../../doc/plan-capability-relevance-fewshot-upgrade.md)
- ResearchEngine 技术方案：[research-engine-and-auto-research-design.md](../../doc/research-engine-and-auto-research-design.md)
- 实验下发设计：[experiment-dispatch.md](../../doc/experiment-dispatch.md)
