# Task 4 report: contract ownership and types

## RED

`python -m pytest tests/test_module_boundary_facades.py tests/test_runtime_retrieval_models.py -q`

Result: 4 failures as expected: all three retired modules remained importable and
`RequestControl` attached `_request_control_reason` to `threading.Event`.

## GREEN and static checks

`python -m pytest tests/test_runtime_retrieval_models.py tests/test_query_semantics.py tests/test_query_policy_injection.py tests/test_build_job_domain.py tests/test_build_job_composition.py tests/test_build_job_persistence.py tests/test_build_job_external_worker.py -q`

Result: `43 passed`.

`python -m pytest tests/test_hotspot_function_ratchets.py tests/test_abstraction_ratchets.py tests/test_import_dag.py tests/test_runtime_retrieval_models.py tests/test_query_semantics.py tests/test_query_policy_injection.py tests/test_build_job_domain.py tests/test_build_job_composition.py tests/test_build_job_persistence.py tests/test_build_job_external_worker.py -q`

Result: `102 passed, 6 subtests passed`.

`python -m mypy --config-file pyproject.toml`

Result: `Success: no issues found in 386 source files`.

`pre-commit run --all-files`

Result: passed after its first run reformatted files. The first invocation needed
approved cache access because the default cache SQLite database was read-only.

## Full verification

`python -m pytest -q` (1800-second timeout)

Result: `2227 passed, 225 subtests passed in 752.79s`.

## Changes and review

- Deleted the query, retrieval, and build-job executor facades; package exports now
  point directly to owning modules.
- Replaced dynamic request-cancellation event state with shared `_CancellationState`.
- Moved concrete build-job execution into `app.build_jobs.service`; runners receive
  precise execution/result callables, avoiding both a runtime-to-app import cycle and
  any third build-job port.
- Replaced `RetrievalRequest.copy_with` calls with `dataclasses.replace`.
- Typed JSON DTO boundaries as `JsonObject`/`JsonValue`, explicitly narrowing ingress.
- Self-review: `git diff --check` passed; retirement symbol search found only intentional
  assertions in the new retirement tests.

## Concerns

No remaining concerns. Full tests, import DAG, abstraction ratchets, mypy, and hooks pass.
