from __future__ import annotations

import unittest

from scripts.pressure_api_service import run_pressure_test


class PressureApiServiceTests(unittest.TestCase):
    def test_pressure_run_reports_admission_rejections(self) -> None:
        result = run_pressure_test(
            requests=12,
            workers=4,
            answer_delay_ms=50.0,
            trace_delay_ms=10.0,
            trace_queue_size=1,
            max_concurrent_answers=1,
            answer_acquire_timeout_seconds=0.01,
        )

        payload = result.to_dict()
        self.assertEqual(payload["requests"], 12)
        self.assertGreater(payload["completed_requests"], 0)
        self.assertGreater(payload["rejected_requests"], 0)
        self.assertEqual(
            payload["completed_requests"] + payload["rejected_requests"],
            payload["requests"],
        )
        self.assertIn("trace_stats", payload)
        self.assertIn("dropped_events", payload["trace_stats"])
        self.assertIn("written_events", payload["trace_stats"])
        self.assertIn("failed_events", payload["trace_stats"])
        self.assertIn("closed", payload["trace_stats"])


if __name__ == "__main__":
    unittest.main()
