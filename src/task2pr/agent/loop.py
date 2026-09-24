"""Explore-only agent loop (Stage 3): investigate a repo, propose a plan.

This is a minimal "agentic loop": each turn we send the running conversation
to Claude along with a fixed set of tool schemas. Claude either asks to call
a tool (stop_reason == "tool_use") or finishes with plain text. We execute
whatever tool it asked for, append the *result* back into the conversation
as a new message, and send the whole thing back - Claude has no memory
between calls except what's in that growing `messages` list, so the loop is
the only thing giving it continuity across tool calls.

No file edits happen here. The tools available (see task2pr.tools) are
read-only and sandboxed to the target repo.
"""
from __future__ import annotations

import logging
from pathlib import Path

import anthropic

from task2pr.tools import READ_ONLY_TOOL_SCHEMAS, run_tool
from task2pr.tools.filesystem import RepoSandbox

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-5"
MAX_TOKENS = 4096
MAX_ITERATIONS = 15

SYSTEM_PROMPT = """You are a senior software engineer investigating a code \
repository in order to plan a change described by a task. You have \
read-only tools: list_directory, read_file, and grep. Use them to verify \
anything you claim - do not guess at file names, function names, or code \
structure that you have not actually seen.

Explore only as much as you need to write a concrete, actionable plan. \
When you are confident, stop calling tools and reply with a final plan in \
exactly this format:

## Summary
One or two sentences on what the change does.

## Files to change
A bullet list of specific file paths, and what changes in each.

## Approach
A short numbered list of the steps you would take to implement the change.

## Risks / open questions
Anything you're unsure about, or that a human should confirm before this \
change is implemented.
"""


class AgentLoopError(RuntimeError):
    """Raised when the loop can't produce a plan (e.g. hits the iteration cap)."""


def run_explore_loop(
    client: anthropic.Anthropic,
    task_description: str,
    repo_root: Path,
    max_iterations: int = MAX_ITERATIONS,
) -> str:
    sandbox = RepoSandbox(repo_root=repo_root)
    messages: list[dict] = [
        {"role": "user", "content": f"Task description:\n\n{task_description}"}
    ]

    for iteration in range(1, max_iterations + 1):
        logger.info("Agent loop iteration %d/%d", iteration, max_iterations)
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=READ_ONLY_TOOL_SCHEMAS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            return extract_text(response)

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

    raise AgentLoopError(
        f"Agent did not converge on a plan within {max_iterations} iterations."
    )


def extract_text(response: anthropic.types.Message) -> str:
    return "\n".join(block.text for block in response.content if block.type == "text")
