"""Edit-and-test agent loop (Stage 4): make a code change, then verify it.

Same tool-use loop shape as the explore loop (agent.loop), but with two
differences:

1. Claude gets write_file/edit_file in addition to the read-only tools, so
   it can actually modify the target repo.
2. When Claude stops calling tools - meaning it believes the change is
   done - the harness (not Claude) runs the target repo's test suite via a
   fixed, operator-supplied command. Claude never gets a tool to execute
   arbitrary shell commands; it can only ask to read/write files. The test
   result is fed back in as a normal message, and if it failed, Claude gets
   another round to fix it, up to max_test_attempts.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import anthropic

from task2pr.agent.loop import MAX_TOKENS, MODEL, AgentLoopError, extract_text
from task2pr.tools import EDIT_TOOL_SCHEMAS, run_tool
from task2pr.tools.filesystem import RepoSandbox
from task2pr.tools.test_runner import run_tests

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 30
MAX_TEST_ATTEMPTS = 3

SYSTEM_PROMPT = """You are a senior software engineer making a code change \
to a repository, described by a task. You have tools to explore the repo \
(list_directory, read_file, grep) and to modify it (write_file, edit_file).

Work in this order:
1. Explore enough to understand the existing code relevant to the task. Do \
not guess at code you have not read, and do not modify files unrelated to \
the task.
2. Make the change. Prefer edit_file for changes to existing files, so you \
don't discard unrelated content; use write_file for new files.
3. When you believe the change is complete, stop calling tools and reply \
with a short summary of what you changed and why. The test suite will then \
be run automatically. If it fails, you will see the failure output and get \
a chance to fix it.
"""


@dataclass(frozen=True)
class EditResult:
    success: bool
    summary: str
    test_output: str
    test_attempts: int


def run_edit_loop(
    client: anthropic.Anthropic,
    task_description: str,
    repo_root: Path,
    test_command: str,
    max_iterations: int = MAX_ITERATIONS,
    max_test_attempts: int = MAX_TEST_ATTEMPTS,
) -> EditResult:
    sandbox = RepoSandbox(repo_root=repo_root)
    messages: list[dict] = [
        {"role": "user", "content": f"Task description:\n\n{task_description}"}
    ]
    test_attempts = 0

    for iteration in range(1, max_iterations + 1):
        logger.info("Edit loop iteration %d/%d", iteration, max_iterations)
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=EDIT_TOOL_SCHEMAS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                logger.info("Tool call: %s(%s)", block.name, block.input)
                result = run_tool(sandbox, block.name, block.input)
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": result}
                )
            messages.append({"role": "user", "content": tool_results})
            continue

        # Claude stopped calling tools: it believes the change is done.
        summary = extract_text(response)
        test_attempts += 1
        logger.info(
            "Running test command (attempt %d/%d): %s",
            test_attempts,
            max_test_attempts,
            test_command,
        )
        result = run_tests(test_command, repo_root)

        if result.passed:
            return EditResult(
                success=True,
                summary=summary,
                test_output=result.output,
                test_attempts=test_attempts,
            )

        if test_attempts >= max_test_attempts:
            return EditResult(
                success=False,
                summary=summary,
                test_output=result.output,
                test_attempts=test_attempts,
            )

        messages.append(
            {
                "role": "user",
                "content": (
                    f"The test suite failed (attempt {test_attempts}/{max_test_attempts}):\n\n"
                    f"{result.output}\n\nPlease fix the issue and continue."
                ),
            }
        )

    raise AgentLoopError(
        f"Agent did not finish editing within {max_iterations} tool-call iterations."
    )
