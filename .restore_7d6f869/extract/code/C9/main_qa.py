"""Interactive QA CLI entrypoint."""

from __future__ import annotations

import logging

from rag_modules.interfaces.cli_console import run_qa_cli

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    system = None
    try:
        system = run_qa_cli()
    except Exception:
        logger.exception("QA CLI exited with an error.")
        raise
    finally:
        if system is not None:
            system.close()


if __name__ == "__main__":
    main()
