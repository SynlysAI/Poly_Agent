from __future__ import annotations

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
