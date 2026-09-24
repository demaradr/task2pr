import subprocess

import pytest

import task2pr.github.ship as ship_module
from task2pr.github.ship import ShipError, ship_branch

BASE = "https://api.github.com"


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "file.txt").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/acme/widgets.git"],
        cwd=tmp_path,
        check=True,
    )
    return tmp_path


def test_ship_branch_raises_when_nothing_changed(repo):
    with pytest.raises(ShipError, match="No changes to ship"):
        ship_branch(repo, "fake-token", "Some task", "body")


def test_ship_branch_creates_commit_and_opens_pr(repo, monkeypatch, requests_mock):
    (repo / "file.txt").write_text("changed\n")

    pushed = {}
    monkeypatch.setattr(
        ship_module,
        "push_branch",
        lambda repo_root, branch_name, owner, repo_name, token: pushed.update(
            branch=branch_name, owner=owner, repo=repo_name
        ),
    )
    requests_mock.get(f"{BASE}/repos/acme/widgets", json={"default_branch": "main"})
    requests_mock.post(
        f"{BASE}/repos/acme/widgets/pulls",
        json={"number": 7, "html_url": "https://github.com/acme/widgets/pull/7"},
    )

    pr = ship_branch(repo, "fake-token", "Fix the thing", "PR body text")

    assert pr.number == 7
    assert pushed["owner"] == "acme"
    assert pushed["repo"] == "widgets"
    assert pushed["branch"].startswith("task2pr/fix-the-thing")
    sent = requests_mock.last_request.json()
    assert sent["title"] == "Fix the thing"
    assert sent["base"] == "main"
    assert sent["body"] == "PR body text"


def test_ship_branch_wraps_github_api_errors(repo, monkeypatch, requests_mock):
    (repo / "file.txt").write_text("changed\n")
    monkeypatch.setattr(
        ship_module,
        "push_branch",
        lambda repo_root, branch_name, owner, repo_name, token: None,
    )
    requests_mock.get(f"{BASE}/repos/acme/widgets", status_code=500, text="boom")

    with pytest.raises(ShipError):
        ship_branch(repo, "fake-token", "Fix the thing", "body")
