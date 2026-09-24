import subprocess

import pytest

from task2pr.github.git_ops import (
    GitOpsError,
    commit_all,
    create_and_checkout_branch,
    get_remote_url,
    has_uncommitted_changes,
    parse_github_owner_repo,
)


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "file.txt").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/someowner/somerepo.git"],
        cwd=tmp_path,
        check=True,
    )
    return tmp_path


def test_has_uncommitted_changes_false_on_clean_repo(repo):
    assert not has_uncommitted_changes(repo)


def test_has_uncommitted_changes_true_after_edit(repo):
    (repo / "file.txt").write_text("changed\n")
    assert has_uncommitted_changes(repo)


def test_create_and_checkout_branch(repo):
    create_and_checkout_branch(repo, "task2pr/my-branch")
    result = subprocess.run(
        ["git", "branch", "--show-current"], cwd=repo, capture_output=True, text=True
    )
    assert result.stdout.strip() == "task2pr/my-branch"


def test_commit_all_commits_working_tree_changes(repo):
    (repo / "file.txt").write_text("changed\n")
    commit_all(repo, "task2pr: fix something")

    assert not has_uncommitted_changes(repo)
    log = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"], cwd=repo, capture_output=True, text=True
    )
    assert log.stdout.strip() == "task2pr: fix something"


def test_get_remote_url(repo):
    assert get_remote_url(repo) == "https://github.com/someowner/somerepo.git"


def test_create_branch_that_already_exists_raises(repo):
    create_and_checkout_branch(repo, "dup-branch")
    subprocess.run(["git", "checkout", "-q", "-"], cwd=repo, check=True)
    with pytest.raises(GitOpsError):
        create_and_checkout_branch(repo, "dup-branch")


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/owner/repo.git", ("owner", "repo")),
        ("https://github.com/owner/repo", ("owner", "repo")),
        ("git@github.com:owner/repo.git", ("owner", "repo")),
        ("git@github.com:owner/repo", ("owner", "repo")),
    ],
)
def test_parse_github_owner_repo(url, expected):
    assert parse_github_owner_repo(url) == expected


def test_parse_github_owner_repo_rejects_non_github_url():
    with pytest.raises(GitOpsError, match="Could not parse"):
        parse_github_owner_repo("https://gitlab.com/owner/repo.git")
