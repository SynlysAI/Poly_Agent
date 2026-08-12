from __future__ import annotations

import multiprocessing
from pathlib import Path

from app.infra.demo_store import DemoJsonStore


def _increment_store(path: str, iterations: int, start: multiprocessing.synchronize.Event) -> None:
    store = DemoJsonStore(Path(path))
    start.wait()
    for _ in range(iterations):
        def increment(data):
            rows = data["assistant_runs"]
            value = int(rows[0]["value"]) if rows else 0
            rows[:] = [{"value": value + 1}]

        store.mutate(increment)


def test_demo_store_mutations_are_atomic_across_processes(tmp_path: Path) -> None:
    path = tmp_path / "demo-db.json"
    start = multiprocessing.Event()
    iterations = 40
    processes = [
        multiprocessing.Process(target=_increment_store, args=(str(path), iterations, start))
        for _ in range(3)
    ]

    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(timeout=10)

    assert all(process.exitcode == 0 for process in processes)
    assert DemoJsonStore(path).load()["assistant_runs"] == [{"value": iterations * len(processes)}]
