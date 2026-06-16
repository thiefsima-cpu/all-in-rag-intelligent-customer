from __future__ import annotations

import unittest

from rag_modules.infra.resilience import CircuitBreaker, CircuitOpenError


class InfrastructureResilienceTests(unittest.TestCase):
    def test_circuit_breaker_opens_then_recovers_through_half_open_probe(self) -> None:
        now = [0.0]
        breaker = CircuitBreaker(
            failure_threshold=2,
            recovery_timeout_seconds=5.0,
            clock=lambda: now[0],
        )

        def fail():
            raise TimeoutError("downstream timeout")

        with self.assertRaises(TimeoutError):
            breaker.call(fail)
        with self.assertRaises(TimeoutError):
            breaker.call(fail)
        self.assertEqual(breaker.snapshot().state, "open")

        with self.assertRaises(CircuitOpenError):
            breaker.call(lambda: "blocked")

        now[0] = 5.0
        self.assertEqual(breaker.call(lambda: "ok"), "ok")
        self.assertEqual(breaker.snapshot().state, "closed")
        self.assertEqual(breaker.snapshot().failure_count, 0)


if __name__ == "__main__":
    unittest.main()
