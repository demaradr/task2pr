"""Tests for the explore loop, using a fake Anthropic client (no real API
calls / no API key needed). We hand-build fake response objects shaped like
what the SDK returns, so we can verify the loop's control flow: it executes
tool calls, feeds results back, and stops on the first non-tool_use reply.
"""
from types import SimpleNamespace

import pytest

from task2pr.agent.loop import AgentLoopError, run_explore_loop


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
        # Snapshot messages - the loop mutates the same list object in
        # place on every iteration, so without copying here, every call
        # recorded in self.calls would end up pointing at the final state.
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "main.py").write_text("def add(a, b):\n    return a + b\n")
    return tmp_path


def test_loop_executes_tool_call_then_returns_final_plan(repo):
    responses = [
        response(
            [tool_use_block("list_directory", {"path": "."})],
            stop_reason="tool_use",
        ),
        response(
            [text_block("## Summary\nAdd logging.")],
            stop_reason="end_turn",
        ),
    ]
    client = FakeClient(responses)

    plan = run_explore_loop(client, "Add logging to add()", repo)

    assert "## Summary" in plan
    assert client.messages.calls[1]["messages"][-1]["role"] == "user"
    tool_result = client.messages.calls[1]["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert "main.py" in tool_result["content"]


def test_loop_raises_after_max_iterations(repo):
    # Always returns a tool_use response, so the loop never converges.
    responses = [
        response([tool_use_block("list_directory", {"path": "."})], stop_reason="tool_use")
        for _ in range(3)
    ]
    client = FakeClient(responses)

    with pytest.raises(AgentLoopError, match="did not converge"):
        run_explore_loop(client, "Some task", repo, max_iterations=3)


def test_loop_handles_bad_tool_input_gracefully(repo):
    responses = [
        response(
            [tool_use_block("read_file", {"path": "../outside.py"})],
            stop_reason="tool_use",
        ),
        response([text_block("## Summary\nDone.")], stop_reason="end_turn"),
    ]
    client = FakeClient(responses)

    plan = run_explore_loop(client, "Some task", repo)

    tool_result = client.messages.calls[1]["messages"][-1]["content"][0]
    assert "Error" in tool_result["content"]
    assert "## Summary" in plan
