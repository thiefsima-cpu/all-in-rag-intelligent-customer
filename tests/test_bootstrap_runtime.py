from __future__ import annotations

import importlib
import importlib.util
import unittest


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeSession:
    def __init__(
        self,
        *,
        post_responses: list[_FakeResponse] | None = None,
        get_responses: list[_FakeResponse] | None = None,
    ) -> None:
        self.post_responses = list(post_responses or [])
        self.get_responses = list(get_responses or [])
        self.calls: list[tuple[str, str]] = []

    def post(self, url: str, *, timeout: float):
        del timeout
        self.calls.append(("POST", url))
        return self.post_responses.pop(0)

    def get(self, url: str, *, timeout: float):
        del timeout
        self.calls.append(("GET", url))
        return self.get_responses.pop(0)


def _bootstrap_module(test_case: unittest.TestCase):
    spec = importlib.util.find_spec("scripts.bootstrap_runtime")
    test_case.assertIsNotNone(spec)
    return importlib.import_module("scripts.bootstrap_runtime")


def _settings(module, **overrides):
    values = {
        "auto_bootstrap": True,
        "force_rebuild": False,
        "build_api_url": "http://build-api:8001",
        "request_timeout_seconds": 5.0,
        "build_timeout_seconds": 30.0,
        "poll_interval_seconds": 0.0,
    }
    values.update(overrides)
    return module.RuntimeBootstrapSettings(**values)


class RuntimeBootstrapTests(unittest.TestCase):
    def test_disabled_bootstrap_has_no_side_effects(self) -> None:
        module = _bootstrap_module(self)
        session = _FakeSession()
        importer_calls: list[object] = []

        result = module.run_bootstrap(
            _settings(module, auto_bootstrap=False),
            config=object(),
            importer=lambda config, **kwargs: importer_calls.append((config, kwargs)),
            session=session,
        )

        self.assertEqual({"status": "skipped", "reason": "disabled"}, result)
        self.assertEqual([], importer_calls)
        self.assertEqual([], session.calls)

    def test_normal_bootstrap_imports_if_empty_and_waits_for_build(self) -> None:
        module = _bootstrap_module(self)
        session = _FakeSession(
            post_responses=[_FakeResponse(202, {"job": {"job_id": "a" * 32, "status": "queued"}})],
            get_responses=[
                _FakeResponse(200, {"job": {"job_id": "a" * 32, "status": "running"}}),
                _FakeResponse(200, {"job": {"job_id": "a" * 32, "status": "succeeded"}}),
            ],
        )
        importer_calls: list[tuple[object, bool]] = []

        result = module.run_bootstrap(
            _settings(module),
            config="config",
            importer=lambda config, *, only_if_empty: (
                importer_calls.append((config, only_if_empty)) or True
            ),
            session=session,
            sleep=lambda seconds: None,
        )

        self.assertEqual([("config", True)], importer_calls)
        self.assertEqual("succeeded", result["status"])
        self.assertTrue(result["graph_imported"])
        self.assertEqual(
            [
                ("POST", "http://build-api:8001/v1/jobs/build"),
                ("GET", f"http://build-api:8001/v1/jobs/{'a' * 32}"),
                ("GET", f"http://build-api:8001/v1/jobs/{'a' * 32}"),
            ],
            session.calls,
        )

    def test_force_rebuild_uses_rebuild_endpoint(self) -> None:
        module = _bootstrap_module(self)
        session = _FakeSession(
            post_responses=[
                _FakeResponse(202, {"job": {"job_id": "b" * 32, "status": "succeeded"}})
            ]
        )

        result = module.run_bootstrap(
            _settings(module, force_rebuild=True),
            config=object(),
            importer=lambda config, *, only_if_empty: False,
            session=session,
        )

        self.assertEqual("succeeded", result["status"])
        self.assertEqual(
            [("POST", "http://build-api:8001/v1/jobs/rebuild")],
            session.calls,
        )

    def test_build_conflict_waits_for_the_active_job(self) -> None:
        module = _bootstrap_module(self)
        session = _FakeSession(
            post_responses=[_FakeResponse(409, {"job": {"job_id": "c" * 32, "status": "running"}})],
            get_responses=[
                _FakeResponse(200, {"job": {"job_id": "c" * 32, "status": "succeeded"}})
            ],
        )

        result = module.run_bootstrap(
            _settings(module),
            config=object(),
            importer=lambda config, *, only_if_empty: False,
            session=session,
            sleep=lambda seconds: None,
        )

        self.assertEqual("succeeded", result["status"])
        self.assertEqual(("GET", f"http://build-api:8001/v1/jobs/{'c' * 32}"), session.calls[-1])

    def test_failed_build_job_is_propagated(self) -> None:
        module = _bootstrap_module(self)
        session = _FakeSession(
            post_responses=[
                _FakeResponse(
                    202,
                    {
                        "job": {
                            "job_id": "d" * 32,
                            "status": "failed",
                            "error": "embedding failed",
                        }
                    },
                )
            ]
        )

        with self.assertRaisesRegex(RuntimeError, "embedding failed"):
            module.run_bootstrap(
                _settings(module),
                config=object(),
                importer=lambda config, *, only_if_empty: False,
                session=session,
            )

    def test_build_polling_timeout_is_propagated(self) -> None:
        module = _bootstrap_module(self)
        session = _FakeSession(
            post_responses=[_FakeResponse(202, {"job": {"job_id": "e" * 32, "status": "running"}})]
        )
        clock_values = iter([0.0, 2.0])

        with self.assertRaisesRegex(TimeoutError, "timed out"):
            module.run_bootstrap(
                _settings(module, build_timeout_seconds=1.0),
                config=object(),
                importer=lambda config, *, only_if_empty: False,
                session=session,
                monotonic=lambda: next(clock_values),
                sleep=lambda seconds: None,
            )

    def test_settings_are_loaded_from_environment(self) -> None:
        module = _bootstrap_module(self)

        settings = module.RuntimeBootstrapSettings.from_env(
            {
                "AUTO_BOOTSTRAP": "false",
                "FORCE_REBUILD": "true",
                "BUILD_API_URL": "http://custom:9000/",
                "BOOTSTRAP_REQUEST_TIMEOUT_SECONDS": "7",
                "BOOTSTRAP_BUILD_TIMEOUT_SECONDS": "42",
                "BOOTSTRAP_POLL_INTERVAL_SECONDS": "0.5",
            }
        )

        self.assertFalse(settings.auto_bootstrap)
        self.assertTrue(settings.force_rebuild)
        self.assertEqual("http://custom:9000", settings.build_api_url)
        self.assertEqual(7.0, settings.request_timeout_seconds)
        self.assertEqual(42.0, settings.build_timeout_seconds)
        self.assertEqual(0.5, settings.poll_interval_seconds)

    def test_empty_environment_uses_stable_defaults(self) -> None:
        module = _bootstrap_module(self)

        settings = module.RuntimeBootstrapSettings.from_env({})

        self.assertTrue(settings.auto_bootstrap)
        self.assertFalse(settings.force_rebuild)
        self.assertEqual("http://build-api:8001", settings.build_api_url)
        self.assertEqual(10.0, settings.request_timeout_seconds)
        self.assertEqual(1800.0, settings.build_timeout_seconds)
        self.assertEqual(2.0, settings.poll_interval_seconds)


if __name__ == "__main__":
    unittest.main()
