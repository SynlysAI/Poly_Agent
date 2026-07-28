"""外部集成状态探测服务。"""

from __future__ import annotations

import shutil
import socket
import subprocess
import re
import importlib.metadata
import importlib.util
from pathlib import Path
from urllib.parse import urlparse

from app.core.config import settings
from app.core.time import utc_now
from app.services.integration_config_service import IntegrationConfigService


class IntegrationStatusService:
    """收集 worker/artifact/SpecLabOS/本机计算工具状态摘要。"""

    def get_status(self) -> dict:
        """返回集成状态列表。"""
        checked_at = utc_now().isoformat()
        config_map = {
            item.service_key: item
            for item in IntegrationConfigService().list_configs().items
        }
        items = [
            self._worker_status(checked_at),
            self._mongodb_status(checked_at),
            self._data_asset_mongodb_status(checked_at),
            self._artifact_status(checked_at),
            self._weknora_status(checked_at),
            self._knowledge_graph_status(checked_at),
            self._alchemist_status(checked_at),
            self._speclabos_status(checked_at),
            self._rdkit_status(checked_at),
            self._openbabel_status(checked_at),
            self._xtb_status(checked_at),
            self._crest_status(checked_at),
            self._orca_status(checked_at),
            self._docker_status(checked_at),
        ]
        return {
            "items": [
                self._merge_persisted_config(item, config_map)
                for item in items
            ]
        }

    def _merge_persisted_config(self, item: dict, config_map: dict) -> dict:
        """合并持久化配置摘要和最后检查结果。"""
        service_key = item["service"]
        config = config_map.get(service_key)
        if not config:
            return item
        details = dict(item.get("details") or {})
        details.update(
            {
                "configured": bool(config.endpoint or config.config_summary or config.secret_refs),
                "enabled": config.enabled,
                "last_error_summary": config.last_error_summary,
            }
        )
        item["details"] = details
        if config.last_checked_at:
            item["status"] = config.last_status
            item["checked_at"] = config.last_checked_at.isoformat()
        elif details["configured"] and not config.enabled:
            item["status"] = "disabled"
        elif details["configured"] and item["status"] == "not_configured":
            item["status"] = "down"
        return item

    def _worker_status(self, checked_at: str) -> dict:
        return {
            "service": "computation-worker",
            "status": "up",
            "checked_at": checked_at,
            "details": {
                "worker_id": "worker-local-real",
                "capabilities": [
                    "LOCAL_STRUCTURE",
                    "LOCAL_XTB",
                    "ORCA_COMPUTE_ENGINE_LASER",
                ],
            },
        }

    def _artifact_status(self, checked_at: str) -> dict:
        return {
            "service": "artifact-store",
            "status": "up" if settings.outputs_root.exists() else "down",
            "checked_at": checked_at,
            "details": {"root": str(settings.outputs_root)},
        }

    def _mongodb_status(self, checked_at: str) -> dict:
        available = self._can_connect(settings.mongodb_host, settings.mongodb_port)
        return {
            "service": "mongodb",
            "status": "up" if available else "down",
            "checked_at": checked_at,
            "details": {
                "host": settings.mongodb_host,
                "port": settings.mongodb_port,
                "database": settings.mongodb_database,
                "required": settings.require_mongodb,
                "reason": None if available else "MongoDB port is not reachable",
            },
        }

    def _data_asset_mongodb_status(self, checked_at: str) -> dict:
        uri = settings.data_asset_mongodb_uri
        if not uri:
            return {
                "service": "data-asset-mongodb",
                "status": "not_configured",
                "checked_at": checked_at,
                "details": {
                    "database": settings.data_asset_mongodb_database,
                    "reason": "DATA_ASSET_MONGODB_URI is not configured",
                },
            }
        host, port = self._parse_mongodb_endpoint(uri)
        available = bool(host and self._can_connect(host, port))
        return {
            "service": "data-asset-mongodb",
            "status": "up" if available else "down",
            "checked_at": checked_at,
            "details": {
                "host": host,
                "port": port,
                "database": settings.data_asset_mongodb_database,
                "configured": True,
                "reason": None if available else "data asset MongoDB endpoint is not reachable",
            },
        }

    def _weknora_status(self, checked_at: str) -> dict:
        """返回 WeKnora 知识服务状态。"""
        health = self._knowledge_health()
        if not health:
            return {
                "service": "weknora",
                "status": "not_configured",
                "checked_at": checked_at,
                "details": {"reason": "WeKnora service is not configured or not reachable"},
            }
        raw_status = getattr(health, "status", "unavailable")
        configured = bool(getattr(health, "configured", False))
        if raw_status == "ready" and configured:
            status = "up"
        elif raw_status == "warning":
            status = "degraded"
        elif not configured:
            status = "not_configured"
        else:
            status = "down"
        return {
            "service": "weknora",
            "status": status,
            "checked_at": checked_at,
            "details": {
                "configured": configured,
                "systems": list(getattr(health, "systems", []) or []),
                "message": getattr(health, "message", ""),
            },
        }

    def _knowledge_graph_status(self, checked_at: str) -> dict:
        health = self._knowledge_health()
        systems = list(getattr(health, "systems", []) or []) if health else []
        configured = bool(getattr(health, "configured", False)) if health else False
        if not configured:
            status = "not_configured"
            reason = "Knowledge graph is unavailable until WeKnora has a ready knowledge base"
        elif systems:
            status = "up"
            reason = None
        else:
            status = "degraded"
            reason = "WeKnora is reachable but no searchable knowledge base was reported"
        return {
            "service": "knowledge-graph",
            "status": status,
            "checked_at": checked_at,
            "details": {
                "provider": "weknora",
                "systems": systems,
                "reason": reason,
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

    def _knowledge_health(self):
        try:
            from app.services.knowledge_service import KnowledgeService

            return KnowledgeService().health()
        except Exception:
            return None

    @staticmethod
    def _parse_mongodb_endpoint(uri: str) -> tuple[str | None, int]:
        parsed = urlparse(uri)
        host = parsed.hostname
        port = parsed.port or 27017
        return host, port

    def _alchemist_status(self, checked_at: str) -> dict:
        return {
            "service": "alchemist-backend",
            "status": "built_in",
            "checked_at": checked_at,
            "details": {
                "message": "ALchemist 实验设计与优化已内置到 Poly Agent 后端，无需外部服务",
                "model_storage": str(settings.alchemist_runtime_root),
            },
        }

    def _speclabos_status(self, checked_at: str) -> dict:
        configured = bool(settings.speclabos_base_url and settings.speclabos_api_key)
        return {
            "service": "speclabos",
            "status": "available" if configured else "not_configured",
            "checked_at": checked_at,
            "details": {
                "message": (
                    "已配置外部实验任务下发，等待连通性验证"
                    if configured
                    else "未配置 SpecLabOS 外部实验任务下发"
                ),
                "endpoint": settings.speclabos_base_url or None,
                "execution_scope": "仅登记外部实验任务，不触发设备或工作流执行",
            },
        }

    def _docker_status(self, checked_at: str) -> dict:
        return {
            "service": "docker",
            "status": "available" if shutil.which("docker") else "not_available",
            "checked_at": checked_at,
            "details": {},
        }

    def _rdkit_status(self, checked_at: str) -> dict:
        spec = importlib.util.find_spec("rdkit")
        available = spec is not None
        version = None
        path = None
        reason = None
        if available:
            path = str(spec.origin or next(iter(spec.submodule_search_locations or []), "")) or None
            try:
                version = importlib.metadata.version("rdkit")
            except importlib.metadata.PackageNotFoundError:
                version = "unknown"
        else:
            reason = "python package rdkit is not importable"
        return {
            "service": "rdkit",
            "status": "available" if available else "not_available",
            "checked_at": checked_at,
            "details": {
                "path": path,
                "version": version,
                "reason": reason,
                "capabilities": ["smiles_to_3d", "sdf_export", "xyz_export"] if available else [],
            },
        }

    def _openbabel_status(self, checked_at: str) -> dict:
        obabel_path = shutil.which("obabel")
        version = None
        reason = None
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
                if completed.returncode != 0:
                    reason = f"obabel -V returned {completed.returncode}"
            except subprocess.TimeoutExpired:
                version = "unknown"
                reason = "obabel -V timed out"
            except OSError as exc:
                version = "unknown"
                reason = str(exc)
        else:
            reason = "obabel executable not found on PATH"
        return {
            "service": "openbabel",
            "status": "available" if obabel_path else "not_available",
            "checked_at": checked_at,
            "details": {
                "path": obabel_path,
                "version": version,
                "reason": reason,
                "capabilities": ["smiles_to_3d", "sdf_export", "xyz_export"] if obabel_path else [],
            },
        }

    def _xtb_status(self, checked_at: str) -> dict:
        xtb_path = shutil.which(settings.xtb_executable) or shutil.which("xtb")
        version = None
        reason = None
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
                if completed.returncode != 0:
                    reason = f"xtb --version returned {completed.returncode}"
            except subprocess.TimeoutExpired:
                version = "unknown"
                reason = "xtb --version timed out"
            except OSError as exc:
                version = "unknown"
                reason = str(exc)
        else:
            reason = "xtb executable not found on PATH"
        return {
            "service": "xtb",
            "status": "available" if xtb_path else "not_available",
            "checked_at": checked_at,
            "details": {
                "path": xtb_path,
                "version": version,
                "reason": reason,
                "capabilities": ["geometry_optimization", "single_point"] if xtb_path else [],
            },
        }

    def _crest_status(self, checked_at: str) -> dict:
        crest_path = shutil.which(settings.crest_executable) or shutil.which("crest")
        return self._executable_status(
            "crest",
            crest_path,
            [crest_path, "--version"] if crest_path else None,
            checked_at,
            ["conformer_search"] if crest_path else [],
        )

    def _orca_status(self, checked_at: str) -> dict:
        orca_path = shutil.which(settings.orca_executable) or shutil.which("orca")
        return self._executable_status(
            "orca",
            orca_path,
            [orca_path] if orca_path else None,
            checked_at,
            ["dft_refinement", "excited_state"] if orca_path and settings.orca_license_available else [],
            license_required=True,
        )

    def _executable_status(
        self,
        service: str,
        executable_path: str | None,
        command: list[str] | None,
        checked_at: str,
        capabilities: list[str],
        *,
        license_required: bool = False,
    ) -> dict:
        version = None
        reason = None
        if executable_path and command:
            try:
                completed = subprocess.run(
                    command,
                    text=True,
                    capture_output=True,
                    timeout=4,
                    check=False,
                )
                raw_stdout = completed.stdout or ""
                raw_stderr = completed.stderr or ""
                version = self._clean_version_text(service, raw_stdout or raw_stderr)
                if completed.returncode != 0 and service != "orca":
                    reason = f"{service} probe returned {completed.returncode}"
            except subprocess.TimeoutExpired:
                version = "detected"
                raw_stdout = ""
                raw_stderr = ""
                reason = f"{service} probe timed out"
            except OSError as exc:
                version = "unknown"
                raw_stdout = ""
                raw_stderr = ""
                reason = str(exc)
        else:
            reason = f"{service} executable not found on PATH"
            raw_stdout = ""
            raw_stderr = ""
        if license_required and executable_path and not settings.orca_license_available:
            reason = "ORCA license is not marked available in backend configuration"
        return {
            "service": service,
            "status": "available" if executable_path and not reason else "not_available",
            "checked_at": checked_at,
            "details": {
                "path": executable_path,
                "version": version,
                "reason": reason,
                "raw_stdout": raw_stdout[-1000:] if raw_stdout else None,
                "raw_stderr": raw_stderr[-1000:] if raw_stderr else None,
                "capabilities": capabilities if executable_path and not reason else [],
            },
        }

    @staticmethod
    def _clean_version_text(service: str, output: str) -> str:
        text = (output or "").strip()
        if not text:
            return "detected"
        service_pattern = re.compile(rf"\b{re.escape(service)}\b[^\n]*\b(?:version|[vV]ersion)\b[^\n]*", re.IGNORECASE)
        match = service_pattern.search(text)
        if match:
            return " ".join(match.group(0).split())[:160]
        generic = re.search(r"\b(?:version|Version)\s*[:=]?\s*[A-Za-z0-9][A-Za-z0-9._+\- ]{0,80}", text)
        if generic:
            return " ".join(generic.group(0).split())[:160]
        for line in text.splitlines():
            normalized = " ".join(line.strip().split())
            if not normalized:
                continue
            alnum_count = sum(char.isalnum() for char in normalized)
            if alnum_count >= 3 and alnum_count >= len(normalized) / 3:
                return normalized[:160]
        return "detected"
