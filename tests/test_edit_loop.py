"""Tests for the edit-and-test loop's control flow: it should keep letting
Claude call edit tools, then run tests once Claude stops, then either
return success or feed the failure back and give Claude another attempt -
up to max_test_attempts. Both the Anthropic client and the test runner are
faked so this never makes a real API call or shells out.
"""
from types import SimpleNamespace

import pytest

import task2pr.agent.edit_loop as edit_loop
from task2pr.agent.edit_loop import AgentLoopError, run_edit_loop
from task2pr.tools.test_runner import RunResult


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def tool_use_block(name, tool_input, tool_id="tool_1"):
    return SimpleNamespace(type="tool_use", name=name, input=tool_input, id=tool_id)


def response(content, stop_reason):
    return SimpleNamespace(content=content, stop_reason=stop_reason)


class FakeMessages:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "main.py").write_text("def add(a, b):\n    return a - b\n")
    return tmp_path


def test_loop_succeeds_when_tests_pass_first_try(repo, monkeypatch):
    monkeypatch.setattr(
        edit_loop, "run_tests", lambda command, root, timeout=120: RunResult(True, 0, "all good")
    )
    responses = [
        response(
            [tool_use_block("edit_file", {"path": "main.py", "old_string": "a - b", "new_string": "a + b"})],
            stop_reason="tool_use",
        ),
        response([text_block("Fixed the subtraction bug.")], stop_reason="end_turn"),
    ]
    client = FakeClient(responses)

    result = run_edit_loop(client, "Fix add()", repo, test_command="pytest")

    assert result.success
    assert result.test_attempts == 1
    assert (repo / "main.py").read_text() == "def add(a, b):\n    return a + b\n"


def test_loop_retries_after_test_failure_then_succeeds(repo, monkeypatch):
    test_results = [RunResult(False, 1, "AssertionError: boom"), RunResult(True, 0, "ok")]
    monkeypatch.setattr(
        edit_loop, "run_tests", lambda command, root, timeout=120: test_results.pop(0)
    )
    responses = [
        response([text_block("First attempt.")], stop_reason="end_turn"),
        response([text_block("Fixed it after seeing the failure.")], stop_reason="end_turn"),
    ]
    client = FakeClient(responses)

    result = run_edit_loop(client, "Fix add()", repo, test_command="pytest", max_test_attempts=3)

    assert result.success
    assert result.test_attempts == 2
    # The failure output must have been handed back to Claude for the retry.
    second_call_messages = client.messages.calls[1]["messages"]
    assert any("boom" in str(m["content"]) for m in second_call_messages)


def test_loop_gives_up_after_max_test_attempts(repo, monkeypatch):
    monkeypatch.setattr(
        edit_loop,
        "run_tests",
        lambda command, root, timeout=120: RunResult(False, 1, "still broken"),
    )
    responses = [
        response([text_block(f"Attempt {i}.")], stop_reason="end_turn") for i in range(1, 3)
    ]
    client = FakeClient(responses)

    result = run_edit_loop(client, "Fix add()", repo, test_command="pytest", max_test_attempts=2)

    assert not result.success
    assert result.test_attempts == 2
    assert "still broken" in result.test_output


def test_loop_raises_when_iteration_cap_hit_before_finishing(repo):
    responses = [
        response([tool_use_block("read_file", {"path": "main.py"})], stop_reason="tool_use")
        for _ in range(3)
    ]
    client = FakeClient(responses)

    with pytest.raises(AgentLoopError, match="did not finish editing"):
        run_edit_loop(client, "Fix add()", repo, test_command="pytest", max_iterations=3)
