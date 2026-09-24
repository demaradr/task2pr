"""Orchestrates: branch -> commit -> push -> open PR.

This is only ever called after a task2pr edit run has already reported
success (tests passing) - see cli.py's run-task --open-pr wiring. It never
decides on its own whether the change is good; it just ships what's
already there in the working tree.
"""
from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

from task2pr.github.client import GitHubAPIError, GitHubClient, PullRequestInfo
from task2pr.github.git_ops import (
    GitOpsError,
    commit_all,
    create_and_checkout_branch,
    get_remote_url,
    has_uncommitted_changes,
    parse_github_owner_repo,
    push_branch,
)

logger = logging.getLogger(__name__)


class ShipError(RuntimeError):
    """Raised when branching, committing, pushing, or PR creation fails."""


def _slugify_branch_name(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40]
    suffix = uuid.uuid4().hex[:6]
    return f"task2pr/{slug}-{suffix}" if slug else f"task2pr/task-{suffix}"


def ship_branch(
    repo_root: Path,
    github_token: str,
    task_title: str,
    pr_body: str,
    branch_name: str | None = None,
    base_branch: str | None = None,
) -> PullRequestInfo:
    try:
        if not has_uncommitted_changes(repo_root):
            raise ShipError("No changes to ship - the working tree is clean.")

        owner, repo = parse_github_owner_repo(get_remote_url(repo_root))
        branch_name = branch_name or _slugify_branch_name(task_title)

        logger.info("Creating branch %s", branch_name)
        create_and_checkout_branch(repo_root, branch_name)
        commit_all(repo_root, f"task2pr: {task_title}")
        push_branch(repo_root, branch_name, owner, repo, github_token)

        client = GitHubClient(github_token)
        base = base_branch or client.get_default_branch(owner, repo)
        return client.create_pull_request(
            owner, repo, head=branch_name, base=base, title=task_title, body=pr_body
        )
    except (GitOpsError, GitHubAPIError) as exc:
        raise ShipError(str(exc)) from exc
