from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from rag_modules.kernel.routing import RouteStatistics, SearchStrategy


def test_route_statistics_records_concurrent_requests_without_losing_counts() -> None:
    statistics = RouteStatistics()
    strategies = tuple(SearchStrategy)
    iterations_per_worker = 2_000
    worker_count = 12

    def record(worker_index: int) -> None:
        strategy = strategies[worker_index % len(strategies)]
        for _ in range(iterations_per_worker):
            statistics.record(strategy)

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        list(executor.map(record, range(worker_count)))

    snapshot = statistics.to_dict()
    assert snapshot == {
        "traditional_count": 8_000,
        "graph_rag_count": 8_000,
        "combined_count": 8_000,
        "total_queries": 24_000,
    }


def test_route_statistics_snapshots_are_consistent_during_concurrent_updates() -> None:
    statistics = RouteStatistics()
    started = threading.Event()

    def record() -> None:
        started.set()
        for index in range(10_000):
            statistics.record(tuple(SearchStrategy)[index % len(SearchStrategy)])

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(record)
        assert started.wait(timeout=1.0)
        while not future.done():
            snapshot = statistics.to_dict()
            assert snapshot["total_queries"] == (
                snapshot["traditional_count"]
                + snapshot["graph_rag_count"]
                + snapshot["combined_count"]
            )
        future.result()

    summary = statistics.summary()
    assert (
        summary["traditional_ratio"] + summary["graph_rag_ratio"] + summary["combined_ratio"] == 1.0
    )
