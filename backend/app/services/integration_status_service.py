"""外部集成状态探测服务。"""

from __future__ import annotations

import shutil
import socket
import subprocess
import importlib.metadata
import importlib.util
from datetime import datetime
from pathlib import Path

from app.core.config import settings


class IntegrationStatusService:
    """收集 ChemOS/worker/artifact/AiiDA/SpecLabOS 状态摘要。"""

    def get_status(self) -> dict:
        """返回集成状态列表。"""
        checked_at = datetime.utcnow().isoformat()
        return {
            "items": [
                self._worker_status(checked_at),
                self._artifact_status(checked_at),
                self._chemos_status(checked_at),
                self._port_status("chemos-streamlit", "127.0.0.1", 8501, checked_at),
                self._port_status("chemos-sila", "127.0.0.1", 65001, checked_at),
                self._port_status("atlas", "127.0.0.1", 65100, checked_at),
                self._aiida_status(checked_at),
                self._speclabos_status(checked_at),
                self._rdkit_status(checked_at),
                self._openbabel_status(checked_at),
                self._xtb_status(checked_at),
                self._docker_status(checked_at),
            ]
        }

    def _worker_status(self, checked_at: str) -> dict:
        return {
            "service": "computation-worker",
            "status": "up",
            "checked_at": checked_at,
            "details": {
                "worker_id": "worker-local-mock",
                "capabilities": ["MOCK_XTB_ONLY", "MOCK_LASER", "LOCAL_STRUCTURE", "LOCAL_XTB"],
            },
        }

    def _artifact_status(self, checked_at: str) -> dict:
        return {
            "service": "artifact-store",
            "status": "up" if settings.outputs_root.exists() else "down",
            "checked_at": checked_at,
            "details": {"root": str(settings.outputs_root)},
        }

    def _chemos_status(self, checked_at: str) -> dict:
        script = settings.project_root / "scripts" / "run_chemos.sh"
        if not script.exists():
            return {
                "service": "chemos-demo",
                "status": "not_configured",
                "checked_at": checked_at,
                "details": {"reason": "scripts/run_chemos.sh missing"},
            }
        check = self._run_script(script, "check")
        status = self._run_script(script, "status")
        service_status = "available" if check["returncode"] == 0 else "degraded"
        return {
            "service": "chemos-demo",
            "status": service_status,
            "checked_at": checked_at,
            "details": {
                "check": check,
                "status": status,
            },
        }

    def _run_script(self, script: Path, command: str) -> dict:
        try:
            completed = subprocess.run(
                [str(script), command],
                cwd=str(settings.project_root),
                text=True,
                capture_output=True,
                timeout=8,
                check=False,
            )
            return {
                "returncode": completed.returncode,
                "stdout": completed.stdout[-4000:],
                "stderr": completed.stderr[-1000:],
            }
        except subprocess.TimeoutExpired:
            return {"returncode": 124, "stdout": "", "stderr": "timeout"}
        except OSError as exc:
            return {"returncode": 127, "stdout": "", "stderr": str(exc)}

    def _port_status(self, service: str, host: str, port: int, checked_at: str) -> dict:
        available = self._can_connect(host, port)
        return {
            "service": service,
            "status": "up" if available else "not_configured",
            "checked_at": checked_at,
            "details": {"host": host, "port": port},
        }

    def _can_connect(self, host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            return False

    def _aiida_status(self, checked_at: str) -> dict:
        return {
            "service": "aiida",
            "status": "not_configured",
            "checked_at": checked_at,
            "details": {"reason": "MVP 仅登记 reference artifact/parser 边界"},
        }

    def _speclabos_status(self, checked_at: str) -> dict:
        return {
            "service": "speclabos",
            "status": "not_configured",
            "checked_at": checked_at,
            "details": {"reason": "MVP 不运行真实 workflow"},
        }

    def _docker_status(self, checked_at: str) -> dict:
        return {
            "service": "docker",
            "status": "available" if shutil.which("docker") else "not_available",
            "checked_at": checked_at,
            "details": {},
        }

    def _rdkit_status(self, checked_at: str) -> dict:
        available = importlib.util.find_spec("rdkit") is not None
        version = None
        if available:
            try:
                version = importlib.metadata.version("rdkit")
            except importlib.metadata.PackageNotFoundError:
                version = "unknown"
        return {
            "service": "rdkit",
            "status": "available" if available else "not_available",
            "checked_at": checked_at,
            "details": {
                "version": version,
                "capabilities": ["smiles_to_3d", "sdf_export", "xyz_export"] if available else [],
            },
        }

    def _openbabel_status(self, checked_at: str) -> dict:
        obabel_path = shutil.which("obabel")
        version = None
        if obabel_path:
            try:
                completed = subprocess.run(
                    [obabel_path, "-V"],
                    text=True,
                    capture_output=True,
                    timeout=4,
                    check=False,
                )
                version = (completed.stdout or completed.stderr).strip()[:200] or "unknown"
            except (OSError, subprocess.TimeoutExpired):
                version = "unknown"
        return {
            "service": "openbabel",
            "status": "available" if obabel_path else "not_available",
            "checked_at": checked_at,
            "details": {
                "path": obabel_path,
                "version": version,
                "capabilities": ["smiles_to_3d", "sdf_export", "xyz_export"] if obabel_path else [],
            },
        }

    def _xtb_status(self, checked_at: str) -> dict:
        xtb_path = shutil.which("xtb")
        version = None
        if xtb_path:
            try:
                completed = subprocess.run(
                    [xtb_path, "--version"],
                    text=True,
                    capture_output=True,
                    timeout=4,
                    check=False,
                )
                version = (completed.stdout or completed.stderr).strip()[:200] or "unknown"
            except (OSError, subprocess.TimeoutExpired):
                version = "unknown"
        return {
            "service": "xtb",
            "status": "available" if xtb_path else "not_available",
            "checked_at": checked_at,
            "details": {
                "path": xtb_path,
                "version": version,
                "capabilities": ["geometry_optimization", "single_point"] if xtb_path else [],
            },
        }
