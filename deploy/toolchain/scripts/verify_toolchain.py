#!/usr/bin/env python3
"""verify_toolchain.py — Poly_Agent 计算工具链批量验收脚本。

验收项目：
  1. 核心工具 CLI 验证（python, rdkit, obabel, xtb, crest）
  2. MongoDB ping
  3. 后端 /api/v1/health 健康检查
  4. 后端 /api/v1/integrations/status 集成状态
  5. Smoke Demo 1: LOCAL_STRUCTURE / RDKit（CCO → structure.json/.xyz/.sdf）
  6. Smoke Demo 2: LOCAL_XTB / XTB（O → CREST + xTB, normal_termination=true）
  7. 后端单元测试
  8. 前端构建

输出：
  - .runtime/toolchain-verify/report.json  （机器可读）
  - .runtime/toolchain-verify/report.md    （人类可读）

用法：
  python verify_toolchain.py --root /path/to/Poly_Agent [--mode core|full] [--backend-port 5201]
"""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---- 工具函数 ----


def can_connect(host: str, port: int, timeout: float = 1.0) -> bool:
    """TCP 连通性检查。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def run_cmd(cmd: list[str], cwd: str | None = None, timeout: float = 30, env: dict | None = None) -> dict:
    """执行命令并返回结构化结果。"""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=env or os.environ.copy(),
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout[:4000],
            "stderr": result.stderr[:2000],
            "success": result.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {"returncode": 124, "stdout": "", "stderr": "timeout", "success": False}
    except OSError as exc:
        return {"returncode": 127, "stdout": "", "stderr": str(exc), "success": False}


def check_python_module(module_name: str) -> dict:
    """检查 Python 模块是否可导入。"""
    spec = importlib.util.find_spec(module_name)
    version = None
    error = None
    if spec is not None:
        try:
            version = importlib.metadata.version(module_name)
        except importlib.metadata.PackageNotFoundError:
            version = "unknown"
    else:
        error = f"module '{module_name}' not found"
    return {
        "name": module_name,
        "available": spec is not None,
        "version": version,
        "error": error,
    }


class ToolchainVerifier:
    """工具链验收器。"""

    def __init__(self, root: str, mode: str = "core", backend_port: int = 5201) -> None:
        self.root = Path(root)
        self.mode = mode
        self.backend_port = backend_port
        self.backend_url = f"http://127.0.0.1:{backend_port}"
        self.report_dir = self.root / ".runtime" / "toolchain-verify"
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.results: list[dict] = []
        self.started_at = datetime.now(timezone.utc)

    def add_result(self, name: str, passed: bool, details: dict, required: bool = True) -> None:
        """添加一项验收结果。"""
        self.results.append({
            "name": name,
            "passed": passed,
            "required": required,
            "details": details,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        status = "✓ PASS" if passed else "✗ FAIL"
        marker = "" if passed else " [REQUIRED]" if required else " [OPTIONAL]"
        print(f"  {status}: {name}{marker}")

    # ==============================================================
    # 1. 核心工具 CLI 验证
    # ==============================================================

    def verify_python(self) -> None:
        """验证 Python 版本。"""
        result = run_cmd(["python", "--version"])
        self.add_result("python", result["success"], {
            "command": "python --version",
            "output": result["stdout"].strip() or result["stderr"].strip(),
        })

    def verify_rdkit(self) -> None:
        """验证 RDKit。"""
        info = check_python_module("rdkit")
        if info["available"]:
            self.add_result("rdkit", True, {
                "version": info["version"],
                "command": "python -c 'import rdkit; print(rdkit.__version__)'",
            })
        else:
            self.add_result("rdkit", False, {
                "error": info["error"],
            })

    def verify_openbabel(self) -> None:
        """验证 OpenBabel。"""
        result = run_cmd(["obabel", "-V"])
        version = (result["stdout"] or result["stderr"]).strip()[:200]
        self.add_result("openbabel", result["success"], {
            "command": "obabel -V",
            "version": version,
        })

    def verify_xtb(self) -> None:
        """验证 xTB。"""
        result = run_cmd(["xtb", "--version"])
        version = (result["stdout"] or result["stderr"]).strip()[:200]
        self.add_result("xtb", result["success"], {
            "command": "xtb --version",
            "version": version,
        })

    def verify_crest(self) -> None:
        """验证 CREST。"""
        result = run_cmd(["crest", "--version"])
        version = (result["stdout"] or result["stderr"]).strip()[:200]
        self.add_result("crest", result["success"], {
            "command": "crest --version",
            "version": version,
        })

    def verify_node(self) -> None:
        """验证 Node.js。"""
        result = run_cmd(["node", "--version"])
        self.add_result("nodejs", result["success"], {
            "command": "node --version",
            "output": result["stdout"].strip(),
        })

    def verify_npm(self) -> None:
        """验证 npm。"""
        result = run_cmd(["npm", "--version"])
        self.add_result("npm", result["success"], {
            "command": "npm --version",
            "output": result["stdout"].strip(),
        })

    # ==============================================================
    # 2. MongoDB ping
    # ==============================================================

    def verify_mongodb(self) -> None:
        """验证 MongoDB 连通性。"""
        # 尝试使用 mongosh ping
        result = run_cmd(
            ["mongosh", "--eval", "db.runCommand({ping: 1})", "--quiet"],
            timeout=5,
        )
        if result["success"]:
            self.add_result("mongodb", True, {
                "method": "mongosh ping",
                "output": result["stdout"].strip(),
            })
        else:
            # 回退：检查端口
            port = int(os.getenv("MONGODB_PORT", "27017"))
            host = os.getenv("MONGODB_HOST", "127.0.0.1")
            if can_connect(host, port):
                self.add_result("mongodb", True, {
                    "method": f"TCP {host}:{port}",
                    "note": "mongosh 不可用，但 MongoDB 端口可达",
                })
            else:
                self.add_result("mongodb", False, {
                    "method": f"TCP {host}:{port}",
                    "error": "MongoDB 端口不可达",
                    "mongosh_error": result["stderr"].strip()[:200],
                })

    # ==============================================================
    # 3. 后端健康检查
    # ==============================================================

    def verify_backend_health(self) -> None:
        """验证后端 /api/v1/health。"""
        if not can_connect("127.0.0.1", self.backend_port):
            self.add_result("backend_health", False, {
                "endpoint": f"{self.backend_url}/api/v1/health",
                "error": f"后端端口 {self.backend_port} 不可达（服务未启动？）",
            })
            return

        try:
            import urllib.request
            import urllib.error

            req = urllib.request.Request(f"{self.backend_url}/api/v1/health")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                api_up = (data.get("data") or {}).get("api") == "up"
                self.add_result("backend_health", api_up and resp.status == 200, {
                    "endpoint": f"{self.backend_url}/api/v1/health",
                    "status_code": resp.status,
                    "response": data,
                })
        except Exception as exc:
            self.add_result("backend_health", False, {
                "endpoint": f"{self.backend_url}/api/v1/health",
                "error": str(exc),
            })

    # ==============================================================
    # 4. 集成状态
    # ==============================================================

    def verify_integration_status(self) -> None:
        """验证 /api/v1/integrations/status。"""
        if not can_connect("127.0.0.1", self.backend_port):
            self.add_result("integration_status", False, {
                "error": f"后端端口 {self.backend_port} 不可达",
            }, required=False)
            return

        try:
            import urllib.request

            req = urllib.request.Request(f"{self.backend_url}/api/v1/integrations/status")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                items = (data.get("data") or {}).get("items", [])
                summary = {}
                for item in items:
                    svc = item.get("service", "?")
                    summary[svc] = item.get("status", "?")
                self.add_result("integration_status", True, {
                    "endpoint": f"{self.backend_url}/api/v1/integrations/status",
                    "item_count": len(items),
                    "summary": summary,
                }, required=False)
        except Exception as exc:
            self.add_result("integration_status", False, {
                "error": str(exc),
            }, required=False)

    # ==============================================================
    # 5. Smoke Demo 1: LOCAL_STRUCTURE / RDKit
    # ==============================================================

    def verify_smoke_local_structure(self) -> None:
        """Smoke Demo 1: CCO → RDKit 3D 结构生成。"""
        workdir = self.report_dir / "smoke_local_structure"
        workdir.mkdir(parents=True, exist_ok=True)

        script = f"""
