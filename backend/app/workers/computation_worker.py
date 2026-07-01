"""计算任务 worker。

该 worker 使用 MongoDB find_one_and_update 原子领取 queued run；Mongo 不可用时沿用
demo JSON store 的进程内锁领取逻辑，便于本地 MVP smoke test。
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass

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
        running = self.service.initialize_acquired_run(acquired, worker_id=self.worker_id, now=now)
        finished = self.service.finish_acquired_run(running, worker_id=self.worker_id, now=utc_now())
        return WorkerResult(claimed=True, run_id=finished.run_id, status=finished.status)

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
