"""Offline knowledge-base build entrypoint."""

from __future__ import annotations

import argparse
import logging

from rag_modules.interfaces.cli_console import build_knowledge_base_only

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build or rebuild offline GraphRAG knowledge-base artifacts.",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Delete existing vector artifacts before rebuilding.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    system = None
    try:
        system = build_knowledge_base_only(rebuild=args.rebuild)
    except Exception:
        logger.exception("Knowledge-base build failed.")
        raise
    finally:
        if system is not None:
            system.close()


if __name__ == "__main__":
    main()
