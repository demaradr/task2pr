"""Command-line entry point for task2pr.

This is intentionally thin right now (Stage 1: just config validation).
Later stages will add subcommands like `poll`, `run-task`, and `eval`.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import anthropic

from task2pr.agent import AgentLoopError, run_edit_loop, run_explore_loop
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

    explore = subparsers.add_parser(
        "explore",
        help="Explore a target repo and propose a plan for a task (read-only, no edits).",
    )
    explore.add_argument("--repo", required=True, help="Path to the target repo on disk.")
    task_source = explore.add_mutually_exclusive_group(required=True)
    task_source.add_argument("--task-text", help="Inline task description.")
    task_source.add_argument(
        "--wrike-task-id", help="Fetch the task description from this Wrike task id."
    )

    run_task = subparsers.add_parser(
        "run-task",
        help="Make a code change for a task, then run tests and retry on failure.",
    )
    run_task.add_argument("--repo", required=True, help="Path to the target repo on disk.")
    run_task_source = run_task.add_mutually_exclusive_group(required=True)
    run_task_source.add_argument("--task-text", help="Inline task description.")
    run_task_source.add_argument(
        "--wrike-task-id", help="Fetch the task description from this Wrike task id."
    )
    run_task.add_argument(
        "--test-cmd",
        required=True,
        help='Command to run the target repo\'s test suite, e.g. "pytest -q".',
    )
    run_task.add_argument(
        "--max-test-attempts",
        type=int,
        default=3,
        help="Give up after this many failed test runs (default: 3).",
    )

    return parser


def _resolve_repo_root(repo_arg: str) -> Path | None:
    repo_root = Path(repo_arg).resolve()
    if not repo_root.is_dir():
        print(f"Error: {repo_root} is not a directory.", file=sys.stderr)
        return None
    return repo_root


def _resolve_task_description(
    settings: Settings, task_text: str | None, wrike_task_id: str | None
) -> str | None:
    if wrike_task_id:
        wrike_client = WrikeClient(settings.wrike_api_token)
        try:
            task = wrike_client.get_task(wrike_task_id)
        except WrikeAPIError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return None
        return f"{task.title}\n\n{task.description}"
    return task_text


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

    if args.command == "explore":
        settings = Settings.load()
        try:
            settings.require("anthropic_api_key")
            if args.wrike_task_id:
                settings.require("wrike_api_token")
        except MissingConfigError as exc:
            print(f"Config invalid: {exc}", file=sys.stderr)
            return 1
        configure_logging(settings.log_level)

        repo_root = _resolve_repo_root(args.repo)
        if repo_root is None:
            return 1

        task_description = _resolve_task_description(
            settings, args.task_text, args.wrike_task_id
        )
        if task_description is None:
            return 1

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        try:
            plan = run_explore_loop(client, task_description, repo_root)
        except AgentLoopError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        print(plan)
        return 0

    if args.command == "run-task":
        settings = Settings.load()
        try:
            settings.require("anthropic_api_key")
            if args.wrike_task_id:
                settings.require("wrike_api_token")
        except MissingConfigError as exc:
            print(f"Config invalid: {exc}", file=sys.stderr)
            return 1
        configure_logging(settings.log_level)

        repo_root = _resolve_repo_root(args.repo)
        if repo_root is None:
            return 1

        task_description = _resolve_task_description(
            settings, args.task_text, args.wrike_task_id
        )
        if task_description is None:
            return 1

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        try:
            result = run_edit_loop(
                client,
                task_description,
                repo_root,
                args.test_cmd,
                max_test_attempts=args.max_test_attempts,
            )
        except AgentLoopError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        print(result.summary)
        print()
        status = "PASSED" if result.success else "FAILED"
        print(f"Tests {status} after {result.test_attempts} attempt(s).")
        if not result.success:
            print()
            print(result.test_output)
        return 0 if result.success else 1

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
