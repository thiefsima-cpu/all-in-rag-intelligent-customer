"""Build-job worker entrypoint for external-worker deployments."""

from __future__ import annotations

import logging
import os
import signal
import threading

from rag_modules.app.assembly import compose_build_job_worker, create_application_system
from rag_modules.app.runtime_operations import resolve_runtime_operation_coordinator
from rag_modules.interfaces.console_runtime import configure_utf8_stdio

configure_utf8_stdio()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _env_value(name: str, default: str) -> str:
    value = os.getenv(name)
    if value not in (None, ""):
        return str(value)
    return default


def _install_signal_handlers(stop_event: threading.Event) -> None:
    def request_stop(signum, _frame) -> None:
        logger.info("Build worker stop requested by signal %s.", signum)
        stop_event.set()

    for signal_number in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(signal_number, request_stop)
        except (ValueError, OSError):
            continue


def run_build_job_worker(*, stop_event: threading.Event | None = None) -> None:
    """Run the external build-job worker until a stop signal is received."""

    resolved_stop_event = stop_event or threading.Event()
    if stop_event is None:
        _install_signal_handlers(resolved_stop_event)

    system = create_application_system()
    config = system.config
    worker_id = _env_value("BUILD_JOB_WORKER_ID", f"external-worker-{os.getpid()}")
    runner = compose_build_job_worker(
        system=system,
        config=config,
        coordinator=resolve_runtime_operation_coordinator(system),
        worker_id=worker_id,
    )

    logger.info(
        "Starting build-job worker id=%s backend=%s poll_interval=%.3fs.",
        worker_id,
        runner.backend,
        runner.poll_interval_seconds,
    )
    try:
        runner.start()
        while not resolved_stop_event.wait(timeout=0.5):
            pass
    finally:
        runner.shutdown()
        system.close()
        logger.info("Build-job worker stopped.")


def main() -> int:
    try:
        run_build_job_worker()
        return 0
    except Exception:
        logger.exception("Build worker failed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
