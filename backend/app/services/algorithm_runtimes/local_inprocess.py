"""Development-only in-process runtime backend."""

from __future__ import annotations

import hashlib
import importlib
import os
import sys
import time
from pathlib import Path
from typing import Any

from app.services.algorithm_runtimes.base import RuntimeExecutionLogs, RuntimeExecutionResult


class LocalInProcessRuntimeBackend:
    """Run uploaded code inside the API process.

    This is retained for local development and compatibility tests only.
    """

    backend_name = "local_inprocess"
    legacy_kind = "local_python_adapter"

    def validate_runtime(self, *, package_path: Path, runtime: dict[str, Any]) -> dict[str, Any]:
        return {"backend": self.backend_name, "health": "ready", "package_path": str(package_path)}

    def build(
        self,
        *,
        version_id: str,
        package_sha256: str,
        package_path: Path,
        runtime: dict[str, Any],
        requirements: str = "",
    ) -> dict[str, Any]:
        package_digest = f"sha256:{package_sha256}"
        requirements_sha256 = hashlib.sha256(requirements.encode("utf-8")).hexdigest()
        environment_digest = self._digest(
            {"backend": self.backend_name, "python": runtime.get("python"), "requirements": requirements_sha256}
        )
        runtime_digest = self._digest(
            {"backend": self.backend_name, "version_id": version_id, "environment_digest": environment_digest}
        )
        return {
            "package_digest": package_digest,
            "requirements_sha256": requirements_sha256,
            "environment_digest": environment_digest,
            "runtime_digest": runtime_digest,
        }

    def deploy(
        self,
        *,
        version_id: str,
        package_path: Path,
        runtime: dict[str, Any],
        digests: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "kind": self.legacy_kind,
            "backend": self.backend_name,
            "health": "ready",
            "endpoint": "internal://algorithm-package-runner",
            "endpoint_type": "in_process",
            "deployed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "resource_limits": runtime.get("resources") or {},
            **digests,
        }

    def health(self, *, deployment: dict[str, Any]) -> dict[str, Any]:
        return {"backend": self.backend_name, "health": deployment.get("health", "unknown")}

    def predict(
        self,
        *,
        package_path: Path,
        entrypoint: str,
        loader: str | None,
        inputs: dict[str, Any],
        timeout_seconds: int,
        input_files: dict[str, str] | None = None,
        output_dir: Path | None = None,
        resource_assets: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> RuntimeExecutionResult:
        module_name, func_name = self._split_callable(entrypoint)
        loader_ref = self._split_callable(loader) if loader else None
        sys_path = str(package_path)
        old_cwd = os.getcwd()
        sys.path.insert(0, sys_path)
        started = time.monotonic()
        try:
            os.chdir(package_path)
            run_context = {
                "package_path": str(package_path),
                "input_files": input_files or {},
                "output_dir": str(output_dir) if output_dir else None,
                "resource_assets": resource_assets or {},
                "runtime": self.legacy_kind,
                "runtime_backend": self.backend_name,
                **(context or {}),
            }
            model = None
            if loader_ref:
                loader_module = importlib.import_module(loader_ref[0])
                loader_func = getattr(loader_module, loader_ref[1])
                model = loader_func(run_context)
            module = importlib.import_module(module_name)
            predict_func = getattr(module, func_name)
            try:
                output = predict_func(inputs, run_context, model)
            except TypeError:
                output = predict_func(inputs, run_context)
            if not isinstance(output, dict):
                raise ValueError("predict() 必须返回 dict")
            duration_ms = int((time.monotonic() - started) * 1000)
            return RuntimeExecutionResult(
                output=output,
                runtime={
                    "backend": self.backend_name,
                    "kind": self.legacy_kind,
                    "duration_ms": duration_ms,
                    "timeout_seconds": timeout_seconds,
                },
                logs=RuntimeExecutionLogs(),
            )
        finally:
            os.chdir(old_cwd)
            if sys.path and sys.path[0] == sys_path:
                sys.path.pop(0)
            root_module = module_name.rsplit(".", 1)[0]
            for name in list(sys.modules):
                if name == module_name or name.startswith(root_module + "."):
                    sys.modules.pop(name, None)

    def stop(self, *, deployment: dict[str, Any]) -> dict[str, Any]:
        return {"backend": self.backend_name, "stopped": True}

    def logs(self, *, deployment: dict[str, Any]) -> RuntimeExecutionLogs:
        return RuntimeExecutionLogs()

    @staticmethod
    def _split_callable(value: str | None) -> tuple[str, str]:
        if not value or ":" not in value:
            raise ValueError("入口函数必须使用 module:function 格式")
        module, func = value.split(":", 1)
        if not module or not func:
            raise ValueError("入口函数必须包含 module 和 function")
        return module, func

    @staticmethod
    def _digest(payload: dict[str, Any]) -> str:
        import json

        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return f"sha256:{hashlib.sha256(raw).hexdigest()}"
