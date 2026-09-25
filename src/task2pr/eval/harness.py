"""Eval harness (Stage 7): run the edit-and-test loop against a small
seeded set of known tasks, each with its own throwaway fixture repo and a
deterministic pass/fail check (its own test suite), and report a score.

Deliberately decoupled from GitHub and Wrike - eval tasks never open a PR
or touch a real Wrike task. Each task gets a fresh copy of its fixture
directory so tasks never interfere with each other and re-running the eval
never mutates the checked-in fixtures. The only real side effect of running
this is Anthropic API calls.
"""
from __future__ import annotations

import json
import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import anthropic

from task2pr.agent import AgentLoopError, run_edit_loop

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TASKS_DIR = _REPO_ROOT / "eval" / "tasks"
DEFAULT_FIXTURES_DIR = _REPO_ROOT / "eval" / "fixtures"


@dataclass(frozen=True)
class EvalTask:
    id: str
    description: str
    test_cmd: str
    fixture_dir: Path


@dataclass(frozen=True)
class EvalOutcome:
    task_id: str
    success: bool
    test_attempts: int
    detail: str


def load_tasks(tasks_dir: Path, fixtures_dir: Path) -> list[EvalTask]:
    tasks = []
    for task_file in sorted(tasks_dir.glob("*.json")):
        raw = json.loads(task_file.read_text())
        tasks.append(
            EvalTask(
                id=raw["id"],
                description=raw["description"],
                test_cmd=raw["test_cmd"],
                fixture_dir=fixtures_dir / raw["fixture"],
            )
        )
    return tasks


def run_eval(
    client: anthropic.Anthropic,
    tasks_dir: Path = DEFAULT_TASKS_DIR,
    fixtures_dir: Path = DEFAULT_FIXTURES_DIR,
) -> list[EvalOutcome]:
    tasks = load_tasks(tasks_dir, fixtures_dir)
    outcomes = []

    with tempfile.TemporaryDirectory(prefix="task2pr-eval-") as tmp:
        workdir = Path(tmp)
        for task in tasks:
            logger.info("Running eval task %s", task.id)
            repo_copy = workdir / task.id
            shutil.copytree(task.fixture_dir, repo_copy)

            try:
                result = run_edit_loop(client, task.description, repo_copy, task.test_cmd)
                outcomes.append(
                    EvalOutcome(
                        task_id=task.id,
                        success=result.success,
                        test_attempts=result.test_attempts,
                        detail=result.summary if result.success else result.test_output,
                    )
                )
            except AgentLoopError as exc:
                outcomes.append(
                    EvalOutcome(task_id=task.id, success=False, test_attempts=0, detail=str(exc))
                )

    return outcomes
