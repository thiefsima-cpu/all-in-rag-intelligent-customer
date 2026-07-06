from __future__ import annotations

import threading
import unittest

from rag_modules.app.runtime_operations import RuntimeOperationCoordinator


class RuntimeOperationCoordinatorTests(unittest.TestCase):
    def test_lifecycle_owner_can_enter_inspection_reentrantly(self) -> None:
        coordinator = RuntimeOperationCoordinator()
        entered_inspection = threading.Event()

        def run_lifecycle() -> None:
            with coordinator.lifecycle_operation():
                with coordinator.inspection_operation():
                    entered_inspection.set()

        thread = threading.Thread(target=run_lifecycle, daemon=True)
        thread.start()

        self.assertTrue(
            entered_inspection.wait(timeout=0.5),
            "lifecycle owner should not deadlock when collecting its own operation response",
        )
        thread.join(timeout=1.0)

    def test_other_threads_wait_for_active_lifecycle_before_inspection(self) -> None:
        coordinator = RuntimeOperationCoordinator()
        lifecycle_entered = threading.Event()
        release_lifecycle = threading.Event()
        entered_inspection = threading.Event()

        def run_lifecycle() -> None:
            with coordinator.lifecycle_operation():
                lifecycle_entered.set()
                release_lifecycle.wait(timeout=1.0)

        lifecycle_thread = threading.Thread(target=run_lifecycle)
        lifecycle_thread.start()
        self.assertTrue(lifecycle_entered.wait(timeout=0.5))

        def run_inspection() -> None:
            with coordinator.inspection_operation():
                entered_inspection.set()

        inspection_thread = threading.Thread(target=run_inspection)
        inspection_thread.start()

        self.assertFalse(entered_inspection.wait(timeout=0.05))
        release_lifecycle.set()
        self.assertTrue(entered_inspection.wait(timeout=1.0))
        lifecycle_thread.join(timeout=1.0)
        inspection_thread.join(timeout=1.0)


if __name__ == "__main__":
    unittest.main()
