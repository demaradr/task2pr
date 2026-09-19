"""Command-line entry point for task2pr.

This is intentionally thin right now (Stage 1: just config validation).
Later stages will add subcommands like `poll`, `run-task`, and `eval`.
"""
from __future__ import annotations

import argparse
import logging
import sys

from task2pr.config import MissingConfigError, Settings
from task2pr.logging_setup import configure_logging

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="task2pr",
        description="Wrike task -> code change -> GitHub PR automation agent.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "check-config",
        help="Validate that required environment variables are set.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "check-config":
        try:
            settings = Settings.load()
        except MissingConfigError as exc:
            print(f"Config invalid: {exc}", file=sys.stderr)
            return 1
        configure_logging(settings.log_level)
        logger.info("Config OK. Log level=%s", settings.log_level)
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
