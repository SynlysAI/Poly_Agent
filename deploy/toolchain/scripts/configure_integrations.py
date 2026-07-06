#!/usr/bin/env python3
"""configure_integrations.py — 写入 Poly_Agent 服务集成配置摘要。

该脚本在工具链安装完成后调用，通过 Poly_Agent API 写入各服务的
enabled/endpoint/config_summary 等元数据。

用法：
  # 通过 API 写入配置（需要后端在运行且提供认证信息）
  python configure_integrations.py \
    --root /path/to/Poly_Agent \
    --mode full \
    --backend-url http://127.0.0.1:5100 \
    --username admin --password admin123456

  # 仅输出配置摘要而不调用 API（dry-run）
  python configure_integrations.py --root /path/to/Poly_Agent --mode core --dry-run

  # 在 bootstrap 阶段调用（后端未启动，仅输出摘要供后续使用）
  python configure_integrations.py --root /path/to/Poly_Agent --mode full --print-only

集成策略（与工具链部署方案对齐）：
  - computation-worker: enabled, status=up
  - artifact-store: enabled, status=up
  - alchemist-backend: 有 endpoint 时 enabled；endpoint 不可达时显示 down
  - orca: 仅 ORCA_LICENSE_AVAILABLE=true 且 probe 正常时标记可用
  - atlas: 默认 disabled, status=down
  - speclabos: 默认 disabled
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[3]

# ---- 默认配置摘要 ----
SERVICE_CONFIGS: dict[str, dict[str, Any]] = {
    "computation-worker": {
        "display_name": "Computation worker",
        "service_type": "worker",
        "enabled": True,
        "endpoint": None,
        "config_summary": {
            "worker_id": "worker-local-real",
            "capabilities": [
                "LOCAL_STRUCTURE",
                "LOCAL_XTB",
                "ORCA_COMPUTE_ENGINE_LASER",
            ],
        },
    },
    "artifact-store": {
        "display_name": "Artifact store",
        "service_type": "artifact",
        "enabled": True,
        "endpoint": None,
        "config_summary": {
            "root": ".runtime/outputs",
        },
    },
    "alchemist-backend": {
        "display_name": "ALchemist backend",
        "service_type": "optimizer",
        "enabled": False,
        "endpoint": "http://127.0.0.1:8004/api/v1",
        "config_summary": {
            "note": "未检测到 ALchemist endpoint 连通性",
        },
    },
    "orca": {
        "display_name": "ORCA",
        "service_type": "workflow",
        "enabled": False,
        "endpoint": None,
        "config_summary": {
            "license_available": False,
            "note": "ORCA 商业软件，仅做路径/许可证探测",
        },
    },
    "atlas": {
        "display_name": "Atlas optimizer",
        "service_type": "optimizer",
        "enabled": False,
        "endpoint": "http://127.0.0.1:65100",
        "config_summary": {
            "status": "down",
            "note": "参考仓库不完整，默认 disabled",
        },
    },
    "speclabos": {
        "display_name": "SpecLabOS",
        "service_type": "experiment",
        "enabled": False,
        "endpoint": None,
        "config_summary": {
            "note": "MVP 不运行真实 workflow",
        },
    },
}


def probe_port(host: str, port: int, timeout: float = 0.8) -> bool:
    """探测 TCP 端口连通性。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def probe_executable(name: str) -> tuple[bool, str | None]:
    """检查可执行文件是否在 PATH 上。"""
    path = shutil.which(name)
    return (path is not None, path)


