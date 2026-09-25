"""Tests for the eval harness's orchestration: loading task definitions,
copying fixtures into isolated throwaway dirs, and scoring outcomes. Uses a
fake Anthropic client (same pattern as test_edit_loop.py) so this never
makes a real API call - it's testing the harness, not the model's actual
coding ability.
"""
import json
from types import SimpleNamespace

import pytest

from task2pr.eval.harness import DEFAULT_FIXTURES_DIR, DEFAULT_TASKS_DIR, load_tasks, run_eval


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def tool_use_block(name, tool_input, tool_id="tool_1"):
    return SimpleNamespace(type="tool_use", name=name, input=tool_input, id=tool_id)


def response(content, stop_reason):
    return SimpleNamespace(content=content, stop_reason=stop_reason)


class FakeMessages:
    def __init__(self, responses):
        self._responses = list(responses)

    def create(self, **kwargs):
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


@pytest.fixture
def tasks_and_fixtures(tmp_path):
    fixtures_dir = tmp_path / "fixtures"
    task_fixture = fixtures_dir / "greet"
    task_fixture.mkdir(parents=True)
    (task_fixture / "greet.py").write_text("def greet():\n    return 'bye'\n")

    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "greet.json").write_text(
        json.dumps(
            {
                "id": "greet",
                "fixture": "greet",
                "description": "Fix greet() to return 'hi' instead of 'bye'.",
                "test_cmd": "python3 -c \"import greet; assert greet.greet() == 'hi'\"",
            }
        )
    )
    return tasks_dir, fixtures_dir, task_fixture


def test_load_tasks_parses_json_definitions(tasks_and_fixtures):
    tasks_dir, fixtures_dir, task_fixture = tasks_and_fixtures

    tasks = load_tasks(tasks_dir, fixtures_dir)

    assert len(tasks) == 1
    assert tasks[0].id == "greet"
    assert tasks[0].fixture_dir == task_fixture


def test_run_eval_reports_success_and_never_mutates_fixture(tasks_and_fixtures):
    tasks_dir, fixtures_dir, task_fixture = tasks_and_fixtures
    responses = [
        response(
            [
                tool_use_block(
                    "edit_file",
                    {"path": "greet.py", "old_string": "return 'bye'", "new_string": "return 'hi'"},
                )
            ],
            stop_reason="tool_use",
        ),
        response([text_block("Fixed greet().")], stop_reason="end_turn"),
    ]
    client = FakeClient(responses)

    outcomes = run_eval(client, tasks_dir, fixtures_dir)

    assert len(outcomes) == 1
    assert outcomes[0].task_id == "greet"
    assert outcomes[0].success
    assert outcomes[0].test_attempts == 1
    # The checked-in fixture itself must be untouched - only the throwaway copy was edited.
    assert task_fixture.joinpath("greet.py").read_text() == "def greet():\n    return 'bye'\n"


def test_run_eval_reports_failure_when_tests_never_pass(tasks_and_fixtures):
    tasks_dir, fixtures_dir, _ = tasks_and_fixtures
    # run_edit_loop's default max_test_attempts is 3, so it asks the fake
    # client for a fresh reply after each failed test run.
    responses = [
        response([text_block(f"Attempt {i}.")], stop_reason="end_turn") for i in range(3)
    ]
    client = FakeClient(responses)

    outcomes = run_eval(client, tasks_dir, fixtures_dir)

    assert len(outcomes) == 1
    assert not outcomes[0].success
    assert "AssertionError" in outcomes[0].detail or outcomes[0].detail


def test_bundled_eval_tasks_load_correctly():
    tasks = load_tasks(DEFAULT_TASKS_DIR, DEFAULT_FIXTURES_DIR)

    assert len(tasks) == 3
    task_ids = {task.id for task in tasks}
    assert task_ids == {"add-function", "fix-bug", "divide-by-zero"}
    for task in tasks:
        assert task.fixture_dir.is_dir()
