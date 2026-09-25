import pytest

from task2pr.wrike import WrikeAPIError, WrikeClient

BASE = "https://www.wrike.com/api/v4"


def test_resolve_status_id_matches_case_insensitively(requests_mock):
    requests_mock.get(
        f"{BASE}/workflows",
        json={
            "data": [
                {
                    "id": "wf1",
                    "customStatuses": [
                        {"id": "status-123", "name": "AI Ready"},
                        {"id": "status-456", "name": "In Progress"},
                    ],
                }
            ]
        },
    )
    client = WrikeClient(api_token="fake-token")

    assert client.resolve_status_id("ai ready") == "status-123"


def test_resolve_status_id_raises_when_not_found(requests_mock):
    requests_mock.get(f"{BASE}/workflows", json={"data": []})
    client = WrikeClient(api_token="fake-token")

    with pytest.raises(WrikeAPIError, match="No custom status named"):
        client.resolve_status_id("AI Ready")


def test_get_tasks_by_status_name_returns_parsed_tasks(requests_mock):
    requests_mock.get(
        f"{BASE}/workflows",
        json={"data": [{"id": "wf1", "customStatuses": [{"id": "status-123", "name": "AI Ready"}]}]},
    )
    requests_mock.get(
        f"{BASE}/tasks",
        json={
            "data": [
                {
                    "id": "task-1",
                    "title": "Fix login bug",
                    "description": "<p>Users can't log in</p>",
                    "permalink": "https://www.wrike.com/open.htm?id=task-1",
                    "status": "Active",
                    "customStatusId": "status-123",
                }
            ]
        },
    )
    client = WrikeClient(api_token="fake-token")

    tasks = client.get_tasks_by_status_name("AI Ready")

    assert len(tasks) == 1
    assert tasks[0].id == "task-1"
    assert tasks[0].title == "Fix login bug"
    assert tasks[0].custom_status_id == "status-123"


def test_get_raises_on_http_error(requests_mock):
    requests_mock.get(f"{BASE}/workflows", status_code=401, text="Unauthorized")
    client = WrikeClient(api_token="bad-token")

    with pytest.raises(WrikeAPIError, match="401"):
        client.list_custom_statuses()


def test_mark_task_complete_sends_completed_status(requests_mock):
    requests_mock.put(f"{BASE}/tasks/task-1", json={"data": [{"id": "task-1"}]})
    client = WrikeClient(api_token="fake-token")

    client.mark_task_complete("task-1")

    assert requests_mock.last_request.qs["status"] == ["completed"]


def test_mark_task_complete_raises_on_error(requests_mock):
    requests_mock.put(f"{BASE}/tasks/task-1", status_code=403, text="Forbidden")
    client = WrikeClient(api_token="fake-token")

    with pytest.raises(WrikeAPIError, match="403"):
        client.mark_task_complete("task-1")
