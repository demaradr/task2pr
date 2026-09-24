"""Local git operations (branch/commit/push) via subprocess.

These act on a repo that's already cloned locally - task2pr does not clone
repos itself yet. Push authenticates with a short-lived, in-memory URL
(https://x-access-token:<token>@github.com/...) built only for that one
`git push` call; the token is never written to .git/config or logged.
"""
from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_GITHUB_URL_PATTERNS = [
    re.compile(r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"),
    re.compile(r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$"),
]


class GitOpsError(RuntimeError):
    """Raised when a local git operation fails."""


def _run_git(args: list[str], repo_root: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise GitOpsError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def has_uncommitted_changes(repo_root: Path) -> bool:
    return bool(_run_git(["status", "--porcelain"], repo_root))


def get_remote_url(repo_root: Path, remote: str = "origin") -> str:
    return _run_git(["remote", "get-url", remote], repo_root)


def parse_github_owner_repo(remote_url: str) -> tuple[str, str]:
    for pattern in _GITHUB_URL_PATTERNS:
        match = pattern.match(remote_url.strip())
        if match:
            return match["owner"], match["repo"]
    raise GitOpsError(
        f"Could not parse a GitHub owner/repo from remote URL {remote_url!r}. "
        "Expected an https://github.com/... or git@github.com:... URL."
    )


def create_and_checkout_branch(repo_root: Path, branch_name: str) -> None:
    _run_git(["checkout", "-b", branch_name], repo_root)


def commit_all(repo_root: Path, message: str) -> None:
    _run_git(["add", "-A"], repo_root)
    _run_git(["commit", "-m", message], repo_root)


def push_branch(repo_root: Path, branch_name: str, owner: str, repo: str, token: str) -> None:
    authenticated_url = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
    logger.info("Pushing branch %s to %s/%s", branch_name, owner, repo)
    result = subprocess.run(
        ["git", "push", authenticated_url, f"HEAD:refs/heads/{branch_name}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Strip the token out of anything git echoes back before it hits logs/output.
        sanitized_stderr = result.stderr.replace(token, "***")
        raise GitOpsError(f"git push failed: {sanitized_stderr.strip()}")