def probe_conda_env(env_name: str) -> bool:
    """检查 conda 环境是否存在。"""
    try:
        result = subprocess.run(
            ["conda", "env", "list"],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        for line in result.stdout.splitlines():
            if line.strip() and not line.startswith("#"):
                if line.split()[0] == env_name:
                    return True
        return False
    except Exception:
        return False


def build_configs(root: str, mode: str, alchemist_available: str) -> dict[str, dict]:
    """根据实际探测结果构建配置摘要。"""
    configs = {}
    runtime_dir = Path(root) / ".runtime"

    # ---- computation-worker（核心必装，始终 enabled） ----
    configs["computation-worker"] = {
        **SERVICE_CONFIGS["computation-worker"],
        "enabled": True,
        "config_summary": {
            **SERVICE_CONFIGS["computation-worker"]["config_summary"],
            "root": str(root),
        },
    }

    # ---- artifact-store ----
    outputs_root = Path(os.getenv("POLY_AGENT_OUTPUT_ROOT", str(runtime_dir / "outputs")))
    configs["artifact-store"] = {
        **SERVICE_CONFIGS["artifact-store"],
        "enabled": True,
        "config_summary": {
            "root": str(outputs_root),
            "exists": outputs_root.exists(),
        },
    }

    # ---- alchemist-backend ----
    alchemist_has_source = bool(alchemist_available and alchemist_available not in ("false", "0", ""))
    alchemist_reachable = False
    if alchemist_has_source:
        alchemist_reachable = probe_port("127.0.0.1", 8004)
    # 也检查 conda 环境
    alchemist_env_exists = probe_conda_env("poly_agent_alchemist")

    configs["alchemist-backend"] = {
        **SERVICE_CONFIGS["alchemist-backend"],
        "enabled": alchemist_env_exists,
        "config_summary": {
            "conda_env": "poly_agent_alchemist" if alchemist_env_exists else None,
            "endpoint_reachable": alchemist_reachable,
            "note": (
                "ALchemist 已部署且 endpoint 可达"
                if alchemist_reachable
                else "ALchemist 已部署但 endpoint 不可达（服务未启动？）"
            )
            if alchemist_env_exists
            else "ALchemist 未安装或跳过",
        },
    }

    # ---- orca ----
    orca_license = os.getenv("ORCA_LICENSE_AVAILABLE", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }
    orca_found, orca_path = probe_executable("orca")
    orca_available = orca_found and orca_license

    configs["orca"] = {
        **SERVICE_CONFIGS["orca"],
        "enabled": orca_available,
        "config_summary": {
            "path": orca_path,
            "license_available": orca_license,
            "executable_found": orca_found,
            "note": (
                "ORCA 可用"
                if orca_available
                else "ORCA license 未标记可用或可执行文件未找到"
            ),
        },
    }

    # ---- atlas ----
    atlas_reachable = probe_port("127.0.0.1", 65100)
    configs["atlas"] = {
        **SERVICE_CONFIGS["atlas"],
        "enabled": False,  # 默认 disabled
        "config_summary": {
            "port": 65100,
            "reachable": atlas_reachable,
            "note": "参考仓库不完整，默认 disabled",
        },
    }

    # ---- speclabos ----
    configs["speclabos"] = {
        **SERVICE_CONFIGS["speclabos"],
    }

    return configs


def print_configs(configs: dict[str, dict]) -> None:
    """打印配置摘要（人类可读）。"""
    print("\n" + "=" * 60)
    print("  服务集成配置摘要")
    print("=" * 60)
    for key, cfg in configs.items():
        status = "enabled" if cfg["enabled"] else "disabled"
        endpoint = cfg.get("endpoint") or "(none)"
        print(f"\n  [{status:8s}] {key}")
        print(f"    endpoint: {endpoint}")
        for k, v in cfg.get("config_summary", {}).items():
            print(f"    {k}: {v}")
    print("\n" + "=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="写入 Poly_Agent 服务集成配置摘要")
    parser.add_argument("--root", required=True, help="Poly_Agent 项目根目录")
    parser.add_argument("--mode", default="core", choices=["core", "full"])
    parser.add_argument("--backend-url", default="http://127.0.0.1:5100")
    parser.add_argument("--username", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--alchemist-available", default="")
    parser.add_argument("--dry-run", action="store_true", help="仅输出配置而不调用 API")
    parser.add_argument("--print-only", action="store_true", help="仅输出配置摘要（不尝试 API）")
    args = parser.parse_args()

    configs = build_configs(
        root=args.root,
        mode=args.mode,
        alchemist_available=args.alchemist_available,
    )

    print_configs(configs)

    if args.print_only or args.dry_run:
        if args.dry_run:
            print("[dry-run] 以上配置不会写入系统。")
        return

    # ---- 尝试通过 API 写入 ----
    try:
        import httpx
    except ImportError:
        print("[configure] httpx 未安装，无法调用 API。请先启动后端后手动配置。")
        print("[configure] 配置摘要已输出到 stdout，可据此手动填写。")
        return

    # 获取 API token
    api_base = args.backend_url.rstrip("/") + "/api/v1"
    headers: dict[str, str] = {}
    if args.username and args.password:
        try:
            resp = httpx.post(
                f"{api_base}/auth/login",
                json={"username": args.username, "password": args.password},
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                token = (data.get("data") or {}).get("access_token", "")
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                    print("[configure] API 认证成功。")
                else:
                    print("[configure] 警告：无法获取 token，将以无认证模式尝试。")
            else:
                print(f"[configure] 警告：登录失败 ({resp.status_code})，以无认证模式尝试。")
        except Exception as exc:
            print(f"[configure] 警告：无法连接后端 API: {exc}")

    # 写入每个服务配置
    success = 0
    failed = 0
    for service_key, cfg in configs.items():
        try:
            payload = {
                "display_name": cfg["display_name"],
                "service_type": cfg["service_type"],
                "enabled": cfg["enabled"],
                "endpoint": cfg.get("endpoint"),
                "config_summary": cfg["config_summary"],
                "secret_refs": {},
            }
            resp = httpx.put(
                f"{api_base}/integrations/configs/{service_key}",
                json=payload,
                headers=headers,
                timeout=10,
            )
            if resp.status_code == 200:
                print(f"[configure] ✓ {service_key} 配置已写入")
                success += 1
            else:
                print(f"[configure] ✗ {service_key} 写入失败: HTTP {resp.status_code} {resp.text[:200]}")
                failed += 1
        except Exception as exc:
            print(f"[configure] ✗ {service_key} 请求异常: {exc}")
            failed += 1

    print(f"\n[configure] 完成: {success} 成功, {failed} 失败")

    if failed > 0:
        print("[configure] 提示：可稍后在管理面板中手动配置集成服务。")
        sys.exit(1)


if __name__ == "__main__":
    main()
