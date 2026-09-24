"""Thin GitHub REST API client: just enough to open a pull request.

Branching/committing/pushing is done with plain git (see git_ops.py) since
that's already available locally on a cloned repo. Opening a PR has no git
equivalent - it's a GitHub-specific concept - so that part goes through the
API.
"""
from __future__ import annotations

from dataclasses import dataclass

import requests

BASE_URL = "https://api.github.com"


class GitHubAPIError(RuntimeError):
    """Raised when the GitHub API returns an error response."""


@dataclass(frozen=True)
class PullRequestInfo:
    number: int
    html_url: str


class GitHubClient:
    def __init__(self, token: str, base_url: str = BASE_URL, session: requests.Session | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            }
        )

    def get_default_branch(self, owner: str, repo: str) -> str:
        response = self._session.get(f"{self._base_url}/repos/{owner}/{repo}", timeout=30)
        if not response.ok:
            raise GitHubAPIError(
                f"GitHub API error {response.status_code} fetching repo info: {response.text}"
            )
        return response.json()["default_branch"]

    def create_pull_request(
        self,
        owner: str,
        repo: str,
        head: str,
        base: str,
        title: str,
        body: str,
    ) -> PullRequestInfo:
        response = self._session.post(
            f"{self._base_url}/repos/{owner}/{repo}/pulls",
            json={"title": title, "head": head, "base": base, "body": body},
            timeout=30,
        )
        if not response.ok:
            raise GitHubAPIError(
                f"GitHub API error {response.status_code} creating PR: {response.text}"
            )
        data = response.json()
        return PullRequestInfo(number=data["number"], html_url=data["html_url"])
