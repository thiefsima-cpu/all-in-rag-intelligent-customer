from __future__ import annotations

from types import SimpleNamespace

import tests.api_app_helpers as h

json = h.json
unittest = h.unittest
TestClient = h.TestClient
build_test_config = h.build_test_config
create_build_api_app = h.create_build_api_app
create_serving_api_app = h.create_serving_api_app
MAX_QUESTION_CHARS = h.MAX_QUESTION_CHARS
ErrorCode = h.ErrorCode
build_error_payload = h.build_error_payload
_API_TOKEN = h._API_TOKEN
_API_CONFIG = h._API_CONFIG
_client = h._client
_assert_error_response = h._assert_error_response
_assert_request_id = h._assert_request_id
_FakeApiSystem = h._FakeApiSystem
_FailedAnswerSystem = h._FailedAnswerSystem


class ApiSecurityTests(unittest.TestCase):
    """Security, auth, and sanitized error-contract API behavior."""

    def test_error_catalog_builds_the_new_breaking_contract(self) -> None:
        payload = build_error_payload(
            ErrorCode.VALIDATION_ERROR,
            request_id="catalog-test",
            details=[{"field": "body.question", "reason": "string_too_long"}],
        )

        self.assertEqual(
            payload,
            {
                "ok": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "The request is invalid.",
                    "details": [{"field": "body.question", "reason": "string_too_long"}],
                },
                "request_id": "catalog-test",
            },
        )

    def test_valid_client_request_id_is_preserved_on_success(self) -> None:
        app = create_serving_api_app(system=_FakeApiSystem())

        with TestClient(app) as client:
            response = client.get("/v1/health", headers={"X-Request-ID": "client.req:42"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-request-id"], "client.req:42")

    def test_missing_or_invalid_request_id_is_replaced(self) -> None:
        app = create_serving_api_app(system=_FakeApiSystem())

        with TestClient(app) as client:
            missing = client.get("/v1/health")
            invalid = client.get("/v1/health", headers={"X-Request-ID": "bad/id secret"})

        _assert_request_id(missing.headers["x-request-id"])
        _assert_request_id(invalid.headers["x-request-id"])
        self.assertNotEqual(invalid.headers["x-request-id"], "bad/id secret")

    def test_validation_error_does_not_echo_request_input(self) -> None:
        secret_question = "PRIVATE-QUESTION-" + "x" * MAX_QUESTION_CHARS
        app = create_serving_api_app(system=_FakeApiSystem())

        with _client(app) as client:
            response = client.post(
                "/v1/answers",
                json={"question": secret_question},
                headers={"X-Request-ID": "validation-42"},
            )

        payload = _assert_error_response(
            response,
            status_code=422,
            code="VALIDATION_ERROR",
            request_id="validation-42",
        )
        self.assertNotIn(secret_question, json.dumps(payload, ensure_ascii=False))
        self.assertEqual(
            payload["error"]["details"],
            [{"field": "body.question", "reason": "string_too_long"}],
        )

    def test_unknown_exception_returns_internal_error_without_raw_text(self) -> None:
        secret = "provider-secret-error-body"
        app = create_serving_api_app(system=_FakeApiSystem())

        @app.get("/_test/boom")
        def boom():
            raise RuntimeError(secret)

        with _client(app) as client:
            response = client.get("/_test/boom", headers={"X-Request-ID": "boom-42"})

        payload = _assert_error_response(
            response,
            status_code=500,
            code="INTERNAL_ERROR",
            request_id="boom-42",
        )
        self.assertNotIn(secret, json.dumps(payload))
        self.assertNotIn("RuntimeError", json.dumps(payload))

    def test_not_found_and_method_not_allowed_use_the_common_contract(self) -> None:
        app = create_serving_api_app(system=_FakeApiSystem())

        with _client(app) as client:
            missing = client.get("/does-not-exist")
            method = client.put("/v1/health")

        _assert_error_response(missing, status_code=404, code="NOT_FOUND")
        _assert_error_response(method, status_code=405, code="METHOD_NOT_ALLOWED")

    def test_openapi_uses_the_common_error_schema(self) -> None:
        config = build_test_config({"api": {"access_token": _API_TOKEN, "openapi_enabled": True}})
        app = create_serving_api_app(system=_FakeApiSystem(), config=config)

        with _client(app) as client:
            schema = client.get("/openapi.json").json()

        self.assertIn("ErrorResponseModel", schema["components"]["schemas"])
        validation_schema = schema["paths"]["/v1/answers"]["post"]["responses"]["422"]
        self.assertEqual(
            validation_schema["content"]["application/json"]["schema"]["$ref"],
            "#/components/schemas/ErrorResponseModel",
        )

    def test_failed_answer_becomes_typed_500_without_raw_exception(self) -> None:
        secret = "answer-provider-secret"
        system = _FailedAnswerSystem(secret)
        system.serving_runtime = SimpleNamespace(
            answer_workflow=SimpleNamespace(
                answer_workflow_copy=SimpleNamespace(answer_failed="CUSTOM_FAILED")
            )
        )
        app = create_serving_api_app(system=system)

        with _client(app) as client:
            response = client.post(
                "/v1/answers",
                json={"question": "safe question"},
                headers={"X-Request-ID": "answer-failed-42"},
            )

        payload = _assert_error_response(
            response,
            status_code=500,
            code="ANSWER_FAILED",
            request_id="answer-failed-42",
        )
        self.assertEqual(payload["error"]["message"], "CUSTOM_FAILED")
        self.assertNotIn(secret, json.dumps(payload))

    def test_openapi_security_metadata_clears_v1_health_and_keeps_debug_protected(self) -> None:
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

        self.assertEqual(schema["paths"]["/v1/health"]["get"]["security"], [])
        self.assertNotEqual(schema["paths"]["/v1/debug/answers"]["post"].get("security"), [])

    def test_docs_and_openapi_are_disabled_by_default(self) -> None:
        app = create_serving_api_app(system=_FakeApiSystem(), config=_API_CONFIG)

        with TestClient(app) as client:
            docs_response = client.get("/docs")
            redoc_response = client.get("/redoc")
            openapi_response = client.get("/openapi.json")

        self.assertEqual(docs_response.status_code, 404)
        self.assertEqual(redoc_response.status_code, 404)
        self.assertEqual(openapi_response.status_code, 404)

    def test_enabled_docs_and_openapi_require_credentials_by_default(self) -> None:
        config = build_test_config(
            {
                "api": {
                    "access_token": _API_TOKEN,
                    "docs_enabled": True,
                    "openapi_enabled": True,
                }
            }
        )
        app = create_serving_api_app(system=_FakeApiSystem(), config=config)

        with TestClient(app) as anonymous:
            docs_unauthorized = anonymous.get("/docs")
            openapi_unauthorized = anonymous.get("/openapi.json")
        with _client(app) as authenticated:
            docs_authorized = authenticated.get("/docs")
            openapi_authorized = authenticated.get("/openapi.json")

        self.assertEqual(docs_unauthorized.status_code, 401)
        self.assertEqual(openapi_unauthorized.status_code, 401)
        self.assertEqual(docs_authorized.status_code, 200)
        self.assertEqual(openapi_authorized.status_code, 200)

    def test_docs_and_openapi_can_be_made_public(self) -> None:
        config = build_test_config(
            {
                "api": {
                    "access_token": _API_TOKEN,
                    "docs_enabled": True,
                    "openapi_enabled": True,
                    "docs_public": True,
                    "openapi_public": True,
                }
            }
        )
        app = create_serving_api_app(system=_FakeApiSystem(), config=config)

        with TestClient(app) as client:
            docs_response = client.get("/docs")
            openapi_response = client.get("/openapi.json")

        self.assertEqual(docs_response.status_code, 200)
        self.assertEqual(openapi_response.status_code, 200)

    def test_openapi_security_metadata_only_clears_public_paths(self) -> None:
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

        self.assertEqual(schema["security"], [{"BearerAuth": []}, {"ApiKeyAuth": []}])
        self.assertEqual(schema["paths"]["/v1/health"]["get"]["security"], [])
        self.assertNotEqual(schema["paths"]["/v1/stats"]["get"].get("security"), [])

    def test_protected_routes_require_api_credentials(self) -> None:
        app = create_serving_api_app(system=_FakeApiSystem())

        with TestClient(app) as client:
            health_response = client.get("/v1/health")
            unauthorized_response = client.get("/v1/stats")
            invalid_response = client.get(
                "/v1/stats",
                headers={"Authorization": "Bearer wrong-token"},
            )
            api_key_response = client.get(
                "/v1/stats",
                headers={"X-API-Key": _API_TOKEN},
            )

        self.assertEqual(health_response.status_code, 200)
        _assert_error_response(unauthorized_response, status_code=401, code="UNAUTHORIZED")
        _assert_error_response(invalid_response, status_code=401, code="UNAUTHORIZED")
        self.assertEqual(
            unauthorized_response.headers["www-authenticate"],
            "Bearer",
        )
        self.assertEqual(api_key_response.status_code, 200)

    def test_build_job_audit_route_requires_api_credentials(self) -> None:
        app = create_build_api_app(system=_FakeApiSystem())

        with TestClient(app) as client:
            response = client.get(f"/v1/jobs/{'a' * 32}/events")

        _assert_error_response(response, status_code=401, code="UNAUTHORIZED")

    def test_authentication_fails_closed_when_token_is_not_configured(self) -> None:
        config = build_test_config({"api": {"auth_enabled": True, "access_token": ""}})
        app = create_serving_api_app(system=_FakeApiSystem(), config=config)

        with TestClient(app) as client:
            response = client.get("/v1/stats")

        _assert_error_response(response, status_code=503, code="SERVICE_MISCONFIGURED")

    def test_authentication_rejects_weak_configured_token(self) -> None:
        config = build_test_config({"api": {"auth_enabled": True, "access_token": "too-short"}})
        app = create_serving_api_app(system=_FakeApiSystem(), config=config)

        with TestClient(app) as client:
            response = client.get(
                "/v1/stats",
                headers={"Authorization": "Bearer too-short"},
            )

        _assert_error_response(response, status_code=503, code="SERVICE_MISCONFIGURED")

    def test_request_body_and_question_limits_are_enforced(self) -> None:
        system = _FakeApiSystem()
        system.system_ready = True
        body_limited_config = build_test_config(
            {
                "api": {
                    "access_token": _API_TOKEN,
                    "max_request_body_bytes": 1024,
                }
            }
        )
        body_limited_app = create_serving_api_app(
            system=system,
            config=body_limited_config,
        )
        field_limited_app = create_serving_api_app(system=_FakeApiSystem())

        with _client(body_limited_app) as client:
            oversized_body = client.post(
                "/v1/answers",
                json={"question": "x" * 2000},
            )
        with _client(field_limited_app) as client:
            oversized_question = client.post(
                "/v1/answers",
                json={"question": "x" * (MAX_QUESTION_CHARS + 1)},
            )
            blank_question = client.post(
                "/v1/answers",
                json={"question": "   "},
            )

        _assert_error_response(oversized_body, status_code=413, code="REQUEST_TOO_LARGE")
        _assert_error_response(
            oversized_question,
            status_code=422,
            code="VALIDATION_ERROR",
        )
        _assert_error_response(blank_question, status_code=422, code="VALIDATION_ERROR")

    def test_prometheus_metrics_endpoint_requires_credentials_by_default(self) -> None:
        app = create_serving_api_app(system=_FakeApiSystem(), config=_API_CONFIG)

        with TestClient(app) as anonymous:
            unauthorized = anonymous.get("/metrics")
        with _client(app) as authenticated:
            authorized = authenticated.get("/metrics")

        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(authorized.status_code, 200)
        self.assertIn("graphrag_queries_total", authorized.text)
        self.assertIn("graphrag_sse_executor_active", authorized.text)
        self.assertIn("graphrag_sse_executor_queued", authorized.text)
        self.assertIn("graphrag_sse_executor_rejected_total", authorized.text)
        self.assertTrue(authorized.headers["content-type"].startswith("text/plain"))

    def test_prometheus_metrics_endpoint_can_be_made_public(self) -> None:
        config = build_test_config(
            {
                "api": {"access_token": _API_TOKEN},
                "observability": {"prometheus_public": True},
            }
        )
        app = create_serving_api_app(system=_FakeApiSystem(), config=config)

        with TestClient(app) as client:
            response = client.get("/metrics")

        self.assertEqual(response.status_code, 200)
        self.assertIn("graphrag_queries_total", response.text)

    def test_prometheus_metrics_endpoint_can_be_disabled(self) -> None:
        config = build_test_config(
            {
                "api": {"access_token": _API_TOKEN},
                "observability": {"enable_prometheus": False},
            }
        )
        app = create_serving_api_app(system=_FakeApiSystem(), config=config)

        with _client(app) as client:
            response = client.get("/metrics")

        self.assertEqual(response.status_code, 404)
