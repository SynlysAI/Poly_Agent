from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from app.services.algorithm_runtimes.base import AlgorithmRuntimeError
from app.services.algorithm_runtimes.local_sandbox import LocalSandboxRuntimeBackend


def _write_package(tmp_path: Path, source: str) -> Path:
    package_path = tmp_path / "package"
    package_path.mkdir()
    src_path = package_path / "src"
    src_path.mkdir()
    (src_path / "__init__.py").write_text("", encoding="utf-8")
    (src_path / "handler.py").write_text(textwrap.dedent(source).strip() + "\n", encoding="utf-8")
    return package_path


def test_local_sandbox_runtime_predicts_with_metadata(tmp_path: Path) -> None:
    package_path = _write_package(
        tmp_path,
        """
        def load(context):
            return {"bias": 2}

        def predict(inputs, context, model=None):
            print("model loaded")
            return {
                "prediction": {"value": inputs["value"] + model["bias"]},
                "feature_summary": {"backend": context["runtime"]},
            }
        """,
    )

    backend = LocalSandboxRuntimeBackend(max_output_bytes=2048)
    result = backend.predict(
        package_path=package_path,
        entrypoint="src.handler:predict",
        loader="src.handler:load",
        inputs={"value": 3},
        timeout_seconds=5,
        context={"run_id": "arun_test"},
    )

    assert result.output["prediction"]["value"] == 5
    assert result.runtime["backend"] == "local_sandbox_runtime"
    assert result.runtime["worker_pid"]
    assert result.logs.stdout.strip() == "model loaded"
    assert result.logs.truncated is False


def test_local_sandbox_runtime_timeout_kills_child(tmp_path: Path) -> None:
    package_path = _write_package(
        tmp_path,
        """
        def predict(inputs, context):
            while True:
                pass
        """,
    )

    backend = LocalSandboxRuntimeBackend(max_output_bytes=2048)

    with pytest.raises(AlgorithmRuntimeError) as exc_info:
        backend.predict(
            package_path=package_path,
            entrypoint="src.handler:predict",
            loader=None,
            inputs={},
            timeout_seconds=1,
            context={"run_id": "arun_timeout"},
        )

    error = exc_info.value
    assert error.error_type == "TimeoutExpired"
    assert "timed out" in error.message
    assert error.runtime["backend"] == "local_sandbox_runtime"


def test_sandbox_shim_import_does_not_start_fastapi_app() -> None:
    """验证导入 sandbox shim 不会触发 FastAPI 应用初始化。"""
    project_root = Path(__file__).resolve().parents[2]
    backend_root = project_root / "backend"
    code = (
        "import sys; "
        "import app.services.algorithm_runtimes.sandbox_shim; "
        "assert 'app.main' not in sys.modules"
    )
    env = {
        **os.environ,
        "APP_ENV": "test",
        "STORAGE_BACKEND": "sqlite",
        "PYTHONPATH": os.pathsep.join([str(backend_root), os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep),
    }

    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
