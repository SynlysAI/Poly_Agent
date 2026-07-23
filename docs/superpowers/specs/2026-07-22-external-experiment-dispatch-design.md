# PolyAgent 与 SpecLabOS 外部实验任务联动设计

> 日期：2026-07-22 | 状态：待规格复核 | 版本：1.0

## 1. 目标与范围

打通 PolyAgent 向 SpecLabOS 下发实验条件的最小闭环：

1. PolyAgent 的 Alchemist 在生成贝叶斯优化实验建议后，可将一组或多组候选条件下发到 SpecLabOS。
2. SpecLabOS 接收并持久化该实验批次，在任务中心展示可查询的只读列表与详情。
3. 首期不连接设备、工作流、SmartAccess 或实验结果回传；接收后的任务状态固定为“已接收”。
4. 接口使用通用外部实验任务协议，不绑定 Alchemist，后续可接入 PolyAgent 的其他模块或其他上游系统。

不包含的范围：

- 自动选择实验设备、实验工作流或执行节点。
- 向设备或执行端下发真实湿实验指令。
- SpecLabOS 向 PolyAgent 回传执行状态或实验输出。
- 对历史推荐、任务撤销和重试队列进行复杂管理。

## 2. 方案选择

采用“通用实验批次任务”方案。

| 方案 | 结论 | 原因 |
| --- | --- | --- |
| 通用外部实验批次下发 | 采用 | 将来源、实验对象和条件列表统一建模，能承载 Alchemist 单点和批量采集建议，也能扩展其他来源。 |
| 复用 SmartAccess 运行任务 | 不采用 | 任务建议接收不等同于远程执行，会过早耦合工作流、节点和消息队列。 |
| 复用编排工作流任务 | 不采用 | 需要设备能力与参数映射，超出首期“接收并展示”的范围。 |

## 3. 总体架构

```text
Alchemist 采集优化面板
        |
        | 用户确认实验名称、实验对象和实验说明
        v
PolyAgent 后端下发接口
        |
        | HTTP POST + Authorization: Bearer <SPECLABOS_API_KEY>
        v
SpecLabOS 外部实验任务接收接口
        |
        v
MongoDB external_experiment_dispatches
        |
        v
SpecLabOS 任务中心 / 外部实验任务 页签
```

PolyAgent 前端不直接访问 SpecLabOS，所有跨系统通信由 PolyAgent 后端执行，以保护 API 密钥并统一处理超时和错误信息。

## 4. 通用数据契约

### 4.1 请求接口

SpecLabOS 提供：`POST /api/external-experiment-dispatches`。

请求头：

```text
Authorization: Bearer <API_KEY>
Content-Type: application/json
```

请求体：

```json
{
  "source_system": "polyagent",
  "source_module": "alchemist",
  "source_reference": {
    "session_id": "会话标识",
    "recommendation_id": "可选的推荐批次标识"
  },
  "experiment_name": "催化条件优化第 3 轮",
  "experiment_object": {
    "name": "目标反应或样品名称",
    "type": "reaction",
    "description": "可选的实验对象说明"
  },
  "experiment_content": "可选的实验说明、操作备注或验收要求",
  "conditions": [
    {
      "condition_id": "condition-1",
      "parameters": {
        "temperature": 100,
        "pressure": 94.87
      },
      "metadata": {
        "predicted_value": 0.0,
        "predicted_std": 0.0,
        "acquisition_value": 0.0
      }
    }
  ],
  "optimization_context": {
    "strategy": "EI",
    "goal": "maximize",
    "parameters": {
      "xi": 0.01
    }
  },
  "extra_metadata": {}
}
```

字段原则：

- `source_system`、`source_module`、`experiment_name`、`experiment_object.name` 与非空 `conditions` 为必填。
- `conditions` 表示一个实验批次中的多组候选条件；首期每条条件只保存，不执行。
- `parameters` 保存通用键值对，避免为某个算法或某类实验固定字段。
- `metadata` 与 `extra_metadata` 用于未来加入模型预测、优先级、样品 ID、耗材信息或来源平台私有字段。
- 服务器生成 `dispatch_id`、`received_at` 与初始状态 `received`，不信任调用方生成的任务 ID 或状态。

### 4.2 响应接口

成功响应：

```json
{
  "dispatch_id": "SpecLabOS 生成的批次标识",
  "status": "received",
  "received_at": "ISO-8601 时间"
}
```

SpecLabOS 同时提供：

- `GET /api/external-experiment-dispatches`：分页查询列表。
- `GET /api/external-experiment-dispatches/{dispatch_id}`：查询完整详情。

## 5. PolyAgent 设计

### 5.1 配置

新增以下环境变量：

```dotenv
SPECLABOS_BASE_URL=http://10.26.15.93:8010
SPECLABOS_API_KEY=<SpecLabOS 接入密钥>
```

可选增加超时配置，默认 30 秒。缺少地址或密钥时，PolyAgent 保留 Alchemist 推荐结果，但禁用下发并提示管理员完成配置。

### 5.2 服务边界