import json, sys
sys.path.insert(0, '{self.root / "backend"}')
from app.computation_adapters.local_structure import LocalStructureAdapter
from app.computation_adapters.base import AdapterContext
from app.schemas.computation import ComputationRun

adapter = LocalStructureAdapter()

# 构造最小 ComputationRun
run_data = {{
    "run_id": "smoke-local-structure-1",
    "workflow_type": "LOCAL_STRUCTURE",
    "engine": "RDKit",
    "input": {{"smiles": "CCO"}},
    "resources": {{"max_wallclock_seconds": 60}},
}}
run = ComputationRun(**run_data)

ctx = AdapterContext(
    run=run,
    worker_id="verify-toolchain",
    workdir=Path('{workdir}'),
    started_at=None,
    timeout_seconds=60,
)
adapter.CHECK_AVAILABILITY = True
result = adapter.run(ctx)

# 收集 artifacts
artifacts = adapter.collect_artifacts(ctx, result)
artifact_names = [a.name for a in artifacts]

# 检查文件
structure_json = Path('{workdir}') / "structure.json"
structure_xyz = Path('{workdir}') / "structure.xyz"
structure_sdf = Path('{workdir}') / "structure.sdf"

print("STATUS:", result.status)
print("ARTIFACTS:", artifact_names)
print("HAS_JSON:", structure_json.exists())
print("HAS_XYZ:", structure_xyz.exists())
print("HAS_SDF:", structure_sdf.exists())
if structure_json.exists():
    with open(structure_json) as f:
        data = json.load(f)
        print("ATOM_COUNT:", data.get("num_atoms", "N/A"))
