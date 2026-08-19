"""Worker process for durable LUI assistant runs."""

from __future__ import annotations

import argparse
import signal
import time

from app.core.logging import get_logger
from app.services.assistant_run_service import assistant_run_service


logger = get_logger("poly_agent.assistant_run_worker")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-id", default="assistant-local-1")
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args()
    stopping = False

    def stop(*_args) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        from app.infra.research_engine_repositories import ensure_lui_repository_indexes

        ensure_lui_repository_indexes()
    except Exception:
        logger.exception("LUI 热路径 MongoDB 索引初始化失败")
    recovered = assistant_run_service.requeue_stale()
    logger.info("assistant worker started worker_id=%s recovered=%d", args.worker_id, recovered)
    while not stopping:
        continuation_count = assistant_run_service.process_continuations(args.worker_id)
        run_id = assistant_run_service.execute_next(args.worker_id)
        if not run_id and not continuation_count:
            time.sleep(max(0.1, args.interval))
    logger.info("assistant worker stopped worker_id=%s", args.worker_id)


if __name__ == "__main__":
    main()
