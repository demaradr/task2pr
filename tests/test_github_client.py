import pytest

from task2pr.github.client import GitHubAPIError, GitHubClient

BASE = "https://api.github.com"


def test_get_default_branch(requests_mock):
    requests_mock.get(
        f"{BASE}/repos/acme/widgets", json={"default_branch": "main"}
    )
    client = GitHubClient(token="fake-token")

    assert client.get_default_branch("acme", "widgets") == "main"


def test_get_default_branch_raises_on_error(requests_mock):
    requests_mock.get(f"{BASE}/repos/acme/widgets", status_code=404, text="Not Found")
    client = GitHubClient(token="fake-token")

    with pytest.raises(GitHubAPIError, match="404"):
        client.get_default_branch("acme", "widgets")


def test_create_pull_request(requests_mock):
    requests_mock.post(
        f"{BASE}/repos/acme/widgets/pulls",
        json={"number": 42, "html_url": "https://github.com/acme/widgets/pull/42"},
    )
    client = GitHubClient(token="fake-token")

    pr = client.create_pull_request(
        "acme", "widgets", head="task2pr/fix", base="main", title="Fix bug", body="Details"
    )

    assert pr.number == 42
    assert pr.html_url == "https://github.com/acme/widgets/pull/42"
    sent_body = requests_mock.last_request.json()
    assert sent_body == {"title": "Fix bug", "head": "task2pr/fix", "base": "main", "body": "Details"}


def test_create_pull_request_raises_on_error(requests_mock):
    requests_mock.post(
        f"{BASE}/repos/acme/widgets/pulls", status_code=422, text="Validation Failed"
    )
    client = GitHubClient(token="fake-token")

    with pytest.raises(GitHubAPIError, match="422"):
        client.create_pull_request("acme", "widgets", head="x", base="main", title="t", body="b")
