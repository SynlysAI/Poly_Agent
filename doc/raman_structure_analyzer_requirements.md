---
template_version: "0.1"
algorithm_id: raman_structure_analyzer
name: Raman Structure Analyzer
version: 0.1.0
example_id: file_based_predictor
owner_name: Raman Demo Adapter
owner_contact: raman-demo@example.local
description: >
  输入 Raman/IR 光谱 x-y 序列文件和少量 JSON 参数，调用本地 Raman/IR 结构解析参考实现，
  输出候选结构、score、metadata、预处理信息，以及标准化序列、结构候选、结果表和运行报告文件。
material_scope:
  - universal
requirements_hint:
  - numpy
  - pandas
  - scipy
  - torch
  - transformers
  - rdkit
input_schema:
  fields:
    spectype: string
    mode: string
    x0: number
    x1: number
    k: integer
    transmittance: boolean
    device: string
  required:
    - spectype
    - mode
  field_defaults:
    spectype: raman
    mode: beam_search
    k: 3
    transmittance: false
    device: cpu
  field_options:
    spectype:
      - raman
      - ir
    mode:
      - beam_search
      - retrieval
      - function_groups
      - greedy_decode
    device:
      - cpu
      - cuda
output_schema:
  fields:
    candidates: list
    point_count: integer
    metadata: object
    preprocessing: object
  required:
    - candidates
sample_input:
  spectype: raman
  mode: beam_search
  x0: 400
  x1: 1800
  k: 3
  transmittance: false
  device: cpu
contract_version: "0.2"
algorithm_family: vertical_prediction
type: predictor
entrypoint: src.handler:predict
loader: src.handler:load
result_envelope: polyagent_run_result.v1
input_assets:
  - key: spectrum_file
    label: Spectrum data file
    required: true
    asset_role: input
    data_kind: series
    parser: series_xy.v1
    extensions:
      - .txt
      - .dat
      - .csv
      - .xlsx
    mime_types:
      - text/plain
      - text/csv
      - application/octet-stream
      - application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
    max_size_bytes: 10485760
    sample_path: tests/sample_assets/sample_spectrum.dat
output_assets:
  - key: normalized_series
    label: Normalized input series
    asset_role: output
    data_kind: series
    artifact_type: series_json
    mime_type: application/json
  - key: structure_candidates
    label: Structure candidates
    asset_role: output
    data_kind: json
    artifact_type: structure_json
    mime_type: application/json
  - key: candidate_table
    label: Candidate table
    asset_role: output
    data_kind: table
    artifact_type: csv
    mime_type: text/csv
  - key: run_report
    label: Run report
    asset_role: output
    data_kind: json
    artifact_type: report_json
    mime_type: application/json
resource_assets:
  - key: raman_checkpoints
    label: Raman checkpoints root
    asset_role: resource
    data_kind: binary
    parser: binary.v1
    required: true
    resource_type: checkpoints
    required_files:
      - baseline_removal.pth
      - raman_generation.pth
    binding_required: true
    env_var: RAMAN_CHECKPOINTS_ROOT
  - key: raman_database
    label: Raman database root
    asset_role: resource
    data_kind: binary
    parser: binary.v1
    required: true
    resource_type: database
    required_files:
      - raman_db.pkl
    binding_required: true
    env_var: RAMAN_DATABASE_ROOT
  - key: raman_tokenizer
    label: Raman tokenizer root
    asset_role: resource
    data_kind: binary
    parser: binary.v1
    required: true
    resource_type: tokenizer
    required_files:
      - tokenizer_config.json
    binding_required: true
    env_var: RAMAN_TOKENIZER_ROOT
runtime:
  python: "3.11"
  resources:
    cpu: 2
    memory: 8Gi
    gpu: true
  timeout_seconds: 180
developer: Raman Demo Adapter
developer_organization: Local Raman Reference
source_url: refer/raman
method_attributions:
  - name: Raman/IR structure analysis reference implementation
    role: implementation_source
    organization: Local Raman Reference
    description: Adapted from the local refer/raman reference code.
---

# PolyAgent 模型与数据集成需求收集表 - Raman Structure Analyzer

## 第一部分：数据需求

### 1.1 结构化数据（-> MongoDB）

本 demo 不需要预置结构化训练/查询数据写入 MongoDB。运行时输入由用户上传一个 x-y 序列文件，平台作为 `input_asset` 管理，并解析为标准 `series_json`。

字段说明表：

