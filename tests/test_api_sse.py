from __future__ import annotations

import tests.api_app_helpers as h

json = h.json
threading = h.threading
time = h.time
unittest = h.unittest
build_test_config = h.build_test_config
create_serving_api_app = h.create_serving_api_app
AnswerStreamEventType = h.AnswerStreamEventType
GraphRAGServingApiService = h.GraphRAGServingApiService
_API_TOKEN = h._API_TOKEN
_client = h._client
_assert_error_response = h._assert_error_response
_parse_sse_events = h._parse_sse_events
_observe_lifecycle_requests = h._observe_lifecycle_requests
_serving_race_config = h._serving_race_config
_FakeApiSystem = h._FakeApiSystem
_FailedAnswerSystem = h._FailedAnswerSystem
_BlockingApiSystem = h._BlockingApiSystem
_ChunkFloodApiSystem = h._ChunkFloodApiSystem
_StreamingControlCapturingSystem = h._StreamingControlCapturingSystem
_BlockingStreamApiSystem = h._BlockingStreamApiSystem


class ApiSseTests(unittest.TestCase):
    """SSE answer stream events, cancellation, limits, and shutdown behavior."""

    def test_sse_error_uses_common_contract_and_request_id(self) -> None:
        secret = "stream-provider-secret"
        app = create_serving_api_app(system=_FailedAnswerSystem(secret))

        with _client(app) as client:
            with client.stream(
                "POST",
                "/v1/answers/stream",
                json={"question": "safe question"},
                headers={"X-Request-ID": "stream-failed-42"},
            ) as response:
                body = "".join(response.iter_text())

        self.assertEqual(response.status_code, 200)
        self.assertIn("event: error", body)
        self.assertIn('"code": "ANSWER_FAILED"', body)
        self.assertIn('"request_id": "stream-failed-42"', body)
        self.assertNotIn("error_type", body)
        self.assertNotIn(secret, body)
        self.assertIn("event: done", body)

    def test_stream_preflight_failure_uses_http_error_contract(self) -> None:
        app = create_serving_api_app(system=_FakeApiSystem())

        with _client(app) as client:
            response = client.post(
                "/v1/answers/stream",
                json={"question": "safe question"},
            )

        _assert_error_response(response, status_code=409, code="SYSTEM_NOT_READY")

    def test_v1_answer_stream_result_omits_traces_by_default(self) -> None:
        system = _FakeApiSystem()
        system.system_ready = True
        app = create_serving_api_app(system=system)

        with _client(app) as client:
            with client.stream(
                "POST",
                "/v1/answers/stream",
                json={"question": "Can I cook tofu?"},
            ) as response:
                body = "".join(response.iter_text())

        self.assertEqual(response.status_code, 200)
        result_payload = _parse_sse_events(body)["result"][0]["response"]
        self.assertEqual(result_payload["summary"]["answer"], "answer:Can I cook tofu?")
        self.assertEqual(set(result_payload["grounding"]), {"evidence_documents"})
        self.assertEqual(result_payload["diagnostics"]["overall_bucket"], "ok")
        self.assertNotIn("analysis", result_payload["diagnostics"])
        self.assertNotIn("retrieval_outcome", result_payload["grounding"])
        self.assertNotIn("answer_context", result_payload["grounding"])
        self.assertNotIn("route_resolution", result_payload["grounding"])
        self.assertNotIn("traces", result_payload)

    def test_v1_debug_answer_stream_result_includes_traces(self) -> None:
        system = _FakeApiSystem()
        system.system_ready = True
        app = create_serving_api_app(system=system)

        with _client(app) as client:
            with client.stream(
                "POST",
                "/v1/debug/answers/stream",
                json={"question": "Can I cook tofu?"},
            ) as response:
                body = "".join(response.iter_text())

        self.assertEqual(response.status_code, 200)
        result_payload = _parse_sse_events(body)["result"][0]["response"]
        self.assertEqual(
            result_payload["traces"]["generation_trace"]["token_usage_source"],
            "test",
        )

    def test_answer_stream_uses_sse_surface(self) -> None:
        system = _FakeApiSystem()
        system.system_ready = True
        app = create_serving_api_app(system=system)

        with _client(app) as client:
            with client.stream(
                "POST",
                "/v1/answers",
                json={
                    "question": "Can I cook tofu?",
                    "stream": True,
                    "explain_routing": True,
                },
            ) as answer_response:
                body = "".join(answer_response.iter_text())

        self.assertEqual(answer_response.status_code, 200)
        self.assertTrue(answer_response.headers["content-type"].startswith("text/event-stream"))
        self.assertEqual(system.initialize_build_calls, 0)
        self.assertEqual(system.initialize_serving_calls, 1)
        self.assertEqual(system.answer_calls, [("Can I cook tofu?", True, True)])

        events: dict[str, list[dict]] = {}
        for block in body.strip().split("\n\n"):
            lines = [line for line in block.splitlines() if line]
            event_name = ""
            data = None
            for line in lines:
                if line.startswith("event: "):
                    event_name = line[len("event: ") :]
                elif line.startswith("data: "):
                    data = json.loads(line[len("data: ") :])
            if event_name:
                events.setdefault(event_name, []).append(data)

        self.assertEqual(events["message"][0]["message"], "Running query routing...")
        self.assertEqual(events["chunk"][0]["content"], "chunk-1")
        self.assertEqual(events["chunk"][1]["content"], "chunk-2")
        self.assertEqual(
            events["result"][0]["response"]["summary"]["answer"],
            "answer:Can I cook tofu?",
        )
        result_payload = events["result"][0]["response"]
        self.assertEqual(result_payload["summary"]["prompt_tokens"], 11)
        self.assertEqual(result_payload["diagnostics"]["overall_bucket"], "ok")
        self.assertNotIn("traces", result_payload)
        self.assertEqual(events["done"][0]["ok"], True)

    def test_explicit_answer_stream_route_uses_sse_surface(self) -> None:
        system = _FakeApiSystem()
        system.system_ready = True
        config = build_test_config(
            {
                "api": {
                    "access_token": _API_TOKEN,
                    "openapi_enabled": True,
                }
            }
        )
        app = create_serving_api_app(system=system, config=config)

        with _client(app) as client:
            with client.stream(
                "POST",
                "/v1/answers/stream",
                json={
                    "question": "Explain mapo tofu",
                    "explain_routing": False,
                },
            ) as answer_response:
                body = "".join(answer_response.iter_text())

            openapi_response = client.get("/openapi.json")

        self.assertEqual(answer_response.status_code, 200)
        self.assertTrue(answer_response.headers["content-type"].startswith("text/event-stream"))
        self.assertEqual(system.answer_calls, [("Explain mapo tofu", True, False)])
        self.assertIn("event: result", body)

        schema = openapi_response.json()
        self.assertIn("/v1/answers/stream", schema["paths"])
        schemas = schema["components"]["schemas"]
        self.assertIn("GenerationSnapshotResponseModel", schemas)
        self.assertIn("QueryTraceEventResponseModel", schemas)
        generation_schema = schemas["GenerationSnapshotResponseModel"]
        self.assertIn("token_usage_source", generation_schema["properties"])
        token_usage_schema = generation_schema["properties"]["token_usage_source"]
        self.assertEqual(token_usage_schema["type"], "string")
        self.assertEqual(token_usage_schema["default"], "")
        trace_event_schema = schemas["QueryTraceEventResponseModel"]
        self.assertIn("diagnostics", trace_event_schema["properties"])
        self.assertEqual(
            trace_event_schema["properties"]["diagnostics"]["$ref"],
            "#/components/schemas/QueryDiagnosticsResponseModel",
        )
        stream_post = schema["paths"]["/v1/answers/stream"]["post"]
        self.assertEqual(
            stream_post["responses"]["200"]["content"].keys(),
            {"text/event-stream"},
        )

    def test_serving_service_uses_configured_stream_limits(self) -> None:
        system = _FakeApiSystem()
        config = build_test_config(
            {
                "api": {
                    "access_token": _API_TOKEN,
                    "stream_executor_max_workers": 2,
                    "stream_queue_max_size": 7,
                }
            }
        )
        service = GraphRAGServingApiService(system=system, config=config)

        self.assertEqual(service._stream_executor_max_workers, 2)
        self.assertEqual(service._stream_queue_max_size, 7)

    def test_serving_streams_emit_error_events_when_admission_limit_is_full(self) -> None:
        system = _BlockingApiSystem()
        config = build_test_config(
            {
                "api": {
                    "access_token": _API_TOKEN,
                    "max_concurrent_answers": 1,
                    "answer_acquire_timeout_seconds": 0.01,
                    "stream_executor_max_workers": 2,
                    "stream_queue_max_size": 4,
                }
            }
        )
        app = create_serving_api_app(system=system, config=config)

        with _client(app) as client:
            service = app.state.api_service
            first_done = threading.Event()

            def run_first() -> None:
                try:
                    service.answer_question(question="busy tofu")
                finally:
                    first_done.set()

            first_thread = threading.Thread(target=run_first)
            first_thread.start()
            self.assertTrue(system.answer_started.wait(timeout=1.0))

            with client.stream(
                "POST",
                "/v1/answers/stream",
                json={
                    "question": "blocked tofu",
                    "explain_routing": True,
                },
            ) as response:
                body = "".join(response.iter_text())

            system.release_answer.set()
            first_thread.join(timeout=1.0)
            self.assertTrue(first_done.is_set())

        self.assertEqual(response.status_code, 200)
        self.assertIn("event: error", body)
        self.assertIn('"code": "RATE_LIMITED"', body)
        self.assertIn(f'"request_id": "{response.headers["x-request-id"]}"', body)
        self.assertNotIn("error_type", body)
        self.assertIn("event: done", body)

    def test_closing_stream_consumer_stops_background_answer_runner(self) -> None:
        system = _ChunkFloodApiSystem()
        service = GraphRAGServingApiService(system=system)
        events = service.stream_answer_question_events(question="flooded tofu")

        first_event = next(events)
        self.assertEqual(first_event.event, AnswerStreamEventType.message)

        events.close()

        self.assertTrue(
            system.answer_finished.wait(timeout=1.0),
            "closing the SSE consumer should let the background stream runner exit",
        )

    def test_closing_stream_consumer_cancels_answer_request_control(self) -> None:
        system = _StreamingControlCapturingSystem()
        service = GraphRAGServingApiService(system=system)
        events = service.stream_answer_question_events(question="slow stream")

        first_event = next(events)
        self.assertEqual(first_event.event, AnswerStreamEventType.chunk)
        self.assertTrue(system.answer_started.wait(timeout=1.0))

        events.close()

        self.assertTrue(system.answer_finished.wait(timeout=1.0))
        self.assertIsNotNone(system.last_control)
        self.assertTrue(system.last_control.cancelled)
        self.assertEqual(system.last_control.reason, "stream_consumer_closed")

    def test_closing_stream_consumer_allows_pending_shutdown_to_complete(self) -> None:
        system = _ChunkFloodApiSystem()
        service = GraphRAGServingApiService(system=system, config=_serving_race_config())
        lifecycle_requested = _observe_lifecycle_requests(service)
        events = service.stream_answer_question_events(question="flooded tofu")
        first_event = next(events)
        shutdown_done = threading.Event()
        errors: list[BaseException] = []

        def run_shutdown() -> None:
            try:
                service.shutdown()
            except BaseException as exc:
                errors.append(exc)
            finally:
                shutdown_done.set()

        self.assertEqual(first_event.event, AnswerStreamEventType.message)
        shutdown_thread = threading.Thread(target=run_shutdown)
        shutdown_thread.start()
        self.assertTrue(lifecycle_requested.wait(timeout=1.0))
        self.assertFalse(shutdown_done.wait(timeout=0.1))

        events.close()

        shutdown_thread.join(timeout=1.0)
        self.assertTrue(system.answer_finished.wait(timeout=1.0))
        self.assertTrue(shutdown_done.is_set())
        self.assertEqual(system.close_calls, 1)
        self.assertEqual(errors, [])

    def test_shutdown_canceled_queued_sse_runner_finishes_consumer(self) -> None:
        system = _BlockingStreamApiSystem()
        config = build_test_config(
            {
                "api": {
                    "access_token": _API_TOKEN,
                    "serving_hot_refresh_enabled": False,
                    "stream_executor_max_workers": 1,
                    "stream_queue_max_size": 4,
                }
            }
        )
        service = GraphRAGServingApiService(system=system, config=config)
        first_events = service.stream_answer_question_events(question="first stream")
        first_event = next(first_events)
        second_events = service.stream_answer_question_events(question="second stream")
        second_done = threading.Event()
        shutdown_done = threading.Event()
        second_seen = []
        errors: list[BaseException] = []

        def read_second_stream() -> None:
            try:
                second_seen.extend(second_events)
            except BaseException as exc:
                errors.append(exc)
            finally:
                second_done.set()

        def run_shutdown() -> None:
            try:
                service.shutdown()
            except BaseException as exc:
                errors.append(exc)
            finally:
                shutdown_done.set()

        self.assertEqual(first_event.event, AnswerStreamEventType.message)
        self.assertTrue(system.first_stream_started.wait(timeout=1.0))
        second_thread = threading.Thread(target=read_second_stream, daemon=True)
        second_thread.start()
        time.sleep(0.05)
        self.assertFalse(system.second_stream_started.is_set())

        shutdown_thread = threading.Thread(target=run_shutdown)
        shutdown_thread.start()
        system.release_streams.set()
        shutdown_thread.join(timeout=1.0)
        first_events.close()

        self.assertTrue(shutdown_done.is_set())
        self.assertTrue(
            second_done.wait(timeout=1.0),
            "SSE consumers should receive a terminal event when shutdown cancels a queued runner",
        )
        self.assertEqual(
            [event.event for event in second_seen],
            [AnswerStreamEventType.error, AnswerStreamEventType.done],
        )
        self.assertFalse(system.second_stream_started.is_set())
        self.assertEqual(errors, [])

    def test_stream_answer_service_emits_typed_events(self) -> None:
        system = _FakeApiSystem()
        system.system_ready = True
        system.serving_initialized = True
        service = GraphRAGServingApiService(system=system)

        events = list(
            service.stream_answer_question_events(
                question="Typed stream",
                explain_routing=True,
            )
        )

        self.assertEqual(
            [event.event for event in events],
            [
                AnswerStreamEventType.message,
                AnswerStreamEventType.chunk,
                AnswerStreamEventType.chunk,
                AnswerStreamEventType.result,
                AnswerStreamEventType.done,
            ],
        )
        self.assertEqual(events[0].data.message, "Running query routing...")
        self.assertEqual(events[1].data.content, "chunk-1")
        self.assertEqual(events[3].data.response.summary.answer, "answer:Typed stream")
        self.assertTrue(events[4].data.ok)

