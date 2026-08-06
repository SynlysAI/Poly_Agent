# 实验方案转发台

实验方案转发台负责把已完成的 `AlgorithmRun` 按版本化声明式配置转换成目标接口 payload，并在用户确认后调用 SpecLabOS 外部实验任务接收接口。它不计算 PI 评分、不调用 LLM，也不解释具体实验领域逻辑。

## 核心概念

用户在页面中选择一份“实验下发配置”（`ExperimentDispatchProfile`）。配置包含：

- `source_contract`：算法输入/输出字段契约，用 JSON Pointer 声明路径、类型、单位和必填性。
- `target_id@target_version`：目标接口契约。系统提供只读的 `SpecLabOS external experiment dispatch v1` 和 `Generic JSON`。
- `mappings`：以目标字段为中心的字段来源、回退、常量、人工输入和安全转换。
- `branches`：按优先级执行的条件句式，动作只能设置字段、追加警告或阻止生成。
- 版本、状态、可见性、所有者、备注和来源信息。

配置默认私有。发布版本不可原地修改，只能复制为新版本；公开配置只能引用已发布的目标契约。历史清单保存 Run、配置和目标契约快照，后续版本变化不会漂移历史结果。

## API

```text
GET    /api/v1/experiment-dispatch-profiles
POST   /api/v1/experiment-dispatch-profiles
GET    /api/v1/experiment-dispatch-profiles/{profile_id}?version=...
PATCH  /api/v1/experiment-dispatch-profiles/{profile_id}/versions/{version}
POST   /api/v1/experiment-dispatch-profiles/{profile_id}/versions/{version}/publication
POST   /api/v1/experiment-dispatch-profiles/{profile_id}/versions/{version}/copies
PATCH  /api/v1/experiment-dispatch-profiles/{profile_id}/versions/{version}/visibility
GET    /api/v1/experiment-dispatch-targets
GET    /api/v1/experiment-dispatch-candidates
POST   /api/v1/experiment-dispatch-profile-evaluations
POST   /api/v1/experiment-dispatches
GET    /api/v1/experiment-dispatches
GET    /api/v1/experiment-dispatches/{dispatch_id}
GET    /api/v1/experiment-dispatches/{dispatch_id}/export
```

试运行接口接收 `profile_id/version + run_id + manual_values`，返回 payload、逐字段追踪、命中分支、警告、阻断错误和 `preview_digest`，不保存清单。正式保存必须携带同一摘要；Run、配置版本或人工值变化后，服务端会拒绝过期摘要。

## 执行约束

执行器只解释固定的 JSON Pointer、类型转换、数值缩放/偏移、单位查表、枚举查表、文本拼接、数组取项和空值替代。条件操作符限制为 `exists / equals / notEquals / in / between / gt / gte / lt / lte`，不执行 Python、JavaScript、正则脚本、自由公式或用户表达式。

发布和试运行都会校验输入契约、目标字段、类型、必填项、重复赋值和阻断动作。预览不合法、关键字段缺失或目标契约校验失败时禁止保存。

## PI 迁移

`refer/pi` 只用于生成初始的系统公开配置 `pi_synthesis_dispatch@1.0.0`，运行时不作为注册表读取。PI 的工艺查表、资源路径和来源冲突提示都保存在该配置 JSON 中；通用服务不会出现 P01-P09、`difficulty_score`、ChASM 或温度判断。未来电解液、催化、合成和表征流程只需新增目标契约或下发配置。

旧 `experiment_template.v1` 清单读取和导出接口继续保留兼容能力，但新页面不再把模板文件作为运行时配置入口。

## 下发状态

用户点击“一键解析并下发”后，服务端会先保存本地清单，再将清单 payload 包装为 SpecLabOS 外部实验任务请求体并下发。SpecLabOS 返回接收回执后，本地清单状态更新为 `accepted`，并保存 `external_receipt`；如果下发失败，本地清单状态更新为 `failed`，并保存 `dispatch_error` 供页面展示和排查。

旧模板清单接口仍可生成 `prepared` 状态的本地清单，用于兼容历史导出和审计流程。
