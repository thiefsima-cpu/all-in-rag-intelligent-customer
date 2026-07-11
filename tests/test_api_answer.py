from __future__ import annotations

import tests.api_app_helpers as h

json = h.json
threading = h.threading
unittest = h.unittest
patch = h.patch
ValidationError = h.ValidationError
QuestionAnswerResponse = h.QuestionAnswerResponse
QuestionAnswerResult = h.QuestionAnswerResult
build_test_config = h.build_test_config
QueryTraceEvent = h.QueryTraceEvent
create_serving_api_app = h.create_serving_api_app
AnswerResponseModel = h.AnswerResponseModel
PublicAnswerPayloadModel = h.PublicAnswerPayloadModel
GraphRAGServingApiService = h.GraphRAGServingApiService
_API_TOKEN = h._API_TOKEN
_API_CONFIG = h._API_CONFIG
_client = h._client
_assert_error_response = h._assert_error_response
_observe_lifecycle_requests = h._observe_lifecycle_requests
_serving_race_config = h._serving_race_config
_answer_response = h._answer_response
_answer_payload = h._answer_payload
_payload_without_new_summary_fields = h._payload_without_new_summary_fields
_FakeApiSystem = h._FakeApiSystem
_PublicAnswerErrorSystem = h._PublicAnswerErrorSystem
_BlockingApiSystem = h._BlockingApiSystem
_ConcurrentAnswerApiSystem = h._ConcurrentAnswerApiSystem
_LifecycleRaceApiSystem = h._LifecycleRaceApiSystem


