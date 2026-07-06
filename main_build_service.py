"""Build API entrypoint for offline artifact preparation."""

import logging
import os

from rag_modules.interfaces.api import create_build_api_app
from rag_modules.interfaces.console_runtime import configure_utf8_stdio

configure_utf8_stdio()
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = create_build_api_app()


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_value(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is not None and value != "":
        return value
    return default


def main() -> int:
    try:
        import uvicorn

        host = _env_value("BUILD_API_HOST", "0.0.0.0")
        port = int(_env_value("BUILD_API_PORT", "8001"))
        reload_enabled = _env_flag("BUILD_API_RELOAD", default=False)
        uvicorn.run("main_build_service:app", host=host, port=port, reload=reload_enabled)
        return 0
    except Exception:
        logger.exception("Build API startup failed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
