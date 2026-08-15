#!/usr/bin/env python3
"""Dialogue LUI 端到端与响应式验收脚本（Playwright）。

覆盖：
1. 1440px 下“选择算法工具 → 真实模型提议 → 用户确认 → 算法结果续答”的完整流程。
2. 320px / 768px / 1440px 三种视口下无整页横向溢出，算法工具选择器不超出视口。
3. 输出三种视口截图到 e2e/screenshots/。

运行前需要：
- PolyAgent 后端运行在 5201，前端运行在 5200（或通过环境变量覆盖）。
- PI 合成难度评分 Mock 运行在 127.0.0.1:8300。
- 已安装 poly_agent conda 环境的 playwright。

用法：
    conda run -n poly_agent python e2e/dialogue_e2e.py
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

import httpx
from playwright.sync_api import expect, sync_playwright


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND_ENV_PATH = REPO_ROOT / "backend" / ".env"
DEFAULT_BACKEND_URL = os.getenv("POLY_AGENT_BACKEND_URL", "http://127.0.0.1:5201").rstrip("/")
DEFAULT_FRONTEND_URL = os.getenv("POLY_AGENT_FRONTEND_URL", "http://127.0.0.1:5200").rstrip("/")
MOCK_URL = os.getenv("POLY_AGENT_PI_MOCK_URL", "http://127.0.0.1:8300").rstrip("/")
TOOL_NAME = "PI 合成难度评分 Mock"
TOOL_ID = "algorithm:pi_synthesis_mock_v2"
PROMPT = "请使用PI合成难度评分工具，评估 ODA 和 PMDA 在 NMP 中缩聚的合成难度，溶剂状态为 dry"
VIEWPORTS = ((320, 800), (768, 900), (1440, 900))


def load_env_file(path: pathlib.Path) -> dict[str, str]:
    """读取 KEY=VALUE 格式的本地环境文件。

    Args:
        path: 环境文件路径。

    Returns:
        解析后的环境变量字典。
    """
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        if key.strip():
            env[key.strip()] = value
    return env


def login_token(backend_url: str, env: dict[str, str]) -> str:
    """使用本地账号登录并返回访问令牌。

    Args:
        backend_url: 后端基础地址。
        env: 后端环境变量。

    Returns:
        登录成功后的 access_token。
    """
    payload = {
        "username": env.get("AUTH_USERNAME", "admin"),
        "password": env.get("AUTH_PASSWORD", "admin123456"),
    }
    response = httpx.post(
        f"{backend_url}/api/v1/auth/login",
        json=payload,
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()["data"]
    return str(data["access_token"])


def open_authenticated_page(
    playwright,
    frontend_url: str,
    token: str,
    viewport: tuple[int, int],
    path: str = "/dialogue",
):
    """打开已登录页面。

    Args:
        playwright: Playwright 根对象。
        frontend_url: 前端基础地址。
        token: 访问令牌。
        viewport: (宽度, 高度)。
        path: 要打开的路径。

    Returns:
        新创建的 Page。
    """
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
    console_errors: list[str] = []
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: console_errors.append(str(error)))
    page.goto(f"{frontend_url}{path}#token={token}", wait_until="domcontentloaded", timeout=60_000)
    if path == "/dialogue":
        page.locator(".dialogue-page").wait_for(state="visible", timeout=60_000)
    else:
        page.locator(".lui-hero").wait_for(state="visible", timeout=60_000)
    return browser, page, console_errors


def open_tool_category(page, category="垂类算法工具") -> None:
    """打开工具菜单并进入指定分类。"""
    page.get_by_role("button", name="选择工具").click()
    page.get_by_role("button", name=category).click()


def select_tool(page) -> None:
    """在输入区打开工具菜单并启用 PI Mock 工具。"""
    open_tool_category(page)
    tool_item = page.locator(".tool-menu-item", has_text=TOOL_NAME).first
    tool_item.wait_for(state="visible", timeout=15_000)
    tool_item.click()
    expect(tool_item).to_have_attribute("aria-pressed", "true")
    page.keyboard.press("Escape")


def assert_tool_selection_is_draft(page) -> None:
    """勾选工具后断言：不创建会话、不产生消息、不新增历史记录。"""
    page.wait_for_timeout(2_000)
    history_before = page.locator(".history-item").count()
    select_tool(page)
    page.wait_for_timeout(500)
    assert "/dialogue/" not in page.url, "勾选工具不应创建会话 URL"
    assert page.locator(".chat-message-user").count() == 0, "勾选工具不应触发用户消息"
    assert page.locator(".history-item").count() == history_before, "勾选工具不应新增历史记录"


def run_real_model_flow(page) -> None:
    """执行真实模型工具提议、确认执行与结果续答。"""
    assert_tool_selection_is_draft(page)
    composer = page.locator(".composer-box textarea")
    composer.fill(PROMPT)
    page.get_by_role("button", name="发送").click()

    awaiting_card = page.locator(".tool-call-card.tool-call-awaiting_confirmation")
    awaiting_card.first.wait_for(state="visible", timeout=120_000)
    page.get_by_role("button", name="确认执行").first.click()

    completed_card = page.locator(".tool-call-card.tool-call-completed")
    completed_card.first.wait_for(state="visible", timeout=120_000)

    assistant_bubbles = page.locator(".chat-message-assistant .chat-bubble-text")
    expect(assistant_bubbles.last).to_contain_text("难度", timeout=120_000)


def assert_no_horizontal_overflow(page) -> None:
    """断言页面没有超出视口的横向溢出。"""
    metrics = page.evaluate(
        """() => {
            const sidebar = document.querySelector('.app-sidebar')
            return {
                innerWidth: window.innerWidth,
                docScrollWidth: document.documentElement.scrollWidth,
                bodyScrollWidth: document.body.scrollWidth,
                sidebarDisplay: sidebar ? getComputedStyle(sidebar).display : 'none',
            }
        }"""
    )
    assert metrics["docScrollWidth"] <= metrics["innerWidth"] + 1, (
        f"页面横向溢出: scrollWidth={metrics['docScrollWidth']} innerWidth={metrics['innerWidth']}"
    )
    assert metrics["bodyScrollWidth"] <= metrics["innerWidth"] + 1, (
        f"body 横向溢出: bodyScrollWidth={metrics['bodyScrollWidth']} innerWidth={metrics['innerWidth']}"
    )
    if metrics["innerWidth"] < 900:
        assert metrics["sidebarDisplay"] == "none", "小屏下侧边栏未隐藏"


def assert_tool_picker_fits(page) -> None:
    """打开工具菜单两级视图并断言其不超出当前视口。"""
    page.get_by_role("button", name="选择工具").click()
    popper = page.locator(".tool-menu-popper").first
    popper.wait_for(state="visible", timeout=10_000)
    box = popper.bounding_box()
    assert box is not None, "工具菜单没有渲染"
    assert box["x"] >= -1 and box["x"] + box["width"] <= page.viewport_size["width"] + 1, (
        f"工具菜单分类视图超出视口: {box}"
    )
    page.get_by_role("button", name="垂类算法工具").click()
    box = popper.bounding_box()
    assert box is not None, "工具菜单工具列表没有渲染"
    assert box["x"] >= -1 and box["x"] + box["width"] <= page.viewport_size["width"] + 1, (
        f"工具菜单工具列表超出视口: {box}"
    )
    page.keyboard.press("Escape")


def assert_composer_controls_fit(page) -> None:
    """断言模型选择器与工具 warning 不超出当前视口。"""
    model_select = page.locator(".composer-model-select").first
    model_select.wait_for(state="visible", timeout=10_000)
    box = model_select.bounding_box()
    assert box is not None, "模型选择器没有渲染"
    assert box["x"] >= -1 and box["x"] + box["width"] <= page.viewport_size["width"] + 1, (
        f"模型选择器超出视口: {box}"
    )
    warning = page.locator(".composer-model-warning")
    if warning.count():
        warning_box = warning.first.bounding_box()
        assert warning_box is not None, "工具调用 warning 没有渲染"
        assert (
            warning_box["x"] >= -1
            and warning_box["x"] + warning_box["width"] <= page.viewport_size["width"] + 1
        ), f"工具调用 warning 超出视口: {warning_box}"


def run_manual_model_selection_flow(page) -> None:
    """选择非默认模型后切换模式，断言手动选择不被模式默认值覆盖。"""
    model_select = page.locator(".llm-model-select").first
    model_select.click()
    options = page.locator(".llm-model-select-popper .el-select-dropdown__item")
    options.first.wait_for(state="visible", timeout=30_000)
    if options.count() < 2:
        print("SKIP manual model selection flow: only one model available")
        page.keyboard.press("Escape")
        return

    before = model_select.locator(".el-select__selected-item").inner_text().strip()
    options.nth(1).click()
    after = model_select.locator(".el-select__selected-item").inner_text().strip()
    assert after and after != before, f"模型选择未切换: before={before!r} after={after!r}"

    mode_trigger = page.locator(".mode-trigger")
    current_mode = mode_trigger.inner_text().strip()
    target_label = "深度思考" if "科研问答" in current_mode else "科研问答"
    mode_trigger.click()
    target_item = page.locator(".el-dropdown-menu__item", has_text=target_label).first
    target_item.click()
    expect(mode_trigger).to_contain_text(target_label)

    after_mode_switch = model_select.locator(".el-select__selected-item").inner_text().strip()
    assert after_mode_switch == after, (
        f"切换模式后手动模型选择被覆盖: before={after!r} after={after_mode_switch!r}"
    )


def run_dashboard_flow(page) -> None:
    """工作台勾选工具后发送，工具选择应作为草稿透传到对话页。"""
    dashboard = page.locator(".lui-hero")
    dashboard.wait_for(state="visible", timeout=30_000)
    open_tool_category(page)
    tool_item = page.locator(".tool-menu-item", has_text=TOOL_NAME).first
    tool_item.wait_for(state="visible", timeout=15_000)
    tool_item.click()
    assert page.url.startswith(DEFAULT_FRONTEND_URL + "/dashboard"), "工作台勾选工具不应跳转"
    assert page.locator(".dialogue-page").count() == 0, "工作台勾选工具不应创建会话"
    composer = page.locator(".lui-composer textarea")
    composer.fill(PROMPT)
    page.get_by_role("button", name="发送").click()
    page.locator(".dialogue-page").wait_for(state="visible", timeout=30_000)
    chip = page.locator(".mention-chip--tool", has_text=TOOL_NAME)
    chip.wait_for(state="visible", timeout=15_000)


def main() -> int:
    """执行 Playwright 验收主流程。"""
    try:
        health = httpx.get(f"{MOCK_URL}/healthz", timeout=5)
        health.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(
            f"PI 合成难度评分 Mock 未就绪（{MOCK_URL}/healthz）: {exc}\n"
            "请先启动: cd services/pi_algo_test && conda run -n poly_agent uvicorn app:app --host 127.0.0.1 --port 8300",
            file=sys.stderr,
        )
        return 2

    env = load_env_file(BACKEND_ENV_PATH)
    backend_url = DEFAULT_BACKEND_URL
    frontend_url = DEFAULT_FRONTEND_URL
    token = login_token(backend_url, env)
    screenshots_dir = pathlib.Path(__file__).resolve().parent / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser, page, console_errors = open_authenticated_page(
            playwright,
            frontend_url,
            token,
            (1440, 900),
        )
        try:
            run_real_model_flow(page)
            page.screenshot(path=str(screenshots_dir / "dialogue-1440-flow.png"), full_page=True)

            for width, height in VIEWPORTS:
                page.set_viewport_size({"width": width, "height": height})
                page.wait_for_timeout(800)
                assert_no_horizontal_overflow(page)
                assert_tool_picker_fits(page)
                assert_composer_controls_fit(page)
                page.screenshot(path=str(screenshots_dir / f"dialogue-{width}.png"), full_page=True)
                print(f"PASS viewport {width}x{height}")

            page_errors = [
                item
                for item in console_errors
                if "favicon" not in item and "vite" not in item.lower()
            ]
            assert not page_errors, f"浏览器控制台存在错误: {page_errors[:10]}"
            print("PASS real-model E2E flow + responsive checks")
        finally:
            browser.close()

        browser, model_page, model_errors = open_authenticated_page(
            playwright,
            frontend_url,
            token,
            (1440, 900),
        )
        try:
            run_manual_model_selection_flow(model_page)
            model_errors = [
                item
                for item in model_errors
                if "favicon" not in item and "vite" not in item.lower()
            ]
            assert not model_errors, f"手动模型选择浏览器控制台存在错误: {model_errors[:10]}"
            print("PASS manual model selection persistence flow")
        finally:
            browser.close()

        browser, dashboard_page, dashboard_errors = open_authenticated_page(
            playwright,
            frontend_url,
            token,
            (1440, 900),
            "/dashboard",
        )
        try:
            run_dashboard_flow(dashboard_page)
            dashboard_errors = [
                item
                for item in dashboard_errors
                if "favicon" not in item and "vite" not in item.lower()
            ]
            assert not dashboard_errors, f"工作台浏览器控制台存在错误: {dashboard_errors[:10]}"
            print("PASS dashboard tool draft carryover flow")
        finally:
            browser.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
