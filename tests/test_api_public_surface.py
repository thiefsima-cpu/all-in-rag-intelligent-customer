from __future__ import annotations

import tests.api_app_helpers as h

json = h.json
unittest = h.unittest
Path = h.Path
TestClient = h.TestClient
build_test_config = h.build_test_config
create_build_api_app = h.create_build_api_app
create_serving_api_app = h.create_serving_api_app
API_VERSION = h.API_VERSION
ARTIFACT_HEALTH_MISSING = h.ARTIFACT_HEALTH_MISSING
ARTIFACT_HEALTH_READY = h.ARTIFACT_HEALTH_READY
_API_TOKEN = h._API_TOKEN
_client = h._client
_assert_error_response = h._assert_error_response
_FakeApiSystem = h._FakeApiSystem
_PublicManifestErrorSystem = h._PublicManifestErrorSystem


class ApiPublicSurfaceTests(unittest.TestCase):
    """Versioned route, health, readiness, stats, and diagnostics surface behavior."""

    def test_serving_liveness_is_public_and_does_not_require_readiness(self) -> None:
        app = create_serving_api_app(system=_FakeApiSystem())

        with TestClient(app) as client:
            response = client.get("/v1/health/live")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertFalse(response.json()["system_ready"])

    def test_owned_serving_api_fails_startup_when_model_api_key_is_missing(self) -> None:
        config = build_test_config({"models": {"api_key": ""}})
        app = create_serving_api_app(config=config)

        with self.assertRaisesRegex(ValueError, "DASHSCOPE_API_KEY"):
            with TestClient(app):
                pass

    def test_serving_readiness_returns_503_until_system_is_ready(self) -> None:
        system = _FakeApiSystem()
        app = create_serving_api_app(system=system)

        with TestClient(app) as client:
            unready_response = client.get("/v1/health/ready")
            system.system_ready = True
            system.serving_initialized = True
            ready_response = client.get("/v1/health/ready")

        self.assertEqual(unready_response.status_code, 503)
        self.assertEqual(unready_response.json()["status"], "not_ready")
        self.assertEqual(ready_response.status_code, 200)
        self.assertEqual(ready_response.json()["status"], "ok")

    def test_serving_health_surface_reports_runtime_state(self) -> None:
        app = create_serving_api_app(system=_FakeApiSystem())

        with _client(app) as client:
            response = client.get("/v1/health")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertFalse(payload["system_ready"])
        self.assertEqual(payload["manifest_health"], ARTIFACT_HEALTH_MISSING)

    def test_serving_stats_and_diagnostics_use_structured_response_models(self) -> None:
        system = _FakeApiSystem()
        system.system_ready = True
        system.serving_initialized = True
        app = create_serving_api_app(system=system)

        with _client(app) as client:
            stats_response = client.get("/v1/stats")
            diagnostics_response = client.get("/v1/diagnostics")

        self.assertEqual(stats_response.status_code, 200)
        stats_payload = stats_response.json()["stats"]
        self.assertTrue(stats_payload["ready"])
        self.assertIn("models", stats_payload)
        self.assertIn("trace_stats", stats_payload)
        self.assertIn("route_stats", stats_payload)
        self.assertIn("artifact_manifest", stats_payload)
        self.assertEqual(
            stats_payload["artifact_manifest"]["health"],
            ARTIFACT_HEALTH_READY,
        )

        self.assertEqual(diagnostics_response.status_code, 200)
        diagnostics_payload = diagnostics_response.json()["diagnostics"]
        self.assertEqual(diagnostics_payload["mode"], "serve")
        self.assertTrue(diagnostics_payload["system_ready"])
        self.assertTrue(diagnostics_payload["retrieval_engines_initialized"])
        self.assertIn("trace_stats", diagnostics_payload)
        self.assertEqual(
            diagnostics_payload["manifest"]["collection_name"],
            "recipes",
        )

    def test_manifest_error_is_sanitized_in_diagnostics_and_stats(self) -> None:
        secret = "private-manifest-error"
        app = create_serving_api_app(system=_PublicManifestErrorSystem(secret))

        with _client(app) as client:
            diagnostics = client.get("/v1/diagnostics")
            stats = client.get("/v1/stats")

        serialized = json.dumps(
            {"diagnostics": diagnostics.json(), "stats": stats.json()},
            ensure_ascii=False,
        )
        self.assertNotIn(secret, serialized)
        self.assertIn("BUILD_FAILED", serialized)

    def test_serving_surface_does_not_expose_build_routes(self) -> None:
        app = create_serving_api_app(system=_FakeApiSystem())

        with _client(app) as client:
            response = client.post("/v1/jobs/build")

        self.assertEqual(response.status_code, 404)

    def test_build_surface_does_not_expose_answer_routes(self) -> None:
        app = create_build_api_app(system=_FakeApiSystem())

        with _client(app) as client:
            response = client.post("/v1/answers", json={"question": "Can I cook tofu?"})

        self.assertEqual(response.status_code, 404)

    def test_serving_and_build_apps_share_api_version_constant(self) -> None:
        serving_app = create_serving_api_app(system=_FakeApiSystem())
        build_app = create_build_api_app(system=_FakeApiSystem())
        app_source = (
            Path(__file__).resolve().parents[1] / "rag_modules" / "interfaces" / "api" / "app.py"
        ).read_text(encoding="utf-8")

        self.assertEqual(serving_app.version, API_VERSION)
        self.assertEqual(build_app.version, API_VERSION)
        self.assertIn("version=API_VERSION", app_source)
        self.assertNotIn('version="1.0.0"', app_source)

    def test_v1_health_paths_are_public_and_protected_paths_stay_protected(self) -> None:
        app = create_serving_api_app(system=_FakeApiSystem())

        with TestClient(app) as client:
            health = client.get("/v1/health")
            stats = client.get("/v1/stats")
            debug = client.post("/v1/debug/answers", json={"question": "tofu"})

        self.assertEqual(health.status_code, 200)
        _assert_error_response(stats, status_code=401, code="UNAUTHORIZED")
        _assert_error_response(debug, status_code=401, code="UNAUTHORIZED")

    def test_unversioned_serving_routes_are_retired(self) -> None:
        config = build_test_config(
            {
                "api": {
                    "access_token": _API_TOKEN,
                    "openapi_enabled": True,
                }
            }
        )
        app = create_serving_api_app(system=_FakeApiSystem(), config=config)

        with _client(app) as client:
            schema = client.get("/openapi.json").json()

            responses = {
                "/": client.get("/"),
                "/health": client.get("/health"),
                "/health/live": client.get("/health/live"),
                "/health/ready": client.get("/health/ready"),
                "/stats": client.get("/stats"),
                "/diagnostics": client.get("/diagnostics"),
                "/runtime/serving/initialize": client.post("/runtime/serving/initialize"),
                "/runtime/serving/refresh": client.post("/runtime/serving/refresh"),
                "/answers": client.post("/answers", json={"question": "tofu"}),
                "/answers/stream": client.post("/answers/stream", json={"question": "tofu"}),
            }

        for path, response in responses.items():
            self.assertEqual(response.status_code, 404, path)
            self.assertNotIn(path, schema["paths"])

        self.assertIn("/v1/health", schema["paths"])
        self.assertIn("/v1/answers", schema["paths"])
        self.assertIn("/v1/answers/stream", schema["paths"])

    def test_unversioned_build_routes_are_retired(self) -> None:
        config = build_test_config(
            {
                "api": {
                    "access_token": _API_TOKEN,
                    "openapi_enabled": True,
                }
            }
        )
        app = create_build_api_app(system=_FakeApiSystem(), config=config)

        with _client(app) as client:
            schema = client.get("/openapi.json").json()

            responses = {
                "/": client.get("/"),
                "/health": client.get("/health"),
                "/health/live": client.get("/health/live"),
                "/health/ready": client.get("/health/ready"),
                "/stats": client.get("/stats"),
                "/diagnostics": client.get("/diagnostics"),
                "/runtime/build/initialize": client.post("/runtime/build/initialize"),
                "/jobs": client.get("/jobs"),
                f"/jobs/{'0' * 32}": client.get(f"/jobs/{'0' * 32}"),
                f"/jobs/{'0' * 32}/cancel": client.post(f"/jobs/{'0' * 32}/cancel"),
                f"/jobs/{'0' * 32}/retry": client.post(f"/jobs/{'0' * 32}/retry"),
                "/jobs/build": client.post("/jobs/build"),
                "/jobs/rebuild": client.post("/jobs/rebuild"),
                "/artifacts": client.get("/artifacts"),
                "/knowledge-base/build": client.post("/knowledge-base/build"),
                "/knowledge-base/rebuild": client.post("/knowledge-base/rebuild"),
                "/v1/knowledge-base/build": client.post("/v1/knowledge-base/build"),
                "/v1/knowledge-base/rebuild": client.post("/v1/knowledge-base/rebuild"),
            }

        for path, response in responses.items():
            self.assertEqual(response.status_code, 404, path)
            if path.endswith("/cancel"):
                templated_path = "/jobs/{job_id}/cancel"
            elif path.endswith("/retry"):
                templated_path = "/jobs/{job_id}/retry"
            elif path.startswith("/jobs/"):
                templated_path = "/jobs/{job_id}"
            else:
                templated_path = path
            self.assertNotIn(templated_path, schema["paths"])

        self.assertIn("/v1/health", schema["paths"])
        self.assertIn("/v1/jobs", schema["paths"])
        self.assertIn("/v1/jobs/{job_id}/cancel", schema["paths"])
        self.assertIn("/v1/jobs/{job_id}/retry", schema["paths"])
        self.assertIn("/v1/jobs/build", schema["paths"])

