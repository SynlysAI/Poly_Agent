# Dialogue LUI 端到端与响应式验收

`dialogue_e2e.py` 使用 Playwright（poly_agent conda 环境）验证：

1. 1440px 下完整链路：工具菜单勾选垂类算法工具（仅草稿、不创建会话/历史）→ 真实模型发起工具调用 → 用户在卡片确认 → 算法运行 → 结果注入并续答。
2. 工作台勾选工具后发送，工具选择以草稿透传到对话页。
3. 320px / 768px / 1440px 三种视口下无整页横向溢出，工具菜单两级视图不超出视口。
4. 手动选择非默认模型后切换问答/深度模式，断言模型选择不被模式默认值覆盖。
5. 320px / 768px / 1440px 下模型选择器与工具 warning 不超出视口。
6. 输出截图到 `e2e/screenshots/`。

`capability_admin_e2e.py` 使用同一组本地服务验证：

1. 管理员在 `/tools?tab=ai-ready` 可见三个 AI 能力分组、来源牌，且没有配置按钮。
2. `/tools` 页签顺序为“状态、AI 能力、LLM 模型、Agent 连接器、算法清单、算法工具、服务配置”；Agent 连接器支持显式探测与策略配置。
3. 管理员在 `/admin` 可见“用户与邀请码”治理区。
4. 一次性普通用户只见 AI 能力，没有配置跳转；直接访问管理 tab 自动回落，且不触发管理 API；访问 `/admin` 会回退工作台。
5. `/capabilities` 旧链接跳转 `/tools`，AI 能力 320px / 768px / 1440px 无横向溢出，且页面无 console 错误。

## 运行前置

- 后端 `127.0.0.1:5201`、前端 `127.0.0.1:5200` 已启动。
- PI 合成难度评分 Mock 已启动（`services/pi_algo_test`，默认端口 8300；仅 `dialogue_e2e.py` 需要）。
- `capability_admin_e2e.py` 需要后端启用认证，并使用 `backend/.env` 中的管理员账号。
- 已安装 Chromium：`conda run -n poly_agent python -m playwright install chromium`。
- `dialogue_e2e.py` 使用真实外部模型，不使用 mock 替代；慢网关下工具确认到续答最多等待 10 分钟。

可用 `POLY_AGENT_BACKEND_URL`、`POLY_AGENT_FRONTEND_URL`、`POLY_AGENT_PI_MOCK_URL` 覆盖默认服务地址。

## 运行

```bash
make test-e2e
```

或：

```bash
conda run -n poly_agent python e2e/dialogue_e2e.py
```

脚本失败时会以非零状态退出，方便接入 CI。
