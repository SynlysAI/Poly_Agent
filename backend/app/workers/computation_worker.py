"""计算任务 worker。

该 worker 使用 MongoDB find_one_and_update 原子领取 queued run；Mongo 不可用时沿用
demo JSON store 的进程内锁领取逻辑，便于本地 MVP smoke test。
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass

import json

from app.computation_adapters.base import AdapterContext
from app.computation_adapters.base import AdapterRunResult
from app.computation_adapters.base import ArtifactSpec
from app.computation_adapters.base import build_steps
from app.computation_adapters.registry import get_adapter
from app.core.config import settings
from app.infra.computation_repositories import ComputationRunRepository, utc_now
from app.schemas.computation import ComputationRun
from app.services.computation_service import ComputationService


@dataclass
class WorkerResult:
    """单次 worker 执行结果。"""

    claimed: bool
    run_id: str | None = None
    status: str | None = None


class ComputationWorker:
    """领取并执行 queued computation run。"""

    def __init__(self, *, worker_id: str = "worker-mock-1") -> None:
        self.worker_id = worker_id
        self.service = ComputationService()

    def acquire_and_run_one(self) -> WorkerResult:
        """领取一个 queued run 并执行。"""
        now = utc_now()
        doc = ComputationRunRepository.acquire_queued_run(worker_id=self.worker_id, now=now)
        if not doc:
            return WorkerResult(claimed=False)
        acquired = ComputationRun(**doc)
        adapter = get_adapter(acquired.workflow_type, acquired.engine)
        running = self.service.initialize_acquired_run(
            acquired,
            worker_id=self.worker_id,
            now=now,
            step_labels=adapter.step_labels,
        )
        workdir = settings.outputs_root / "computations" / running.run_id / "work"
        context = AdapterContext(
            run=running,
            worker_id=self.worker_id,
            workdir=workdir,
            started_at=running.started_at or now,
            timeout_seconds=running.resources.max_wallclock_seconds,
        )
        try:
            validation_result = adapter.validate_input(context)
            adapter_result = validation_result or adapter.run(context)
            adapter_result.artifact_specs = adapter.collect_artifacts(context, adapter_result)
            adapter_result.result_summary = adapter.parse_result(context, adapter_result)
        except Exception as exc:
            adapter_result = self._build_unhandled_failure(context, adapter.step_labels, exc)
        finished = self.service.finish_acquired_run(
            running,
            worker_id=self.worker_id,
            now=utc_now(),
            adapter_result=adapter_result,
        )
        if finished.status == "completed" and finished.campaign_id and finished.suggestion_id:
            from app.services.optimization_service import OptimizationService

            OptimizationService().process_completed_computation(
                finished.run_id,
                actor_user_id=self.worker_id,
            )
        return WorkerResult(claimed=True, run_id=finished.run_id, status=finished.status)

    def _build_unhandled_failure(
        self,
        context: AdapterContext,
        step_labels: dict[str, str],
        exc: Exception,
    ) -> AdapterRunResult:
        """Convert unexpected adapter exceptions to a failed retryable run."""
        context.workdir.mkdir(parents=True, exist_ok=True)
        message = str(exc)[:1000] or exc.__class__.__name__
        error = {"error_code": "ADAPTER_UNHANDLED_EXCEPTION", "message": message, "retryable": True}
        error_path = context.workdir / "adapter-error.json"
        log_path = context.workdir / "worker.log"
        error_path.write_text(json.dumps(error, ensure_ascii=False, indent=2), encoding="utf-8")
        log_path.write_text(
            "\n".join(
                [
                    f"run_id={context.run.run_id}",
                    f"workflow_type={context.run.workflow_type}",
                    f"engine={context.run.engine}",
                    f"error_code={error['error_code']}",
                    f"message={message}",
                ]
            ),
            encoding="utf-8",
        )
        now = utc_now()
        failed_step_key = next(iter(step_labels), "ADAPTER_RUN")
        return AdapterRunResult(
            status="failed",
            steps=build_steps(
                step_labels or {failed_step_key: "Adapter execution"},
                status="failed",
                started_at=context.started_at,
                finished_at=now,
                failed_step_key=failed_step_key,
                error_message=message,
            ),
            artifact_specs=[
                ArtifactSpec(
                    step_key=failed_step_key,
                    artifact_type="error_json",
                    name="adapter-error.json",
                    path=error_path,
                    mime_type="application/json",
                    parser_name="computation_worker",
                    parser_version="0.1.0",
                    metadata={"source": "worker", "source_step": failed_step_key, "error_code": error["error_code"]},
                ),
                ArtifactSpec(
                    step_key=failed_step_key,
                    artifact_type="log_text",
                    name="worker.log",
                    path=log_path,
                    mime_type="text/plain",
                    parser_name="computation_worker",
                    parser_version="0.1.0",
                    metadata={"source": "worker", "source_step": failed_step_key, "error_code": error["error_code"]},
                ),
            ],
            error=error,
        )

    def run_forever(self, *, interval_seconds: float = 1.0) -> None:
        """持续轮询执行 queued runs。"""
        while True:
            result = self.acquire_and_run_one()
            if not result.claimed:
                time.sleep(interval_seconds)


def main() -> None:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="Run Poly Agent computation worker")
    parser.add_argument("--worker-id", default="worker-mock-1")
    parser.add_argument("--once", action="store_true", help="claim and run at most one queued run")
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()

    worker = ComputationWorker(worker_id=args.worker_id)
    if args.once:
        result = worker.acquire_and_run_one()
        print(result)
        return
    worker.run_forever(interval_seconds=args.interval)


if __name__ == "__main__":
    main()
