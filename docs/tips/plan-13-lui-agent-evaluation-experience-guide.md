# Plan 13：LUI Agent 评测体系体验指南与环境配置

> 适用版本：2026-09-01 Plan 13 全量完成 + Plan 13.1（录制事实 full 评测）代码侧完成版本
>
> 关联计划：[Plan 13：LUI Agent 评估与八项指标体系工作计划](../../doc/research-engine-plan-13-lui-agent-evaluation-plan.md)

## 一、这个功能做了什么

Plan 13 给 `/dialogue` 科研问答建了一套**"考试成绩单 + 体检报告"**：用 8 个数字量化 Agent 到底好不好用。以后每次改模型、改提示词、改链路，跑一遍评测就知道是**变好了、变慢了、变贵了还是更爱瞎编了**，不再靠感觉。

```text
Golden Set 标准考题（80 条 / 8 类场景）
    ├─ smoke 模式：内置离线 fixture，不调真实模型，秒级跑完，用于日常回归门禁
    └─ full 模式：真实产品链路执行 + 录制事实，得到真实延迟/成本/质量基线
```

### 八项指标（M1–M8）

| 指标 | 回答的问题 |
| --- | --- |
| 任务成功率（M1） | 用户任务是否端到端完成 |
| 工具调用正确率（M2） | 是否选对工具并给对参数 |
| 检索召回 Recall@K（M3） | 知识库/联网证据是否在 Top-K 被找回 |
| 最终回答准确率（M4） | 回答是否满足事实与任务要求 |
| 幻觉率（M5） | 是否出现无依据、虚构或错误来源 |
| P50/P95 延迟（M6） | 回答、首 token、工具和检索链路耗时 |
| 推理成本（M7） | 每任务消耗多少 token |
| 人工兜底比例（M8） | 多少任务需要人工确认、补参或接管 |

### Plan 13.1 新增的能力（2026-09-01）

1. **录制事实驱动器** `scripts/run_lui_capture.py`：把 80 条考题经真实产品链路执行（登录 → 建会话 → 提问 → 自动确认参数齐全的工具提案 → 等续答 → 抓取原始事实），补齐了此前缺失的“任务执行”半截。
2. **续答评测上下文透传修复**：工具确认后的服务端续答 run 不再丢失 `evaluation_id / task_id`，工具任务的最终回答能被正确抓取和评分。
3. **评测报告页管理员专属回归**：后端接口 `require_admin`（普通用户 403），前端路由守卫 + 菜单隐藏（普通用户重定向工作台），并补了自动化测试防回退。

## 二、如何体验

### 1. 页面入口：管理员评测报告（推荐先看这个）

1. 用**管理员账号**登录（默认 `admin`，见 `backend/.env` 的 `AUTH_USERNAME/AUTH_PASSWORD`）。
2. 左侧边栏 → 系统管理 → **评测报告**，或直接访问 `/admin/lui-evaluation`。
3. 右上角可切换 `smoke 快速集` / `full 完整集` 两种基线。

页面上能看到：M1–M8 通过率、分桶成功率（8 类场景）、qa/deep 模式成功率、人工抽检结论。普通用户既看不到菜单，直接输 URL 也会被踢回工作台。

### 2. 命令行：smoke 快速回归（不花钱，秒级）

```bash
# 离线 fixture 快速集 + 基线门禁（LUI 相关 PR 至少跑这个）
make test-lui-eval

# 或单独跑一次并输出报告
PYTHONPATH=backend conda run -n poly_agent python scripts/run_lui_eval.py \
  --dataset backend/evaluation/lui/dataset --mode smoke \
  --report-dir backend/evaluation/lui/reports
```

报告输出到 `backend/evaluation/lui/reports/`（`report.json` 机器可读、`report.md` 人类可读、`cases/` 失败样例）。

### 3. 命令行：录制事实 full 评测（真实模型，花 token）

完整流程是"先执行、再录制、后评测"三步：

```bash
# 第 1 步：把 Golden 任务经真实产品链路执行并抓取事实（登录信息走环境变量）
set -a; source backend/.env; set +a
export LUI_EVAL_USERNAME="$AUTH_USERNAME" LUI_EVAL_PASSWORD="$AUTH_PASSWORD"

PYTHONPATH=backend conda run -n poly_agent python scripts/run_lui_capture.py \
  --evaluation-id lui-eval-full-$(date +%Y.%m.%d) \
  --provider-id default_openai --model-id deepseek-v4-flash

# 第 2 步：基于录制事实生成完整报告 + 人工抽检表
PYTHONPATH=backend conda run -n poly_agent python scripts/run_lui_eval.py \
  --dataset backend/evaluation/lui/dataset --mode full \
  --facts-dir backend/evaluation/lui/fixtures/lui-eval-full-$(date +%Y.%m.%d) \
  --report-dir backend/evaluation/lui/reports \
  --metadata '{"model": "default_openai/deepseek-v4-flash"}' \
  --export-review-sheet backend/evaluation/lui/reports/full-manual-review-sheet.json \
  --reviewer "抽检人"

# 第 3 步：人工完成 ≥20% M4/M5 抽检后，汇入结论并保存 full 基线
PYTHONPATH=backend conda run -n poly_agent python scripts/run_lui_eval.py \
  --dataset backend/evaluation/lui/dataset --mode full \
  --facts-dir backend/evaluation/lui/fixtures/lui-eval-full-$(date +%Y.%m.%d) \
  --report-dir backend/evaluation/lui/reports \
  --manual-review backend/evaluation/lui/baselines/full-manual-review.json \
  --baseline backend/evaluation/lui/baselines/full-$(date +%Y.%m.%d).json
```

