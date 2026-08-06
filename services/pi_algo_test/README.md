# PI 合成难度评分 Mock 接口（services/pi_algo_test）

针对 `refer/pi/` 需求（PI 自动实验对接：单体结构 → 难度评分 → 选择 P01–P09 工艺执行文件）搭建的
**真实 HTTP 接口 + 轻量确定性 mock 算法**，用于垂类算法上传与实验转发的仿真验证。

## 目录结构

| 文件 | 说明 |
| --- | --- |
| `app.py` | FastAPI 服务，`GET /healthz` 与 `POST /predict` |
| `mock_scoring.py` | 确定性打分引擎，运行时读取同目录 `PI_synthesis_difficulty_scoring_rules_v1.0.json` 的工艺区间 |
| `PI_synthesis_difficulty_scoring_rules_v1.0.json` | 评分规则（自包含副本；原始需求文档保留在 `refer/pi/`） |
| `client_simulate.py` | 本地仿真脚本：不经过平台，直接调用 `/predict` 并校验输出契约 |
| `platform_e2e.py` | 平台串通脚本：注册远程接口 → 测试 → 激活 → AlgorithmRun → 实验转发预览 → 下发配置评估 |
| `payloads/pi_interface.json` | 注册远程接口型垂类模型的完整请求体 |
| `sample_input.json` / `sample_output.json` | 示例请求与响应 |

## 启动 mock 服务

```bash
cd services/pi_algo_test
conda run -n poly_agent uvicorn app:app --host 127.0.0.1 --port 8300
```

验证：

```bash
curl -s http://127.0.0.1:8300/healthz
curl -s -X POST http://127.0.0.1:8300/predict -H 'Content-Type: application/json' -d @sample_input.json
```

## 本地仿真（不依赖平台）

```bash
conda run -n poly_agent python client_simulate.py
```

脚本会调用 `/predict`、打印完整评分 JSON，并断言：

- `D == R + H + S + U`
- `difficulty_score == D`
- `selected_process` 与评分规则 JSON 的 D 区间一致（0–11 → PI-P01 … 89–100 → PI-P09）
- `recommended_parameters` 回显输入

## 输出契约（与平台转发的对应关系）

`POST /predict` 直接返回评分 JSON（无包裹层），关键字段：

- `difficulty_score` + `recommended_parameters`：供实验模板 `pi_synthesis` 选择变体，
  生成 `execution_inputs.instruction_set_path`（`ChASM/PI-PXX.chasm`）与
  `hardware_graph_path`（`graph/test_ClosedLoop_PI_1024.graphml`）；
- `selected_process` + `calculation`：供下发配置 `pi_synthesis_dispatch` 映射
  SpecLabOS 请求的 `conditions` 与 `optimization_context`；
- `score_details` / `risk_tags` / `confidence` / `applicability`：对齐评分规则 JSON
  的 `required_model_output_schema`。

请求体必填 `diamine`、`dianhydride`、`solvent`；可选 `diamine_solubility`、
`dianhydride_solubility`（0–5）、`water_content_status`、`inert_atmosphere_status`
等字段做 ± 修正（未知字段不报错）。

## 平台串通（全链路）

前置条件：

1. 后端已启动（默认 `http://127.0.0.1:5100`），且 `backend/.env` 已追加：

   ```bash
   REMOTE_INTERFACE_ALLOW_PRIVATE_NETWORK=true
   ```

   该变量允许平台调用 127.0.0.1 本地接口（`_guard_endpoint` 默认拦截私网/回环地址），
   追加后需重启后端（保持原 5100 端口与启动方式）。

2. mock 服务已启动（8300 端口）。

3. 执行串通脚本：

   ```bash
   conda run -n poly_agent python platform_e2e.py
   ```

脚本依次执行：登录 → 注册 `pi_synthesis_mock` 远程接口 → 真实调用 `:test` →
激活版本 → 创建 `AlgorithmRun` → 实验转发预览（断言 chasm/graphml 路径）→
下发配置评估（断言 `conditions` 含 `selected_process`、payload 含指令集路径）。

## 已知差异

- **P05 温度**：评分规则 JSON 中 PI-P05 为 30℃；`PI自动实验对接规则.docx` 与
  实验模板中为 25℃。本 mock 以评分规则 JSON 为准（30℃），平台下发配置注释中
  亦标注了该冲突，接入真实算法前需确认。
- **算法为 mock**：分数由 `diamine|dianhydride|solvent` 的 SHA-256 确定性派生，
  不包含完整 R/H/S/U 规则引擎。接入真实算法时只需替换 `mock_scoring.py` 内部实现，
  HTTP 接口契约与平台注册配置保持不变。

## 归属说明

注册请求体（`payloads/pi_interface.json`）已按平台归属规范填写
`developer` / `developer_organization` / `developer_contact` / `source_url` /
`citation`；评分规则来源为随服务分发的 `PI_synthesis_difficulty_scoring_rules_v1.0.json`
（原始需求文档仍保留在 `refer/pi/`）。
