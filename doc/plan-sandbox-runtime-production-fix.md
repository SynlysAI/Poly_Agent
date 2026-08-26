# 垂类模型 sandbox 启动失败修复计划

## 背景

生产环境调用 `electrolyte_formulation_predictor` 时，`local_sandbox_runtime` 子进程在执行用户算法前导入 `app` 包。由于 `backend/app/__init__.py` 导入了整个 FastAPI 应用，生产安全校验在子进程内触发，导致子进程没有输出协议 JSON，最终被外层包装为 `sandbox runtime did not return JSON`。

## 修复原则

- 保持 sandbox 环境变量白名单不放宽，避免向上传算法暴露认证密钥。
- 保持后端正式入口仍为 `app.main:app`。
- 只移除包初始化副作用，并增加回归测试防止再次引入。

## 行动项

- [x] 定位生产失败链路并确认根因。
- [x] 修复 `backend/app/__init__.py` 的应用导入副作用。
- [x] 补充 sandbox shim 轻量导入回归测试。
- [x] 运行本地相关测试。
- [x] 应用生产修复并重启 PM2 服务。
- [x] 线上验证垂类模型执行恢复。

## 状态记录

- 2026-08-26：完成生产只读排查，确认根因为 `app/__init__.py` 导入 `app.main`、sandbox 环境过滤 `AUTH_SECRET` 与生产配置校验叠加。
- 2026-08-26：已移除 `app/__init__.py` 的应用导入副作用，并新增独立进程回归测试；开始本地测试验证。
- 2026-08-26：`backend/tests/test_algorithm_runtimes.py` 3 项测试通过，`backend/tests/test_electrolyte_formulation_package.py` 5 项测试通过；本地验证完成。
- 2026-08-26：修复提交 `37afbef` 已推送 `develop`，合并提交 `79545d1` 已推送 `main`；生产仓库快进到 `79545d1`。
- 2026-08-26：生产 `poly-agent-backend` 与 `poly-agent-algorithm-worker` 已重启并保持 online，后端健康检查返回 MongoDB up。
- 2026-08-26：线上服务级冒烟运行 `arun_41047afdb08a` 完成，返回 1 条预测，runtime 退出码 0，耗时约 3.0 秒。
