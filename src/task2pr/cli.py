"""Command-line entry point for task2pr.

This is intentionally thin right now (Stage 1: just config validation).
Later stages will add subcommands like `poll`, `run-task`, and `eval`.
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

import anthropic

from task2pr.agent import AgentLoopError, run_edit_loop, run_explore_loop
from task2pr.config import MissingConfigError, Settings
from task2pr.eval import DEFAULT_FIXTURES_DIR, DEFAULT_TASKS_DIR, run_eval
from task2pr.github import ShipError, ship_branch
from task2pr.logging_setup import configure_logging
from task2pr.store import TaskMapping, TaskMappingStore
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
    run_task.add_argument(
        "--open-pr",
        action="store_true",
        help=(
            "If the change passes tests, push a branch and open a GitHub PR. "
            "Never runs if tests fail."
        ),
    )

    serve_webhook = subparsers.add_parser(
        "serve-webhook",
        help="Run the GitHub webhook receiver that marks Wrike tasks done when their PR merges.",
    )
    serve_webhook.add_argument(
        "--host", default="127.0.0.1", help="Interface to bind (default: 127.0.0.1)."
    )
    serve_webhook.add_argument(
        "--port", type=int, default=8000, help="Port to listen on (default: 8000)."
    )

    eval_parser = subparsers.add_parser(
        "eval",
        help="Run the seeded eval task set through the edit-and-test loop and report a score.",
    )
    eval_parser.add_argument(
        "--tasks-dir",
        default=None,
        help=f"Directory of eval task JSON files (default: {DEFAULT_TASKS_DIR}).",
    )
    eval_parser.add_argument(
        "--fixtures-dir",
        default=None,
        help=f"Directory of fixture repos (default: {DEFAULT_FIXTURES_DIR}).",
    )

    return parser


def _resolve_repo_root(repo_arg: str) -> Path | None:
    repo_root = Path(repo_arg).resolve()
    if not repo_root.is_dir():
        print(f"Error: {repo_root} is not a directory.", file=sys.stderr)
        return None
    return repo_root


@dataclass(frozen=True)
class ResolvedTask:
    title: str
    description: str
    wrike_permalink: str | None = None


def _resolve_task(
    settings: Settings, task_text: str | None, wrike_task_id: str | None
) -> ResolvedTask | None:
    if wrike_task_id:
        wrike_client = WrikeClient(settings.wrike_api_token)
        try:
            task = wrike_client.get_task(wrike_task_id)
        except WrikeAPIError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return None
        return ResolvedTask(
            title=task.title,
            description=f"{task.title}\n\n{task.description}",
            wrike_permalink=task.permalink,
        )
    title = task_text.splitlines()[0][:72] if task_text else "task2pr change"
    return ResolvedTask(title=title, description=task_text)


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

        task = _resolve_task(settings, args.task_text, args.wrike_task_id)
        if task is None:
            return 1

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        try:
            plan = run_explore_loop(client, task.description, repo_root)
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
            if args.open_pr:
                settings.require("github_token")
        except MissingConfigError as exc:
            print(f"Config invalid: {exc}", file=sys.stderr)
            return 1
        configure_logging(settings.log_level)

        repo_root = _resolve_repo_root(args.repo)
        if repo_root is None:
            return 1

        task = _resolve_task(settings, args.task_text, args.wrike_task_id)
        if task is None:
            return 1

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        try:
            result = run_edit_loop(
                client,
                task.description,
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
            return 1

        if not args.open_pr:
            return 0

        pr_body = result.summary
        if task.wrike_permalink:
            pr_body += f"\n\n---\nWrike task: {task.wrike_permalink}"

        try:
            ship_result = ship_branch(repo_root, settings.github_token, task.title, pr_body)
        except ShipError as exc:
            print(f"Error opening PR: {exc}", file=sys.stderr)
            return 1

        if args.wrike_task_id:
            TaskMappingStore(settings.state_path).record(
                TaskMapping(
                    wrike_task_id=args.wrike_task_id,
                    github_owner=ship_result.owner,
                    github_repo=ship_result.repo,
                    pr_number=ship_result.pr_number,
                    branch=ship_result.branch,
                )
            )

        print(f"Opened PR #{ship_result.pr_number}: {ship_result.pr_url}")
        return 0

    if args.command == "serve-webhook":
        settings = Settings.load()
        try:
            settings.require("wrike_api_token", "github_webhook_secret")
        except MissingConfigError as exc:
            print(f"Config invalid: {exc}", file=sys.stderr)
            return 1
        configure_logging(settings.log_level)

        # Imported lazily so every other command stays fast to start - only
        # this one needs the web server stack.
        import uvicorn

        from task2pr.webhook import create_app

        app = create_app(settings)
        uvicorn.run(app, host=args.host, port=args.port)
        return 0

    if args.command == "eval":
        settings = Settings.load()
        try:
            settings.require("anthropic_api_key")
        except MissingConfigError as exc:
            print(f"Config invalid: {exc}", file=sys.stderr)
            return 1
        configure_logging(settings.log_level)

        tasks_dir = Path(args.tasks_dir) if args.tasks_dir else DEFAULT_TASKS_DIR
        fixtures_dir = Path(args.fixtures_dir) if args.fixtures_dir else DEFAULT_FIXTURES_DIR

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        outcomes = run_eval(client, tasks_dir, fixtures_dir)

        for outcome in outcomes:
            status = "PASS" if outcome.success else "FAIL"
            print(f"[{status}] {outcome.task_id} ({outcome.test_attempts} attempt(s))")
            if not outcome.success:
                last_line = outcome.detail.strip().splitlines()[-1] if outcome.detail.strip() else ""
                print(f"       {last_line}")

        passed = sum(1 for outcome in outcomes if outcome.success)
        print()
        print(f"Score: {passed}/{len(outcomes)} tasks passed.")
        return 0 if passed == len(outcomes) else 1

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