"""
        result = run_cmd(
            ["python", "-c", script],
            cwd=str(self.root / "backend"),
            timeout=30,
        )

        has_json = "HAS_JSON: True" in result["stdout"]
        has_xyz = "HAS_XYZ: True" in result["stdout"]
        has_sdf = "HAS_SDF: True" in result["stdout"]
        status_ok = "STATUS: completed" in result["stdout"]
        passed = status_ok and has_json and has_xyz and has_sdf

        self.add_result("smoke_local_structure", passed, {
            "smiles": "CCO",
            "engine": "RDKit",
            "workflow": "LOCAL_STRUCTURE",
            "status": "completed" if status_ok else "failed",
            "artifacts": {
                "structure.json": has_json,
                "structure.xyz": has_xyz,
                "structure.sdf": has_sdf,
            },
            "output": result["stdout"][:2000],
            "error": result["stderr"][:1000] if not passed else None,
        })

    # ==============================================================
    # 6. Smoke Demo 2: LOCAL_XTB / XTB
    # ==============================================================

    def verify_smoke_local_xtb(self) -> None:
        """Smoke Demo 2: O → CREST + xTB 计算。"""
        workdir = self.report_dir / "smoke_local_xtb"
        workdir.mkdir(parents=True, exist_ok=True)

        script = f"""
import json, sys
sys.path.insert(0, '{self.root / "backend"}')
from pathlib import Path
from app.computation_adapters.local_xtb import LocalXtbAdapter
from app.computation_adapters.base import AdapterContext
from app.schemas.computation import ComputationRun

adapter = LocalXtbAdapter()

# 构造最小 ComputationRun
run_data = {{
    "run_id": "smoke-local-xtb-1",
    "workflow_type": "LOCAL_XTB",
    "engine": "XTB",
    "input": {{"smiles": "O"}},
    "resources": {{"max_wallclock_seconds": 120}},
}}
run = ComputationRun(**run_data)

ctx = AdapterContext(
    run=run,
    worker_id="verify-toolchain",
    workdir=Path('{workdir}'),
    started_at=None,
    timeout_seconds=120,
)

try:
    result = adapter.run(ctx)
    summary = adapter.parse_result(ctx, result)
    print("STATUS:", result.status)
    print("NORMAL_TERMINATION:", summary.get("normal_termination", "N/A"))
    print("SUMMARY:", json.dumps(summary, default=str))