class ApiAnswerTests(unittest.TestCase):
    """HTTP answer payload, schema, admission, and answer lifecycle behavior."""

    def test_serving_answer_returns_409_when_artifacts_are_not_ready(self) -> None:
        system = _FakeApiSystem()
        app = create_serving_api_app(system=system)

        with _client(app) as client:
            response = client.post("/v1/answers", json={"question": "Can I cook tofu?"})

        _assert_error_response(response, status_code=409, code="SYSTEM_NOT_READY")
        self.assertEqual(system.initialize_serving_calls, 1)

    def test_answer_flow_uses_serving_api_surface(self) -> None:
        system = _FakeApiSystem()
        system.system_ready = True
        app = create_serving_api_app(system=system)

        with _client(app) as client:
            answer_response = client.post(
                "/v1/debug/answers",
                json={
                    "question": "Can I cook tofu?",
                    "stream": False,
                    "explain_routing": True,
                },
            )

        self.assertEqual(answer_response.status_code, 200)
        self.assertEqual(system.initialize_build_calls, 0)
        self.assertEqual(system.initialize_serving_calls, 1)
        self.assertEqual(system.answer_calls, [("Can I cook tofu?", False, True)])
        answer_payload = answer_response.json()["response"]
        self.assertEqual(answer_payload["summary"]["answer"], "answer:Can I cook tofu?")
        self.assertEqual(
            answer_payload["diagnostics"]["diagnostics"]["overall_bucket"],
            "ok",
        )
        self.assertEqual(answer_payload["summary"]["prompt_tokens"], 11)
        self.assertEqual(answer_payload["summary"]["total_tokens"], 18)

    def test_v1_answer_omits_traces_by_default(self) -> None:
        system = _FakeApiSystem()
        system.system_ready = True
        app = create_serving_api_app(system=system)

        with _client(app) as client:
            response = client.post("/v1/answers", json={"question": "Can I cook tofu?"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()["response"]
        self.assertEqual(payload["summary"]["answer"], "answer:Can I cook tofu?")
        self.assertEqual(set(payload["grounding"]), {"evidence_documents"})
        self.assertEqual(
            set(payload["grounding"]["evidence_documents"][0]),
            {
                "content",
                "recipe_name",
                "score",
                "source",
                "evidence_type",
                "matched_terms",
            },
        )
        self.assertEqual(payload["diagnostics"]["overall_bucket"], "ok")
        self.assertNotIn("analysis", payload["diagnostics"])
        self.assertNotIn("retrieval_outcome", payload["grounding"])
        self.assertNotIn("answer_context", payload["grounding"])
        self.assertNotIn("route_resolution", payload["grounding"])
        self.assertNotIn("traces", payload)

    def test_v1_debug_answer_includes_traces(self) -> None:
        system = _FakeApiSystem()
        system.system_ready = True
        app = create_serving_api_app(system=system)

        with _client(app) as client:
            response = client.post("/v1/debug/answers", json={"question": "Can I cook tofu?"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()["response"]
        self.assertEqual(
            payload["traces"]["generation_trace"]["token_usage_source"],
            "test",
        )

    def test_openapi_distinguishes_public_and_debug_answer_schemas(self) -> None:
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

        public_response_ref = schema["paths"]["/v1/answers"]["post"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]["$ref"]
        debug_response_ref = schema["paths"]["/v1/debug/answers"]["post"]["responses"]["200"][
            "content"
        ]["application/json"]["schema"]["$ref"]

        self.assertEqual(public_response_ref, "#/components/schemas/PublicAnswerResponseModel")
        self.assertEqual(debug_response_ref, "#/components/schemas/AnswerResponseModel")
        self.assertNotIn(
            "traces",
            schema["components"]["schemas"]["PublicAnswerPayloadModel"]["properties"],
        )
        self.assertEqual(
            schema["components"]["schemas"]["PublicAnswerPayloadModel"]["properties"]["grounding"][
                "$ref"
            ],
            "#/components/schemas/PublicAnswerGroundingModel",
        )
        self.assertEqual(
            schema["components"]["schemas"]["PublicAnswerPayloadModel"]["properties"][
                "diagnostics"
            ]["$ref"],
            "#/components/schemas/PublicAnswerDiagnosticsModel",
        )
        public_grounding_properties = schema["components"]["schemas"]["PublicAnswerGroundingModel"][
            "properties"
        ]
        self.assertEqual(set(public_grounding_properties), {"evidence_documents"})
        public_evidence_properties = schema["components"]["schemas"][
            "PublicEvidenceDocumentResponseModel"
        ]["properties"]
        self.assertEqual(
            set(public_evidence_properties),
            {
                "content",
                "recipe_name",
                "score",
                "source",
                "evidence_type",
                "matched_terms",
            },
        )
        public_diagnostics_properties = schema["components"]["schemas"][
            "PublicAnswerDiagnosticsModel"
        ]["properties"]
        self.assertNotIn("analysis", public_diagnostics_properties)
        self.assertIn("overall_bucket", public_diagnostics_properties)
        self.assertIn("traces", schema["components"]["schemas"]["AnswerPayloadModel"]["properties"])

    def test_public_answer_payload_model_rejects_debug_only_fields(self) -> None:
        payload = PublicAnswerPayloadModel.from_dto(
            _answer_response("Can I cook tofu?")
        ).model_dump()
        payload["grounding"]["route_resolution"] = {"metadata": {"internal": True}}
        payload["diagnostics"]["analysis"] = {"recommended_strategy": "hybrid_traditional"}

        with self.assertRaises(ValidationError) as context:
            PublicAnswerPayloadModel.model_validate(payload)

        locations = {tuple(error["loc"]) for error in context.exception.errors()}
        self.assertIn(("grounding", "route_resolution"), locations)
        self.assertIn(("diagnostics", "analysis"), locations)

    def test_answer_trace_error_fields_are_sanitized_on_success(self) -> None:
        secret = "private-answer-trace-error"
        app = create_serving_api_app(system=_PublicAnswerErrorSystem(secret))

        with _client(app) as client:
            response = client.post("/v1/debug/answers", json={"question": "safe question"})

        self.assertEqual(response.status_code, 200)
        serialized = json.dumps(response.json(), ensure_ascii=False)
        self.assertNotIn(secret, serialized)
        self.assertIn("ANSWER_FAILED", serialized)

    def test_answer_response_model_accepts_runtime_shaped_payload(self) -> None:
        payload = _answer_payload("Can I cook tofu?")

        model = AnswerResponseModel.model_validate({"response": payload})

        dumped = model.model_dump()
        self.assertEqual(dumped["response"]["summary"]["answer"], "answer:Can I cook tofu?")
        self.assertEqual(dumped["response"]["summary"]["prompt_tokens"], 11)
        self.assertEqual(
            dumped["response"]["grounding"]["retrieval_outcome"]["evidence_documents"][0][
                "recipe_name"
            ],
            "mapo tofu",
        )
        self.assertEqual(
            dumped["response"]["diagnostics"]["diagnostics"]["overall_bucket"],
            "ok",
        )
        self.assertEqual(
            dumped["response"]["traces"]["generation_trace"]["token_usage_source"],
            "test",
        )

    def test_answer_response_model_rejects_unknown_stable_fields(self) -> None:
        accepted_locations: list[tuple[str, ...]] = []

        def check_rejects_extra_field(payload: dict, expected_location: tuple[str, ...]) -> None:
            try:
                AnswerResponseModel.model_validate({"response": payload})
            except ValidationError as exc:
                self.assertIn(
                    expected_location,
                    {tuple(error["loc"]) for error in exc.errors()},
                )
            else:
                accepted_locations.append(expected_location)

        payload = _payload_without_new_summary_fields("Can I cook tofu?")
        payload["summary"]["unexpected"] = True

        check_rejects_extra_field(payload, ("response", "summary", "unexpected"))

        payload = _payload_without_new_summary_fields("Can I cook tofu?")
        payload["traces"]["generation_trace"]["unexpected"] = True

        check_rejects_extra_field(payload, ("response", "traces", "generation_trace", "unexpected"))

        payload = _payload_without_new_summary_fields("Can I cook tofu?")
        payload["diagnostics"]["diagnostics"]["explained"] = True

        check_rejects_extra_field(payload, ("response", "diagnostics", "diagnostics", "explained"))
        self.assertEqual([], accepted_locations)

    def test_answer_response_schema_exposes_summary_token_fields(self) -> None:
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

        summary_schema = schema["components"]["schemas"]["AnswerSummaryModel"]
        self.assertIn("prompt_tokens", summary_schema["properties"])
        self.assertIn("completion_tokens", summary_schema["properties"])
        self.assertIn("total_tokens", summary_schema["properties"])
        self.assertIn("estimated_cost_usd", summary_schema["properties"])
        self.assertIn("token_usage_source", summary_schema["properties"])

    def test_answer_http_and_sse_paths_do_not_call_application_to_dict(self) -> None:
        class _TypedResponseApiSystem(_FakeApiSystem):
            def answer_question_response(
                self,
                question: str,
                *,
                stream: bool = False,
                explain_routing: bool = False,
                message_callback=None,
                chunk_callback=None,
                control=None,
            ) -> QuestionAnswerResponse:
                del control
                if stream:
                    if message_callback:
                        message_callback("Running query routing...")
                    if chunk_callback:
                        chunk_callback("chunk-1")
                self.answer_calls.append((question, stream, explain_routing))
                return QuestionAnswerResult(
                    answer=f"answer:{question}",
                    analysis=None,
                    trace_event=QueryTraceEvent(query=question),
                ).to_response()

        system = _TypedResponseApiSystem()
        system.system_ready = True
        system.serving_initialized = True
        app = create_serving_api_app(system=system, config=_API_CONFIG)

        with patch.object(
            QuestionAnswerResponse,
            "to_dict",
            side_effect=AssertionError("application response serialized internally"),
        ):
            with _client(app) as client:
                answer_response = client.post("/v1/answers", json={"question": "tofu"})
                stream_response = client.post("/v1/answers/stream", json={"question": "tofu"})

        self.assertEqual(answer_response.status_code, 200)
        self.assertEqual(answer_response.json()["response"]["summary"]["answer"], "answer:tofu")
        self.assertEqual(stream_response.status_code, 200)
        self.assertIn("event: result", stream_response.text)

    def test_serving_stats_do_not_block_while_answer_is_in_flight(self) -> None:
        system = _BlockingApiSystem()
        service = GraphRAGServingApiService(system=system)
        answer_done = threading.Event()
        stats_done = threading.Event()

        def run_answer() -> None:
            try:
                service.answer_question(question="slow tofu")
            finally:
                answer_done.set()

        def run_stats() -> None:
            service.collect_stats()
            stats_done.set()

        answer_thread = threading.Thread(target=run_answer)
        stats_thread = threading.Thread(target=run_stats)
        answer_thread.start()
        self.assertTrue(system.answer_started.wait(timeout=1.0))

        stats_thread.start()
        self.assertTrue(
            stats_done.wait(timeout=0.5),
            "stats collection should not wait for the in-flight answer lock",
        )
        self.assertFalse(answer_done.is_set())

        system.release_answer.set()
        answer_thread.join(timeout=1.0)
        stats_thread.join(timeout=1.0)
        self.assertTrue(answer_done.is_set())

    def test_serving_answers_can_run_concurrently(self) -> None:
        system = _ConcurrentAnswerApiSystem()
        service = GraphRAGServingApiService(system=system)
        first_done = threading.Event()
        second_done = threading.Event()

        def run_first() -> None:
            try:
                service.answer_question(question="first tofu")
            finally:
                first_done.set()

        def run_second() -> None:
            try:
                service.answer_question(question="second tofu")
            finally:
                second_done.set()

        first_thread = threading.Thread(target=run_first)
        second_thread = threading.Thread(target=run_second)
        first_thread.start()
        second_thread.start()

        self.assertTrue(
            system.both_answers_started.wait(timeout=0.5),
            "independent answer requests should not serialize behind a global answer lock",
        )
        self.assertFalse(first_done.is_set())
        self.assertFalse(second_done.is_set())

        system.release_answers.set()
        first_thread.join(timeout=1.0)
        second_thread.join(timeout=1.0)
        self.assertTrue(first_done.is_set())
        self.assertTrue(second_done.is_set())
        self.assertEqual(len(system.answer_calls), 2)

    def test_serving_answers_return_429_when_admission_limit_is_full(self) -> None:
        system = _BlockingApiSystem()
        config = build_test_config(
            {
                "api": {
                    "access_token": _API_TOKEN,
                    "max_concurrent_answers": 1,
                    "answer_acquire_timeout_seconds": 0.01,
                }
            }
        )
        app = create_serving_api_app(system=system, config=config)

        with _client(app) as client:
            service = app.state.api_service
            first_done = threading.Event()

            def run_first() -> None:
                try:
                    service.answer_question(question="first tofu")
                finally:
                    first_done.set()

            first_thread = threading.Thread(target=run_first)
            first_thread.start()
            self.assertTrue(system.answer_started.wait(timeout=1.0))

            response = client.post(
                "/v1/answers",
                json={
                    "question": "second tofu",
                    "stream": False,
                    "explain_routing": True,
                },
            )

            system.release_answer.set()
            first_thread.join(timeout=1.0)
            self.assertTrue(first_done.is_set())

        _assert_error_response(response, status_code=429, code="RATE_LIMITED")

    def test_pending_refresh_blocks_new_answers_until_active_answer_finishes(self) -> None:
        system = _LifecycleRaceApiSystem()
        service = GraphRAGServingApiService(system=system, config=_serving_race_config())
        lifecycle_requested = _observe_lifecycle_requests(service)
        first_done = threading.Event()
        refresh_done = threading.Event()
        second_done = threading.Event()
        errors: list[BaseException] = []

        def run_first_answer() -> None:
            try:
                service.answer_question(question="first tofu")
            except BaseException as exc:
                errors.append(exc)
            finally:
                first_done.set()

        def run_refresh() -> None:
            try:
                service.refresh_serving_runtime()
            except BaseException as exc:
                errors.append(exc)
            finally:
                refresh_done.set()

        def run_second_answer() -> None:
            try:
                service.answer_question(question="second tofu")
            except BaseException as exc:
                errors.append(exc)
            finally:
                second_done.set()

        first_thread = threading.Thread(target=run_first_answer)
        refresh_thread = threading.Thread(target=run_refresh)
        second_thread = threading.Thread(target=run_second_answer)
        first_thread.start()
        self.assertTrue(system.first_answer_started.wait(timeout=1.0))

        refresh_thread.start()
        self.assertTrue(lifecycle_requested.wait(timeout=1.0))

        second_thread.start()
        self.assertFalse(
            system.second_answer_started.wait(timeout=0.1),
            "new answers must not enter while a refresh is waiting for lifecycle access",
        )
        self.assertFalse(system.refresh_started.is_set())

        system.release_answers.set()
        first_thread.join(timeout=1.0)
        refresh_thread.join(timeout=1.0)
        second_thread.join(timeout=1.0)

        self.assertTrue(first_done.is_set())
        self.assertTrue(refresh_done.is_set())
        self.assertTrue(second_done.is_set())
        self.assertTrue(system.refresh_started.is_set())
        self.assertEqual(system.refresh_calls, 1)
        self.assertEqual(errors, [])

    def test_pending_shutdown_blocks_new_answers_until_active_answer_finishes(self) -> None:
        system = _LifecycleRaceApiSystem()
        service = GraphRAGServingApiService(system=system, config=_serving_race_config())
        lifecycle_requested = _observe_lifecycle_requests(service)
        first_done = threading.Event()
        shutdown_done = threading.Event()
        second_done = threading.Event()
        errors: list[BaseException] = []

        def run_first_answer() -> None:
            try:
                service.answer_question(question="first tofu")
            except BaseException as exc:
                errors.append(exc)
            finally:
                first_done.set()

        def run_shutdown() -> None:
            try:
                service.shutdown()
            except BaseException as exc:
                errors.append(exc)
            finally:
                shutdown_done.set()

        def run_second_answer() -> None:
            try:
                service.answer_question(question="second tofu")
            except BaseException:
                pass
            finally:
                second_done.set()

        first_thread = threading.Thread(target=run_first_answer)
        shutdown_thread = threading.Thread(target=run_shutdown)
        second_thread = threading.Thread(target=run_second_answer)
        first_thread.start()
        self.assertTrue(system.first_answer_started.wait(timeout=1.0))

        shutdown_thread.start()
        self.assertTrue(lifecycle_requested.wait(timeout=1.0))

        second_thread.start()
        self.assertFalse(
            system.second_answer_started.wait(timeout=0.1),
            "new answers must not enter while shutdown is waiting for lifecycle access",
        )

        system.release_answers.set()
        first_thread.join(timeout=1.0)
        shutdown_thread.join(timeout=1.0)
        second_thread.join(timeout=1.0)

        self.assertTrue(first_done.is_set())
        self.assertTrue(shutdown_done.is_set())
        self.assertTrue(second_done.is_set())
        self.assertTrue(system.close_started.is_set())
        self.assertFalse(system.second_answer_started.is_set())
        self.assertEqual(errors, [])
