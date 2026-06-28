"""One-shot Docker bootstrap for graph data and knowledge-base artifacts."""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import requests

from rag_modules.configuration import load_config
from scripts.import_neo4j import import_graph


def _env_flag(env: Mapping[str, str], name: str, *, default: bool) -> bool:
    value = env.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class RuntimeBootstrapSettings:
    auto_bootstrap: bool = True
    force_rebuild: bool = False
    build_api_url: str = "http://build-api:8001"
    request_timeout_seconds: float = 10.0
    build_timeout_seconds: float = 1800.0
    poll_interval_seconds: float = 2.0

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "RuntimeBootstrapSettings":
        source = env if env is not None else os.environ
        defaults = cls()
        return cls(
            auto_bootstrap=_env_flag(source, "AUTO_BOOTSTRAP", default=True),
            force_rebuild=_env_flag(source, "FORCE_REBUILD", default=False),
            build_api_url=str(source.get("BUILD_API_URL") or defaults.build_api_url).rstrip("/"),
            request_timeout_seconds=float(
                source.get("BOOTSTRAP_REQUEST_TIMEOUT_SECONDS") or defaults.request_timeout_seconds
            ),
            build_timeout_seconds=float(
                source.get("BOOTSTRAP_BUILD_TIMEOUT_SECONDS") or defaults.build_timeout_seconds
            ),
            poll_interval_seconds=float(
                source.get("BOOTSTRAP_POLL_INTERVAL_SECONDS") or defaults.poll_interval_seconds
            ),
        )


def _job_from_response(response) -> dict[str, Any]:
    payload = response.json()
    job = payload.get("job") if isinstance(payload, Mapping) else None
    if not isinstance(job, Mapping) or not str(job.get("job_id") or ""):
        raise RuntimeError("Build API returned a response without a valid job.")
    return dict(job)


def _submit_build_job(session, settings: RuntimeBootstrapSettings) -> dict[str, Any]:
    operation = "rebuild" if settings.force_rebuild else "build"
    response = session.post(
        f"{settings.build_api_url}/jobs/{operation}",
        timeout=settings.request_timeout_seconds,
    )
    if response.status_code != 409:
        response.raise_for_status()
    return _job_from_response(response)


def _wait_for_build_job(
    session,
    settings: RuntimeBootstrapSettings,
    job: dict[str, Any],
    *,
    monotonic=time.monotonic,
    sleep=time.sleep,
) -> dict[str, Any]:
    deadline = monotonic() + settings.build_timeout_seconds
    while True:
        status = str(job.get("status") or "")
        if status == "succeeded":
            return job
        if status == "failed":
            error = str(job.get("error") or job.get("message") or "unknown build error")
            raise RuntimeError(f"Knowledge-base build failed: {error}")
        if status not in {"queued", "running"}:
            raise RuntimeError(f"Build API returned unsupported job status: {status or '<empty>'}")
        if monotonic() >= deadline:
            raise TimeoutError(
                f"Knowledge-base build timed out after {settings.build_timeout_seconds:g} seconds."
            )

        sleep(settings.poll_interval_seconds)
        job_id = str(job["job_id"])
        response = session.get(
            f"{settings.build_api_url}/jobs/{job_id}",
            timeout=settings.request_timeout_seconds,
        )
        response.raise_for_status()
        job = _job_from_response(response)


def run_bootstrap(
    settings: RuntimeBootstrapSettings,
    *,
    config=None,
    importer=import_graph,
    session=None,
    monotonic=time.monotonic,
    sleep=time.sleep,
) -> dict[str, Any]:
    if not settings.auto_bootstrap:
        print("Runtime bootstrap disabled by AUTO_BOOTSTRAP=false.")
        return {"status": "skipped", "reason": "disabled"}

    resolved_config = config or load_config()
    graph_imported = bool(importer(resolved_config, only_if_empty=True))
    http_session = session or requests.Session()
    owns_session = session is None
    try:
        job = _submit_build_job(http_session, settings)
        finished_job = _wait_for_build_job(
            http_session,
            settings,
            job,
            monotonic=monotonic,
            sleep=sleep,
        )
        return {
            "status": "succeeded",
            "graph_imported": graph_imported,
            "job": finished_job,
        }
    finally:
        if owns_session:
            http_session.close()


def main() -> int:
    try:
        result = run_bootstrap(RuntimeBootstrapSettings.from_env())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"[ERROR] Runtime bootstrap failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
