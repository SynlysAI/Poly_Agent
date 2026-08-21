#!/usr/bin/env python3
"""Poly Agent 操作指导截图脚本（Playwright）。

登录生产环境 https://polyagent.xmuzc.com，对操作指导文档涉及的
9 个页面逐一截图，保存到 e2e/screenshots/guide/ 目录。

用法:
    python3 e2e/screenshot_guide.py
"""

from __future__ import annotations

import pathlib
import sys
import time

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

BASE_URL = "https://polyagent.xmuzc.com"
USERNAME = "admin"
PASSWORD = "admin123456"
OUTPUT_DIR = pathlib.Path(__file__).resolve().parent / "screenshots" / "guide"
VIEWPORT = {"width": 1440, "height": 900}

# (文件名, 路由路径, 页面描述, 额外等待描述)
PAGES = [
    ("01-dashboard.png", "/dashboard", "工作台看板", "看板卡片渲染"),
    ("02-dialogue.png", "/dialogue", "工作台问答", "对话界面加载"),
    ("03-research-engine.png", "/research-engine", "研发引擎", "研发任务列表"),
    ("04-computation-submit.png", "/computations/submit", "计算智能任务提交", "提交表单"),
    ("05-alchemist.png", "/optimization/alchemist", "Alchemist 实验设计", "实验设计工具"),
    ("06-vertical-prediction.png", "/vertical-prediction", "垂类预测模型", "模型管理列表"),
    ("07-task-center.png", "/tasks/center", "任务中心", "任务列表"),
    ("08-knowledge.png", "/knowledge", "知识库", "知识库问答"),
    ("09-data-catalog.png", "/database/data-catalog", "数据管理", "数据目录"),
]


def login(page) -> None:
    """登录 Poly Agent 生产环境。

    Args:
        page: Playwright Page 实例。
    """
    print("→ 正在打开登录页面...")
    page.goto(f"{BASE_URL}/login?redirect=/", wait_until="networkidle", timeout=30000)
    time.sleep(1)

    print("→ 填写账号密码...")
    username_input = page.locator("input.login-native-input").nth(0)
    password_input = page.locator("input.login-native-input-password")
    username_input.fill(USERNAME)
    password_input.fill(PASSWORD)

    print("→ 点击登录按钮...")
    login_button = page.locator("button.login-submit")
    login_button.click()

    # 等待跳转到 dashboard
    print("→ 等待登录完成并跳转...")
    page.wait_for_url("**/dashboard", timeout=15000)
    time.sleep(2)
    print("✓ 登录成功")


def take_screenshot(page, filename: str, path: str, desc: str, wait_hint: str) -> None:
    """对指定页面截图。

    Args:
        page: Playwright Page 实例。
        filename: 截图文件名。
        path: 页面路由路径。
        desc: 页面描述。
        wait_hint: 等待提示。
    """
    url = f"{BASE_URL}{path}"
    print(f"→ 截图: {desc} ({path})")

    try:
        page.goto(url, wait_until="networkidle", timeout=20000)
    except PlaywrightTimeoutError:
        print(f"  ⚠ networkidle 超时，改用 domcontentloaded")
        page.goto(url, wait_until="domcontentloaded", timeout=20000)

    # 等待页面内容渲染
    time.sleep(3)

    output_path = OUTPUT_DIR / filename
    page.screenshot(path=str(output_path), full_page=True)
    size_kb = output_path.stat().st_size / 1024
    print(f"  ✓ 已保存: {output_path} ({size_kb:.0f} KB)")


def main() -> int:
    """脚本主入口。

    Returns:
        退出码，0 表示成功。
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            viewport=VIEWPORT,
            locale="zh-CN",
        )
        page = context.new_page()

        try:
            login(page)

            print(f"\n→ 开始截取 {len(PAGES)} 个页面...\n")
            for filename, path, desc, wait_hint in PAGES:
                take_screenshot(page, filename, path, desc, wait_hint)

            print("\n✓ 全部截图完成")
            return 0

        except Exception as exc:
            print(f"\n✗ 截图失败: {exc}", file=sys.stderr)
            # 保存失败时的页面状态
            error_path = OUTPUT_DIR / "error-state.png"
            try:
                page.screenshot(path=str(error_path))
                print(f"  错误状态截图: {error_path}", file=sys.stderr)
            except Exception:
                pass
            return 1

        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
