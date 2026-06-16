# Runtime Hardening Design

## Goal

Fix console encoding, process exit semantics, dependency isolation, health
probes, and trace privacy without changing the application core or exposing
user content through observability outputs.

## Design

Entrypoints configure UTF-8 output once and return integer exit codes. Startup
exceptions are logged and return `1`; successful server termination returns
`0`. `__main__` raises `SystemExit(main())` so supervisors receive the result.

The API exposes separate probe semantics:

- `/health/live` reports that the process can serve HTTP and always returns
  `200` while the app is running.
- `/health/ready` returns `200` only when the relevant runtime is usable and
  `503` otherwise.
- `/health` remains a compatibility alias for liveness and still reports the
  detailed runtime state.

Query traces are sanitized before they cross the sink boundary. Raw query,
answer, prompt, content, error, credential, token, password, and authorization
values are not persisted by default. Text content is replaced by a stable
salted SHA-256 fingerprint plus character count. Nested dictionaries and lists
are recursively sanitized, including route, graph, retrieval, and generation
snapshots. Operators may change the salt through configuration, but there is
no option to persist raw user content.

Dependencies use repository-local virtual environments. Runtime and
development inputs remain separate; generated locks are installed only inside
`.venv`. A PowerShell bootstrap script creates the environment, upgrades the
packaging toolchain, installs the selected lock, and runs `pip check`. A
verification script fails when invoked from the global interpreter or when
runtime locks contain development-only tools. The legacy agent keeps its own
environment and is not installed into the main application environment.

## Testing

Regression tests cover UTF-8 stream configuration, non-zero startup failure
codes, liveness/readiness status codes, recursive trace sanitization, lock-file
separation, and isolated-interpreter verification. The complete test suite,
encoding audit, lock checks, and a clean `.venv` installation are the release
gate.
