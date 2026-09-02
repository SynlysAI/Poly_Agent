#!/usr/bin/env python3
"""能力中心与权限治理 Playwright 验收脚本。"""

from __future__ import annotations

import os
import pathlib
import sys
import time

import httpx
from playwright.sync_api import expect, sync_playwright


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND_ENV_PATH = REPO_ROOT / "backend" / ".env"
BACKEND_URL = os.getenv("POLY_AGENT_BACKEND_URL", "http://127.0.0.1:5201").rstrip("/")
FRONTEND_URL = os.getenv("POLY_AGENT_FRONTEND_URL", "http://127.0.0.1:5200").rstrip("/")
VIEWPORTS = ((320, 800), (768, 900), (1440, 900))


def load_env_file(path: pathlib.Path) -> dict[str, str]:
    """读取本地后端环境文件。

    Args:
        path: 环境文件路径。

    Returns:
        KEY=VALUE 字典。
    """
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def api_headers(token: str) -> dict[str, str]:
    """构建认证请求头。

    Args:
        token: 访问令牌。

    Returns:
        Authorization 请求头。
    """
    return {"Authorization": f"Bearer {token}"}


def login(backend_url: str, env: dict[str, str], username: str, password: str) -> str:
    """登录并返回访问令牌。

    Args:
        backend_url: 后端地址。
        env: 本地环境变量。
        username: 用户名。
        password: 密码。

    Returns:
        access token。
    """
    response = httpx.post(
        f"{backend_url}/api/v1/auth/login",
        json={"username": username, "password": password},
        timeout=15,
    )
    response.raise_for_status()
    return str(response.json()["data"]["access_token"])


def create_test_user(backend_url: str, admin_token: str) -> tuple[str, str]:
    """通过邀请码创建一次性普通用户。

    Args:
        backend_url: 后端地址。
        admin_token: 管理员访问令牌。

    Returns:
        (用户名, 密码) 元组。
    """
    suffix = f"cap{int(time.time())}"
    password = f"Cap-{suffix}-123456"
    invite_response = httpx.post(
        f"{backend_url}/api/v1/admin/invite-codes",
        json={"expires_hours": 1, "max_uses": 1},
        headers=api_headers(admin_token),
        timeout=15,
    )
    invite_response.raise_for_status()
    invite_code = str(invite_response.json()["data"]["invite_code"])
    username = f"e2e_{suffix}"
    register_response = httpx.post(
        f"{backend_url}/api/v1/auth/register",
        json={
            "invite_code": invite_code,
            "username": username,
            "password": password,
            "real_name": "能力中心 E2E",
            "organization": "PolyAgent E2E",
        },
        timeout=15,
    )
    register_response.raise_for_status()
    return username, password


def open_page(playwright, frontend_url: str, token: str, path: str, wait_selector: str):
    """打开已登录页面并收集 console/page error。

    Args:
        playwright: Playwright 根对象。
        frontend_url: 前端地址。
        token: 访问令牌。
        path: 页面路径。
        wait_selector: 页面主元素选择器。

    Returns:
        (browser, page, errors) 元组。
    """
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors: list[str] = []
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(f"{frontend_url}{path}#token={token}", wait_until="domcontentloaded", timeout=60_000)
    page.locator(wait_selector).wait_for(state="visible", timeout=60_000)
    return browser, page, errors


def assert_no_console_errors(errors: list[str]) -> None:
    """断言浏览器无业务相关错误。

    Args:
        errors: console 与 page error 列表。
    """
    filtered = [item for item in errors if "favicon" not in item and "vite" not in item.lower()]
    assert not filtered, f"浏览器控制台存在错误: {filtered[:10]}"


def assert_no_horizontal_overflow(page) -> None:
    """断言当前页面没有横向溢出。

    Args:
        page: Playwright 页面。
    """
    metrics = page.evaluate(
        """() => ({
            innerWidth: window.innerWidth,
            scrollWidth: document.documentElement.scrollWidth,
        })"""
    )
    assert metrics["scrollWidth"] <= metrics["innerWidth"] + 1, f"页面横向溢出: {metrics}"


def verify_admin_capability_page(page) -> None:
    """验证管理员能力目录内容。

    Args:
        page: 已打开 /capabilities 的页面。
    """
    expect(page.get_by_role("heading", name="能力中心")).to_be_visible()
    expect(page.locator(".module-source")).to_contain_text("OpenAI")
    for title in ("对话工具", "外部 Agent 连接器", "报告 Skill", "LLM 能力"):
        expect(page.locator(".group-heading h2", has_text=title)).to_be_visible()
    expect(page.locator(".capability-card").first).to_be_visible()
    expect(page.locator(".capability-card", has_text="Codex Agent 连接器").first).to_be_visible()


