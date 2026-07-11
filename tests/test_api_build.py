from __future__ import annotations

import os

import tests.api_app_helpers as h
from rag_modules.runtime.build_jobs import ExternalBuildJobQueueRunner

json = h.json
tempfile = h.tempfile
threading = h.threading
unittest = h.unittest
Path = h.Path
TestClient = h.TestClient
build_test_config = h.build_test_config
create_build_api_app = h.create_build_api_app
ARTIFACT_HEALTH_MISSING = h.ARTIFACT_HEALTH_MISSING
InProcessBuildJobRunner = h.InProcessBuildJobRunner
_API_TOKEN = h._API_TOKEN
_client = h._client
_assert_error_response = h._assert_error_response
_wait_for_job_status = h._wait_for_job_status
_wait_for_service_job_status = h._wait_for_service_job_status
_FakeApiSystem = h._FakeApiSystem
_BlockingBuildApiSystem = h._BlockingBuildApiSystem
_FailingBuildApiSystem = h._FailingBuildApiSystem
_FailOnceBuildApiSystem = h._FailOnceBuildApiSystem


class ApiBuildTests(unittest.TestCase):
    """Build API job, runtime, idempotency, and diagnostics behavior."""

    def test_build_app_default_test_config_does_not_create_checkout_storage(self) -> None:
        previous_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                os.chdir(temp_dir)

                create_build_api_app(system=_FakeApiSystem())

                self.assertFalse((Path(temp_dir) / "storage" / "indexes").exists())
            finally:
                os.chdir(previous_cwd)

    def test_build_readiness_requires_initialized_build_runtime(self) -> None:
        system = _FakeApiSystem()
        app = create_build_api_app(system=system)

        with TestClient(app) as client:
            unready_response = client.get("/v1/health/ready")
            system.build_initialized = True
            ready_response = client.get("/v1/health/ready")

        self.assertEqual(unready_response.status_code, 503)
        self.assertEqual(ready_response.status_code, 200)

    def test_build_health_surface_reports_runtime_state(self) -> None:
        app = create_build_api_app(system=_FakeApiSystem())

        with _client(app) as client:
            response = client.get("/v1/health")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertFalse(payload["build_initialized"])
        self.assertEqual(payload["manifest_health"], ARTIFACT_HEALTH_MISSING)

    def test_build_diagnostics_include_safe_build_job_store_warning_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = build_test_config(
                {
                    "api": {"access_token": _API_TOKEN},
                    "storage": {
                        "artifact_manifest_path": str(root / "manifest.json"),
                        "build_job_store_path": str(root / "jobs.json"),
                    },
                }
            )
            system = _FakeApiSystem()
            system.config = config
            repository_dir = root / "jobs.d" / "jobs"
            repository_dir.mkdir(parents=True)
            (root / "jobs.d" / "metadata.json").write_text(
                json.dumps({"schema_version": 3}),
                encoding="utf-8",
            )
            (repository_dir / f"{'6' * 32}.json").write_text(
                "{broken secret-diagnostics-value",
                encoding="utf-8",
            )
            app = create_build_api_app(system=system, config=config)

            with _client(app) as client:
                response = client.get("/v1/diagnostics")

        self.assertEqual(response.status_code, 200)
        payload = response.json()["diagnostics"]["build_job_store"]
        dumped = json.dumps(response.json(), ensure_ascii=False)
        self.assertGreaterEqual(payload["warning_count"], 1)
        self.assertIn("BUILD_JOB_STORE_CORRUPT_RECORD", payload["warning_codes"])
        self.assertNotIn("secret-diagnostics-value", dumped)

    def test_build_diagnostics_include_corrupt_idempotency_warning_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = build_test_config(
                {
                    "api": {"access_token": _API_TOKEN},
                    "storage": {
                        "artifact_manifest_path": str(root / "manifest.json"),
                        "build_job_store_path": str(root / "jobs.json"),
                    },
                }
            )
            system = _FakeApiSystem()
            system.config = config
            idempotency_dir = root / "jobs.d" / "idempotency"
            idempotency_dir.mkdir(parents=True)
            (root / "jobs.d" / "metadata.json").write_text(
                json.dumps({"schema_version": 3}),
                encoding="utf-8",
            )
            (idempotency_dir / "bad-index.json").write_text(
                '["secret-idempotency-value"]',
                encoding="utf-8",
            )
            app = create_build_api_app(system=system, config=config)

            with _client(app) as client:
                response = client.get("/v1/diagnostics")

        self.assertEqual(response.status_code, 200)
        payload = response.json()["diagnostics"]["build_job_store"]
        dumped = json.dumps(response.json(), ensure_ascii=False)
        self.assertGreaterEqual(payload["warning_count"], 1)
        self.assertIn("BUILD_JOB_STORE_CORRUPT_IDEMPOTENCY", payload["warning_codes"])
        self.assertNotIn("secret-idempotency-value", dumped)

    def test_build_jobs_skip_invalid_job_records_instead_of_returning_500(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = build_test_config(
                {
                    "api": {"access_token": _API_TOKEN},
                    "storage": {
                        "artifact_manifest_path": str(root / "manifest.json"),
                        "build_job_store_path": str(root / "jobs.json"),
                    },
                }
            )
            system = _FakeApiSystem()
            system.config = config
            jobs_dir = root / "jobs.d" / "jobs"
            jobs_dir.mkdir(parents=True)
            (root / "jobs.d" / "metadata.json").write_text(
                json.dumps({"schema_version": 3}),
                encoding="utf-8",
            )
            (jobs_dir / f"{'9' * 32}.json").write_text(
                json.dumps(
                    {
                        "job_id": "9" * 32,
                        "request_id": "secret-invalid-job",
                        "job_type": "build",
                        "status": "not-a-status",
                        "created_at": "2026-06-29T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )
            app = create_build_api_app(system=system, config=config)

            with TestClient(
                app,
                headers={"Authorization": f"Bearer {_API_TOKEN}"},
                raise_server_exceptions=False,
            ) as client:
                jobs_response = client.get("/v1/jobs")
                diagnostics_response = client.get("/v1/diagnostics")

        self.assertEqual(jobs_response.status_code, 200)
        self.assertEqual(jobs_response.json()["jobs"], [])
        payload = diagnostics_response.json()["diagnostics"]["build_job_store"]
        dumped = json.dumps(
            {"jobs": jobs_response.json(), "diagnostics": diagnostics_response.json()},
            ensure_ascii=False,
        )
        self.assertIn("BUILD_JOB_STORE_CORRUPT_RECORD", payload["warning_codes"])
        self.assertNotIn("secret-invalid-job", dumped)

    def test_build_flow_uses_build_api_surface(self) -> None:
        system = _FakeApiSystem()
        app = create_build_api_app(system=system)

        with _client(app) as client:
            build_response = client.post("/v1/jobs/build")
            job_payload = build_response.json()["job"]
            finished_job = _wait_for_job_status(
                client,
                job_payload["job_id"],
                "succeeded",
            )

        self.assertEqual(build_response.status_code, 202)
        self.assertEqual(system.initialize_build_calls, 1)
        self.assertEqual(system.build_calls, 1)
        self.assertEqual(system.initialize_serving_calls, 0)
        self.assertEqual(finished_job["job_type"], "build")
        self.assertEqual(finished_job["result"]["message"], "Knowledge base build completed.")

    def test_build_jobs_surface_lists_and_reads_jobs(self) -> None:
        system = _FakeApiSystem()
        app = create_build_api_app(system=system)

        with _client(app) as client:
            build_response = client.post("/v1/jobs/build")
            build_job = build_response.json()["job"]
            finished_job = _wait_for_job_status(client, build_job["job_id"], "succeeded")
            list_response = client.get("/v1/jobs")
            detail_response = client.get(f"/v1/jobs/{build_job['job_id']}")

        self.assertEqual(build_response.status_code, 202)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.json()["job"]["job_id"], build_job["job_id"])
        self.assertEqual(detail_response.json()["job"]["status"], "succeeded")
        self.assertEqual(list_response.json()["jobs"][0]["job_id"], build_job["job_id"])
        self.assertEqual(finished_job["result"]["message"], "Knowledge base build completed.")

    def test_build_jobs_surface_paginates_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_test_config(
                {
                    "api": {
                        "access_token": _API_TOKEN,
                        "build_job_list_default_limit": 2,
                        "build_job_list_max_limit": 2,
                    },
                    "storage": {
                        "artifact_manifest_path": str(Path(temp_dir) / "manifest.json"),
                        "build_job_store_path": str(Path(temp_dir) / "jobs.json"),
                    },
                }
            )
            system = _FakeApiSystem()
            system.config = config
            app = create_build_api_app(system=system, config=config)

            with _client(app) as client:
                job_ids: list[str] = []
                for _ in range(3):
                    submitted = client.post("/v1/jobs/build").json()["job"]
                    finished = _wait_for_job_status(client, submitted["job_id"], "succeeded")
                    job_ids.append(finished["job_id"])
                first_page = client.get("/v1/jobs", params={"limit": 2})
                cursor = first_page.json()["next_cursor"]
                second_page = client.get("/v1/jobs", params={"limit": 2, "cursor": cursor})

        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(second_page.status_code, 200)
        self.assertEqual(
            [job["job_id"] for job in first_page.json()["jobs"]], list(reversed(job_ids))[0:2]
        )
        self.assertTrue(cursor)
        self.assertEqual(
            [job["job_id"] for job in second_page.json()["jobs"]], list(reversed(job_ids))[2:3]
        )
        self.assertEqual(second_page.json()["next_cursor"], "")

    def test_build_jobs_surface_rejects_invalid_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_test_config(
                {
                    "api": {"access_token": _API_TOKEN},
                    "storage": {
                        "artifact_manifest_path": str(Path(temp_dir) / "manifest.json"),
                        "build_job_store_path": str(Path(temp_dir) / "jobs.json"),
                    },
                }
            )
            system = _FakeApiSystem()
            system.config = config
            app = create_build_api_app(system=system, config=config)

            with _client(app) as client:
                response = client.get("/v1/jobs", params={"cursor": "not-a-cursor"})

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], "INVALID_REQUEST")
        self.assertEqual(payload["error"]["details"]["field"], "cursor")

    def test_v1_build_jobs_accept_idempotency_and_paginated_list_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_test_config(
                {
                    "api": {"access_token": _API_TOKEN},
                    "storage": {
                        "artifact_manifest_path": str(Path(temp_dir) / "manifest.json"),
                        "build_job_store_path": str(Path(temp_dir) / "jobs.json"),
                    },
                }
            )
            system = _FakeApiSystem()
            system.config = config
            app = create_build_api_app(system=system, config=config)

            with _client(app) as client:
                first = client.post("/v1/jobs/build", headers={"Idempotency-Key": "v1-key"})
                job_id = first.json()["job"]["job_id"]
                _wait_for_job_status(client, job_id, "succeeded")
                repeated = client.post("/v1/jobs/build", headers={"Idempotency-Key": "v1-key"})
                listed = client.get("/v1/jobs", params={"limit": 1})

        self.assertEqual(repeated.json()["job"]["job_id"], job_id)
        self.assertIn("next_cursor", listed.json())

    def test_build_job_route_accepts_idempotency_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_test_config(
                {
                    "api": {"access_token": _API_TOKEN},
                    "storage": {
                        "artifact_manifest_path": str(Path(temp_dir) / "manifest.json"),
                        "build_job_store_path": str(Path(temp_dir) / "jobs.json"),
                    },
                }
            )
            system = _FakeApiSystem()
            system.config = config
            app = create_build_api_app(system=system, config=config)

            with _client(app) as client:
                first = client.post("/v1/jobs/build", headers={"Idempotency-Key": "job-key"})
                job_id = first.json()["job"]["job_id"]
                _wait_for_job_status(client, job_id, "succeeded")
                repeated = client.post("/v1/jobs/build", headers={"Idempotency-Key": "job-key"})

        self.assertEqual(repeated.json()["job"]["job_id"], job_id)

    def test_build_jobs_surface_reuses_idempotency_key_for_same_job_type(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_test_config(
                {
                    "api": {"access_token": _API_TOKEN},
                    "storage": {
                        "artifact_manifest_path": str(Path(temp_dir) / "manifest.json"),
                        "build_job_store_path": str(Path(temp_dir) / "jobs.json"),
                    },
                }
            )
            system = _FakeApiSystem()
            system.config = config
            app = create_build_api_app(system=system, config=config)

            with _client(app) as client:
                first_response = client.post(
                    "/v1/jobs/build",
                    headers={"Idempotency-Key": "retry-key-1"},
                )
                first_job = first_response.json()["job"]
                _wait_for_job_status(client, first_job["job_id"], "succeeded")
                second_response = client.post(
                    "/v1/jobs/build",
                    headers={"Idempotency-Key": "retry-key-1"},
                )

        self.assertEqual(first_response.status_code, 202)
        self.assertEqual(second_response.status_code, 202)
        self.assertEqual(second_response.json()["job"]["job_id"], first_job["job_id"])
        self.assertEqual(system.build_calls, 1)

    def test_build_jobs_surface_rejects_idempotency_key_reused_for_different_type(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_test_config(
                {
                    "api": {"access_token": _API_TOKEN},
                    "storage": {
                        "artifact_manifest_path": str(Path(temp_dir) / "manifest.json"),
                        "build_job_store_path": str(Path(temp_dir) / "jobs.json"),
                    },
                }
            )
            system = _FakeApiSystem()
            system.config = config
            app = create_build_api_app(system=system, config=config)

            with _client(app) as client:
                first_response = client.post(
                    "/v1/jobs/build",
                    headers={"Idempotency-Key": "retry-key-2"},
                )
                first_job = first_response.json()["job"]
                _wait_for_job_status(client, first_job["job_id"], "succeeded")
                conflict_response = client.post(
                    "/v1/jobs/rebuild",
                    headers={"Idempotency-Key": "retry-key-2"},
                )

        payload = _assert_error_response(
            conflict_response,
            status_code=409,
            code="BUILD_JOB_CONFLICT",
        )
        self.assertEqual(payload["error"]["details"]["job_id"], first_job["job_id"])
        self.assertEqual(payload["error"]["details"]["job_type"], "build")

    def test_build_jobs_surface_rejects_invalid_idempotency_key(self) -> None:
        app = create_build_api_app(system=_FakeApiSystem())

        with _client(app) as client:
            response = client.post("/v1/jobs/build", headers={"Idempotency-Key": "../bad"})

        payload = _assert_error_response(response, status_code=400, code="INVALID_REQUEST")
        self.assertEqual(payload["error"]["details"]["field"], "Idempotency-Key")

    def test_build_jobs_surface_replays_active_job_with_same_idempotency_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_test_config(
                {
                    "api": {"access_token": _API_TOKEN},
                    "storage": {
                        "artifact_manifest_path": str(Path(temp_dir) / "manifest.json"),
                        "build_job_store_path": str(Path(temp_dir) / "jobs.json"),
                    },
                }
            )
            system = _BlockingBuildApiSystem()
            system.config = config
            app = create_build_api_app(system=system, config=config)

            with _client(app) as client:
                first_response = client.post(
                    "/v1/jobs/build",
                    headers={"Idempotency-Key": "active-key-1"},
                )
                first_job = first_response.json()["job"]
                self.assertTrue(system.build_started.wait(timeout=1.0))

                replay_response = client.post(
                    "/v1/jobs/build",
                    headers={"Idempotency-Key": "active-key-1"},
                )

                system.release_build.set()
                _wait_for_job_status(client, first_job["job_id"], "succeeded")

        self.assertEqual(first_response.status_code, 202)
        self.assertEqual(replay_response.status_code, 202)
        self.assertEqual(replay_response.json()["job"]["job_id"], first_job["job_id"])
        self.assertEqual(system.build_calls, 1)

    def test_rejected_idempotency_key_does_not_reserve_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_test_config(
                {
                    "api": {"access_token": _API_TOKEN},
                    "storage": {
                        "artifact_manifest_path": str(Path(temp_dir) / "manifest.json"),
                        "build_job_store_path": str(Path(temp_dir) / "jobs.json"),
                    },
                }
            )
            system = _BlockingBuildApiSystem()
            system.config = config
            app = create_build_api_app(system=system, config=config)

            with _client(app) as client:
                first_response = client.post(
                    "/v1/jobs/build",
                    headers={"Idempotency-Key": "active-key-2"},
                )
                first_job = first_response.json()["job"]
                self.assertTrue(system.build_started.wait(timeout=1.0))

                conflict_response = client.post(
                    "/v1/jobs/rebuild",
                    headers={"Idempotency-Key": "later-key"},
                )

                system.release_build.set()
                _wait_for_job_status(client, first_job["job_id"], "succeeded")
                accepted_response = client.post(
                    "/v1/jobs/rebuild",
                    headers={"Idempotency-Key": "later-key"},
                )
                accepted_job = accepted_response.json()["job"]
                _wait_for_job_status(client, accepted_job["job_id"], "succeeded")

        _assert_error_response(conflict_response, status_code=409, code="BUILD_JOB_CONFLICT")
        self.assertEqual(accepted_response.status_code, 202)
        self.assertNotEqual(accepted_job["job_id"], first_job["job_id"])

    def test_build_jobs_surface_rejects_parallel_build_submission(self) -> None:
        system = _BlockingBuildApiSystem()
        app = create_build_api_app(system=system)

        with _client(app) as client:
            first_response = client.post("/v1/jobs/build")
            first_job = first_response.json()["job"]
            self.assertTrue(system.build_started.wait(timeout=1.0))

            conflict_response = client.post("/v1/jobs/rebuild")

            system.release_build.set()
            _wait_for_job_status(client, first_job["job_id"], "succeeded")

        self.assertEqual(first_response.status_code, 202)
        conflict_payload = _assert_error_response(
            conflict_response,
            status_code=409,
            code="BUILD_JOB_CONFLICT",
        )
        self.assertEqual(conflict_payload["error"]["details"]["job_id"], first_job["job_id"])

    def test_build_job_cancel_route_cancels_running_job(self) -> None:
        system = _BlockingBuildApiSystem()
        app = create_build_api_app(system=system)

        with _client(app) as client:
            submitted_response = client.post("/v1/jobs/build")
            submitted = submitted_response.json()["job"]
            self.assertTrue(system.build_started.wait(timeout=1.0))

            cancel_response = client.post(f"/v1/jobs/{submitted['job_id']}/cancel")

            system.release_build.set()
            cancelled = _wait_for_job_status(client, submitted["job_id"], "cancelled")

        self.assertEqual(cancel_response.status_code, 202)
        self.assertIn(cancel_response.json()["job"]["status"], {"cancel_requested", "cancelled"})
        self.assertEqual(cancelled["status"], "cancelled")

    def test_build_job_retry_route_queues_new_job_from_failed_job(self) -> None:
        system = _FailOnceBuildApiSystem()
        app = create_build_api_app(system=system)

        with _client(app) as client:
            submitted = client.post("/v1/jobs/build").json()["job"]
            failed = _wait_for_job_status(client, submitted["job_id"], "failed")

            retry_response = client.post(f"/v1/jobs/{failed['job_id']}/retry")
            retried = retry_response.json()["job"]
            completed = _wait_for_job_status(client, retried["job_id"], "succeeded")

        self.assertEqual(retry_response.status_code, 202)
        self.assertNotEqual(retried["job_id"], failed["job_id"])
        self.assertEqual(completed["retry_of_job_id"], failed["job_id"])
        self.assertEqual(system.build_calls, 2)

    def test_build_job_retry_route_rejects_running_job(self) -> None:
        system = _BlockingBuildApiSystem()
        app = create_build_api_app(system=system)

        with _client(app) as client:
            submitted = client.post("/v1/jobs/build").json()["job"]
            self.assertTrue(system.build_started.wait(timeout=1.0))

            retry_response = client.post(f"/v1/jobs/{submitted['job_id']}/retry")

            system.release_build.set()
            _wait_for_job_status(client, submitted["job_id"], "succeeded")

        _assert_error_response(
            retry_response,
            status_code=409,
            code="BUILD_JOB_CONFLICT",
        )

    def test_build_job_cancel_route_rejects_succeeded_job(self) -> None:
        app = create_build_api_app(system=_FakeApiSystem())

        with _client(app) as client:
            submitted = client.post("/v1/jobs/build").json()["job"]
            succeeded = _wait_for_job_status(client, submitted["job_id"], "succeeded")

            cancel_response = client.post(f"/v1/jobs/{succeeded['job_id']}/cancel")

        _assert_error_response(
            cancel_response,
            status_code=409,
            code="BUILD_JOB_CONFLICT",
        )

    def test_build_http_failed_build_job_keeps_submission_request_id_without_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_test_config(
                {
                    "api": {"access_token": _API_TOKEN},
                    "storage": {
                        "artifact_manifest_path": str(Path(temp_dir) / "manifest.json"),
                        "build_job_store_path": str(Path(temp_dir) / "jobs.json"),
                    },
                }
            )
            secret = "build-http-secret"
            system = _FailingBuildApiSystem(secret)
            system.config = config
            app = create_build_api_app(system=system, config=config)

            with _client(app) as client:
                submitted = client.post(
                    "/v1/jobs/build",
                    headers={"X-Request-ID": "build-http-42"},
                ).json()["job"]
                failed = _wait_for_job_status(client, submitted["job_id"], "failed")

        self.assertEqual(failed["request_id"], "build-http-42")
        self.assertEqual(failed["error"]["request_id"], "build-http-42")
        self.assertEqual(failed["error"]["code"], "BUILD_FAILED")
        self.assertEqual(system.received_build_request_id, "build-http-42")
        self.assertEqual(system.received_build_job_id, submitted["job_id"])
        self.assertNotIn(secret, json.dumps(failed, ensure_ascii=False))

    def test_v1_build_routes_match_unversioned_build_routes(self) -> None:
        system = _FakeApiSystem()
        app = create_build_api_app(system=system)

        with _client(app) as client:
            health = client.get("/v1/health")
            initialize = client.post("/v1/runtime/build/initialize")
            build_response = client.post("/v1/jobs/build")
            build_job = build_response.json().get("job", {})
            finished_job = _wait_for_job_status(
                client,
                build_job.get("job_id", ""),
                "succeeded",
            )
            list_response = client.get("/v1/jobs")
            artifacts = client.get("/v1/artifacts")

        self.assertEqual(health.status_code, 200)
        self.assertEqual(initialize.status_code, 200)
        self.assertEqual(build_response.status_code, 202)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(artifacts.status_code, 200)
        self.assertEqual(list_response.json()["jobs"][0]["job_id"], build_job["job_id"])
        self.assertEqual(finished_job["result"]["message"], "Knowledge base build completed.")

    def test_build_service_delegates_executor_ownership_to_runner(self) -> None:
        app = create_build_api_app(system=_FakeApiSystem())

        with _client(app):
            service = app.state.api_service
            runner = service._build_jobs._runner

        self.assertIsInstance(runner, InProcessBuildJobRunner)
        self.assertFalse(hasattr(service, "_build_job_runner"))
        self.assertFalse(hasattr(service, "_build_executor"))
        self.assertFalse(hasattr(service, "_build_executor_lock"))
        self.assertFalse(hasattr(service, "_resolve_build_executor"))
        self.assertFalse(hasattr(service, "_job_registry"))

    def test_build_service_uses_configured_runner_backend_and_limits(self) -> None:
        config = build_test_config(
            {
                "api": {
                    "build_job_runner_backend": "in_process",
                    "build_job_runner_max_workers": 3,
                }
            }
        )
        system = _FakeApiSystem()
        system.config = config

        app = create_build_api_app(system=system, config=config)

        with _client(app):
            runner = app.state.api_service._build_jobs._runner

        self.assertEqual(runner.backend, "in_process")
        self.assertEqual(runner._max_workers, 3)

    def test_build_service_external_worker_backend_queues_without_local_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_test_config(
                {
                    "api": {
                        "access_token": _API_TOKEN,
                        "build_job_runner_backend": "external_worker",
                    },
                    "storage": {
                        "artifact_manifest_path": str(Path(temp_dir) / "manifest.json"),
                        "build_job_store_path": str(Path(temp_dir) / "jobs.json"),
                    },
                }
            )
            system = _FakeApiSystem()
            system.config = config
            app = create_build_api_app(system=system, config=config)

            with _client(app) as client:
                response = client.post("/v1/jobs/build")
                job = response.json()["job"]
                detail_response = client.get(f"/v1/jobs/{job['job_id']}")
                runner = app.state.api_service._build_jobs._runner

        self.assertEqual(response.status_code, 202)
        self.assertIsInstance(runner, ExternalBuildJobQueueRunner)
        self.assertEqual(job["status"], "queued")
        self.assertEqual(detail_response.json()["job"]["status"], "queued")
        self.assertEqual(system.build_calls, 0)
        self.assertEqual(system.initialize_build_calls, 0)

    def test_build_diagnostics_use_cached_snapshot_while_build_is_in_flight(self) -> None:
        system = _BlockingBuildApiSystem()
        app = create_build_api_app(system=system)

        with _client(app):
            service = app.state.api_service
            service.collect_stats()
            baseline = service.collect_startup_diagnostics("build")
            diagnostics_done = threading.Event()
            diagnostics_payload: dict[str, object] = {}

            job = service.submit_build_job(rebuild=False)
            self.assertTrue(system.build_started.wait(timeout=1.0))

            def read_diagnostics() -> None:
                diagnostics_payload["diagnostics"] = service.collect_startup_diagnostics("build")
                diagnostics_payload["stats"] = service.collect_stats()
                diagnostics_done.set()

            diagnostics_thread = threading.Thread(target=read_diagnostics)
            diagnostics_thread.start()
            self.assertTrue(
                diagnostics_done.wait(timeout=0.5),
                "diagnostics and stats should return cached snapshots during a build",
            )
            self.assertEqual(diagnostics_payload["diagnostics"], baseline)
            self.assertEqual(diagnostics_payload["stats"]["ready"], False)

            system.release_build.set()
            diagnostics_thread.join(timeout=1.0)
            completed_job = _wait_for_service_job_status(
                service,
                job["job_id"],
                "succeeded",
            )
            self.assertEqual(completed_job["status"], "succeeded")