常用技巧：

- **先试点再全量**：加 `--categories tool_selection,knowledge_retrieval,project_fact` 只跑部分分桶，省 token 好排错。
- **重跑失败任务**：加 `--only-task LUI-KR-0003`，同一 `--evaluation-id` 下驱动器会取该任务最新 run。
- **失败不中断整批**：失败任务会列出清单、不写事实，命令退出码 1。
- **保留会话排查**：每任务建独立会话（标题带 `[LUI-EVAL]` 前缀）默认保留；确认链路没问题后可加 `--cleanup-chats` 清理。
- **工具确认策略**：驱动器只自动确认参数齐全（`awaiting_confirmation`）的提案；缺参提案保持原样，按 M2 参数错误如实扣分，不掩盖模型补参能力。

### 4. 生产侧持续观测（可选）

```bash
# 默认 dry-run，不连任何存储；支持 NDJSON 快照或显式只读 DB 模式
PYTHONPATH=backend conda run -n poly_agent python scripts/sample_lui_production_metrics.py --help
```

建议节奏：每两周或大版本发布前，导出快照 → 采样聚合 → 人工标注小批次 → 与上期对比 → 必要时刷新基线。

## 三、环境配置

### 1. 启动完整服务栈

full 评测需要**后端 + 前端 + 三个 worker** 全部在跑（smoke 不需要任何服务）：

```bash
bash scripts/restart_poly_agent_services.sh

# 验证
curl -s http://127.0.0.1:5201/api/v1/health
curl -I -s http://127.0.0.1:5200/
```

关键点：**assistant run worker 必须在跑**（`app.workers.assistant_run_worker`），录制任务靠它执行；如果刚改过 `assistant_run_service.py` 等后端代码，务必重启服务让 worker 加载新代码（uvicorn `--reload` 只热载 API 进程，不会热载 worker）。

### 2. 模型配置

录制事实评测要求固定同一个模型，保证同一份报告可比。当前环境推荐：

| 用途 | provider | model | 说明 |
| --- | --- | --- | --- |
| tool-capable 主模型 | `default_openai` | `deepseek-v4-flash` | 支持 tool_calling，qa/deep 默认路由 |

可在「工具服务 → LLM 模型」确认；评测时用 `--provider-id/--model-id` 显式锁定。

### 3. 登录与存储

- 登录账号读 `backend/.env` 的 `AUTH_USERNAME` / `AUTH_PASSWORD`（建议用管理员或专用评测账号，普通用户无法选中部分算法工具）。
- 本地默认 `STORAGE_BACKEND=sqlite`，数据在 `.runtime/poly-agent.sqlite3`；驱动器会自动加载 `backend/.env`，与后端读写同一份存储，无需额外配置。

### 4. 当前环境已知缺口（2026-09-01 试点实测）

试点首跑（`lui-eval-full-2026.09.01-pilot`，deepseek-v4-flash）结果：

| 分桶 | 结果 | 结论 |
| --- | --- | --- |
| knowledge_retrieval + project_fact（20 条） | 执行与事实抓取 20/20 全通 | 链路验证通过，M6 延迟 / M7 token 首次获得真实数值 |
| tool_selection（10 条） | 创建会话即被 403 阻断 | 工具目录口径冲突，见下 |

两个待解决缺口（全量前必须处理，**不要为对答案伪造环境数据**）：

1. **知识库缺失**：Golden 依赖的知识库（如 `kb-fluoro-handbook`）在当前环境不存在，WeKnora 返回 404，M3 Recall=0。需先在「知识库」模块接入真实知识库。
2. **工具目录口径冲突**：Golden 期望 `vertical_predictor_adapter / weknora_adapter / mobo_alchemist_adapter` 可作为 LUI 工具，但产品 LUI 工具目录只放行 `vertical_algorithm` 分组且要求 active 版本；当前环境实际可调用的是 5 个已上传垂类模型。需要决策：产品侧放行三适配器（需权限边界评审），或工具题改用已激活垂类工具（需递增数据集版本）。

## 四、常见问题

| 问题 | 原因与处理 |
| --- | --- |
| full 报告里大量 `missing_facts` | 该任务没有录制事实（未跑驱动器，或执行失败）。先跑 `run_lui_capture.py`，失败任务看 `failed_task` 清单。 |
| 创建会话报 403「算法工具不可用」 | 所选算法不在 LUI 可调用目录（无 active 版本或非垂类分组），见上文工具口径缺口。 |
| 工具任务抓不到最终回答 | 确认 worker 已加载 2026-09-01 之后的代码（续答透传修复），旧 worker 会让续答 run 丢失评测标记。 |
| M6/M7 显示"未判定" | smoke 模式下 fixture 没有真实耗时/token，属预期；full 录制事实模式才有数值。 |
| 评测数字和上期不可比 | 检查报告 `dataset_version` 与 `metadata.model` 是否一致；换模型或改数据集必须分开对比。 |
| 普通用户想看评测报告 | 设计如此：评测报告为管理员专属，普通用户 403 / 重定向工作台。 |

## 五、一句话总结

框架、指标、门禁、页面、录制驱动器全部就绪，"考试系统"已验收；smoke 门禁日常可跑，full 真实基线等知识库与工具目录两个环境缺口解决后即可全量落库。
