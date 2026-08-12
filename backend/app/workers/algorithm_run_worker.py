"""Durable worker for confirmed LUI vertical-algorithm runs."""

from __future__ import annotations

import argparse
import signal
import time

from app.core.time import utc_now
from app.infra.research_engine_repositories import AlgorithmRunRepository
from app.services.research_engine_service import ResearchEngineService
from app.schemas.research_engine import AlgorithmRunCreate


class AlgorithmRunWorker:
    def __init__(self, worker_id: str = "algorithm-local-1") -> None:
        self.worker_id = worker_id

    def acquire_and_run_one(self) -> str | None:
        doc = AlgorithmRunRepository.claim_next_queued(self.worker_id, utc_now())
        if not doc:
            return None
        payload = AlgorithmRunCreate(
            algorithm_id=doc["algorithm_id"],
            algorithm_version_id=doc.get("algorithm_version_id"),
            trigger_source=doc.get("trigger_source", "human_workflow"),
            trigger_context_id=doc.get("trigger_context_id"),
            input_snapshot=doc.get("input_snapshot") or {},
            input_asset_refs=doc.get("input_asset_refs") or {},
            reason="durable algorithm worker",
        )
        try:
            ResearchEngineService().create_algorithm_run(
                payload,
                actor_user_id=doc.get("created_by") or "system",
                is_admin=True,
                existing_run_id=doc["run_id"],
            )
        except Exception:
            # The service persists failed status and error details.
            pass
        return doc["run_id"]

    def run_forever(self, interval_seconds: float = 0.5) -> None:
        while True:
            if not self.acquire_and_run_one():
                time.sleep(max(0.1, interval_seconds))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-id", default="algorithm-local-1")
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args()
    AlgorithmRunWorker(args.worker_id).run_forever(args.interval)


if __name__ == "__main__":
    main()
