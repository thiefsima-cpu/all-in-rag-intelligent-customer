from __future__ import annotations

import threading
import unittest

from rag_modules.interfaces.api.services.errors import ApiBackpressureError
from rag_modules.interfaces.api.services.serving_stream_executor import BoundedStreamExecutor


class BoundedStreamExecutorTests(unittest.TestCase):
    def test_running_plus_queued_are_bounded_and_saturation_rejects_immediately(self) -> None:
        started = threading.Event()
        release = threading.Event()
        executor = BoundedStreamExecutor(max_workers=1, max_outstanding=2)

        def block() -> None:
            started.set()
            release.wait(timeout=2.0)

        first = executor.submit(block)
        self.assertTrue(started.wait(timeout=1.0))
        second = executor.submit(lambda: None)

        with self.assertRaises(ApiBackpressureError):
            executor.submit(lambda: None)

        saturated = executor.snapshot()
        self.assertEqual((saturated.active, saturated.queued), (1, 1))
        self.assertEqual(saturated.peak_outstanding, 2)
        self.assertEqual(saturated.rejected, 1)

        release.set()
        first.result(timeout=1.0)
        second.result(timeout=1.0)
        self.assertEqual((executor.snapshot().active, executor.snapshot().queued), (0, 0))
        executor.shutdown()

    def test_cancelling_queued_future_releases_exactly_one_slot(self) -> None:
        started = threading.Event()
        release = threading.Event()
        executor = BoundedStreamExecutor(max_workers=1, max_outstanding=2)

        def block() -> None:
            started.set()
            release.wait(timeout=2.0)

        first = executor.submit(block)
        self.assertTrue(started.wait(timeout=1.0))
        queued = executor.submit(lambda: None)

        self.assertTrue(queued.cancel())
        replacement = executor.submit(lambda: None)
        self.assertEqual(executor.snapshot().queued, 1)

        release.set()
        first.result(timeout=1.0)
        replacement.result(timeout=1.0)
        self.assertEqual((executor.snapshot().active, executor.snapshot().queued), (0, 0))
        executor.shutdown()

    def test_task_failure_releases_capacity(self) -> None:
        executor = BoundedStreamExecutor(max_workers=1, max_outstanding=1)

        def fail() -> None:
            raise ValueError("expected failure")

        with self.assertRaisesRegex(ValueError, "expected failure"):
            executor.submit(fail).result(timeout=1.0)

        executor.submit(lambda: None).result(timeout=1.0)
        self.assertEqual((executor.snapshot().active, executor.snapshot().queued), (0, 0))
        executor.shutdown()

    def test_shutdown_cancels_queued_future_and_rejects_new_submissions(self) -> None:
        started = threading.Event()
        release = threading.Event()
        executor = BoundedStreamExecutor(max_workers=1, max_outstanding=2)

        def block() -> None:
            started.set()
            release.wait(timeout=2.0)

        running = executor.submit(block)
        self.assertTrue(started.wait(timeout=1.0))
        queued = executor.submit(lambda: None)

        executor.shutdown()

        self.assertTrue(queued.cancelled())
        self.assertEqual((executor.snapshot().active, executor.snapshot().queued), (1, 0))
        with self.assertRaises(RuntimeError):
            executor.submit(lambda: None)

        release.set()
        running.result(timeout=1.0)
        self.assertEqual((executor.snapshot().active, executor.snapshot().queued), (0, 0))


if __name__ == "__main__":
    unittest.main()
