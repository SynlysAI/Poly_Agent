# 远程接口配置 Demo 服务

教学用玩具 Tg 预测服务，用于配合 PolyAgent「垂类模型（接口配置）」完成端到端联调：
本地启动服务 → 在接口配置页一键填入示例场景 → 确认 endpoint → 保存并样例测试 → 激活。

该服务只做教学演示：规则简单、无真实模型，请不要把它当作正式预测服务使用。

## 启动

```bash
cd examples/interface_config/demo_service
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8301
```

启动后验证：

```bash
curl http://127.0.0.1:8301/healthz
curl -X POST http://127.0.0.1:8301/predict -H "Content-Type: application/json" -d '{"smiles": "CCO"}'
curl "http://127.0.0.1:8301/predict?smiles=CCO"
```

## 可选鉴权（演示“密钥引用”）

设置 `DEMO_API_TOKEN` 环境变量后，服务要求 `Authorization: Bearer <token>`，无 token 或 token 错误返回 401：

```bash
DEMO_API_TOKEN=demo-secret uvicorn app:app --host 127.0.0.1 --port 8301

curl -X POST http://127.0.0.1:8301/predict \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer demo-secret" \
  -d '{"smiles": "CCO"}'
```

在接口配置向导中，把「密钥引用」配置为 `Authorization → MODEL_API_TOKEN`，再把 `MODEL_API_TOKEN`
对应的环境变量/密钥值设置为 `demo-secret` 即可完成联调。平台只保存引用名，不保存密钥值。

## 与接口配置向导的对照

| 配置项 | 推荐填写 |
| --- | --- |
| 协议 | `FastAPI`（POST JSON）或 `HTTP`（GET Query） |
| Endpoint URL | `http://127.0.0.1:8301/predict` |
| 请求方法 | `POST`（JSON body）或 `GET`（Query 绑定） |
| 超时（秒） | `30` |
| 输入字段 | `smiles`（string，必填） |
| 输出字段 | `prediction`（number，必填） |
| 响应提取路径 | `data.prediction` |
| 样例输入 | `{"smiles": "CCO"}` |

对应前端「示例场景 · 一键填入」中的：

- `fastapi_smiles`：FastAPI 单分子性质预测（POST JSON）。
- `http_get_binding`：GET 查询参数绑定（`smiles → ?smiles=CCO`）。
- `auth_header_secret`：带鉴权的接口接入（`DEMO_API_TOKEN`）。

## 本地联调说明

平台生产环境默认要求 HTTPS 并阻断 loopback/私网地址。本地用 `http://127.0.0.1:8301` 联调时，
需要后端开发环境显式开启私网访问（配置项 `REMOTE_INTERFACE_ALLOW_PRIVATE_NETWORK=true`，
对应环境变量 `REMOTE_INTERFACE_ALLOW_PRIVATE_NETWORK`），仅限开发环境使用。

## 框架与归属

Demo 服务基于 FastAPI 框架编写，仅作平台教学示例；服务不声明任何真实模型、机构或 Logo。
在接口配置页正式登记模型时，请填写真实开发者、机构、来源 URL 与引用信息。
