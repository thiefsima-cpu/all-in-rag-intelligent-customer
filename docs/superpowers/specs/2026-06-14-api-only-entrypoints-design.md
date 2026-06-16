# API-Only Entrypoints Design

## Goal

Remove CLI delivery mode from the project so runtime operation is exposed only through the existing FastAPI entrypoints:

- `main.py` for serving and question answering.
- `main_build_service.py` for build and rebuild jobs.

## Scope

The CLI retirement removes both command-line scripts and the public CLI interface layer:

- Delete `main_qa.py`.
- Delete `main_build_kb.py`.
- Delete `rag_modules/interfaces/cli_console.py`.
- Remove CLI exports from `rag_modules.interfaces`.
- Remove interactive application wiring from the application facade and composition layer.
- Update public surface manifest and tests so CLI is no longer a canonical public API.

The API behavior remains unchanged. Serving and build APIs keep their current routes, app factories, environment variables, startup lifecycles, and shutdown behavior.

## Architecture

The application system keeps separate operations and answering services because both are required by API surfaces. The interactive service is removed because it exists only to connect the application facade to `InteractiveCliConsole`.

The remaining interface package exposes only FastAPI factories. Build functionality moves exclusively through `create_build_api_app()` and `main_build_service.py`; answering functionality moves exclusively through `create_serving_api_app()` and `main.py`.

## Data Flow

Serving flow:

1. `main.py` creates `create_serving_api_app()`.
2. API routes call `GraphRAGServingApiService`.
3. The service initializes serving runtime as needed and calls `answer_question_response()`.

Build flow:

1. `main_build_service.py` creates `create_build_api_app()`.
2. API routes call `GraphRAGBuildApiService`.
3. The service queues build or rebuild jobs and invokes application build operations.

No user input loop, console command parser, or `run_interactive()` path remains.

## Error Handling

Existing API error behavior stays intact:

- Startup failures in `main.py` and `main_build_service.py` still return nonzero exit codes.
- Serving requests still return readiness errors when artifacts are missing or stale.
- Build job conflicts and missing job lookups still use the current API exception handlers.

CLI-specific warnings about running `main_build_kb.py` are removed because there is no CLI fallback after this change.

## Testing

Tests should prove:

- `main.py` and `main_build_service.py` remain the only runtime entrypoint scripts.
- `rag_modules.interfaces` exports API factories only.
- The public surface manifest no longer lists `rag_modules.interfaces.cli_console`.
- Application assembly no longer requires or exposes an interactive service.
- API route tests continue to pass unchanged.

The removed CLI tests should not be replaced with equivalent console tests because the behavior is intentionally retired.
