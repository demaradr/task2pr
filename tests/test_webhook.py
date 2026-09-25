import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from task2pr.config import Settings
from task2pr.store import TaskMapping, TaskMappingStore
from task2pr.webhook import create_app

SECRET = "test-webhook-secret"
WRIKE_BASE = "https://www.wrike.com/api/v4"


def _sign(body: bytes) -> str:
    digest = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@pytest.fixture
def settings(tmp_path):
    return Settings(
        wrike_api_token="fake-wrike-token",
        github_token=None,
        anthropic_api_key=None,
        github_webhook_secret=SECRET,
        state_path=tmp_path / "state.json",
    )


@pytest.fixture
def client(settings):
    return TestClient(create_app(settings))


def merged_pr_payload(owner="acme", repo="widgets", pr_number=42):
    return {
        "action": "closed",
        "pull_request": {"number": pr_number, "merged": True},
        "repository": {"name": repo, "owner": {"login": owner}},
    }


def test_rejects_missing_signature(client):
    body = json.dumps(merged_pr_payload()).encode()
    response = client.post(
        "/webhooks/github", content=body, headers={"X-GitHub-Event": "pull_request"}
    )
    assert response.status_code == 401


def test_rejects_invalid_signature(client):
    body = json.dumps(merged_pr_payload()).encode()
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": "sha256=deadbeef"},
    )
    assert response.status_code == 401


def test_ignores_non_pull_request_events(client):
    body = json.dumps({"zen": "some other event"}).encode()
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={"X-GitHub-Event": "ping", "X-Hub-Signature-256": _sign(body)},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_ignores_unmerged_pull_request(client):
    payload = merged_pr_payload()
    payload["pull_request"]["merged"] = False
    body = json.dumps(payload).encode()
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": _sign(body)},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_ignores_merged_pr_with_no_mapping(client):
    body = json.dumps(merged_pr_payload()).encode()
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": _sign(body)},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_marks_wrike_task_complete_when_pr_merged(client, settings, requests_mock):
    TaskMappingStore(settings.state_path).record(
        TaskMapping(
            wrike_task_id="task-99",
            github_owner="acme",
            github_repo="widgets",
            pr_number=42,
            branch="task2pr/fix-something",
        )
    )
    requests_mock.put(f"{WRIKE_BASE}/tasks/task-99", json={"data": [{"id": "task-99"}]})

    body = json.dumps(merged_pr_payload()).encode()
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": _sign(body)},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "wrike_task_id": "task-99"}
    assert requests_mock.last_request.qs["status"] == ["completed"]


def test_returns_502_when_wrike_update_fails(client, settings, requests_mock):
    TaskMappingStore(settings.state_path).record(
        TaskMapping(
            wrike_task_id="task-99",
            github_owner="acme",
            github_repo="widgets",
            pr_number=42,
            branch="task2pr/fix-something",
        )
    )
    requests_mock.put(f"{WRIKE_BASE}/tasks/task-99", status_code=500, text="boom")

    body = json.dumps(merged_pr_payload()).encode()
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": _sign(body)},
    )

    assert response.status_code == 502