新增独立的 SpecLabOS 下发客户端服务，职责仅包括：

- 读取配置并构建目标 URL。
- 使用 Bearer Token 调用 SpecLabOS 接收接口。
- 映射网络、超时、非 2xx 响应为可读的业务错误。
- 返回 `dispatch_id` 与接收状态。

该服务不得了解 Alchemist 的页面状态；Alchemist 路由负责把 Session、采集策略和用户填写的实验信息转换为通用数据契约。

### 5.3 Alchemist 后端接口

新增 Session 范围内的下发接口：

```text
POST /api/v1/alchemist/sessions/{session_id}/acquisition/dispatch
```

接口接收实验名称、实验对象、实验说明、当前推荐条件和采集上下文；服务端校验：

- 调用用户拥有该 Session 的访问权限。
- 当前模型已训练。
- 条件列表非空，且每条条件包含当前搜索空间中的全部变量。
- 条件值满足变量类型、边界、离散集合或分类集合要求。

校验通过后，由服务端补充 `source_system=polyagent`、`source_module=alchemist`、Session 标识，再转发给 SpecLabOS。

### 5.4 Alchemist 前端交互

在“采集优化”面板的建议结果区域新增“下发至 SpecLabOS”按钮：

1. 仅在已有推荐条件时可用。
2. 弹窗必填“实验任务名称”“实验对象名称”，可选填写对象类型和实验说明。
3. 弹窗中只读展示待下发条件数量和条件表，避免用户误以为已执行。
4. 成功后展示 SpecLabOS 返回的批次标识和“已接收”状态；失败时保留原推荐表，提示原因，不改变模型或实验数据。

已有 Alchemist 方法来源标注保持不变；新增联动能力不新增或伪造第三方来源归属。

## 6. SpecLabOS 设计

### 6.1 后端模块

新增外部实验任务的 schema、repository、service 和 API route：

- Schema：请求、列表项、详情、接收响应。
- Repository：使用独立集合 `external_experiment_dispatches`，保存批次头信息、条件数组、来源上下文和时间戳。
- Service：进行必填字段校验、生成批次 ID、设置 `received` 状态。
- Route：接收、列表、详情三个接口。

接收接口使用 SpecLabOS 的统一 `external_api.api_token` 进行 Bearer Token 校验，同时兼容平台用户 Token 查询任务列表和详情。部署时，PolyAgent 的 `SPECLABOS_API_KEY` 必须与该统一令牌一致；SmartAccess 和 DataHub 的专用令牌不参与外部实验任务调用。

### 6.2 前端页签

任务中心新增：

```text
路由：/tasks/external-experiment-dispatches
页签名称：外部实验任务
```

列表字段：

| 字段 | 说明 |
| --- | --- |
| 状态 | 首期展示“已接收”。 |
| 实验任务 | `experiment_name`。 |
| 来源 | 系统和模块，例如 `PolyAgent / Alchemist`。 |
| 实验对象 | 对象名称与类型。 |
| 条件组数 | `conditions` 的数量。 |
| 关联来源 | 如 Alchemist Session 标识。 |
| 下发时间 | `received_at`。 |

详情抽屉或详情页展示实验说明、优化上下文、每条条件的参数表和可选元数据。首期没有“开始执行”“取消”按钮，避免暗示内部实验执行已经完成。

## 7. 错误处理与安全

- PolyAgent 的 API 密钥仅在后端读取和发送，绝不返回前端或写入浏览器存储。
- SpecLabOS 接收接口拒绝缺失或错误的 Bearer Token。
- PolyAgent 连接失败、超时或 SpecLabOS 返回错误时，返回明确错误；原推荐条件仍可继续查看、导出或再次下发。
- SpecLabOS 仅把有效请求写入数据库；无效数据返回 4xx，不创建部分记录。
- 接口保留来源与关联标识，为将来的幂等键、状态回传、执行适配器和审计日志提供基础。

## 8. 实施顺序

1. 在 SpecLabOS 新增通用外部实验任务数据模型、持久化、接收和查询接口。
2. 在 SpecLabOS 任务中心增加“外部实验任务”页签、列表和详情展示。
3. 在 PolyAgent 增加 SpecLabOS 配置、HTTP 下发客户端和 Alchemist 下发路由。
4. 在 PolyAgent 采集优化面板增加下发弹窗及成功/失败反馈。
5. 以配置的 SpecLabOS 地址完成接口联调；验证单点 EI 和批量 qEI 两类条件均能展示为一个批次。

## 9. 验收标准

1. Alchemist 对已训练模型生成建议后，用户可填写实验信息并成功下发。
2. SpecLabOS 返回 `dispatch_id`，PolyAgent 页面显示“已接收”。
3. SpecLabOS 的“外部实验任务”页签展示该批次及正确的条件组数。
4. 打开详情可查看所有条件参数、实验对象、实验说明和来源上下文。
5. 未配置或配置错误时，下发失败不影响 Alchemist 当前推荐结果。
6. 接口不依赖 SmartAccess 模板、设备或内部湿实验执行逻辑。
