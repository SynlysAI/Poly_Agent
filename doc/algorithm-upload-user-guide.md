# Poly Agent 算法上传部署用户指南

当前入口：`任务提交 -> 垂类预测模型`，对应路由 `/vertical-prediction`。

工作台包含四个 Tab：

- `上传部署`：上传 Python 脚本或标准 ZIP，下载模板，完成校验、构建、部署和激活。
- `算法管理`：查看版本、状态和追溯信息，执行部署、激活、回滚、冻结和下线；SHA256 默认放在折叠追溯区里。
- `测试调用`：根据版本 `input_schema` 填写参数，调用指定版本并查看输出、artifact 和耗时。
- `运行记录`：按算法、版本、状态和日期查找 AlgorithmRun，并查看输入输出与 digest。

ResearchEngine 只调用已治理的算法，不再提供算法上传入口。

## 使用方式

P0 支持三种入口：

- 网页打包助手：上传原始 `.py`、`requirements.txt` 和样例输入，页面生成标准 ZIP。
- 标准 ZIP 上传：下载模板或用 CLI 生成 ZIP 后上传。
- 本地 CLI：适合算法工程师在代码目录中打包。

## Python 入口契约

```python
def load(context: dict) -> object | None:
    return None

def predict(inputs: dict, context: dict, model: object | None = None) -> dict:
    return {"prediction": {}}
```

文件型算法仍使用同一个入口。平台会把原始上传文件路径放入 `context["input_files"]`，把通用解析结果放入 `context["parsed_inputs"]`，把可写输出目录放入 `context["output_dir"]`。handler 返回 `polyagent_run_result.v1` 时，平台会按 `output_assets` 登记文件产物。

P0 只支持 Python 3.11。上传包不能包含 Dockerfile、`.env`、shell 脚本、宿主机路径或路径穿越。

## 通用文件 I/O

`contract_version: "0.2"` 可声明文件输入、文件输出和受管资源：

- `input_assets`：声明用户运行时上传的文件。通用字段包括 `key`、`label`、`required`、`data_kind`、`parser`、`extensions`、`mime_types`、`max_size_bytes`、`sample_path`。
- `output_assets`：声明 handler 写入 `context["output_dir"]` 的产物文件。
- `resource_assets`：声明权重、数据库、tokenizer 等只读资源；大文件不放入 ZIP，优先通过“资源管理”登记服务器/挂载路径并按 `algorithm_id + asset_key` 自动绑定，`env_var` 保留为兼容兜底。

首批通用解析器：

- `table.v1`：`.csv/.xlsx` 到标准表格 JSON。
- `series_xy.v1`：`.txt/.dat/.csv/.xlsx` 到标准 x-y 序列 JSON。
- `json.v1`、`text.v1`、`binary.v1`：基础 JSON、文本和二进制 passthrough。

平台产品代码不区分 Raman 或其他业务模型，只按 `data_kind/parser/artifact_type` 渲染上传控件、预览和下载入口。

## CLI 示例

```bash
python scripts/pack_algorithm.py \
  --algorithm-id vertical_tg_predictor_demo \
  --name "Polymer Tg Predictor Demo" \
  --version 0.1.0 \
  --entrypoint src.handler:predict \
  --loader src.handler:load \
  --source-dir examples/algorithm_upload/vertical_tg_predictor_demo \
  --requirements examples/algorithm_upload/vertical_tg_predictor_demo/requirements.txt \
  --sample-input examples/algorithm_upload/vertical_tg_predictor_demo/tests/sample_input.json \
  --output /tmp/vertical_tg_predictor_demo-0.1.0.zip
```

网页工作台在提交后按顺序执行：校验、构建、部署、激活。激活版本会进入 AlgorithmRegistry，并可在垂类预测模型、人工 Workflow 和 AutoResearch 中调用。

进入 `垂类预测模型` 详情页后，可以查看单页 `算法摘要`，这里会把原先分散的亮点介绍和最佳实践合并成一处；当摘要需要追溯时，作者、机构、导师课题组和 digest 只保留一个展示位置，其他位置默认收起。

## 网页打包助手

1. 在“上传部署”选择“上传 Python 脚本”。
2. 填写算法 ID、名称、版本、开发者、开发机构、导师课题组、联系方式、类型、材料范围、触发方式、入口函数和加载函数。
3. 在输入/输出契约表格中维护字段名、类型、必填、单位、枚举和范围。
4. 如果模型需要大权重、数据库或 tokenizer，先在“资源管理”登记后端可访问路径，再在资源契约中声明 `asset_key`、`required_files` 和 `binding_required`。
5. 上传 `.py` 文件和可选的 `requirements.txt`。
6. 填写样例输入 JSON。格式错误会在提交前提示。
7. 检查页面生成的 `polyagent.algorithm.yaml` 预览，然后点击“校验、部署并激活”。
8. 完成后可下载平台生成的标准 ZIP，用于留档或再次上传。

## 来源、引用与机构 Logo

新算法包应尽量提供开发者来源，字段会显示在模型中心、详情页、版本治理和预测结果页：

- `developer`：模型开发者或团队。
- `developer_organization`：开发机构或单位。
- `mentor_team`：导师课题组信息，例如“张三教授课题组”。
- `developer_contact`：联系方式。
- `source_url`：论文、仓库、模型卡或算法说明链接。
- `citation`：推荐引用文本。
- `logo_asset` / `logo_url`：仅填写已授权或官方公开可展示的机构 Logo；缺失时页面显示文字来源牌。
- `method_attributions`：算法方法、框架或依赖来源列表。

历史包缺失来源字段时，平台使用创建人和“用户上传算法包”兜底，不伪造机构或 Logo。

## 版本治理

- `部署`：将已构建版本登记到本地 sandbox runtime staging。
- `激活`：设置 AlgorithmRegistry 的 active version；原 active 版本退回待激活状态。
- `回滚`：重新激活一个历史 staging 版本。
- `冻结`：保留版本与历史记录，但禁止新任务选择。
- `下线`：将版本标记为 decommissioned；历史 AlgorithmRun 仍保留追溯信息。

冻结或下线的版本不能用于新的测试调用、人工 Workflow 或 AutoResearch。

## 当前执行边界

P0.1-P0.3 已完成，P0-prod 默认使用 `local_sandbox_runtime`：上传算法在独立 Python 子进程中执行，支持 timeout、stdout/stderr 捕获和环境变量白名单。`local_inprocess` 仅保留给 dev/test 兼容路径。界面中的 `runtime_digest`、`environment_digest` 和 `package_digest` 是平台运行时追溯摘要，不是真实 Docker 镜像摘要；依赖安装、系统级资源隔离、硬性网络隔离和日志运维 API 仍属于后续增强。

## 标准 ZIP 结构

```text
polyagent.algorithm.yaml
requirements.txt
src/handler.py
tests/sample_input.json
tests/sample_assets/
README.md
model/
```

`polyagent.algorithm.yaml` 由网页打包助手或 CLI 生成。高级用户可以手写，但字段必须与页面展示的契约一致。大资源不要放入 ZIP；通过资源管理登记 mounted path，并确保路径位于 `.runtime/algorithm-resources` 或 `POLYAGENT_ALGORITHM_RESOURCE_ROOTS` 允许目录内。
