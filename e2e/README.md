# Dialogue LUI 端到端与响应式验收

`dialogue_e2e.py` 使用 Playwright（poly_agent conda 环境）验证：

1. 1440px 下完整链路：工具菜单勾选垂类算法工具（仅草稿、不创建会话/历史）→ 真实模型发起工具调用 → 用户在卡片确认 → 算法运行 → 结果注入并续答。
2. 工作台勾选工具后发送，工具选择以草稿透传到对话页。
3. 320px / 768px / 1440px 三种视口下无整页横向溢出，工具菜单两级视图不超出视口。
4. 手动选择非默认模型后切换问答/深度模式，断言模型选择不被模式默认值覆盖。
5. 320px / 768px / 1440px 下模型选择器与工具 warning 不超出视口。
6. 输出截图到 `e2e/screenshots/`。

`capability_admin_e2e.py` 使用同一组本地服务验证：

1. 管理员在 `/capabilities` 可见四个能力分组、来源牌和配置入口。
2. `/tools` 保留 6 个既有 tab，并能跳转能力中心。
3. 管理员在 `/admin` 可见“用户与邀请码”治理区。
4. 一次性普通用户只见调用目录，没有配置跳转；访问 `/tools`、`/admin` 会回退工作台。
5. 能力中心 320px / 768px / 1440px 无横向溢出，且页面无 console 错误。

## 运行前置

- 后端 `127.0.0.1:5201`、前端 `127.0.0.1:5200` 已启动。
- PI 合成难度评分 Mock 已启动（`services/pi_algo_test`，默认端口 8300；仅 `dialogue_e2e.py` 需要）。
- `capability_admin_e2e.py` 需要后端启用认证，并使用 `backend/.env` 中的管理员账号。
- 已安装 Chromium：`conda run -n poly_agent python -m playwright install chromium`。

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
