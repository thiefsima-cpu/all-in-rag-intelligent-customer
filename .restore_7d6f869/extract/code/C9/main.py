"""Serving API entrypoint for the GraphRAG system."""

import logging
import os

from rag_modules.interfaces.api import create_serving_api_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = create_serving_api_app()


def _env_value(primary: str, fallback: str, default: str) -> str:
    value = os.getenv(primary)
    if value not in (None, ""):
        return value
    value = os.getenv(fallback)
    if value not in (None, ""):
        return value
    return default


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main():
    try:
        import uvicorn

        host = _env_value("SERVING_API_HOST", "API_HOST", "0.0.0.0")
        port = int(_env_value("SERVING_API_PORT", "API_PORT", "8000"))
        reload_enabled = _env_flag("SERVING_API_RELOAD", default=_env_flag("API_RELOAD", default=False))
        uvicorn.run("main:app", host=host, port=port, reload=reload_enabled)
    except Exception as exc:
        logger.error("API startup failed: %s", exc)
        import traceback

        traceback.print_exc()
        print(f"\n[ERROR] API service error: {exc}")


if __name__ == "__main__":
    main()