| 字段名 | 类型 | 是否必填 | 说明（含义+单位） | 示例值 |
| --- | --- | --- | --- | --- |
| spectype | string | 是 | 光谱类型 | raman |
| mode | string | 是 | 推理模式 | beam_search |
| x0 | number | 否 | 光谱 x 轴下界 | 400 |
| x1 | number | 否 | 光谱 x 轴上界 | 1800 |
| k | integer | 否 | 候选数量 | 3 |
| transmittance | boolean | 否 | IR transmittance 标记 | false |
| device | string | 否 | 推理设备 | cpu |
| spectrum_file | file | 是 | 运行时上传的 x-y 序列文件 | sample_spectrum.dat |

JSON 示例（一条完整记录）：

```json
{
  "spectype": "raman",
  "mode": "beam_search",
  "x0": 400,
  "x1": 1800,
  "k": 3,
  "transmittance": false,
  "device": "cpu"
}
```

原始数据文件：

| 字段 | 填写内容 |
| --- | --- |
| 文件格式 / 数量 / 大小 | `.txt/.dat/.csv/.xlsx`，运行时上传 1 个文件，单文件上限 10MB |
| 编码 / 分隔符 / 是否含表头 | 文本建议 UTF-8；支持空格、逗号、分号等常见分隔；`.xlsx` 读取前两列数值 |
| 提交方式 | 算法运行时通过 multipart 文件 part 上传，part 名称必须为 `spectrum_file` |
| 是否脱敏 | 不涉及个人信息；如包含实验元数据，由算法提交人自行脱敏 |

### 1.2 非结构化文件（-> MinIO / Artifact）

| 字段 | 填写内容 |
| --- | --- |
| 文件类型 / 数量 / 大小 | 输入：`.txt/.dat/.csv/.xlsx` x-y 序列文件；输出：`.json/.csv` |
| 与 MongoDB 记录的关联方式 | 通过 `AlgorithmRun.run_id` 和 artifact `owner_type=algorithm_run` 关联 |
| 文件命名规则 / 提交方式 | 输入文件 part key 为 `spectrum_file`；输出文件由 handler 写入 `context["output_dir"]` |

### 1.3 数据集元信息

| 字段 | 填写内容 |
| --- | --- |
| 数据名称 / 代号 | Raman/IR spectrum runtime input / `spectrum_file` |
| 负责人 | Raman Demo Adapter / raman-demo@example.local |
| 通俗功能描述（非技术人员能看懂） | 上传一条 Raman 或 IR 光谱，系统根据光谱形状给出可能的分子/结构候选。 |
| 来源 / 规模 / 更新频率 | 用户运行时上传；demo 内置 `tests/sample_assets/sample_spectrum.dat` 作为校验样例；不做周期更新。 |
| 关联数据说明 | 原始输入文件、平台解析后的 `series_json`、模型输出结构和报告均登记为运行 artifact。 |

### 1.4 可视化需求

| 字段 | 填写内容 |
| --- | --- |
| 展示形式 | JSON summary + artifact 列表 + 序列曲线预览 + CSV/JSON 下载 |
| 核心展示内容 | 候选结构、score、point_count、推理 metadata、预处理信息 |
| 图表类型 + 坐标轴 | 折线图，X=Raman shift 或输入 x 轴，Y=Intensity |
| 交互需求 | 支持查看 `series_json` 曲线、预览 JSON/CSV、下载原始输入和输出文件 |
| 参考截图 | 暂无 |

### 1.5 下游使用

| 字段 | 填写内容 |
| --- | --- |
| 下游分析接口 | 垂类预测模型测试调用、人工 workflow、后续 AutoResearch 编排 |
| 调用方式 | `POST /api/v1/research-engine/algorithm-runs:multipart` |
| 数据筛选条件 | 按 algorithm_id、run_id、artifact_type、created_by 查询 |
| 是否参与模型训练 | 否，本 demo 用于推理流程验证 |
| 输出格式需求 | `output_summary` JSON + `series_json/structure_json/csv/report_json` artifacts |

## 第二部分：模型 / 算法需求

### 2.1 算法基本信息

| 字段 | 填写内容 |
| --- | --- |
| 算法名称 / 代号 | Raman Structure Analyzer / `raman_structure_analyzer` |
| 负责人 | Raman Demo Adapter / raman-demo@example.local |
| 算法功能介绍 | 输入 Raman/IR 光谱 x-y 序列和 JSON 参数，调用本地 Raman 结构解析参考实现，输出候选结构、score、metadata、预处理信息和结果文件。 |
| 适用体系 | 通用材料 / 分子结构解析 demo |
| 分析类型 | 文件型垂类模型推理；结构候选预测 |
| 当前状态 | demo 可上传；真实推理依赖外部 Raman 权重、数据库、tokenizer 和 Python 依赖 |

### 2.2 算法运行方式

