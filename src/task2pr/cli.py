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
from task2pr.wrike import WrikeAPIError, WrikeClient

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

    poll_wrike = subparsers.add_parser(
        "poll-wrike",
        help="List Wrike tasks currently set to the AI-ready custom status.",
    )
    poll_wrike.add_argument(
        "--status",
        default="AI Ready",
        help='Custom status name to filter on (default: "AI Ready").',
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "check-config":
        settings = Settings.load()
        try:
            settings.require("wrike_api_token", "github_token", "anthropic_api_key")
        except MissingConfigError as exc:
            print(f"Config invalid: {exc}", file=sys.stderr)
            return 1
        configure_logging(settings.log_level)
        logger.info("Config OK. Log level=%s", settings.log_level)
        return 0

    if args.command == "poll-wrike":
        settings = Settings.load()
        try:
            settings.require("wrike_api_token")
        except MissingConfigError as exc:
            print(f"Config invalid: {exc}", file=sys.stderr)
            return 1
        configure_logging(settings.log_level)

        client = WrikeClient(settings.wrike_api_token)
        try:
            tasks = client.get_tasks_by_status_name(args.status)
        except WrikeAPIError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        if not tasks:
            print(f"No tasks found with status {args.status!r}.")
            return 0

        for task in tasks:
            print(f"[{task.id}] {task.title}")
            print(f"  {task.permalink}")
            print()
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