except Exception as e:
    print("STATUS: failed")
    print("ERROR:", str(e))
"""
        result = run_cmd(
            ["python", "-c", script],
            cwd=str(self.root / "backend"),
            timeout=180,
            env={**os.environ.copy(), "PYTHONNOUSERSITE": "1"},
        )

        status_ok = "STATUS: completed" in result["stdout"]
        normal_term = "NORMAL_TERMINATION: True" in result["stdout"]
        passed = status_ok and normal_term

        self.add_result("smoke_local_xtb", passed, {
            "smiles": "O",
            "engine": "XTB",
            "workflow": "LOCAL_XTB",
            "status": "completed" if status_ok else "failed",
            "normal_termination": normal_term,
            "output": result["stdout"][:2000],
            "error": result["stderr"][:1000] if not passed else None,
        })

    # ==============================================================
    # 7. 后端单元测试
    # ==============================================================

    def verify_backend_tests(self) -> None:
        """运行后端单元测试。"""
        result = run_cmd(
            ["python", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
            cwd=str(self.root / "backend"),
            timeout=120,
        )
        passed = result["success"]
        self.add_result("backend_tests", passed, {
            "command": "python -m unittest discover -s tests -p 'test_*.py'",
            "stdout_tail": result["stdout"][-2000:],
            "stderr_tail": result["stderr"][-1000:] if not passed else None,
        }, required=False)

    # ==============================================================
    # 8. 前端构建
    # ==============================================================

    def verify_frontend_build(self) -> None:
        """验证前端构建。"""
        result = run_cmd(
            ["npm", "run", "build"],
            cwd=str(self.root / "frontend"),
            timeout=120,
        )
        passed = result["success"]
        dist_exists = (self.root / "frontend" / "dist" / "index.html").exists()
        self.add_result("frontend_build", passed and dist_exists, {
            "command": "npm run build",
            "dist_exists": dist_exists,
            "stderr_tail": result["stderr"][-1000:] if not passed else None,
        }, required=False)

    # ==============================================================
    # 可选服务验证
    # ==============================================================

    def verify_optional_services(self) -> None:
        """验证可选服务（仅 full 模式）。"""
        if self.mode != "full":
            return

        # ALchemist
        alchemist_reachable = can_connect("127.0.0.1", 8004)
        self.add_result("alchemist_backend", alchemist_reachable, {
            "port": 8004,
            "reachable": alchemist_reachable,
        }, required=False)

        # ORCA
        orca_found, orca_path = False, shutil.which("orca")
        if orca_path:
            orca_found = True
        orca_license = os.getenv("ORCA_LICENSE_AVAILABLE", "false").strip().lower() in {
            "1", "true", "yes", "on",
        }
        self.add_result("orca", orca_found and orca_license, {
            "executable_found": orca_found,
            "path": orca_path,
            "license_available": orca_license,
        }, required=False)

    # ==============================================================
    # 运行全部验证 & 生成报告
    # ==============================================================

    def run_all(self) -> int:
        """运行全部验收项目。"""
        print("=" * 60)
        print("  Poly_Agent 工具链验收")
        print(f"  模式: {self.mode}")
        print(f"  时间: {self.started_at.isoformat()}")
        print("=" * 60)
        print()

        # ---- 核心工具 CLI ----
        print("[1/8] 核心工具 CLI 验证")
        self.verify_python()
        self.verify_node()
        self.verify_npm()
        self.verify_rdkit()
        self.verify_openbabel()
        self.verify_xtb()
        self.verify_crest()
        print()

        # ---- MongoDB ----
        print("[2/8] MongoDB 连通性")
        self.verify_mongodb()
        print()

        # ---- 后端健康 ----
        print("[3/8] 后端健康检查")
        self.verify_backend_health()
        print()

        # ---- 集成状态 ----
        print("[4/8] 集成状态")
        self.verify_integration_status()
        print()

        # ---- Smoke Demos ----
        print("[5/8] Smoke Demo: LOCAL_STRUCTURE / RDKit")
        self.verify_smoke_local_structure()
        print()

        print("[6/8] Smoke Demo: LOCAL_XTB / XTB")
        self.verify_smoke_local_xtb()
        print()

        # ---- 测试 & 构建 ----
        print("[7/8] 后端单元测试")
        self.verify_backend_tests()
        print()

        print("[8/8] 前端构建")
        self.verify_frontend_build()
        print()

        # ---- 可选服务 ----
        if self.mode == "full":
            print("[可选] 可选服务验证")
            self.verify_optional_services()
            print()

        # ---- 生成报告 ----
        self.write_report_json()
        self.write_report_md()
        self.print_summary()

        # 返回退出码：所有 required 项都通过才算成功
        required_failures = [r for r in self.results if r["required"] and not r["passed"]]
        return 1 if required_failures else 0

    def write_report_json(self) -> None:
        """写 JSON 报告。"""
        report = {
            "package": "poly-agent-toolchain",
            "mode": self.mode,
            "root": str(self.root),
            "started_at": self.started_at.isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "summary": self._summary(),
            "results": self.results,
        }
        path = self.report_dir / "report.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON 报告: {path}")

    def write_report_md(self) -> None:
        """写 Markdown 报告。"""
        summary = self._summary()
        lines = [
            "# Poly_Agent 工具链验收报告",
            "",
            f"**时间**: {self.started_at.isoformat()}",
            f"**模式**: {self.mode}",
            f"**项目根目录**: `{self.root}`",
            "",
            "## 摘要",
            "",
            f"| 指标 | 值 |",
            f"|------|-----|",
            f"| 总计 | {summary['total']} |",
            f"| 通过 | {summary['passed']} |",
            f"| 失败 | {summary['failed']} |",
            f"| 必装项失败 | {summary['required_failed']} |",
            f"| 可选项失败 | {summary['optional_failed']} |",
            "",
            "## 详细结果",
            "",
            "| 项目 | 结果 | 类型 | 详情 |",
            "|------|------|------|------|",
        ]
        for r in self.results:
            status = "✅ PASS" if r["passed"] else "❌ FAIL"
            req = "必装" if r["required"] else "可选"
            detail = json.dumps(r["details"], ensure_ascii=False)[:120]
            lines.append(f"| {r['name']} | {status} | {req} | {detail} |")

        lines.extend([
            "",
            "---",
            "",
            f"*报告由 verify_toolchain.py 自动生成*",
        ])

        path = self.report_dir / "report.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        print(f"Markdown 报告: {path}")

    def _summary(self) -> dict:
        """生成摘要。"""
        total = len(self.results)
        passed = sum(1 for r in self.results if r["passed"])
        failed = total - passed
        required_failed = sum(1 for r in self.results if r["required"] and not r["passed"])
        optional_failed = sum(1 for r in self.results if not r["required"] and not r["passed"])
        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "required_failed": required_failed,
            "optional_failed": optional_failed,
        }

    def print_summary(self) -> None:
        """打印摘要。"""
        s = self._summary()
        print()
        print("=" * 60)
        print(f"  验收完成: {s['passed']}/{s['total']} 通过")
        if s["required_failed"] > 0:
            print(f"  ⚠  {s['required_failed']} 个必装项失败！")
        if s["optional_failed"] > 0:
            print(f"  ⓘ  {s['optional_failed']} 个可选项失败（不影响核心功能）")
        print(f"  报告: {self.report_dir / 'report.md'}")
        print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="Poly_Agent 计算工具链验收脚本")
    parser.add_argument("--root", required=True, help="Poly_Agent 项目根目录")
    parser.add_argument("--mode", default="core", choices=["core", "full"])
    parser.add_argument("--backend-port", type=int, default=5201)
    parser.add_argument("--report-dir", default=None)
    args = parser.parse_args()

    verifier = ToolchainVerifier(
        root=args.root,
        mode=args.mode,
        backend_port=args.backend_port,
    )
    if args.report_dir:
        verifier.report_dir = Path(args.report_dir)
        verifier.report_dir.mkdir(parents=True, exist_ok=True)

    exit_code = verifier.run_all()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