| 字段 | 填写内容 |
| --- | --- |
| 语言 / 版本 | Python 3.11 |
| 依赖（附 requirements.txt） | `numpy`、`pandas`、`scipy`、`torch`、`transformers`、`rdkit` |
| GPU 需求（是/否，显存） | 可选；`device=cpu` 可走 CPU，真实大模型建议 GPU；显存需求按 checkpoint 配置确认 |
| 入口脚本 + 调用示例 | `src.handler:predict`；平台通过 `AlgorithmRun` 调用，不直接运行脚本 |
| 模型权重（名称、大小、格式） | 不进入 ZIP；优先在资源管理登记 mounted path，按 `algorithm_id + asset_key` 自动绑定；`RAMAN_CHECKPOINTS_ROOT`、`RAMAN_DATABASE_ROOT`、`RAMAN_TOKENIZER_ROOT` 仅作兼容兜底 |
| 推理函数签名 | `def predict(inputs: dict, context: dict, model=None) -> dict` |
| 预处理 / 后处理需求 | 平台先用 `series_xy.v1` 解析输入文件；handler 读取 `context["parsed_inputs"]["spectrum_file"]` 并写出 artifacts |

### 2.3 已部署 HTTP 服务

| 字段 | 填写内容 |
| --- | --- |
| 服务地址 | 不适用，采用上传算法包本地 sandbox runtime |
| 接口路径 + 方法 | 不适用 |
| 鉴权方式 | 继承 PolyAgent 当前用户鉴权 |
| 健康检查接口 | 使用算法版本 health/logs 接口 |
| 并发能力 / 超时时间 | demo runtime timeout 180 秒；并发能力以后端执行器配置为准 |

### 2.4 其他要求

| 字段 | 填写内容 |
| --- | --- |
| 可视化需求（展示类型/交互需求） | 展示 output summary、输入文件、平台解析产物、模型输出 artifacts；`series_json` 支持曲线预览 |
| 性能（单次耗时/资源瓶颈） | 取决于 Raman checkpoint 和设备；CPU 可能较慢，GPU/模型资源为主要瓶颈 |
| 评估指标 | demo 暂不提供正式 accuracy 指标；验收关注流程可上传、可校验、可运行、artifact 完整 |
| 已知局限 | 无真实资源或依赖时校验/运行失败；不做 mock fallback；不支持 PDF/docx 文献解析 |
| 补充说明（License/特殊依赖等） | 来源为本地 `refer/raman` 参考实现；上线前需确认模型资源授权、依赖镜像和 GPU 调度 |

## 上传解析补充元数据

下面内容用于适配 `examples/algorithm_upload/raman_structure_analyzer-0.1.0.zip`。如果你要改 Raman 测试 ZIP 的上传解析字段，优先修改 YAML front matter 中同名字段，再同步修改正文说明。

### input_assets

```yaml
input_assets:
  - key: spectrum_file
    label: Spectrum data file
    required: true
    asset_role: input
    data_kind: series
    parser: series_xy.v1
    extensions: [.txt, .dat, .csv, .xlsx]
    mime_types:
      - text/plain
      - text/csv
      - application/octet-stream
      - application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
    max_size_bytes: 10485760
    sample_path: tests/sample_assets/sample_spectrum.dat
```

### output_assets

```yaml
output_assets:
  - key: normalized_series
    artifact_type: series_json
    mime_type: application/json
  - key: structure_candidates
    artifact_type: structure_json
    mime_type: application/json
  - key: candidate_table
    artifact_type: csv
    mime_type: text/csv
  - key: run_report
    artifact_type: report_json
    mime_type: application/json
```

### resource_assets

```yaml
resource_assets:
  - key: raman_checkpoints
    resource_type: checkpoints
    required_files: [baseline_removal.pth, raman_generation.pth]
    binding_required: true
    env_var: RAMAN_CHECKPOINTS_ROOT
    required: true
  - key: raman_database
    resource_type: database
    required_files: [raman_db.pkl]
    binding_required: true
    env_var: RAMAN_DATABASE_ROOT
    required: true
  - key: raman_tokenizer
    resource_type: tokenizer
    required_files: [tokenizer_config.json]
    binding_required: true
    env_var: RAMAN_TOKENIZER_ROOT
    required: true
```

### 输入 JSON 示例

```json
{
  "spectype": "raman",
  "mode": "beam_search",
  "x0": 400,
  "x1": 1800,
  "k": 3,
  "transmittance": false,
  "device": "cpu"
}
```

### 输出 JSON 示例

```json
{
  "candidates": [
    {
      "rank": 1,
      "structure": "candidate_structure",
      "score": 0.91
    }
  ],
  "point_count": 8,
  "metadata": {
    "spectype": "raman",
    "mode": "beam_search",
    "device": "cpu"
  },
  "preprocessing": {
    "normalization": "platform parser + model preprocess_spectrum"
  }
}
```
