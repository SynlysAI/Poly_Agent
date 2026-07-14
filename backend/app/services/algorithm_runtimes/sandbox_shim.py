"""JSON stdin/stdout shim for uploaded algorithm packages."""

from __future__ import annotations

import importlib
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any


def _split_callable(value: str | None) -> tuple[str, str]:
    if not value or ":" not in value:
        raise ValueError("入口函数必须使用 module:function 格式")
    module, func = value.split(":", 1)
    if not module or not func:
        raise ValueError("入口函数必须包含 module 和 function")
    return module, func


def _run(request: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    package_path = Path(request["package_path"]).resolve()
    entrypoint = request["entrypoint"]
    loader = request.get("loader")
    inputs = request.get("inputs") or {}
    context = dict(request.get("context") or {})
    context.update(
        {
            "package_path": str(package_path),
            "runtime": "local_sandbox_runtime",
            "runtime_backend": "local_sandbox_runtime",
        }
    )
    module_name, func_name = _split_callable(entrypoint)
    loader_ref = _split_callable(loader) if loader else None

    sys.path.insert(0, str(package_path))
    os.chdir(package_path)
    model = None
    if loader_ref:
        loader_module = importlib.import_module(loader_ref[0])
        loader_func = getattr(loader_module, loader_ref[1])
        model = loader_func(context)
    module = importlib.import_module(module_name)
    predict_func = getattr(module, func_name)
    try:
        output = predict_func(inputs, context, model)
    except TypeError:
        output = predict_func(inputs, context)
    if not isinstance(output, dict):
        raise ValueError("predict() 必须返回 dict")
    return {
        "ok": True,
        "output": output,
        "runtime": {
            "backend": "local_sandbox_runtime",
            "duration_ms": int((time.monotonic() - started) * 1000),
            "worker_pid": os.getpid(),
        },
    }


def main() -> int:
    try:
        request = json.loads(sys.stdin.read() or "{}")
        response = _run(request)
    except BaseException as exc:  # noqa: BLE001 - shim must serialize all user-code failures.
        response = {
            "ok": False,
            "error": {
                "error_type": type(exc).__name__,
                "message": str(exc),
                "traceback_tail": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-4000:],
            },
            "runtime": {"backend": "local_sandbox_runtime", "worker_pid": os.getpid()},
        }
    sys.stdout.write(json.dumps(response, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