def verify_admin_tools_and_admin_pages(page) -> None:
    """验证管理员配置入口和用户治理入口。

    Args:
        page: 已登录管理员页面。
    """
    page.goto(f"{FRONTEND_URL}/tools", wait_until="domcontentloaded")
    page.locator(".tools-view").wait_for(state="visible", timeout=60_000)
    tabs = page.locator(".el-tabs__item").all_inner_texts()
    assert [item.strip() for item in tabs] == [
        "状态", "算法清单", "算法工具", "Agent 连接器", "配置", "LLM 模型"
    ], f"/tools tab 回归: {tabs}"
    expect(page.get_by_role("button", name="查看能力中心")).to_be_visible()

    page.goto(f"{FRONTEND_URL}/admin", wait_until="domcontentloaded")
    page.locator(".panel-title", has_text="系统管理").wait_for(state="visible", timeout=60_000)
    page.get_by_text("用户与邀请码", exact=True).click()
    expect(page.get_by_role("heading", name="用户与邀请码")).to_be_visible()
    expect(page.locator(".identity-section").first).to_contain_text("管理员")
    expect(page.get_by_role("button", name="创建邀请码")).to_be_visible()

    page.goto(f"{FRONTEND_URL}/admin/lui-evaluation", wait_until="domcontentloaded")
    page.locator(".lui-eval-page").wait_for(state="visible", timeout=60_000)
    expect(page.get_by_role("heading", name="LUI Agent 评测报告")).to_be_visible()
    expect(page.locator(".el-menu-item", has_text="评测报告")).to_be_visible()


def verify_user_capability_page(page) -> None:
    """验证普通用户能力目录与路由守卫。

    Args:
        page: 已打开 /capabilities 的普通用户页面。
    """
    expect(page.locator(".permission-panel")).to_contain_text("普通用户")
    assert page.locator("button", has_text="前往配置").count() == 0, "普通用户不应看到配置跳转"
    connector_group = page.locator(".capability-group", has_text="外部 Agent 连接器")
    assert connector_group.locator(".capability-card", has_text="Codex").count() == 0, (
        "默认策略下普通用户不应看到外部连接器"
    )

    page.goto(f"{FRONTEND_URL}/tools", wait_until="domcontentloaded")
    print(f"INFO user /tools url={page.url}")
    page.locator(".dashboard-view").wait_for(state="visible", timeout=60_000)
    assert page.url.startswith(f"{FRONTEND_URL}/dashboard"), "普通用户 /tools 应回退工作台"

    page.goto(f"{FRONTEND_URL}/admin", wait_until="domcontentloaded")
    print(f"INFO user /admin url={page.url}")
    page.locator(".dashboard-view").wait_for(state="visible", timeout=60_000)
    assert page.url.startswith(f"{FRONTEND_URL}/dashboard"), "普通用户 /admin 应回退工作台"

    page.goto(f"{FRONTEND_URL}/admin/lui-evaluation", wait_until="domcontentloaded")
    print(f"INFO user /admin/lui-evaluation url={page.url}")
    page.locator(".dashboard-view").wait_for(state="visible", timeout=60_000)
    assert page.url.startswith(f"{FRONTEND_URL}/dashboard"), "普通用户 /admin/lui-evaluation 应回退工作台"
    assert page.locator(".el-menu-item", has_text="评测报告").count() == 0, "普通用户不应看到评测报告入口"


def main() -> int:
    """执行能力中心与权限治理验收。"""
    env = load_env_file(BACKEND_ENV_PATH)
    status = httpx.get(f"{BACKEND_URL}/api/v1/auth/status", timeout=15).json()["data"]
    if not status.get("auth_enabled"):
        raise RuntimeError("能力中心权限 E2E 需要后端启用 AUTH_ENABLED")

    admin_token = login(
        BACKEND_URL,
        env,
        env.get("AUTH_USERNAME", "admin"),
        env.get("AUTH_PASSWORD", "admin123456"),
    )
    username, password = create_test_user(BACKEND_URL, admin_token)
    user_token = login(BACKEND_URL, env, username, password)
    screenshots = pathlib.Path(__file__).resolve().parent / "screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser, page, errors = open_page(
            playwright, FRONTEND_URL, admin_token, "/capabilities", ".capability-view"
        )
        try:
            verify_admin_capability_page(page)
            verify_admin_tools_and_admin_pages(page)
            page.screenshot(path=str(screenshots / "capability-admin-1440.png"), full_page=True)
            assert_no_console_errors(errors)
        finally:
            browser.close()

        browser, page, errors = open_page(
            playwright, FRONTEND_URL, user_token, "/capabilities", ".capability-view"
        )
        try:
            verify_user_capability_page(page)
            for width, height in VIEWPORTS:
                page.set_viewport_size({"width": width, "height": height})
                page.wait_for_timeout(300)
                assert_no_horizontal_overflow(page)
                page.screenshot(
                    path=str(screenshots / f"capability-user-{width}.png"),
                    full_page=True,
                )
            assert_no_console_errors(errors)
        finally:
            browser.close()

    print("PASS capability center + admin governance E2E")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
